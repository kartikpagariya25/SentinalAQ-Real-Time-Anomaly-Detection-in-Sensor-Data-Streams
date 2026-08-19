"""
Shared per-row detection logic, extracted from live_stream.py so the CLI
prototype and the API's StreamEngine never diverge. Ensemble: Z-score +
flatline (statistical first pass) + incremental LOF (river, matching the
Phase 2 benchmark winner) + spatial-correlation correction layer.
"""

import os
import sys
from collections import deque

import pandas as pd
from river import anomaly, stats, utils

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "models"))
import spatial_correlation as sc  # noqa: E402  (re-exported for callers)

build_neighbor_map = sc.build_neighbor_map

FEATURE_COLS = ["pm25", "pm10", "no2", "co", "temperature", "humidity"]

ZSCORE_WINDOW = 12
ZSCORE_THRESHOLD = 3.5
FLATLINE_WINDOW = 4
FLATLINE_STD = 0.5
LOF_NEIGHBORS = 20
LOF_QUANTILE = 0.96
LOF_RESET_EVERY = 300
SPATIAL_RADIUS_KM = 20.0
SPATIAL_WINDOW_MIN = 20.0
SPATIAL_WINDOW_NS = int(pd.Timedelta(minutes=SPATIAL_WINDOW_MIN).value)
SPATIAL_Z_THRESHOLD = 3.0
SPATIAL_AGREEMENT_FRAC = 0.5


class StationState:
    def __init__(self):
        self.means = {c: utils.Rolling(stats.Mean(), window_size=ZSCORE_WINDOW) for c in FEATURE_COLS}
        self.varS = {c: utils.Rolling(stats.Var(), window_size=ZSCORE_WINDOW) for c in FEATURE_COLS}
        self.pm25_hist = deque(maxlen=FLATLINE_WINDOW)
        self.lof = anomaly.QuantileFilter(
            anomaly.LocalOutlierFactor(n_neighbors=LOF_NEIGHBORS), q=LOF_QUANTILE
        )
        self.lof_count = 0
        self.z_hist = deque()  # (ts_ns, pm25_z), pruned to the spatial time window

    def maybe_reset_lof(self):
        self.lof_count += 1
        if self.lof_count >= LOF_RESET_EVERY:
            self.lof = anomaly.QuantileFilter(
                anomaly.LocalOutlierFactor(n_neighbors=LOF_NEIGHBORS), q=LOF_QUANTILE
            )
            self.lof_count = 0


def zscore(state: StationState, col: str, value: float):
    mean, var = state.means[col].get(), state.varS[col].get()
    if mean is None or not var or var <= 0:
        return False, 0.0
    z = (value - mean) / (var ** 0.5)
    return abs(z) > ZSCORE_THRESHOLD, z


def score_row(sid, t: int, values: dict, nan: bool, state: StationState,
              states: dict, neighbor_map: dict):
    """
    Score one reading for station `sid` at time `t` (int64 ns). `values` is
    a dict of FEATURE_COLS -> float for this row. `nan` is True if any core
    pollutant reading is missing (caller decides which columns count).
    `states` is the full station_id -> StationState map (for neighbor
    lookups); `neighbor_map` is station_id -> list of nearby station_ids.

    Mutates `state` in place (rolling stats, LOF, histories) as a side
    effect of scoring - this IS the "learning" step of the online models.

    Returns (flag: int, spatial_label: str, detectors_fired: list[str], z_pm25: float).
    """
    if nan:
        return 0, "", [], 0.0

    detectors_fired = []
    is_flat = len(state.pm25_hist) == FLATLINE_WINDOW and \
        pd.Series(state.pm25_hist).std() < FLATLINE_STD
    if is_flat:
        detectors_fired.append("flatline")

    is_z, z_pm25 = zscore(state, "pm25", values["pm25"])
    if is_z:
        detectors_fired.append("zscore")

    x = {}
    for c in FEATURE_COLS:
        mean, var = state.means[c].get(), state.varS[c].get()
        x[c] = 0.0 if not mean or not var or var <= 0 else (values[c] - mean) / (var ** 0.5)
    score = state.lof.score_one(x)
    is_lof = state.lof.classify(score)
    if is_lof:
        detectors_fired.append("lof")
    state.lof.learn_one(x)
    state.maybe_reset_lof()

    flag = 0
    spatial_label = ""
    if detectors_fired:
        agreeing, total_seen = 0, 0
        for nsid in neighbor_map.get(sid, []):
            nstate = states.get(nsid)
            if nstate is None:
                continue
            matches = [nz for nt, nz in nstate.z_hist if abs(nt - t) <= SPATIAL_WINDOW_NS]
            if not matches:
                continue
            total_seen += 1
            if max(matches) >= SPATIAL_Z_THRESHOLD:
                agreeing += 1
        if total_seen > 0 and agreeing / total_seen >= SPATIAL_AGREEMENT_FRAC:
            spatial_label = "regional_agreement"
        else:
            flag = 1
            spatial_label = "isolated_fault"

    for c in FEATURE_COLS:
        state.means[c].update(values[c])
        state.varS[c].update(values[c])
    state.pm25_hist.append(values["pm25"])
    state.z_hist.append((t, z_pm25))
    while state.z_hist and t - state.z_hist[0][0] > SPATIAL_WINDOW_NS:
        state.z_hist.popleft()

    return flag, spatial_label, detectors_fired, z_pm25
