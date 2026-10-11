"""
Real-time feed for the dashboard API.

Unlike a pure demo/mocked stream, this drives the ACTUAL trained bundle
(models/detector.joblib) over the ACTUAL synthetic network (data/synthetic),
through the same `Ingestor` the REST `/ingest` endpoint uses — it just does
it continuously, in the background, at a readable pace, instead of waiting
for an external client to POST batches.

Every reading seen by the dashboard therefore carries a real LightGBM
verdict/confidence/reason, not a stand-in rule set.
"""
from __future__ import annotations

import asyncio
import random
from typing import Dict, List, Optional

import pandas as pd

from .config import ROOT
from .detector import RAW_COLS
from .ingest import Ingestor, Store
from .model import load_bundle
from .priors import CITIES
from .stream import simulate

TICK_SECONDS = 2.5          # wall-clock seconds between simulated hours
WINDOW_DAYS = 3             # length of one simulated window before looping
LIVE_CITIES = ["Delhi", "Mumbai", "Pune", "Bengaluru", "Kolkata"]
START_DATE = "2026-11-07"   # matches the window the shipped synthetic data covers

_state: Dict[str, object] = {}


def get_ingestor() -> Ingestor:
    if "ing" not in _state:
        _state["ing"] = Ingestor(load_bundle(), Store())
    return _state["ing"]


class LiveFeed:
    """Streams the real pipeline's output and fans it out to subscribers."""

    def __init__(self) -> None:
        self.subscribers: List[asyncio.Queue] = []
        self.ticks = 0
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        async with self._lock:
            self.subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    async def _broadcast(self, rows: List[dict]) -> None:
        async with self._lock:
            for q in self.subscribers:
                if not q.full():
                    q.put_nowait(rows)

    async def run_forever(self) -> None:
        ing = get_ingestor()
        seed = 2026
        while True:
            start = pd.Timestamp(START_DATE) + pd.Timedelta(days=random.randint(0, 20))
            sim = simulate(str(start.date()), WINDOW_DAYS, LIVE_CITIES, seed)
            for ts, tick in sim.groupby("timestamp", sort=True):
                if ts < start:
                    continue  # part of the warm-up lead window, not a "live" hour
                raw = tick[RAW_COLS]
                raw = raw[raw["pm25"].notna() | raw["temp"].notna() | raw["rh"].notna()]
                if raw.empty:
                    await asyncio.sleep(TICK_SECONDS)
                    continue
                result = await asyncio.to_thread(ing.ingest, raw)
                await asyncio.to_thread(ing.close_hour, ts)
                self.ticks += 1
                rows = _fetch_latest_rows(ing, raw["device_id"].tolist(), ts)
                await self._broadcast(rows)
                await asyncio.sleep(TICK_SECONDS)
            seed += 1


def _fetch_latest_rows(ing: Ingestor, device_ids: List[str], ts: pd.Timestamp) -> List[dict]:
    marks = ",".join("?" * len(device_ids))
    q = (f"SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, "
         f"confidence, p_invalid, source, reason, drivers FROM readings "
         f"WHERE ts = ? AND device_id IN ({marks})")
    cur = ing.store.db.execute(q, [ts.isoformat(), *device_ids])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


feed = LiveFeed()
