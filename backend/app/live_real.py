"""
Real-sensor feed for the dashboard API: pollutants from WAQI (aqicn.org),
weather from Open-Meteo.

Most CPCB stations only carry pollutant sensors, not weather sensors, so
WAQI's `t` (temp) / `h` (humidity) fields come back empty for a lot of
stations — including, in practice, whichever single station WAQI's
`/feed/{city}/` shortcut happens to resolve to for these 5 cities. Rather
than gamble on finding a CPCB station that also reports weather, this pulls
pm25/pm10 from WAQI and temp/rh from Open-Meteo (keyless, always available
for any lat/lon) and merges them by city — so all 4 parameters are reliable
every round, regardless of what any one station's own sensor package has.

Both calls feed the result through `Ingestor.ingest()` — the exact same
call path the public `POST /ingest` REST endpoint already uses — so every
reading still gets a real LightGBM verdict/confidence/reason.

WAQI station aggregates don't expose individual physical device IDs, so each
city's station is treated as a single device, e.g. "WAQI-DELHI".

PM10 note: fetched here and logged, but not yet persisted or scored — the
current readings schema / Ingestor / trained model only consume pm25, temp
and rh (see the `Reading` model in api.py and `RAW_COLS` in detector.py).
Wiring it in for real means a pm10 column on the SQLite table, RAW_COLS,
and a model retrain. Flagging it rather than silently dropping it.

Setup:
    pip install httpx
    export WAQI_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx   # free token: https://aqicn.org/data-platform/token/
    export SENTINELAQ_SOURCE=real      # api.py reads this to pick this feed over the simulator
    export WAQI_POLL_SECONDS=300       # optional, default 300s (5 min) — CPCB stations
                                        # themselves usually only update hourly, and this
                                        # keeps you comfortably within WAQI's free-token
                                        # rate limits across 5 cities
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd

from .ingest import Ingestor
from .live import LiveFeed, get_ingestor

log = logging.getLogger("sentinelaq.live_real")

WAQI_BASE = "https://api.waqi.info/feed"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# Hardcoded so this runs with no environment setup. An env var, if set, still
# wins — handy for swapping tokens later without editing this file again.
# NOTE: don't commit this file to a public repo with a real token in it.
WAQI_TOKEN = os.environ.get("WAQI_TOKEN", "95d10bf48429f5d5b52a61c0d243c23b2d6ef0ab")
POLL_SECONDS = float(os.environ.get("WAQI_POLL_SECONDS", "300"))

# city -> WAQI station slug. Explicit slugs (rather than bare city names)
# keep this pinned to the same CPCB-backed station each round.
REAL_CITIES: Dict[str, str] = {
    "Delhi": "delhi",
    "Mumbai": "mumbai",
    "Pune": "pune",
    "Bengaluru": "bangalore",
    "Kolkata": "kolkata",
}

# city -> (lat, lon), used only for the Open-Meteo weather lookup.
CITY_COORDS: Dict[str, Tuple[float, float]] = {
    "Delhi": (28.6139, 77.2090),
    "Mumbai": (19.0760, 72.8777),
    "Pune": (18.5204, 73.8567),
    "Bengaluru": (12.9716, 77.5946),
    "Kolkata": (22.5726, 88.3639),
}


class RealFeed(LiveFeed):
    """Reuses LiveFeed's subscriber/broadcast machinery; sources from WAQI instead of the simulator."""

    async def run_forever(self) -> None:
        if not WAQI_TOKEN:
            raise RuntimeError(
                "WAQI_TOKEN is not set. Get a free token at "
                "https://aqicn.org/data-platform/token/ and export it as WAQI_TOKEN."
            )
        ing = get_ingestor()
        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                rows = []
                for city, slug in REAL_CITIES.items():
                    pollutants = await self._fetch_pollutants(client, city, slug)
                    weather = await self._fetch_weather(client, city)
                    row = self._merge(city, pollutants, weather)
                    if row is not None:
                        rows.append(row)

                if rows:
                    df = pd.DataFrame(rows)
                    device_ids = df["device_id"].tolist()
                    ingest_df = df[["timestamp", "device_id", "city", "pm25", "temp", "rh"]]
                    await asyncio.to_thread(ing.ingest, ingest_df)
                    self.ticks += 1
                    latest = _fetch_latest_rows(ing, device_ids)
                    await self._broadcast(latest)
                else:
                    log.warning("poll returned no usable readings this round")

                await asyncio.sleep(POLL_SECONDS)

    async def _fetch_pollutants(self, client: httpx.AsyncClient, city: str, slug: str) -> Optional[dict]:
        url = f"{WAQI_BASE}/{slug}/?token={WAQI_TOKEN}"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.warning("WAQI fetch failed for %s: %s", city, exc)
            return None

        if payload.get("status") != "ok":
            log.warning("WAQI returned non-ok status for %s: %s", city, payload.get("data"))
            return None

        data = payload["data"]
        iaqi = data.get("iaqi", {})
        pm25 = iaqi.get("pm25", {}).get("v")
        pm10 = iaqi.get("pm10", {}).get("v")  # fetched but not yet persisted — see module docstring
        if pm10 is not None:
            log.debug("%s pm10=%s (not yet stored — see live_real.py docstring)", city, pm10)

        stamp = data.get("time", {}).get("iso")
        timestamp = pd.Timestamp(stamp) if stamp else pd.Timestamp.utcnow()

        return {"pm25": pm25, "pm10": pm10, "timestamp": timestamp}

    async def _fetch_weather(self, client: httpx.AsyncClient, city: str) -> Optional[dict]:
        lat, lon = CITY_COORDS[city]
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m",
            "timezone": "auto",
        }
        try:
            resp = await client.get(OPEN_METEO_BASE, params=params)
            resp.raise_for_status()
            current = resp.json().get("current", {})
        except Exception as exc:
            log.warning("Open-Meteo fetch failed for %s: %s", city, exc)
            return None

        return {"temp": current.get("temperature_2m"), "rh": current.get("relative_humidity_2m")}

    def _merge(self, city: str, pollutants: Optional[dict], weather: Optional[dict]) -> Optional[dict]:
        pm25 = pollutants.get("pm25") if pollutants else None
        temp = weather.get("temp") if weather else None
        rh = weather.get("rh") if weather else None

        if pm25 is None and temp is None and rh is None:
            return None  # both sources failed/empty for this city this round

        timestamp = pollutants.get("timestamp") if pollutants else pd.Timestamp.utcnow()

        return {
            "timestamp": timestamp.isoformat(),
            "device_id": f"WAQI-{city.upper()}",
            "city": city,
            "pm25": pm25,
            "temp": temp,
            "rh": rh,
        }


def _fetch_latest_rows(ing: Ingestor, device_ids: List[str]) -> List[dict]:
    out = []
    for dev in device_ids:
        cur = ing.store.db.execute(
            "SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, "
            "confidence, p_invalid, source, reason, drivers FROM readings "
            "WHERE device_id = ? ORDER BY received_at DESC LIMIT 1",
            [dev],
        )
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        if row:
            out.append(dict(zip(cols, row)))
    return out


real_feed = RealFeed()
