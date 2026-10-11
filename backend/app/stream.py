import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import ui
from .config import HISTORY_HOURS, REPORT_DIR
from .detector import RAW_COLS, Detector
from .generator import generate
from .model import load_bundle
from .profile import load_profile

REPORT_COLS = [
    "timestamp", "device_id", "city", "pm25", "temp", "rh", "verdict", "detected_as",
    "confidence", "reason", "source", "drivers", "truth_label", "truth_cause", "correct",
]


def simulate(start, days, cities, seed):
    lead = pd.Timestamp(start) - pd.Timedelta(hours=HISTORY_HOURS)
    end = pd.Timestamp(start) + pd.Timedelta(days=days)
    return generate(load_profile(), lead, end, seed=seed, cities=cities)


def stream_ticks(start, days, cities, seed=2026, bundle=None):
    bundle = bundle or load_bundle()
    sim = simulate(start, days, cities, seed)
    det = Detector(bundle)
    first = pd.Timestamp(start)
    for ts, tick in sim.groupby("timestamp", sort=True):
        if ts < first:
            det.warm(tick)
            continue
        res = det.process(tick)
        truth = tick.set_index("device_id")[["fault_type", "event_cause"]]
        res["truth_label"] = res["device_id"].map(truth["fault_type"])
        res["truth_cause"] = res["device_id"].map(truth["event_cause"])
        res["detected_as"] = res["pred_class"]
        truth_valid = res["truth_label"].isin(["normal", "pollution_event"])
        res["correct"] = np.where(res["verdict"] == "REVIEW", np.nan, (res["pred_valid"] == truth_valid).astype(float))
        res["confidence"] = res["confidence"].round(3)
        yield res[REPORT_COLS]


class DayWriter:
    def __init__(self, out_dir):
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.buf = []
        self.day = None
        self.summary = []

    def add(self, res):
        day = res["timestamp"].iloc[0].date()
        if self.day is not None and day != self.day:
            self.flush()
        self.day = day
        self.buf.append(res)

    def flush(self):
        if not self.buf:
            return None
        df = pd.concat(self.buf, ignore_index=True)
        path = self.dir / f"{self.day}.csv"
        df.to_csv(path, index=False)
        inv = df["verdict"] == "INVALID"
        row = {
            "date": str(self.day),
            "readings": len(df),
            "valid": int((~inv).sum()),
            "invalid": int(inv.sum()),
            "pollution_events": int((df["detected_as"] == "pollution_event").sum()),
            "mean_confidence": round(float(df["confidence"].mean()), 3),
            "needs_review": int((df["verdict"] == "REVIEW").sum()),
            "agrees_with_simulator": round(float(df["correct"].mean()), 4),
        }
        for c in ("spike", "drift", "stuck", "saturation", "impossible_temp", "th_fault", "rh_fault", "dropout"):
            row[c] = int((df["detected_as"] == c).sum())
        self.summary.append(row)
        pd.DataFrame(self.summary).to_csv(self.dir / "daily_summary.csv", index=False)
        self.buf, self.day = [], None
        return path


def _line(r):
    t = f"{r.timestamp:%H:%M}"
    vals = "NO DATA".ljust(34) if r.detected_as == "dropout" else f"PM {r.pm25:7.1f}  T {r.temp:5.1f}  RH {r.rh:5.1f}"
    if r.verdict == "INVALID":
        tag, style = ("NO DATA " if r.detected_as == "dropout" else "INVALID "), (ui.BOLD, ui.RED)
    elif r.verdict == "REVIEW":
        tag, style = "REVIEW  ", (ui.BOLD, ui.MAGENTA)
    elif r.detected_as == "pollution_event":
        tag, style = "EVENT   ", (ui.BOLD, ui.YELLOW)
    else:
        tag, style = "VALID   ", (ui.GREEN,)
    return ui.paint(f"{t}  {r.device_id:<7} {vals}  {tag} {r.confidence:4.2f}  {r.reason[:88]}", *style)


def run_cli(a):
    cities = [c.strip() for c in a.cities.split(",") if c.strip()]
    out = Path(a.out) if a.out else REPORT_DIR / "daywise"
    ui.title(f"Live stream  |  {a.start} for {a.days} day(s)  |  {', '.join(cities)}")
    ui.step("Warming up with the 48 hours before the start, then streaming (Ctrl+C to stop)")
    writer = DayWriter(out)
    seen, last_day = [], None
    try:
        for res in stream_ticks(a.start, a.days, cities, a.seed):
            ts = res["timestamp"].iloc[0]
            if ts.date() != last_day:
                last_day = ts.date()
                print(ui.paint(f"\n--- {ts:%A %d %b %Y} ---", ui.BOLD, ui.CYAN))
            writer.add(res)
            seen.append(res)
            show = res[res["verdict"] != "VALID"] if a.only_flagged else res
            show = show if not a.only_flagged else pd.concat([show, res[res["detected_as"] == "pollution_event"]]).drop_duplicates("device_id")
            for r in show.itertuples():
                print(_line(r))
            if a.delay > 0:
                time.sleep(a.delay)
    except KeyboardInterrupt:
        print(ui.paint("\nstopped", ui.YELLOW))
    path = writer.flush()
    if not seen:
        return
    df = pd.concat(seen, ignore_index=True)
    ui.title("Stream summary")
    inv = df["verdict"] == "INVALID"
    ui.table(["readings", "valid", "invalid", "review", "pollution events", "mean confidence", "agrees with simulator"], [[
        f"{len(df):,}", f"{(df['verdict'] == 'VALID').sum():,}", f"{inv.sum():,}", f"{(df['verdict'] == 'REVIEW').sum():,}", f"{(df['detected_as'] == 'pollution_event').sum():,}",
        f"{df['confidence'].mean():.3f}", f"{df['correct'].mean():.2%}"]])
    mix = df.loc[inv, "detected_as"].value_counts()
    ui.table(["flagged as", "count"], [[k, int(v)] for k, v in mix.items()])
    ui.ok(f"day-wise reports -> {out}  (one CSV per day + daily_summary.csv)")


def run_ingest_sim(a):
    from .ingest import Ingestor, Store
    cities = [c.strip() for c in a.cities.split(",") if c.strip()]
    store = Store(a.db) if a.db else Store()
    ing = Ingestor(load_bundle(), store)
    sim = simulate(a.start, a.days, cities, 2026)
    ui.title(f"Ingestion pipeline  |  {len(cities)} cities  |  store: {store.path}")
    ui.step("Feeding hourly batches through the same path the API uses (dedupe, late data, scoring, storage)")
    first, ok, dup = pd.Timestamp(a.start), 0, 0
    for ts, tick in sim.groupby("timestamp", sort=True):
        raw = tick[RAW_COLS]
        r = ing.ingest(raw[raw["pm25"].notna() | raw["temp"].notna() | raw["rh"].notna()])
        ing.close_hour(ts)
        ok += r["scored"]
        dup += r["duplicates"]
    ing.ingest(sim[sim["timestamp"] == sim["timestamp"].max()][RAW_COLS])
    ui.ok(f"{store.count():,} readings stored, duplicates ignored on resend")
    for d in range(a.days):
        s = ing.summary(first + pd.Timedelta(days=d))
        ui.table(["date", "readings", "valid", "invalid", "review", "events", "mean confidence"], [[s["date"], s["readings"], s["valid"], s["invalid"], s["review"], s["pollution_events"], s["mean_confidence"]]])
