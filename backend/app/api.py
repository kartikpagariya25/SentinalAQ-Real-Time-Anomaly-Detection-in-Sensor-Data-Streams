import asyncio
import os
from contextlib import asynccontextmanager
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .live import feed as _simulated_feed, get_ingestor
from .live_real import real_feed as _real_feed

# Hardcoded to "real" so no environment setup is needed to use the WAQI +
# Open-Meteo feed. An env var, if set, still wins:
#   SENTINELAQ_SOURCE=real       -> live WAQI/CPCB + Open-Meteo readings (live_real.py)
#   SENTINELAQ_SOURCE=simulated  -> synthetic pipeline (live.py)
LIVE_SOURCE = os.environ.get("SENTINELAQ_SOURCE", "real").lower()
feed = _real_feed if LIVE_SOURCE == "real" else _simulated_feed
print(f"[SentinelAQ] SENTINELAQ_SOURCE={LIVE_SOURCE!r} -> using "
      f"{'RealFeed (WAQI + Open-Meteo)' if feed is _real_feed else 'LiveFeed (simulator)'}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(feed.run_forever())
    yield
    task.cancel()


app = FastAPI(title="SentinelAQ", version="1.0", lifespan=lifespan)

# Allows a separately-hosted frontend (opened from disk, a different port, or
# a dev server) to call this API. Safe to narrow to specific origins later.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Reading(BaseModel):
    timestamp: str
    device_id: str
    city: str
    pm25: Optional[float] = None
    temp: Optional[float] = None
    rh: Optional[float] = None


# --------------------------------------------------------------------------
# Original endpoints — unchanged behaviour.
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    ing = get_ingestor()
    return {"status": "ok", "model": ing.bundle["selection"]["winner"], "stored_readings": ing.store.count(), "devices": len(ing.store.devices()), "live_ticks": feed.ticks}


@app.post("/ingest")
def ingest(readings: List[Reading]):
    if not readings:
        raise HTTPException(400, "empty batch")
    df = pd.DataFrame([r.model_dump() for r in readings])
    return get_ingestor().ingest(df)


@app.post("/close-hour/{ts}")
def close_hour(ts: str):
    return {"dropouts_recorded": get_ingestor().close_hour(ts)}


@app.get("/readings")
def readings(date: str, device: Optional[str] = None, verdict: Optional[str] = None, limit: int = 200):
    d = get_ingestor().store.day(date)
    if device:
        d = d[d["device_id"] == device]
    if verdict:
        d = d[d["verdict"] == verdict.upper()]
    d = d.head(limit).copy()
    d["timestamp"] = d["timestamp"].astype(str)
    return d.where(d.notna(), None).to_dict("records")


@app.get("/report/{date}")
def report(date: str, format: str = "json"):
    ing = get_ingestor()
    if format == "csv":
        return PlainTextResponse(ing.store.day(date).to_csv(index=False), media_type="text/csv")
    return ing.summary(date)


# --------------------------------------------------------------------------
# Dashboard API — reads from the same SQLite store the live feed (live.py)
# fills continuously in the background using the real trained model.
# --------------------------------------------------------------------------
def _rows(sql: str, params: list) -> List[dict]:
    ing = get_ingestor()
    cur = ing.store.db.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


@app.get("/api/overview")
def api_overview():
    ing = get_ingestor()
    total = ing.store.count()
    row = ing.store.db.execute(
        "SELECT verdict, COUNT(*) FROM readings WHERE received_at >= datetime('now', '-60 minutes') GROUP BY verdict"
    ).fetchall()
    counts = {k: v for k, v in row}
    window_total = sum(counts.values())
    events = ing.store.db.execute(
        "SELECT COUNT(*) FROM readings WHERE detected_as = 'pollution_event' AND received_at >= datetime('now', '-60 minutes')"
    ).fetchone()[0]
    mean_conf = ing.store.db.execute(
        "SELECT AVG(confidence) FROM readings WHERE received_at >= datetime('now', '-60 minutes')"
    ).fetchone()[0]
    return {
        "model": ing.bundle["selection"]["winner"],
        "live_ticks": feed.ticks,
        "devices": len(ing.store.devices()),
        "stored_readings": total,
        "window_readings": window_total,
        "valid": counts.get("VALID", 0),
        "review": counts.get("REVIEW", 0),
        "invalid": counts.get("INVALID", 0),
        "valid_pct": round(100 * counts.get("VALID", 0) / window_total, 1) if window_total else 0.0,
        "mean_confidence": round(mean_conf, 3) if mean_conf else 0.0,
        "pollution_events": events,
    }


@app.get("/api/devices")
def api_devices():
    ing = get_ingestor()
    devices = ing.store.devices()
    out = []
    for dev in devices:
        latest = _rows(
            "SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, confidence, reason "
            "FROM readings WHERE device_id = ? ORDER BY ts DESC LIMIT 1", [dev],
        )
        out.append({"device_id": dev, "city": latest[0]["city"] if latest else None, "latest": latest[0] if latest else None})
    return sorted(out, key=lambda d: (d["city"] or "", d["device_id"]))


@app.get("/api/readings/recent")
def api_recent(limit: int = 100, device: Optional[str] = None, city: Optional[str] = None, verdict: Optional[str] = None):
    sql = ("SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, "
           "confidence, reason FROM readings WHERE 1=1")
    params: list = []
    if device:
        sql += " AND device_id = ?"
        params.append(device)
    if city:
        sql += " AND city = ?"
        params.append(city)
    if verdict:
        sql += " AND verdict = ?"
        params.append(verdict.upper())
    sql += " ORDER BY received_at DESC LIMIT ?"
    params.append(limit)
    return _rows(sql, params)


@app.get("/api/timeseries")
def api_timeseries(device: Optional[str] = None, minutes: int = 30, limit: int = 400):
    sql = ("SELECT ts AS timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, confidence "
           "FROM readings WHERE received_at >= datetime('now', ?)")
    params: list = [f"-{minutes} minutes"]
    if device:
        sql += " AND device_id = ?"
        params.append(device)
    sql += " ORDER BY received_at ASC LIMIT ?"
    params.append(limit)
    return _rows(sql, params)


@app.get("/api/anomalies/breakdown")
def api_breakdown():
    rows = ing_breakdown()
    return {r[0]: r[1] for r in rows}


def ing_breakdown():
    ing = get_ingestor()
    return ing.store.db.execute(
        "SELECT detected_as, COUNT(*) FROM readings WHERE verdict != 'VALID' GROUP BY detected_as ORDER BY 2 DESC"
    ).fetchall()


@app.get("/api/cities")
def api_cities():
    ing = get_ingestor()
    rows = ing.store.db.execute(
        "SELECT city, COUNT(*), AVG(pm25), "
        "SUM(CASE WHEN verdict='VALID' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN verdict='REVIEW' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN verdict='INVALID' THEN 1 ELSE 0 END) "
        "FROM readings GROUP BY city ORDER BY city"
    ).fetchall()
    return [
        {"city": c, "readings": n, "avg_pm25": round(avg, 1) if avg is not None else None,
         "valid": v, "review": r, "invalid": i}
        for c, n, avg, v, r, i in rows
    ]


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    q = await feed.subscribe()
    try:
        while True:
            rows = await q.get()
            await websocket.send_json(rows)
    except WebSocketDisconnect:
        pass
    finally:
        await feed.unsubscribe(q)
