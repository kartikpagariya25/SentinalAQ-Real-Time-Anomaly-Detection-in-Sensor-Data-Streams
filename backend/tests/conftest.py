import pandas as pd
import pytest


@pytest.fixture
def tiny_dataset_df():
    """3 stations, 12 rows each, 5-minute cadence, one flatline run and one missing row."""
    rows = []
    stations = [
        ("RESP-0001", 28.6, 77.2),
        ("RESP-0002", 28.7, 77.3),   # close neighbor of RESP-0001
        ("RESP-0003", 19.0, 72.8),   # far away, no neighbors within 20km
    ]
    start = pd.Timestamp("2025-01-01 00:00:00")
    record_id = 1
    for sid, lat, lon in stations:
        for i in range(12):
            ts = start + pd.Timedelta(minutes=5 * i)
            pm25 = 50.0
            is_missing = 0
            if sid == "RESP-0001" and 6 <= i < 10:
                pm25 = 60.0  # flatline run
            if sid == "RESP-0002" and i == 5:
                is_missing = 1
            rows.append({
                "record_id": record_id, "station_id": sid,
                "latitude": lat, "longitude": lon, "timestamp": ts,
                "pm25": None if is_missing else pm25,
                "pm10": None if is_missing else 80.0,
                "no2": None if is_missing else 20.0,
                "co": None if is_missing else 1.0,
                "temperature": 25.0, "humidity": 40.0,
                "is_missing": is_missing, "is_regional_event": 0,
                "anomaly_type": "normal", "anomaly_subtype": "none",
            })
            record_id += 1
    return pd.DataFrame(rows)


@pytest.fixture
def tiny_dataset_csv(tmp_path, tiny_dataset_df):
    path = tmp_path / "tiny_sensor_data.csv"
    tiny_dataset_df.to_csv(path, index=False)
    return str(path)
