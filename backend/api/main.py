import asyncio
import os
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import APIRouter, FastAPI, Request

from api.state import AppState
from api.stream_engine import StreamEngine
from api.routes_stations import router as stations_router
from api.routes_benchmark import router as benchmark_router
from api.routes_stream import router as stream_router

status_router = APIRouter()


@status_router.get("/api/stream/status")
def stream_status(request: Request):
    state = request.app.state.sentinelaq
    return {
        "paused": state.paused,
        "speed_multiplier": state.speed_multiplier,
        "rows_processed": state.rows_processed,
        "started_at": state.started_at.isoformat(),
    }


def create_app(dataset_path: str = "../sensor_data.csv",
               benchmark_csv_path: str | None = None,
               initial_speed: float = 60.0) -> FastAPI:
    benchmark_csv_path = benchmark_csv_path or os.path.join(
        os.path.dirname(__file__), "..", "benchmark_results_v3.csv"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        df = pd.read_csv(dataset_path, parse_dates=["timestamp"]) if not dataset_path.endswith(".parquet") \
            else pd.read_parquet(dataset_path)
        state = AppState.from_dataset(df, speed_multiplier=initial_speed)
        engine = StreamEngine(df, state)
        app.state.sentinelaq = state
        app.state.engine = engine
        app.state.benchmark_csv_path = benchmark_csv_path
        task = asyncio.create_task(engine.run())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(lifespan=lifespan)
    app.include_router(stations_router)
    app.include_router(benchmark_router)
    app.include_router(status_router)
    app.include_router(stream_router)
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(dataset_path=os.environ.get("SENTINELAQ_DATASET", "../sensor_data.csv")),
                host="127.0.0.1", port=8000)
