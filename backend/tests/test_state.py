import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from api.state import AppState


def test_from_dataset_builds_station_meta_and_neighbor_map(tiny_dataset_df):
    state = AppState.from_dataset(tiny_dataset_df)
    ids = {s["station_id"] for s in state.station_meta}
    assert ids == {"RESP-0001", "RESP-0002", "RESP-0003"}
    assert "RESP-0002" in state.neighbor_map["RESP-0001"]
    assert state.neighbor_map["RESP-0003"] == []
    assert state.speed_multiplier == 60.0
    assert state.rows_processed == 0
    assert state.paused is False
