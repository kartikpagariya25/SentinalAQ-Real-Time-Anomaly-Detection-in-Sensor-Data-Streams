import os
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "streaming"))
import scoring  # noqa: E402

HISTORY_MAXLEN = 500


@dataclass
class AppState:
    stations: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    clients: set = field(default_factory=set)
    speed_multiplier: float = 60.0
    paused: bool = False
    rows_processed: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    station_meta: list = field(default_factory=list)
    neighbor_map: dict = field(default_factory=dict)

    @classmethod
    def from_dataset(cls, df: pd.DataFrame, speed_multiplier: float = 60.0) -> "AppState":
        meta_df = df[["station_id", "latitude", "longitude"]].drop_duplicates("station_id")
        station_meta = [
            {"station_id": r.station_id, "latitude": float(r.latitude), "longitude": float(r.longitude)}
            for r in meta_df.itertuples()
        ]
        neighbor_map = {
            sid: list(neighbors)
            for sid, neighbors in scoring.build_neighbor_map(df, scoring.SPATIAL_RADIUS_KM).items()
        }
        return cls(speed_multiplier=speed_multiplier, station_meta=station_meta, neighbor_map=neighbor_map)

    def get_or_create_station(self, sid: str) -> scoring.StationState:
        if sid not in self.stations:
            self.stations[sid] = scoring.StationState()
            self.history[sid] = deque(maxlen=HISTORY_MAXLEN)
        return self.stations[sid]
