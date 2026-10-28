import os
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from .ingest import Ingestor, Store, period_window, PERIODS
from .model import load_bundle
from .report_pdf import build_report_pdf

app = FastAPI(title="SentinelAQ", version="2.0", description="Real-time validity check for air-quality sensor readings")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_state = {}
API_KEY = os.environ.get("SENTINEL_API_KEY")


def get_ingestor():
    if "ing" not in _state:
        _state["ing"] = Ingestor(load_bundle(), Store())
    return _state["ing"]


def check_key(x_api_key):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key")


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
    lo, hi = ing.store.span()
    return {"status": "ok", "model": ing.bundle["selection"]["winner"], "stored_readings": ing.store.count(),
            "devices": len(ing.store.devices()), "auth": bool(API_KEY), "first": lo, "last": hi}


@app.post("/ingest")
def ingest(readings: List[Reading], x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    if not readings:
        raise HTTPException(400, "empty batch")
    df = pd.DataFrame([r.model_dump() for r in readings])
    return get_ingestor().ingest(df)


@app.post("/close-hour/{ts}")
def close_hour(ts: str, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
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
    return _records(d)


@app.get("/readings/recent")
def recent(limit: int = 50, verdict: Optional[str] = None):
    d = get_ingestor().store.recent(limit, verdict)
    d["timestamp"] = d["timestamp"].astype(str)
    return _records(d)


@app.get("/stats")
def stats():
    ing = get_ingestor()
    r = ing.store.recent(500)
    lo, hi = ing.store.span()
    out = {"total": ing.store.count(), "devices": len(ing.store.devices()), "last": hi,
           "latest_window": {"valid": 0, "invalid": 0, "review": 0}, "recent_anomalies": [],
           "by_hour": ing.store.hourly(24)}
    if not r.empty:
        v = r["verdict"].value_counts()
        out["latest_window"] = {"valid": int(v.get("VALID", 0)), "invalid": int(v.get("INVALID", 0)), "review": int(v.get("REVIEW", 0))}
        an = r[r["verdict"] != "VALID"].head(20).copy()
        an["timestamp"] = an["timestamp"].astype(str)
        out["recent_anomalies"] = _records(an)
    return out


def _records(d):
    import math
    rows = d.astype(object).where(d.notna(), None).to_dict("records")
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()} for row in rows]


@app.get("/report/range")
def report_range(period: str = Query("daily"), date: Optional[str] = None, format: str = "json"):
    ing = get_ingestor()
    if period not in PERIODS:
        raise HTTPException(400, f"period must be one of {PERIODS}")
    anchor = date or ing.store.span()[1] or pd.Timestamp.utcnow()
    start, end = period_window(period, anchor)
    if format == "csv":
        csv = ing.store.range(start, end).to_csv(index=False)
        return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=sentinelaq_{period}_{pd.Timestamp(anchor).date()}.csv"})
    summary = ing.summary_range(start, end, period)
    if format == "pdf":
        pdf = build_report_pdf(summary)
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=sentinelaq_{period}_{pd.Timestamp(anchor).date()}.pdf"})
    return summary


@app.get("/report/{date}")
def report(date: str, format: str = "json"):
    ing = get_ingestor()
    if format == "csv":
        return PlainTextResponse(ing.store.day(date).to_csv(index=False), media_type="text/csv")
    if format == "pdf":
        return Response(build_report_pdf(ing.summary(date)), media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=sentinelaq_{date}.pdf"})
    return ing.summary(date)
