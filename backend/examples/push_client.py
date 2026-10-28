"""Minimal example of how an upstream pipeline pushes readings to SentinelAQ.

Run the API first:  python -m app.cli serve
Then:               python examples/push_client.py
"""
import os

import httpx

API = os.environ.get("SENTINEL_URL", "http://127.0.0.1:8000")
KEY = os.environ.get("SENTINEL_API_KEY")
HEADERS = {"X-API-Key": KEY} if KEY else {}

batch = [
    {"timestamp": "2026-09-16T09:00:00", "device_id": "DEL-01", "city": "Delhi", "pm25": 24.5, "temp": 31.2, "rh": 48},
    {"timestamp": "2026-09-16T09:00:00", "device_id": "DEL-02", "city": "Delhi", "pm25": 3333, "temp": 31.0, "rh": 47},
    {"timestamp": "2026-09-16T09:00:00", "device_id": "PNQ-01", "city": "Pune", "pm25": 18.1, "temp": 28.4, "rh": 61},
]

with httpx.Client(timeout=30, headers=HEADERS) as c:
    r = c.post(f"{API}/ingest", json=batch)
    r.raise_for_status()
    print("ingest:", r.json())

    # tell the service the hour is closed, so devices that sent nothing are marked as dropout
    c.post(f"{API}/close-hour/2026-09-16T09:00:00")

    print("day report:", c.get(f"{API}/report/2026-09-16").json())
