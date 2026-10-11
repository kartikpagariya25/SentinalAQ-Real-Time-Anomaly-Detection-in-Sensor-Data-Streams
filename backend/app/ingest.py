import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .config import HISTORY_HOURS, ROOT
from .detector import RAW_COLS, annotate
from .features import build_features

DB_FILE = ROOT / "data" / "live" / "readings.db"
COLS = ["timestamp", "device_id", "city", "pm25", "temp", "rh", "verdict", "detected_as", "confidence", "p_invalid", "source", "reason", "drivers"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    device_id TEXT NOT NULL, ts TEXT NOT NULL, city TEXT, pm25 REAL, temp REAL, rh REAL,
    verdict TEXT, detected_as TEXT, confidence REAL, p_invalid REAL, source TEXT, reason TEXT, drivers TEXT,
    received_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (device_id, ts));
CREATE INDEX IF NOT EXISTS idx_ts ON readings (ts);
CREATE INDEX IF NOT EXISTS idx_city_ts ON readings (city, ts);
"""


class Store:
    def __init__(self, path=DB_FILE):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    def known(self, df):
        if df.empty:
            return set()
        lo, hi = df["timestamp"].min().isoformat(), df["timestamp"].max().isoformat()
        rows = self.db.execute("SELECT device_id, ts FROM readings WHERE ts BETWEEN ? AND ?", (lo, hi)).fetchall()
        return set(rows)

    def history(self, cities, upto, hours=HISTORY_HOURS):
        lo = (upto - pd.Timedelta(hours=hours - 1)).isoformat()
        marks = ",".join("?" * len(cities))
        q = f"SELECT ts AS timestamp, device_id, city, pm25, temp, rh FROM readings WHERE city IN ({marks}) AND ts >= ? AND ts <= ?"
        h = pd.read_sql_query(q, self.db, params=[*cities, lo, upto.isoformat()], parse_dates=["timestamp"])
        for c in ("pm25", "temp", "rh"):
            h[c] = pd.to_numeric(h[c], errors="coerce")
        return h

    def save(self, res):
        rows = res.copy()
        rows["ts"] = rows["timestamp"].map(lambda t: t.isoformat())
        data = [(r.device_id, r.ts, r.city, _n(r.pm25), _n(r.temp), _n(r.rh), r.verdict, r.pred_class, float(r.confidence), float(r.p_invalid), r.source, r.reason, r.drivers)
                for r in rows.itertuples()]
        self.db.executemany("INSERT OR REPLACE INTO readings (device_id, ts, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason, drivers) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
        self.db.commit()

    def day(self, date):
        d = pd.Timestamp(date)
        q = "SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason, drivers FROM readings WHERE ts >= ? AND ts < ? ORDER BY ts, device_id"
        return pd.read_sql_query(q, self.db, params=[d.isoformat(), (d + pd.Timedelta(days=1)).isoformat()], parse_dates=["timestamp"])

    def devices(self):
        return [r[0] for r in self.db.execute("SELECT DISTINCT device_id FROM readings").fetchall()]

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM readings").fetchone()[0]


def _n(x):
    return None if x != x else float(x)


class Ingestor:
    def __init__(self, bundle, store=None):
        self.bundle = bundle
        self.store = store or Store()

    def ingest(self, batch):
        b = batch[RAW_COLS].copy()
        b["timestamp"] = pd.to_datetime(b["timestamp"]).dt.floor("h")
        b = b.drop_duplicates(["device_id", "timestamp"], keep="last")
        seen = self.store.known(b)
        fresh = b[[(d, t.isoformat()) not in seen for d, t in zip(b["device_id"], b["timestamp"])]]
        out = {"received": len(batch), "duplicates": len(batch) - len(fresh), "scored": 0}
        if fresh.empty:
            return out
        cities = fresh["city"].unique().tolist()
        hist = self.store.history(cities, fresh["timestamp"].max())
        allr = pd.concat([hist, fresh[RAW_COLS]], ignore_index=True).drop_duplicates(["device_id", "timestamp"], keep="last")
        feats = build_features(allr)
        keys = set(zip(fresh["device_id"], fresh["timestamp"]))
        cur = feats[[(d, t) in keys for d, t in zip(feats["device_id"], feats["timestamp"])]]
        res = annotate(self.bundle, cur, gaps=self._gaps(allr, cur)).reset_index(drop=True)
        self.store.save(res)
        out["scored"] = len(res)
        out["late"] = int((fresh["timestamp"] < fresh["timestamp"].max()).sum())
        return out

    @staticmethod
    def _gaps(allr, cur):
        miss = cur.loc[cur["pm25"].isna(), ["device_id", "timestamp"]]
        gaps = {}
        for dev, ts in zip(miss["device_id"], miss["timestamp"]):
            pm = allr[(allr["device_id"] == dev) & (allr["timestamp"] <= ts)].sort_values("timestamp")["pm25"].to_numpy()
            n = 0
            for v in pm[::-1]:
                if np.isnan(v):
                    n += 1
                else:
                    break
            gaps[dev] = n
        return gaps

    def close_hour(self, ts):
        ts = pd.Timestamp(ts).floor("h")
        day = self.store.db.execute("SELECT device_id, city FROM readings GROUP BY device_id").fetchall()
        got = {r[0] for r in self.store.db.execute("SELECT device_id FROM readings WHERE ts = ?", (ts.isoformat(),)).fetchall()}
        missing = [(d, c) for d, c in day if d not in got]
        if not missing:
            return 0
        fill = pd.DataFrame({"timestamp": ts, "device_id": [m[0] for m in missing], "city": [m[1] for m in missing], "pm25": np.nan, "temp": np.nan, "rh": np.nan})
        return self.ingest(fill)["scored"]

    def summary(self, date):
        d = self.store.day(date)
        if d.empty:
            return {"date": str(date), "readings": 0}
        v = d["verdict"].value_counts()
        return {
            "date": str(pd.Timestamp(date).date()), "readings": int(len(d)), "valid": int(v.get("VALID", 0)),
            "invalid": int(v.get("INVALID", 0)), "review": int(v.get("REVIEW", 0)),
            "pollution_events": int((d["detected_as"] == "pollution_event").sum()),
            "mean_confidence": round(float(d["confidence"].mean()), 3),
            "faults_by_type": d.loc[d["verdict"] == "INVALID", "detected_as"].value_counts().to_dict(),
            "devices_reporting": int(d["device_id"].nunique()),
        }
