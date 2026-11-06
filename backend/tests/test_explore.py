from argparse import Namespace

import pandas as pd
import pytest

from app import explore


@pytest.fixture()
def data(tmp_path, monkeypatch):
    ts = pd.date_range("2025-01-01", periods=48, freq="h")
    df = pd.DataFrame({
        "timestamp": ts, "device_id": "DEL-01", "city": "Delhi", "pm25": 20.0, "temp": 25.0, "rh": 50.0,
        "fault_type": ["normal"] * 47 + ["spike"], "is_valid": [1] * 47 + [0],
        "fault_tier": "", "event_cause": "", "event_mult": 1.0,
    })
    path = tmp_path / "sensor_data.parquet"
    df.to_parquet(path)
    monkeypatch.setattr(explore, "DATA_FILE", path)
    monkeypatch.setattr(explore, "DEVICES_FILE", tmp_path / "devices.csv")
    return df


def args(**kw):
    base = dict(city=None, device=None, start=None, end=None, fault=None, export=None, rows=5, faults_only=False)
    return Namespace(**{**base, **kw})


def test_overview_without_filters(data, capsys):
    explore.peek(args())
    assert "Look closer" in capsys.readouterr().out


def test_end_alone_filters_instead_of_overview(data, capsys):
    explore.peek(args(end="2025-01-01 12:00"))
    out = capsys.readouterr().out
    assert "Look closer" not in out and "12 rows match" in out


def test_export_alone_writes_file(data, tmp_path, capsys):
    target = tmp_path / "all.csv"
    explore.peek(args(export=str(target)))
    assert len(pd.read_csv(target)) == 48
