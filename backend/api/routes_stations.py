from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


@router.get("/api/stations")
def list_stations(request: Request):
    state = request.app.state.sentinelaq
    return state.station_meta


@router.get("/api/stations/{station_id}/history")
def station_history(station_id: str, request: Request):
    state = request.app.state.sentinelaq
    if station_id not in state.history:
        raise HTTPException(status_code=404, detail="unknown station_id")
    return list(state.history[station_id])
