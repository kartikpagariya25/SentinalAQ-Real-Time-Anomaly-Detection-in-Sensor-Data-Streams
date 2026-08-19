from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/stream")
async def stream_ws(websocket: WebSocket):
    await websocket.accept()
    state = websocket.app.state.sentinelaq
    state.clients.add(websocket)

    snapshot = {
        "type": "snapshot",
        "stations": {sid: list(hist)[-1] if hist else None for sid, hist in state.history.items()},
    }
    await websocket.send_json(snapshot)

    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")
            if action == "set_speed" and "value" in msg:
                state.speed_multiplier = float(msg["value"])
            elif action == "pause":
                state.paused = True
            elif action == "resume":
                state.paused = False
    except WebSocketDisconnect:
        pass
    finally:
        state.clients.discard(websocket)
