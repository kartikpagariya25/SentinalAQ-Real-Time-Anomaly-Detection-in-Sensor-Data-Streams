"""`live-feed`: pushes demo readings to a running API over HTTP (today's hours as they complete, plus the dataset's history streamed continuously)."""
import time

import httpx
import pandas as pd

from . import ui
from .config import DATA_FILE
from .detector import RAW_COLS
from .priors import CITIES as ALL_CITIES
from .stream import simulate

RETRY_MAX_WAIT = 10


def _payload(tick):
    raw = tick[RAW_COLS].copy()
    raw["timestamp"] = raw["timestamp"].astype(str)
    rows = raw.astype(object).where(raw.notna(), None).to_dict("records")
    return [{k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()} for row in rows]


class Link:
    """HTTP client that keeps retrying connection errors, timeouts and 5xx answers until the API responds."""

    def __init__(self, base, headers):
        self.base = base
        self.client = httpx.Client(timeout=120, headers=headers)
        self.down = False

    def call(self, method, path, **kw):
        wait = 1
        while True:
            try:
                r = self.client.request(method, self.base + path, **kw)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError("server error", request=r.request, response=r)
                if self.down:
                    ui.ok("API is back, feed resumed")
                    self.down = False
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if not self.down:
                    ui.warn(f"API not answering ({type(e).__name__}); retrying until it is back")
                    self.down = True
                time.sleep(wait)
                wait = min(wait * 2, RETRY_MAX_WAIT)


def _push(link, tick):
    r = link.call("POST", "/ingest", json=_payload(tick))
    if r.status_code >= 400:
        ui.warn(f"API rejected a batch ({r.status_code}): {r.text[:160]}")
        return None
    return r.json()


def _close(link, ts, pushed, tag):
    link.call("POST", f"/close-hour/{ts.isoformat()}")
    r = link.call("GET", "/stats")
    if r.status_code == 200:
        st = r.json()["latest_window"]
        print(ui.paint(f"{ts:%Y-%m-%d %H:%M}  {tag:<6} pushed {pushed:>3}  |  window  V {st['valid']:<4} I {st['invalid']:<4} R {st['review']:<4}", ui.CYAN))


def _day_ticks(day, cities, seed):
    sim = simulate(day, 2, cities, seed + day.toordinal())
    return {ts: tick for ts, tick in sim.groupby("timestamp", sort=True) if ts >= day}


class Today:
    def __init__(self, cities, seed):
        self.cities, self.seed = cities, seed
        self.day, self.ticks, self.sent = None, {}, set()

    def flush(self, link):
        cur = pd.Timestamp.now().floor("h")
        if self.day != cur.normalize():
            self.day = cur.normalize()
            self.ticks = _day_ticks(self.day, self.cities, self.seed)
            self.sent = set()
            ui.step(f"live day: {self.day:%A %d %b %Y}")
        for ts in sorted(t for t in self.ticks if t <= cur and t not in self.sent):
            res = _push(link, self.ticks[ts])
            if res is not None and res.get("scored", 0):
                _close(link, ts, len(self.ticks[ts]), "live")
            self.sent.add(ts)


def _history(cities, days):
    if not DATA_FILE.exists():
        ui.warn("dataset not found, skipping history stream (run `python -m app.cli generate`)")
        return None
    df = pd.read_parquet(DATA_FILE, columns=RAW_COLS)
    if {x.lower() for x in cities} != {x.lower() for x in ALL_CITIES}:
        df = df[df["city"].isin(cities)]
    lo = df["timestamp"].max().normalize() - pd.Timedelta(days=days - 1)
    return df[df["timestamp"] >= lo]


def _session(a, link, today, cities):
    hj = link.call("GET", "/health").json()
    ui.ok(f"connected, model: {hj['model']}")
    if hj.get("last") and pd.Timestamp(hj["last"]) > pd.Timestamp.now():
        ui.warn(f"store holds future-dated readings (up to {hj['last']}) from an old run - restart with .\\run.ps1 -Fresh")
    today.flush(link)
    hist = _history(cities, a.replay_days) if a.replay_days > 0 else None
    if hist is not None and not hist.empty:
        ui.step(f"Streaming dataset history {hist['timestamp'].min():%Y-%m-%d} to {hist['timestamp'].max():%Y-%m-%d %H:%M}, one hour every {a.delay:g} s")
        for ts, tick in hist.groupby("timestamp", sort=True):
            began = time.time()
            today.flush(link)
            res = _push(link, tick)
            if res is None or res.get("scored", 0) == 0:
                continue
            _close(link, ts, len(tick), "data")
            time.sleep(max(0.0, a.delay - (time.time() - began)))
        ui.ok("dataset history finished")
    if not a.loop:
        return
    ui.step("Now live: each completed hour is scored as it arrives")
    while True:
        today.flush(link)
        time.sleep(5)


def run_live_feed(a):
    cities = [c.strip() for c in a.cities.split(",") if c.strip()]
    if any(c.lower() == "all" for c in cities):
        cities = list(ALL_CITIES.keys())
    base = a.url.rstrip("/")
    headers = {"X-API-Key": a.api_key} if a.api_key else {}
    ui.title(f"Live HTTP feed -> {base}/ingest")
    ui.step("Today's readings arrive as each hour completes; the dataset's past hours stream continuously in between. Nothing is stamped in the future. Ctrl+C to stop.")
    link = Link(base, headers)
    today = Today(cities, a.seed)
    try:
        while True:
            try:
                _session(a, link, today, cities)
                return
            except KeyboardInterrupt:
                raise
            except Exception as e:
                ui.warn(f"feed hit an error ({type(e).__name__}: {e}); restarting in 3 s")
                time.sleep(3)
    except KeyboardInterrupt:
        print(ui.paint("\nstopped", ui.YELLOW))
