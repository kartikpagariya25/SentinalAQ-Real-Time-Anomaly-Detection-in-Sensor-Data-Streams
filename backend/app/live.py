import time

import httpx
import pandas as pd

from . import ui
from .config import DATA_FILE
from .detector import RAW_COLS
from .priors import CITIES as ALL_CITIES
from .stream import simulate

REPLAY_CHUNK = 8


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


def _day_ticks(day, cities, seed):
    sim = simulate(day, 2, cities, seed + day.toordinal())
    return {ts: tick for ts, tick in sim.groupby("timestamp", sort=True) if ts >= day}


class Today:
    def __init__(self, cities, seed):
        self.cities, self.seed = cities, seed
        self.day, self.ticks, self.sent = None, {}, set()

    def flush(self, c, base):
        cur = pd.Timestamp.now().floor("h")
        if self.day != cur.normalize():
            self.day = cur.normalize()
            self.ticks = _day_ticks(self.day, self.cities, self.seed)
            self.sent = set()
            ui.step(f"live day: {self.day:%A %d %b %Y}")
        for ts in sorted(t for t in self.ticks if t <= cur and t not in self.sent):
            n = _push(c, base, self.ticks[ts], ts, "live")
            _close(c, base, ts, n, "live")
            self.sent.add(ts)
        return all(t in self.sent for t in self.ticks if t <= cur)


def _history(cities, days):
    if not DATA_FILE.exists():
        ui.warn("dataset not found, skipping history stream (run `python -m app.cli generate`)")
        return None
    df = pd.read_parquet(DATA_FILE, columns=RAW_COLS)
    if {x.lower() for x in cities} != {x.lower() for x in ALL_CITIES}:
        df = df[df["city"].isin(cities)]
    lo = df["timestamp"].max().normalize() - pd.Timedelta(days=days - 1)
    return df[df["timestamp"] >= lo]


def run_live_feed(a):
    cities = [c.strip() for c in a.cities.split(",") if c.strip()]
    if any(c.lower() == "all" for c in cities):
        cities = list(ALL_CITIES.keys())
    base = a.url.rstrip("/")
    headers = {"X-API-Key": a.api_key} if a.api_key else {}
    ui.title(f"Live HTTP feed -> {base}/ingest")
    ui.step("Today's readings arrive as each hour completes; the dataset's past hours stream continuously in between. Nothing is stamped in the future. Ctrl+C to stop.")
    today = Today(cities, a.seed)
    try:
        with httpx.Client(timeout=30, headers=headers) as c:
            h = c.get(f"{base}/health")
            h.raise_for_status()
            hj = h.json()
            ui.ok(f"connected, model: {hj['model']}")
            if hj.get("last") and pd.Timestamp(hj["last"]) > pd.Timestamp.now():
                ui.warn(f"store holds future-dated readings (up to {hj['last']}) from an old run - restart with .\\run.ps1 -Fresh")
            today.flush(c, base)
            hist = _history(cities, a.replay_days) if a.replay_days > 0 else None
            if hist is not None and not hist.empty:
                ui.step(f"Streaming dataset history {hist['timestamp'].min():%Y-%m-%d} to {hist['timestamp'].max():%Y-%m-%d %H:%M}")
                for ts, tick in hist.groupby("timestamp", sort=True):
                    today.flush(c, base)
                    n = 0
                    for i in range(0, len(tick), REPLAY_CHUNK):
                        n += _push(c, base, tick.iloc[i:i + REPLAY_CHUNK], ts, "data")
                        time.sleep(a.delay)
                    _close(c, base, ts, n, "data")
                ui.ok("dataset history finished")
            while a.loop:
                today.flush(c, base)
                time.sleep(5)
    except KeyboardInterrupt:
        print(ui.paint("\nstopped", ui.YELLOW))
    except httpx.HTTPError as e:
        ui.warn(f"cannot reach API at {base} ({e}). Start it first: python -m app.cli serve")
