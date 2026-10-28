import math
import time

import httpx
import pandas as pd

from . import ui
from .config import DATA_FILE
from .detector import RAW_COLS
from .priors import CITIES as ALL_CITIES
from .stream import simulate

DRIP_CHUNKS = 12


def _payload(tick):
    raw = tick[RAW_COLS].copy()
    raw["timestamp"] = raw["timestamp"].astype(str)
    rows = raw.astype(object).where(raw.notna(), None).to_dict("records")
    return [{k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()} for row in rows]


def _push(c, base, tick, ts, tag):
    rows = _payload(tick)
    c.post(f"{base}/ingest", json=rows).raise_for_status()
    return len(rows)


def _close(c, base, ts, pushed, tag):
    c.post(f"{base}/close-hour/{ts.isoformat()}")
    st = c.get(f"{base}/stats").json()["latest_window"]
    print(ui.paint(f"{ts:%Y-%m-%d %H:%M}  {tag:<6} pushed {pushed:>3}  |  window  V {st['valid']:<4} I {st['invalid']:<4} R {st['review']:<4}", ui.CYAN))


def _replay(c, base, cities, days):
    if not DATA_FILE.exists():
        ui.warn("dataset not found, skipping history replay (run `python -m app.cli generate`)")
        return
    df = pd.read_parquet(DATA_FILE, columns=RAW_COLS)
    if set(c_.lower() for c_ in cities) != {x.lower() for x in ALL_CITIES}:
        df = df[df["city"].isin(cities)]
    end = df["timestamp"].max()
    lo = end.normalize() - pd.Timedelta(days=days - 1)
    df = df[df["timestamp"] >= lo]
    ui.step(f"Replaying dataset history {lo:%Y-%m-%d} to {end:%Y-%m-%d %H:%M} (past timestamps from the dataset)")
    for ts, tick in df.groupby("timestamp", sort=True):
        n = _push(c, base, tick, ts, "data")
        c.post(f"{base}/close-hour/{ts.isoformat()}")
    ui.ok("history loaded")


def _day_ticks(day, cities, seed):
    sim = simulate(day, 2, cities, seed + day.toordinal())
    return {ts: tick for ts, tick in sim.groupby("timestamp", sort=True) if ts >= day}


def run_live_feed(a):
    cities = [c.strip() for c in a.cities.split(",") if c.strip()]
    if any(c.lower() == "all" for c in cities):
        cities = list(ALL_CITIES.keys())
    base = a.url.rstrip("/")
    headers = {"X-API-Key": a.api_key} if a.api_key else {}
    ui.title(f"Live HTTP feed -> {base}/ingest")
    ui.step("History comes from the dataset; today's readings are generated live, hour by hour. Nothing is ever stamped in the future. Ctrl+C to stop.")
    try:
        with httpx.Client(timeout=30, headers=headers) as c:
            h = c.get(f"{base}/health")
            h.raise_for_status()
            hj = h.json()
            ui.ok(f"connected, model: {hj['model']}")
            if hj.get("last") and pd.Timestamp(hj["last"]) > pd.Timestamp.now():
                ui.warn(f"store holds future-dated readings (up to {hj['last']}) from an old run - restart with .\\run.ps1 -Fresh")
            if not hj.get("last") and a.replay_days > 0:
                _replay(c, base, cities, a.replay_days)
            day, ticks, sent = None, {}, set()
            while True:
                now = pd.Timestamp.now()
                cur = now.floor("h")
                if day != cur.normalize():
                    day = cur.normalize()
                    ticks = _day_ticks(day, cities, a.seed)
                    sent = set()
                    ui.step(f"live day: {day:%A %d %b %Y}")
                for ts in sorted(t for t in ticks if t <= cur and t not in sent):
                    tick = ticks[ts]
                    if ts < cur:
                        n = _push(c, base, tick, ts, "catch")
                        _close(c, base, ts, n, "catch")
                        time.sleep(a.delay * 0.3)
                    else:
                        step = max(1, math.ceil(len(tick) / DRIP_CHUNKS))
                        n = 0
                        for i in range(0, len(tick), step):
                            n += _push(c, base, tick.iloc[i:i + step], ts, "live")
                            time.sleep(a.delay)
                        _close(c, base, ts, n, "live")
                    sent.add(ts)
                if not a.loop and all(t in sent for t in ticks if t <= cur):
                    break
                time.sleep(5)
    except KeyboardInterrupt:
        print(ui.paint("\nstopped", ui.YELLOW))
    except httpx.HTTPError as e:
        ui.warn(f"cannot reach API at {base} ({e}). Start it first: python -m app.cli serve")
