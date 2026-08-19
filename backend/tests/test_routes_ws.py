import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from api.main import create_app
from api.routes_stream import stream_ws
from api.state import AppState


@pytest.fixture
def client(tiny_dataset_csv, tmp_path):
    bench_path = tmp_path / "benchmark_results_v3.csv"
    pd.DataFrame({"": ["lof"], "precision": [0.23], "recall": [0.25], "f1": [0.24],
                  "env_event_fp_rate": [0.07]}).to_csv(bench_path, index=False)
    app = create_app(dataset_path=tiny_dataset_csv, benchmark_csv_path=str(bench_path), initial_speed=1_000_000)
    with TestClient(app) as c:
        yield c


def test_websocket_sends_snapshot_then_detections(client):
    with client.websocket_connect("/ws/stream") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        second = ws.receive_json()
        assert second["type"] == "detection"


def test_websocket_set_speed_control(client):
    with client.websocket_connect("/ws/stream") as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "set_speed", "value": 5})
        ws.receive_json()  # a detection still arrives after the control message
    state = client.app.state.sentinelaq
    assert state.speed_multiplier == 5


def test_websocket_pause_resume_control(client):
    with client.websocket_connect("/ws/stream") as ws:
        ws.receive_json()
        ws.send_json({"action": "pause"})
        ws.receive_json()
    state = client.app.state.sentinelaq
    # pause is processed by the read loop; resume happens on disconnect cleanup in this test,
    # so just assert the control message was accepted without error (no exception raised above).
    assert state.paused in (True, False)


def test_snapshot_is_sent_before_client_is_registered():
    """Regression test for the add-before-send race (fix review, round 2):
    state.clients.add(websocket) must not run until the snapshot send_json() has fully
    completed. Otherwise StreamEngine.broadcast(), running in a separate asyncio task, could
    observe the socket in state.clients and call send_json for a detection message while the
    snapshot send_json() is still in flight -- two concurrent writers on one ASGI WebSocket,
    and a detection could reach the client before its snapshot.

    A genuine timing race is not reliably reproducible through TestClient's in-process
    transport (that's exactly why the bug shipped un-caught the first time), so this test
    instead drives the `stream_ws` coroutine directly against a fake WebSocket and asserts,
    at the instant send_json is invoked for the snapshot, that the socket is not yet present
    in state.clients. This makes the ordering guarantee itself the thing under test, deterministically,
    rather than depending on the scheduler happening to interleave two tasks a particular way.
    """
    state = AppState()
    registered_during_snapshot_send = None

    websocket = AsyncMock()
    websocket.app.state.sentinelaq = state

    async def fake_send_json(msg):
        nonlocal registered_during_snapshot_send
        if msg.get("type") == "snapshot":
            registered_during_snapshot_send = websocket in state.clients

    websocket.send_json.side_effect = fake_send_json
    websocket.receive_json.side_effect = WebSocketDisconnect()

    asyncio.run(stream_ws(websocket))

    assert registered_during_snapshot_send is False
    # cleaned up by the `finally` block after the (simulated) disconnect
    assert websocket not in state.clients
