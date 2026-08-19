import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from api.state import AppState
from api.stream_engine import StreamEngine, compute_sleep_seconds

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "streaming"))
import scoring  # noqa: E402


def test_engine_processes_all_rows_once(tiny_dataset_df):
    df = tiny_dataset_df.sort_values("timestamp").reset_index(drop=True)
    state = AppState.from_dataset(df, speed_multiplier=1_000_000)  # effectively no sleep
    engine = StreamEngine(df, state)

    async def run_briefly():
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_briefly())

    assert state.rows_processed >= len(df)  # at least one full pass
    assert "RESP-0001" in state.history
    assert len(state.history["RESP-0001"]) > 0


def test_flatline_row_flagged_and_broadcast(tiny_dataset_df):
    df = tiny_dataset_df.sort_values("timestamp").reset_index(drop=True)
    state = AppState.from_dataset(df, speed_multiplier=1_000_000)
    engine = StreamEngine(df, state)

    sent = []

    class FakeClient:
        async def send_json(self, msg):
            sent.append(msg)

    state.clients.add(FakeClient())

    async def run_briefly():
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_briefly())

    flatline_msgs = [m for m in sent if m["type"] == "detection" and "flatline" in m["detectors_fired"]]
    assert len(flatline_msgs) > 0


def test_compute_sleep_seconds_uses_global_delta_not_capped():
    # 300s real gap at 60x speed -> 5.0s, exactly at the cap.
    assert compute_sleep_seconds(300.0, 60.0) == pytest.approx(5.0)
    # 6s real gap (e.g. the global-stream gap between interleaved stations)
    # at 60x speed -> 0.1s. This is the regression check for Finding 1: before
    # the fix, sleep was computed from the per-station delta (~300s) even
    # though rows arrive globally much closer together, making replay ~50x
    # slower than intended.
    assert compute_sleep_seconds(6.0, 60.0) == pytest.approx(0.1)


def test_compute_sleep_seconds_respects_cap():
    assert compute_sleep_seconds(3000.0, 1.0) == pytest.approx(5.0)


def test_z_hist_bounded_after_many_rows():
    """Regression test for Finding 2: z_hist must not grow unboundedly across a
    dataset wraparound (where the global timestamp jumps backward and the
    time-based prune condition becomes permanently false)."""
    state = scoring.StationState()
    states = {"A": state}
    neighbor_map = {"A": []}
    t = 0
    for i in range(1000):
        values = {"pm25": 50.0, "pm10": 80.0, "no2": 20.0, "co": 1.0, "temperature": 25.0, "humidity": 40.0}
        scoring.score_row("A", t, values, False, state, states, neighbor_map)
        t += 5 * 60 * 1_000_000_000  # keep advancing so the time-based prune stays a no-op path too
    assert len(state.z_hist) <= 500

    # Now simulate a wraparound: timestamp jumps back to the start, which would
    # make the time-based prune condition permanently false without the maxlen cap.
    t = 0
    for i in range(1000):
        values = {"pm25": 50.0, "pm10": 80.0, "no2": 20.0, "co": 1.0, "temperature": 25.0, "humidity": 40.0}
        scoring.score_row("A", t, values, False, state, states, neighbor_map)
        t += 1_000_000_000
    assert len(state.z_hist) <= 500
