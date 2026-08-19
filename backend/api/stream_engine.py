# backend/api/stream_engine.py
import asyncio
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "streaming"))
import scoring  # noqa: E402

from api.state import AppState


class StreamEngine:
    def __init__(self, df: pd.DataFrame, state: AppState):
        self.df = df.sort_values("timestamp").reset_index(drop=True)
        self.state = state
        self._core_cols = ["pm25", "pm10", "no2", "co"]

    async def run(self):
        n = len(self.df)
        stations = self.df["station_id"].to_numpy()
        ts_ns = self.df["timestamp"].values.astype("datetime64[ns]").astype("int64")
        values_by_col = {c: self.df[c].to_numpy(dtype=float) for c in scoring.FEATURE_COLS}
        nan_mask = self.df[self._core_cols].isna().any(axis=1).to_numpy()
        timestamps_iso = self.df["timestamp"].astype(str).to_numpy()

        prev_ts_by_station = {}

        while True:  # loop the dataset forever so a local demo never runs dry
            for i in range(n):
                while self.state.paused:
                    await asyncio.sleep(0.1)

                sid = stations[i]
                t = int(ts_ns[i])
                state_obj = self.state.get_or_create_station(sid)

                real_delta = 300.0  # seconds; dataset default cadence
                if sid in prev_ts_by_station:
                    real_delta = max(0.0, (t - prev_ts_by_station[sid]) / 1e9)
                prev_ts_by_station[sid] = t
                sleep_for = min(real_delta / max(self.state.speed_multiplier, 1e-6), 5.0)
                # Below typical OS timer granularity (~15ms on Windows), a real sleep
                # rounds up to a full tick and throttles throughput for no benefit at
                # high speed_multiplier. Use asyncio.sleep(0) instead: it still yields
                # control to the event loop each row (so cancellation/other tasks can
                # run) without paying for a timer callback.
                await asyncio.sleep(sleep_for if sleep_for > 0.005 else 0)

                try:
                    nan = bool(nan_mask[i])
                    values = {c: float(values_by_col[c][i]) if not np.isnan(values_by_col[c][i]) else 0.0
                              for c in scoring.FEATURE_COLS}
                    flag, spatial_label, detectors_fired, _ = scoring.score_row(
                        sid, t, values, nan, state_obj, self.state.stations, self.state.neighbor_map
                    )

                    message = {
                        "type": "detection",
                        "station_id": str(sid),
                        "timestamp": str(timestamps_iso[i]),
                        "readings": None if nan else values,
                        "flag": flag,
                        "spatial_label": spatial_label,
                        "detectors_fired": detectors_fired,
                    }
                    self.state.history[sid].append(message)
                    self.state.rows_processed += 1
                    await self.broadcast(message)
                except Exception as exc:  # one bad row must never kill the loop for every client
                    print(f"[StreamEngine] error scoring row {i} (station {sid}): {exc!r}")
                    continue

    async def broadcast(self, message: dict):
        dead = []
        for client in list(self.state.clients):
            try:
                await client.send_json(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self.state.clients.discard(client)
