"""API contract tests. They use an empty in-memory store and no model, so they
run on a clean checkout (no data file, no trained detector needed)."""
import pytest
from fastapi.testclient import TestClient

from app import api
from app.ingest import Ingestor, Store


@pytest.fixture()
def client():
    api._state["ing"] = Ingestor(None, Store(":memory:"))
    yield TestClient(api.app)
    api._state.clear()


@pytest.mark.parametrize("url", ["/readings?date=nope", "/report/nope", "/report/range?date=zzz"])
def test_bad_dates_are_400(client, url):
    assert client.get(url).status_code == 400


def test_bad_close_hour_is_400(client):
    assert client.post("/close-hour/nope").status_code == 400


def test_bad_ingest_timestamp_is_400(client):
    body = [{"timestamp": "garbage", "device_id": "D", "city": "Delhi", "pm25": 5.0}]
    assert client.post("/ingest", json=body).status_code == 400


def test_empty_ingest_batch_is_400(client):
    assert client.post("/ingest", json=[]).status_code == 400


@pytest.mark.parametrize("limit", [-1, 0, 5001])
def test_limit_is_bounded(client, limit):
    assert client.get(f"/readings/recent?limit={limit}").status_code == 422
    assert client.get(f"/readings?date=2026-01-01&limit={limit}").status_code == 422


def test_unknown_format_is_rejected(client):
    assert client.get("/report/range?format=xml").status_code == 422
    assert client.get("/report/2026-01-01?format=xml").status_code == 422


def test_empty_store_reports(client):
    s = client.get("/report/range?period=weekly&date=2026-01-07").json()
    assert s["readings"] == 0 and s["by_day"] == []
    assert client.get("/report/2026-01-01?format=csv").headers["content-disposition"].endswith(".csv")
    assert client.get("/report/range?format=pdf").content[:4] == b"%PDF"


def test_api_key_is_enforced(client, monkeypatch):
    monkeypatch.setattr(api, "API_KEY", "secret")
    body = [{"timestamp": "2026-01-01T00:00:00", "device_id": "D", "city": "Delhi", "pm25": 5.0}]
    assert client.post("/ingest", json=body).status_code == 401
    assert client.post("/close-hour/2026-01-01T00:00:00").status_code == 401
