from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .ingest import Ingestor, Store
from .model import load_bundle

app = FastAPI(title="SentinelAQ", version="1.0")
_state = {}


def get_ingestor():
    if "ing" not in _state:
        _state["ing"] = Ingestor(load_bundle(), Store())
    return _state["ing"]


class Reading(BaseModel):
    timestamp: str
    device_id: str
    city: str
    pm25: Optional[float] = None
    temp: Optional[float] = None
    rh: Optional[float] = None


@app.get("/health")
def health():
    ing = get_ingestor()
    return {"status": "ok", "model": ing.bundle["selection"]["winner"], "stored_readings": ing.store.count(), "devices": len(ing.store.devices())}


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
