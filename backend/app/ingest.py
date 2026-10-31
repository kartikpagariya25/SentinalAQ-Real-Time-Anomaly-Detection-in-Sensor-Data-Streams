import sqlite3
from contextlib import contextmanager
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
        self.mem = str(path) == ":memory:"
        if not self.mem:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._shared = sqlite3.connect(str(path), check_same_thread=False, timeout=30) if self.mem else None
        with self._cur() as c:
            c.executescript(SCHEMA)
            if not self.mem:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=NORMAL")

    @contextmanager
    def _cur(self):
        conn = self._shared or sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        if not self.mem:
            conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        finally:
            if not self.mem:
                conn.close()

    def known(self, df):
        if df.empty:
            return set()
        lo, hi = df["timestamp"].min().isoformat(), df["timestamp"].max().isoformat()
        with self._cur() as c:
            return set(c.execute("SELECT device_id, ts FROM readings WHERE ts BETWEEN ? AND ?", (lo, hi)).fetchall())

    def history(self, cities, upto, hours=HISTORY_HOURS):
        lo = (upto - pd.Timedelta(hours=hours - 1)).isoformat()
        marks = ",".join("?" * len(cities))
        q = f"SELECT ts AS timestamp, device_id, city, pm25, temp, rh FROM readings WHERE city IN ({marks}) AND ts >= ? AND ts <= ?"
        with self._cur() as c:
            h = pd.read_sql_query(q, c, params=[*cities, lo, upto.isoformat()], parse_dates=["timestamp"])
        for col in ("pm25", "temp", "rh"):
            h[col] = pd.to_numeric(h[col], errors="coerce")
        return h

    def save(self, res):
        rows = res.copy()
        rows["ts"] = rows["timestamp"].map(lambda t: t.isoformat())
        data = [(r.device_id, r.ts, r.city, _n(r.pm25), _n(r.temp), _n(r.rh), r.verdict, r.pred_class, float(r.confidence), float(r.p_invalid), r.source, r.reason, r.drivers)
                for r in rows.itertuples()]
        with self._cur() as c:
            c.executemany("INSERT OR REPLACE INTO readings (device_id, ts, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason, drivers) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", data)

    def day(self, date):
        d = pd.Timestamp(date)
        q = "SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason, drivers FROM readings WHERE ts >= ? AND ts < ? ORDER BY ts, device_id"
        with self._cur() as c:
            return pd.read_sql_query(q, c, params=[d.isoformat(), (d + pd.Timedelta(days=1)).isoformat()], parse_dates=["timestamp"])

    def range(self, start, end):
        q = "SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason, drivers FROM readings WHERE ts >= ? AND ts < ? ORDER BY ts, device_id"
        with self._cur() as c:
            return pd.read_sql_query(q, c, params=[pd.Timestamp(start).isoformat(), pd.Timestamp(end).isoformat()], parse_dates=["timestamp"])

    def recent(self, limit=50, verdict=None):
        q = "SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason FROM readings"
        params = []
        if verdict:
            q += " WHERE verdict = ?"
            params.append(verdict.upper())
        q += " ORDER BY rowid DESC LIMIT ?"
        params.append(int(limit))
        with self._cur() as c:
            return pd.read_sql_query(q, c, params=params, parse_dates=["timestamp"])

    def hourly(self, hours=24):
        with self._cur() as c:
            mx = c.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
            if not mx:
                return []
            lo = (pd.Timestamp(mx) - pd.Timedelta(hours=hours)).isoformat()
            df = pd.read_sql_query("SELECT substr(ts,1,13) AS hour, verdict, COUNT(*) AS n FROM readings WHERE ts >= ? GROUP BY hour, verdict ORDER BY hour", c, params=[lo])
        if df.empty:
            return []
        piv = df.pivot_table(index="hour", columns="verdict", values="n", fill_value=0)
        out = []
        for hour, r in piv.iterrows():
            out.append({"hour": hour[5:].replace("T", " ") + "h",
                        "VALID": int(r.get("VALID", 0)), "REVIEW": int(r.get("REVIEW", 0)), "INVALID": int(r.get("INVALID", 0))})
        return out

    def devices_cities(self):
        with self._cur() as c:
            return c.execute("SELECT device_id, city FROM readings GROUP BY device_id").fetchall()

    def seen_at(self, ts):
        with self._cur() as c:
            return {r[0] for r in c.execute("SELECT device_id FROM readings WHERE ts = ?", (ts,)).fetchall()}

    def devices(self):
        with self._cur() as c:
            return [r[0] for r in c.execute("SELECT DISTINCT device_id FROM readings").fetchall()]

    def count(self):
        with self._cur() as c:
            return c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]

    def span(self):
        with self._cur() as c:
            r = c.execute("SELECT MIN(ts), MAX(ts) FROM readings").fetchone()
        return (r[0], r[1]) if r else (None, None)


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
        day = self.store.devices_cities()
        got = self.store.seen_at(ts.isoformat())
        missing = [(d, c) for d, c in day if d not in got]
        if not missing:
            return 0
        fill = pd.DataFrame({"timestamp": ts, "device_id": [m[0] for m in missing], "city": [m[1] for m in missing], "pm25": np.nan, "temp": np.nan, "rh": np.nan})
        return self.ingest(fill)["scored"]

    def summary(self, date):
        d = self.store.day(date)
        return _summarise(d, {"date": str(pd.Timestamp(date).date())})

    def summary_range(self, start, end, period="custom"):
        d = self.store.range(start, end)
        meta = {"period": period, "start": str(pd.Timestamp(start).date()), "end": str((pd.Timestamp(end) - pd.Timedelta(seconds=1)).date())}
        out = _summarise(d, meta)
        if not d.empty:
            g = d.assign(day=d["timestamp"].dt.date.astype(str)).groupby("day")["verdict"].value_counts().unstack(fill_value=0)
            out["by_day"] = [{"day": i, "valid": int(r.get("VALID", 0)), "invalid": int(r.get("INVALID", 0)), "review": int(r.get("REVIEW", 0))} for i, r in g.iterrows()]
        else:
            out["by_day"] = []
        return out


PERIODS = ("daily", "weekly", "monthly", "yearly")


def period_window(period, anchor):
    a = pd.Timestamp(anchor).normalize()
    if period == "daily":
        return a, a + pd.Timedelta(days=1)
    if period == "weekly":
        s = a - pd.Timedelta(days=a.weekday())
        return s, s + pd.Timedelta(days=7)
    if period == "monthly":
        s = a.replace(day=1)
        return s, s + pd.offsets.MonthBegin(1)
    if period == "yearly":
        s = a.replace(month=1, day=1)
        return s, s + pd.offsets.YearBegin(1)
    raise ValueError(f"unknown period {period}")


def _summarise(d, meta):
    if d.empty:
        return {**meta, "readings": 0, "valid": 0, "invalid": 0, "review": 0, "pollution_events": 0, "mean_confidence": None, "faults_by_type": {}, "devices_reporting": 0, "by_device": []}
    v = d["verdict"].value_counts()
    flagged = d[d["verdict"] != "VALID"]
    by_device = []
    if not flagged.empty:
        for dev, g in flagged.groupby("device_id"):
            inv = int((g["verdict"] == "INVALID").sum())
            rev = int((g["verdict"] == "REVIEW").sum())
            top = g.loc[g["verdict"] == "INVALID", "detected_as"].value_counts()
            by_device.append({"device": dev, "city": g["city"].iloc[0], "invalid": inv, "review": rev,
                              "total": inv + rev, "top_fault": top.index[0] if len(top) else "-"})
        by_device.sort(key=lambda r: r["total"], reverse=True)
    return {
        **meta, "readings": int(len(d)), "valid": int(v.get("VALID", 0)),
        "invalid": int(v.get("INVALID", 0)), "review": int(v.get("REVIEW", 0)),
        "pollution_events": int((d["detected_as"] == "pollution_event").sum()),
        "mean_confidence": round(float(d["confidence"].mean()), 3),
        "faults_by_type": d.loc[d["verdict"] == "INVALID", "detected_as"].value_counts().to_dict(),
        "devices_reporting": int(d["device_id"].nunique()),
        "by_device": by_device[:20],
    }
