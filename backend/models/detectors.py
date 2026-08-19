"""
detectors.py
============================================================
Baseline MVP anomaly detectors for the Respirer sensor dataset, per
Final_plan.md Section 4.5 "Pragmatic MVP build order":
    1. Statistical / rule-based detectors (cheap, explainable, first pass)
    2. PyOD Isolation Forest + LOF (general multivariate ML coverage)

All detectors take a DataFrame shaped like the output of
generate_sensor_dataset.py (sorted by station_id, timestamp) and return a
0/1 numpy array aligned to df.index, plus (where available) a continuous
anomaly score. Detectors never look at the ground-truth label columns
(anomaly_type, is_anomaly, ...) - they only ever see the sensor readings,
exactly like a real detector would.
============================================================
"""

import numpy as np
import pandas as pd

VALUE_COLS = ["pm25", "pm10", "no2", "co"]
FEATURE_COLS = ["pm25", "pm10", "no2", "co", "temperature", "humidity"]


# ----------------------------------------------------------------------
# A. Statistical / rule-based detectors
# ----------------------------------------------------------------------
def detect_missing(df: pd.DataFrame) -> np.ndarray:
    """Trivial rule: any null pollutant reading -> missing-data flag."""
    return df[VALUE_COLS].isna().any(axis=1).astype(int).to_numpy()


def detect_zscore_outliers(df: pd.DataFrame, window: int = 12,
                            threshold: float = 3.5) -> np.ndarray:
    """
    Rolling Z-score point-anomaly detector (Section 4.5A). For each
    station and pollutant, flags a reading more than `threshold` standard
    deviations from the mean of the `window` readings STRICTLY BEFORE it.

    The baseline deliberately excludes the current point (`shift(1)`
    before `.rolling()`) - including the point being tested in its own
    mean/std lets a single spike drag the baseline toward itself and caps
    the achievable z-score at roughly sqrt(window), silently hiding
    exactly the point-anomalies this detector exists to catch.
    """
    flagged = pd.Series(False, index=df.index)
    for col in VALUE_COLS:
        grp = df.groupby("station_id")[col]
        roll_mean = grp.transform(lambda s: s.shift(1).rolling(window, min_periods=window).mean())
        roll_std = grp.transform(lambda s: s.shift(1).rolling(window, min_periods=window).std())
        roll_std = roll_std.replace(0, np.nan)
        z = (df[col] - roll_mean) / roll_std
        flagged |= z.abs() > threshold
    return flagged.fillna(False).astype(int).to_numpy()


def detect_flatline(df: pd.DataFrame, window: int = 4,
                     std_threshold: float = 0.5) -> np.ndarray:
    """
    Flatline / stuck-sensor detector (Section 4.5A): flags a run where
    pm25's rolling standard deviation collapses to ~0 for `window`
    consecutive samples from the same station.
    """
    grp = df.groupby("station_id")["pm25"]
    roll_std = grp.transform(lambda s: s.rolling(window, min_periods=window).std())
    return (roll_std < std_threshold).fillna(False).astype(int).to_numpy()


def detect_cusum_drift(df: pd.DataFrame, baseline_window: int = 30, ewma_span: int = 20,
                        k: float = 1.0, h: float = 5.0) -> np.ndarray:
    """
    CUSUM drift detector (Section 4.5A): tracks a two-sided cumulative sum
    of pm25's deviation from its own EWMA baseline per station, STANDARDIZED
    by a trailing rolling standard deviation so k/h (in "sigmas") mean the
    same thing regardless of a pollutant's raw scale (pm25 can sit anywhere
    from ~15 to 250+ ug/m3 depending on station profile and season) - using
    raw, unstandardized residuals makes h impossible to tune sensibly across
    stations and flags almost every reading once pm25 gets into the hundreds.

    The accumulator is reset to 0 every time it signals (standard CUSUM
    behavior) - without a reset, one excursion past the threshold leaves
    the accumulator permanently saturated and every subsequent reading for
    that station gets flagged for the rest of the series, which is what an
    earlier version of this detector did (~59% of all rows flagged).

    Known limitation, worth stating rather than hiding: this simple
    EWMA/CUSUM baseline scores low precision on this dataset (~0.05-0.08)
    because the ~12-18% multiplicative sensor noise plus strong diurnal
    swings the generator injects dominate the small early signal of a
    gradual drift ramp. This is exactly the gap Final_plan.md Section 4.5's
    "pragmatic MVP build order" expects the cheap baseline to expose before
    escalating to STL-decomposition + residual thresholding (Section 4.5B),
    which removes the diurnal component before looking for drift and should
    perform meaningfully better - a natural next iteration, not a bug fix.
    """
    flags = np.zeros(len(df), dtype=int)
    values = df["pm25"].to_numpy()
    stations = df["station_id"].to_numpy()

    for station_id in np.unique(stations):
        idx = np.where(stations == station_id)[0]
        series = pd.Series(values[idx])
        ewma = series.ewm(span=ewma_span, adjust=False).mean()
        resid = series - ewma
        resid_std = resid.rolling(baseline_window, min_periods=5).std().bfill()
        resid_std = resid_std.replace(0, np.nan).fillna(resid_std.median() or 1.0)
        std_resid = (resid / resid_std).to_numpy()

        pos, neg = 0.0, 0.0
        for j, r in enumerate(std_resid):
            pos = max(0.0, pos + r - k)
            neg = min(0.0, neg + r + k)
            if pos > h or neg < -h:
                flags[idx[j]] = 1
                pos, neg = 0.0, 0.0

    return flags


def detect_duplicates(df: pd.DataFrame) -> np.ndarray:
    """Comms-layer duplicate detector: same (station_id, timestamp) seen more than once."""
    return df.duplicated(subset=["station_id", "timestamp"], keep=False).astype(int).to_numpy()


def detect_gaps(df: pd.DataFrame, expected_interval_minutes: int = 5,
                 factor: float = 1.5) -> pd.DataFrame:
    """
    Communication-gap detector (Section 4.5A): flags where the time since
    the previous reading from the same station exceeds `factor` times the
    expected sampling interval. Unlike the other detectors this returns a
    table of detected GAP EVENTS (not a per-row flag), since a gap is a
    property of the missing interval, not of any single row - matching
    the shape of generate_sensor_dataset.py's own `_gap_log.csv`.
    """
    d = df[["station_id", "timestamp"]].copy()
    d["prev_ts"] = d.groupby("station_id")["timestamp"].shift(1)
    d["delta_minutes"] = (d["timestamp"] - d["prev_ts"]).dt.total_seconds() / 60.0

    threshold = expected_interval_minutes * factor
    detected = d[d["delta_minutes"] > threshold].copy()
    detected["gap_start"] = detected["prev_ts"]
    detected["gap_end"] = detected["timestamp"]
    detected["detection_delay_minutes"] = detected["delta_minutes"] - expected_interval_minutes

    return detected[["station_id", "gap_start", "gap_end", "detection_delay_minutes"]].reset_index(drop=True)


# ----------------------------------------------------------------------
# B. Time-series model-based (STL decomposition + residual thresholding)
# ----------------------------------------------------------------------
def detect_stl_residual(df: pd.DataFrame, value_col: str = "pm25", period: int = 288,
                         threshold: float = 3.5, min_periods_factor: int = 2) -> np.ndarray:
    """
    STL decomposition + residual z-score thresholding (Section 4.5B).
    Removes trend+seasonal (diurnal) component per station, then flags
    residuals that exceed `threshold` rolling std devs. Missing values are
    interpolated for decomposition only; flags never land on those rows.
    """
    from statsmodels.tsa.seasonal import STL

    flags = np.zeros(len(df), dtype=int)
    stations = df["station_id"].to_numpy()
    values = df[value_col].to_numpy()
    idx_all = np.arange(len(df))
    min_samples = min_periods_factor * period

    for station_id in np.unique(stations):
        idx = idx_all[stations == station_id]
        series = pd.Series(values[idx])
        valid = series.notna()
        if valid.sum() < min_samples:
            continue

        interpolated = series.interpolate(limit_direction="both")
        try:
            resid = STL(interpolated, period=period, robust=True).fit().resid
        except ValueError:
            continue

        resid_std = resid.rolling(period, min_periods=30).std().bfill()
        resid_std = resid_std.replace(0, np.nan)
        resid_std = resid_std.fillna(resid_std.median()).fillna(1.0)
        z = (resid / resid_std).to_numpy()

        station_flags = (np.abs(z) > threshold) & valid.to_numpy()
        flags[idx[station_flags]] = 1

    return flags


# ----------------------------------------------------------------------
# C. Machine learning detectors (PyOD)
# ----------------------------------------------------------------------
def _scored_subset(df: pd.DataFrame):
    """Rows eligible for the multivariate ML detectors: no null features."""
    eligible = df[FEATURE_COLS].notna().all(axis=1)
    return eligible


def _station_normalized_matrix(df: pd.DataFrame, eligible: pd.Series) -> np.ndarray:
    """
    Z-score each feature WITHIN its own station before fitting, instead of a
    single global StandardScaler across all stations pooled together.

    Why this matters here specifically: station_profile drives a large,
    systematic offset in raw pollutant levels (e.g. background ~pm25 15-60
    vs industrial ~150+, per generate_sensor_dataset.py's baseline_mult).
    A global scaler leaves that offset in the data, so an unsupervised
    detector fit on the pooled matrix can partly learn "which station
    profile is this row from" rather than "is this reading unusual FOR
    THIS STATION" - which is the question we actually want answered.
    Normalizing per station removes the profile-level offset and scale
    difference first, so the remaining variance a detector sees is
    genuinely about within-station deviation.

    Station mean/std are computed over ALL of that station's rows,
    including any injected anomalies - consistent with the rest of this
    module's fully-unsupervised assumption (a real detector never sees
    ground-truth labels), and consistent with how the previous global
    StandardScaler was already being fit on unlabeled, anomaly-containing
    data.
    """
    grp = df.loc[eligible].groupby("station_id")[FEATURE_COLS]
    mean = grp.transform("mean")
    std = grp.transform("std").replace(0, np.nan)
    z = (df.loc[eligible, FEATURE_COLS] - mean) / std
    return z.fillna(0.0).to_numpy()


def detect_isolation_forest(df: pd.DataFrame, contamination: float = 0.04,
                             random_state: int = 42) -> np.ndarray:
    """
    PyOD Isolation Forest over the multivariate feature set (Section 4.5C),
    fit on PER-STATION-normalized features (see `_station_normalized_matrix`)
    rather than raw pooled values, so station-profile differences in
    baseline pollution level don't drown out genuine within-station anomalies.
    """
    from pyod.models.iforest import IForest

    eligible = _scored_subset(df)
    preds = np.zeros(len(df), dtype=int)
    if eligible.sum() == 0:
        return preds

    X = _station_normalized_matrix(df, eligible)
    clf = IForest(contamination=contamination, random_state=random_state, n_jobs=-1)
    clf.fit(X)
    preds[eligible.to_numpy()] = clf.labels_
    return preds


def detect_lof(df: pd.DataFrame, contamination: float = 0.04,
               n_neighbors: int = 20) -> np.ndarray:
    """
    PyOD Local Outlier Factor over the multivariate feature set (Section
    4.5C), fit on PER-STATION-normalized features (see
    `_station_normalized_matrix`) for the same reason as
    `detect_isolation_forest` above.
    """
    from pyod.models.lof import LOF

    eligible = _scored_subset(df)
    preds = np.zeros(len(df), dtype=int)
    if eligible.sum() == 0:
        return preds

    X = _station_normalized_matrix(df, eligible)
    clf = LOF(contamination=contamination, n_neighbors=n_neighbors, n_jobs=-1)
    clf.fit(X)
    preds[eligible.to_numpy()] = clf.labels_
    return preds
