"""
spatial_correlation.py
============================================================
Cross-sensor spatial correlation — the project's headline differentiator.

WHY THIS EXISTS (concrete evidence, not a hunch):
benchmark_results_v2.csv shows Isolation Forest flags REAL environmental
events (dust storms, stubble burning, festival fireworks - genuine air
quality, not sensor faults) as anomalies 98.8% of the time. LOF does
somewhat better at 8.3%, but neither is actually looking at what's
happening at other stations - they only ever see one sensor at a time,
so a real regional pollution spike and a lone hardware fault look
statistically identical.

WHAT THIS MODULE DOES:
It's a CORRECTION LAYER, not a standalone detector. Feed it any base
detector's binary flags (Isolation Forest, LOF, Z-score, rules...), and
for every flagged row it asks one question: "did geographically nearby
stations show a similarly elevated reading around the same time?"

  - YES -> very unlikely to be an independent hardware fault (faults on
    physically separate devices have no reason to correlate). Reclassify
    as a real, correlated event and drop the fault flag.
  - NO  -> stays flagged. An isolated deviation with calm neighbors is
    exactly what an independent sensor fault looks like.

This directly targets the demonstrated weakness above, and is meant to be
composed with an existing detector, not to replace it.
============================================================
"""

import numpy as np
import pandas as pd


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def build_neighbor_map(df: pd.DataFrame, radius_km: float = 20.0) -> dict:
    """station_id -> array of other station_ids within radius_km."""
    stations = df[["station_id", "latitude", "longitude"]].drop_duplicates("station_id")
    ids = stations["station_id"].to_numpy()
    lat = stations["latitude"].to_numpy()
    lon = stations["longitude"].to_numpy()

    neighbor_map = {}
    for i, sid in enumerate(ids):
        dist = haversine_km(lat[i], lon[i], lat, lon)
        neighbor_map[sid] = ids[(dist <= radius_km) & (dist > 0)]
    return neighbor_map


def station_relative_zscore(df: pd.DataFrame, col: str = "pm25",
                             window: int = 12) -> pd.Series:
    """
    How unusual is this reading relative to THIS STATION'S OWN RECENT
    baseline - a rolling window ending strictly before the current point
    (same pattern as detectors.detect_zscore_outliers), not a whole-history
    mean/std. Whole-history stats get confused by the normal diurnal
    rush-hour cycle (a routine morning peak can look "unusual" against a
    24-hour average that includes the quiet overnight hours), which made
    an earlier version of this function trigger false neighbor-agreement
    on completely ordinary daily patterns. A short recent-window baseline
    only reacts to a genuine, sudden departure from what this station was
    just doing, which is what "did a real event just start here" needs.
    """
    grp = df.groupby("station_id")[col]
    roll_mean = grp.transform(lambda s: s.shift(1).rolling(window, min_periods=window).mean())
    roll_std = grp.transform(lambda s: s.shift(1).rolling(window, min_periods=window).std())
    roll_std = roll_std.replace(0, np.nan)
    return ((df[col] - roll_mean) / roll_std).fillna(0.0)


def _station_time_index(df: pd.DataFrame, z: pd.Series) -> dict:
    """station_id -> (sorted timestamps as int64 NANOSECONDS, aligned z-scores) for fast windowed lookups.

    IMPORTANT: pandas can parse CSV timestamps as datetime64[us] (its new
    default resolution as of pandas 2.x/3.x), not datetime64[ns]. A naive
    `.values.astype("int64")` then returns MICROSECONDS, while
    `pd.Timedelta(...).value` always returns NANOSECONDS regardless of
    the Timedelta's own reported unit - mixing the two silently turns a
    "20 minute" window into a ~14-DAY window (1000x too wide), which is
    exactly the bug that first made this function flag every single row
    as spatially agreeing. Force nanoseconds explicitly here so the unit
    is correct regardless of what resolution pandas parsed the CSV as.
    """
    idx = {}
    ts_ns = df["timestamp"].values.astype("datetime64[ns]").astype("int64")
    tmp = pd.DataFrame({"station_id": df["station_id"].values, "ts": ts_ns, "z": z.values})
    for sid, g in tmp.groupby("station_id"):
        g = g.sort_values("ts")
        idx[sid] = (g["ts"].to_numpy(), g["z"].to_numpy())
    return idx


def apply_spatial_correction(df: pd.DataFrame, base_flags: np.ndarray,
                              radius_km: float = 20.0, time_window_minutes: float = 20.0,
                              z_threshold: float = 3.0, agreement_frac: float = 0.5,
                              value_col: str = "pm25") -> tuple:
    """
    Re-examine every row flagged by a base detector. Downgrade (un-flag) any
    row where a comparable fraction of nearby stations show a similarly
    elevated reading in the same time window - that pattern is far more
    consistent with a real correlated event than an independent fault.

    TUNING NOTE (from a grid search over radius_km/time_window_minutes/
    z_threshold/agreement_frac against Isolation Forest's output on the
    validation set - see spatial_correction_grid_search.csv):
    there is a genuine, unavoidable tradeoff here, not a free win. Being
    more aggressive about downgrading flagged rows always reduces the
    environmental-event false-positive rate, but it costs recall on real
    faults too - a genuine fault that happens to occur near a coincidental
    neighbor blip gets swept up and wrongly downgraded along with it.
    The defaults here sit at a reasonable middle point (env_event_fp_rate
    0.83 vs 1.00 uncorrected, F1 0.39), not an extreme in either direction.
    A more aggressive setting (radius_km=15, time_window_minutes=60,
    z_threshold=2.5, agreement_frac=0.3) pushes env_event_fp_rate down to
    0.39 but drops recall from 0.42 to 0.20. Which point on that curve is
    actually right depends on Respirer's real tolerance for missed faults
    vs. false alarms on real air-quality events - genuinely a product
    decision, not a modeling one, and worth confirming with them directly
    rather than guessing.
    """
    n = len(df)
    corrected = base_flags.copy()
    spatial_label = np.full(n, "", dtype=object)

    flagged_idx = np.where(base_flags == 1)[0]
    if len(flagged_idx) == 0:
        return corrected, spatial_label

    neighbor_map = build_neighbor_map(df, radius_km)
    z = station_relative_zscore(df, value_col)
    time_idx = _station_time_index(df, z)

    ts_all = df["timestamp"].values.astype("datetime64[ns]").astype("int64")
    station_all = df["station_id"].values
    window_ns = int(pd.Timedelta(minutes=time_window_minutes).value)

    for i in flagged_idx:
        sid = station_all[i]
        t = ts_all[i]
        neighbors = neighbor_map.get(sid, [])
        if len(neighbors) == 0:
            spatial_label[i] = "isolated_fault"
            continue

        agreeing, total_with_data = 0, 0
        for nsid in neighbors:
            n_ts, n_z = time_idx.get(nsid, (None, None))
            if n_ts is None or len(n_ts) == 0:
                continue
            lo = np.searchsorted(n_ts, t - window_ns, side="left")
            hi = np.searchsorted(n_ts, t + window_ns, side="right")
            if hi <= lo:
                continue
            total_with_data += 1
            if (n_z[lo:hi] >= z_threshold).any():
                agreeing += 1

        if total_with_data == 0:
            spatial_label[i] = "isolated_fault"
            continue

        frac = agreeing / total_with_data
        if frac >= agreement_frac:
            corrected[i] = 0
            spatial_label[i] = "regional_agreement"
        else:
            spatial_label[i] = "isolated_fault"

    return corrected, spatial_label
