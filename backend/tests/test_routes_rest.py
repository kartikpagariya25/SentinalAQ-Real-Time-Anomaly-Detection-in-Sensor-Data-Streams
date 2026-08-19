import os
import sys
import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from api.main import create_app


@pytest.fixture
def client(tiny_dataset_csv, tmp_path):
    bench_path = tmp_path / "benchmark_results_v3.csv"
    pd.DataFrame({
        "": ["lof", "lof_corrected", "isolation_forest", "stl_residual"],
        "precision": [0.23, 0.23, 0.41, 0.59],
        "recall": [0.25, 0.25, 0.45, 0.26],
        "f1": [0.24, 0.24, 0.43, 0.37],
        "env_event_fp_rate": [0.07, 0.06, 0.94, 0.49],
    }).to_csv(bench_path, index=False)

    app = create_app(dataset_path=tiny_dataset_csv, benchmark_csv_path=str(bench_path), initial_speed=1_000_000)
    with TestClient(app) as c:
        yield c


def test_stations_endpoint(client):
    resp = client.get("/api/stations")
    assert resp.status_code == 200
    body = resp.json()
    ids = {s["station_id"] for s in body}
    assert ids == {"RESP-0001", "RESP-0002", "RESP-0003"}


def test_station_history_endpoint(client):
    import time
    time.sleep(1.0)  # let the engine (initial_speed=1e6, ~no sleep) process some rows
    resp = client.get("/api/stations/RESP-0001/history")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)


def test_benchmark_endpoint(client):
    resp = client.get("/api/benchmark")
    assert resp.status_code == 200
    body = resp.json()
    assert body["winner"] == "lof"
    assert "why" in body and len(body["why"]) > 0
    assert any(row["method"] == "lof" for row in body["table"])


def test_stream_status_endpoint(client):
    resp = client.get("/api/stream/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["paused"] is False
    assert "rows_processed" in body


@pytest.fixture
def client_with_missing_cell(tiny_dataset_csv, tmp_path):
    """Mirrors the real backend/benchmark_results_v3.csv, where missing_rule and
    duplicate_rule rows have no env_event_fp_rate value (empty cell -> NaN)."""
    bench_path = tmp_path / "benchmark_results_v3_missing.csv"
    pd.DataFrame({
        "": ["lof", "missing_rule", "duplicate_rule", "isolation_forest"],
        "precision": [0.23, 0.50, 0.60, 0.41],
        "recall": [0.25, 0.30, 0.35, 0.45],
        "f1": [0.24, 0.37, 0.44, 0.43],
        "env_event_fp_rate": [0.07, None, None, 0.94],
    }).to_csv(bench_path, index=False)

    app = create_app(dataset_path=tiny_dataset_csv, benchmark_csv_path=str(bench_path), initial_speed=1_000_000)
    with TestClient(app) as c:
        yield c


def test_benchmark_endpoint_handles_nan_cells(client_with_missing_cell):
    resp = client_with_missing_cell.get("/api/benchmark")
    assert resp.status_code == 200
    body = resp.json()
    rows_by_method = {row["method"]: row for row in body["table"]}
    assert rows_by_method["missing_rule"]["env_event_fp_rate"] is None
    assert rows_by_method["duplicate_rule"]["env_event_fp_rate"] is None
    assert rows_by_method["lof"]["env_event_fp_rate"] == pytest.approx(0.07)
