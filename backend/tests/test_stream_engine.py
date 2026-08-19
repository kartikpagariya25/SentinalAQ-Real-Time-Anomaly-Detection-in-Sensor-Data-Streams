import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from api.state import AppState
from api.stream_engine import StreamEngine


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
