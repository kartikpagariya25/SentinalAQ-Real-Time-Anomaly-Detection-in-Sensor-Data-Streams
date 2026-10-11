import pandas as pd

from . import ui
from .config import DATA_FILE, DEVICES_FILE

SHOW = ["timestamp", "device_id", "city", "pm25", "temp", "rh", "fault_type", "fault_tier", "event_cause", "event_mult"]


def peek(a):
    if not DATA_FILE.exists():
        raise SystemExit("no synthetic data yet, run: python -m app.cli generate")
    df = pd.read_parquet(DATA_FILE)
    ui.title(f"Synthetic data  |  {len(df):,} rows  |  {df.device_id.nunique()} devices  |  {df.city.nunique()} cities  |  {df.timestamp.min():%Y-%m-%d} to {df.timestamp.max():%Y-%m-%d}")
    ui.warn("city / device locations are ASSUMED (the real Atmos file has no location). Replace devices.csv when Respirer shares the real mapping")
    q = df
    if a.city:
        q = q[q["city"].str.lower() == a.city.lower()]
    if a.device:
        q = q[q["device_id"] == a.device]
    if a.start:
        q = q[q["timestamp"] >= a.start]
    if a.end:
        q = q[q["timestamp"] < a.end]
    if a.fault:
        q = q[q["fault_type"] == a.fault]
    if a.faults_only:
        q = q[~q["fault_type"].isin(["normal"])]
    if not (a.city or a.device or a.start or a.fault or a.faults_only):
        dev = pd.read_csv(DEVICES_FILE) if DEVICES_FILE.exists() else None
        g = df.groupby("city").agg(devices=("device_id", "nunique"), rows=("timestamp", "size"),
                                   pm_median=("pm25", "median"), faulty=("is_valid", lambda s: 1 - s.mean()))
        ui.table(["city", "devices", "rows", "median PM2.5", "invalid share"],
                 [[c, int(r.devices), f"{int(r.rows):,}", f"{r.pm_median:.1f}", f"{r.faulty:.2%}"] for c, r in g.iterrows()])
        mix = df["fault_type"].value_counts()
        ui.table(["class", "rows", "share"], [[k, f"{v:,}", f"{v / len(df):.2%}"] for k, v in mix.items()])
        ui.step("Look closer, for example:")
        print("  python -m app.cli peek --city Delhi --faults-only --rows 30")
        print("  python -m app.cli peek --device DEL-01 --start 2025-11-01 --end 2025-11-04 --rows 72")
        print("  python -m app.cli peek --fault spike --rows 20")
        print("  python -m app.cli peek --city Pune --export pune.csv")
        return
    ui.ok(f"{len(q):,} rows match")
    if a.export:
        q[SHOW].to_csv(a.export, index=False)
        ui.ok(f"exported -> {a.export}")
    s = q[SHOW].head(a.rows).copy()
    s["timestamp"] = s["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    for c in ("pm25", "temp", "rh", "event_mult"):
        s[c] = s[c].map(lambda x: "" if x != x else f"{x:.1f}")
    ui.table(SHOW, s.fillna("").astype(str).values.tolist())
