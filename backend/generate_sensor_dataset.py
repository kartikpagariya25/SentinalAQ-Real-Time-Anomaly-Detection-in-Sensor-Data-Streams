"""
generate_sensor_dataset.py
============================================================
Simulated Environmental Sensor Data Generator
For: Real-Time Anomaly Detection in Sensor Data Streams
(Respirer India field-monitoring style dataset)

Generates ~1,000,000 "intended" readings with the following distribution
(final row count differs slightly: comm_gap rows are DROPPED to simulate
real packet loss, duplicate rows are ADDED to simulate re-transmission):
    938,000 (93.8%) normal observations
     18,000 (1.8%)  outliers / sudden spikes
      8,000 (0.8%)  missing-data events (null payload, row still arrives)
      8,000 (0.8%)  sensor faults / flatlines
      8,000 (0.8%)  drift / other slow anomalies
      8,000 (0.8%)  comm_gap events (packet never arrives -> row dropped)
      8,000 (0.8%)  environmental events (regional correlated spike, NOT a fault)
      4,000 (0.4%)  duplicate messages (re-transmitted packet -> row added)

Simulates a network of monitoring stations emitting multi-pollutant
readings (PM2.5, PM10, NO2, CO, temperature, humidity) at regular
intervals, with realistic diurnal/seasonal patterns, per-station
baselines, and injected anomalies with ground-truth labels. Environmental
events are injected across a station and its geographic neighbors
simultaneously, so the dataset actually contains the cross-sensor
correlation signal needed to distinguish a real regional event (e.g. a
dust storm or stubble-burning smoke) from a single-sensor fault.

Usage:
    python generate_sensor_dataset.py --output sensor_data.csv --n_stations 50
    python generate_sensor_dataset.py --output sensor_data.parquet --format parquet

Output columns:
    record_id           : unique row id
    station_id          : sensor/station identifier
    latitude, longitude : station location (India bounding box)
    timestamp           : ISO8601 timestamp of reading
    pm25, pm10          : particulate matter (ug/m3)
    no2                 : nitrogen dioxide (ppb)
    co                  : carbon monoxide (ppm)
    temperature         : deg Celsius
    humidity            : relative humidity (%)
    battery_voltage     : device battery voltage (V) - health signal
    signal_strength     : network signal (RSSI, dBm) - comms health
    is_missing          : 1 if this reading represents a missing/null event
    is_regional_event   : 1 if this reading is part of a correlated
                           multi-station environmental event (true positive,
                           not a fault - see anomaly_type=environmental_event)
    anomaly_type        : ground-truth label (normal, outlier, missing,
                           fault_flatline, drift, comm_gap,
                           environmental_event, duplicate)
    anomaly_subtype     : more granular label (e.g. spike_high, spike_low,
                           stuck_sensor, calibration_drift, out_of_range,
                           regional_dust_storm, exact_duplicate)
    is_anomaly          : 0/1 binary flag. missing_data events are NOT
                           counted as "anomaly" in the value sense (flagged
                           separately via is_missing); environmental_event
                           rows are also NOT counted (they are real, not
                           faults - flagged via is_regional_event instead).
                           comm_gap rows never appear in the main output
                           (see <output>_gap_log.csv) so they carry no
                           is_anomaly value here.

A companion file <output>_gap_log.csv is also written, recording the
station/time-window/count of every comm_gap event whose rows were
dropped from the main output (a true comms gap means the record never
arrived, so it cannot exist as a labeled row in the main dataset).
============================================================
"""

import argparse
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ----------------------------------------------------------------------
# Configuration / physical plausibility bounds (rough CPCB / WHO ranges)
# ----------------------------------------------------------------------
POLLUTANT_BOUNDS = {
    "pm25": (0, 1000),      # ug/m3 (extreme, e.g. Diwali/stubble-burning peaks)
    "pm10": (0, 1500),      # ug/m3
    "no2": (0, 400),        # ppb
    "co": (0, 50),          # ppm
    "temperature": (-5, 55),  # deg C (Indian climate range)
    "humidity": (0, 100),   # %
}

# India-ish bounding box for station lat/lon (rough)
INDIA_LAT_RANGE = (8.0, 35.0)
INDIA_LON_RANGE = (68.0, 97.0)

TOTAL_RECORDS = 1_000_000
DIST = {
    "normal": 938_000,
    "outlier": 18_000,
    "missing": 8_000,
    "fault_flatline": 8_000,
    "drift": 8_000,
    "comm_gap": 8_000,
    "environmental_event": 8_000,
    "duplicate": 4_000,
}


# ----------------------------------------------------------------------
# Helper: diurnal + seasonal baseline pattern per pollutant
# ----------------------------------------------------------------------
def diurnal_factor(hour: np.ndarray) -> np.ndarray:
    """
    Simulates typical urban Indian pollution diurnal pattern:
    morning rush-hour peak (~8-10am), evening peak (~7-10pm),
    lower values midday and late night.
    """
    # Two Gaussian bumps (morning & evening rush hours)
    morning = np.exp(-0.5 * ((hour - 9) / 2.0) ** 2)
    evening = np.exp(-0.5 * ((hour - 20) / 2.5) ** 2)
    base = 0.4 + 0.6 * (morning + evening) / 1.2
    return base


def seasonal_factor(day_of_year: np.ndarray) -> np.ndarray:
    """
    Simulates winter-high / monsoon-low PM pattern typical of North India:
    peak around Nov-Jan (day ~ 305-365 and 1-30), trough around Jul-Aug (monsoon).
    """
    # cosine centered so winter (day~15/day~350) is high, monsoon (day~200) is low
    return 0.55 + 0.45 * np.cos(2 * np.pi * (day_of_year - 15) / 365.0)


# ----------------------------------------------------------------------
# Station generator
# ----------------------------------------------------------------------
def generate_stations(n_stations: int, rng: np.random.Generator,
                       n_cities: int = None, city_radius_km: float = 18.0) -> pd.DataFrame:
    """
    Real deployments (Respirer's included) cluster devices within cities,
    not uniformly across the whole country. Pick a handful of "city"
    centers and scatter stations around each one, so "nearby stations" is
    a real geographic concept a spatial-correlation feature can actually
    use - a station's few nearest neighbors end up tens of km away, not
    hundreds/thousands, matching how a real regional pollution event
    (dust storm, stubble burning) would actually show up.
    """
    station_ids = [f"RESP-{i:04d}" for i in range(1, n_stations + 1)]

    if n_cities is None:
        n_cities = max(3, min(25, n_stations // 6))
    city_lats = rng.uniform(*INDIA_LAT_RANGE, size=n_cities)
    city_lons = rng.uniform(*INDIA_LON_RANGE, size=n_cities)

    city_assignment = rng.integers(0, n_cities, size=n_stations)
    deg_radius = city_radius_km / 111.0  # ~1 degree latitude =~ 111 km
    lats = city_lats[city_assignment] + rng.uniform(-deg_radius, deg_radius, size=n_stations)
    lons = city_lons[city_assignment] + rng.uniform(-deg_radius, deg_radius, size=n_stations)
    lats = np.clip(lats, *INDIA_LAT_RANGE)
    lons = np.clip(lons, *INDIA_LON_RANGE)

    # Per-station baseline multipliers -> some stations are naturally
    # "cleaner" (residential/park) vs "dirtier" (traffic/industrial)
    station_profile = rng.choice(
        ["residential", "traffic", "industrial", "background"],
        size=n_stations,
        p=[0.35, 0.30, 0.15, 0.20],
    )
    profile_multiplier = {
        "residential": 1.0,
        "traffic": 1.6,
        "industrial": 1.9,
        "background": 0.6,
    }
    baseline_mult = np.array([profile_multiplier[p] for p in station_profile])

    return pd.DataFrame(
        {
            "station_id": station_ids,
            "latitude": lats,
            "longitude": lons,
            "station_profile": station_profile,
            "baseline_mult": baseline_mult,
        }
    )


def nearest_neighbors(stations: pd.DataFrame, station_id: str, k: int) -> list:
    """Return up to k nearest other station_ids to station_id by simple lat/lon distance."""
    origin = stations.loc[stations["station_id"] == station_id, ["latitude", "longitude"]].iloc[0]
    others = stations[stations["station_id"] != station_id].copy()
    others["dist"] = np.sqrt(
        (others["latitude"] - origin["latitude"]) ** 2
        + (others["longitude"] - origin["longitude"]) ** 2
    )
    return others.nsmallest(k, "dist")["station_id"].tolist()


# ----------------------------------------------------------------------
# Core normal-value simulator (vectorized)
# ----------------------------------------------------------------------
def simulate_normal_values(timestamps: pd.Series, baseline_mult: np.ndarray,
                            rng: np.random.Generator) -> dict:
    hours = timestamps.dt.hour.values + timestamps.dt.minute.values / 60.0
    doy = timestamps.dt.dayofyear.values

    d_factor = diurnal_factor(hours)
    s_factor = seasonal_factor(doy)
    pattern = d_factor * s_factor  # 0..~1 combined pattern strength

    n = len(timestamps)

    # PM2.5 base ~ 20 (clean) to 250 (very polluted) scaled by pattern & station profile
    pm25 = (15 + 220 * pattern) * baseline_mult
    pm25 *= rng.normal(1.0, 0.12, size=n)  # sensor + atmospheric noise
    pm25 = np.clip(pm25, 2, POLLUTANT_BOUNDS["pm25"][1])

    # PM10 correlated with PM2.5 (typically PM10 >= PM2.5, ratio ~1.5-2x)
    pm10 = pm25 * rng.normal(1.6, 0.15, size=n)
    pm10 = np.clip(pm10, pm25, POLLUTANT_BOUNDS["pm10"][1])

    # NO2 correlated with traffic pattern (similar diurnal shape)
    no2 = (8 + 55 * pattern) * baseline_mult
    no2 *= rng.normal(1.0, 0.15, size=n)
    no2 = np.clip(no2, 1, POLLUTANT_BOUNDS["no2"][1])

    # CO correlated with traffic/industrial too, smaller magnitude
    co = (0.3 + 2.2 * pattern) * baseline_mult
    co *= rng.normal(1.0, 0.18, size=n)
    co = np.clip(co, 0.05, POLLUTANT_BOUNDS["co"][1])

    # Temperature: diurnal sinusoidal (cooler at night, warm midday) + seasonal
    temp_seasonal = 22 + 8 * np.cos(2 * np.pi * (doy - 172) / 365.0)  # peak ~summer
    temp_diurnal = 5 * np.sin(2 * np.pi * (hours - 6) / 24.0)
    temperature = temp_seasonal + temp_diurnal + rng.normal(0, 1.2, size=n)
    temperature = np.clip(temperature, *POLLUTANT_BOUNDS["temperature"])

    # Humidity: inversely related to temperature roughly, plus monsoon boost
    monsoon_boost = 25 * np.exp(-0.5 * ((doy - 210) / 40.0) ** 2)
    humidity = 55 - 0.8 * (temperature - 25) + monsoon_boost + rng.normal(0, 5, size=n)
    humidity = np.clip(humidity, *POLLUTANT_BOUNDS["humidity"])

    # Device health signals (normally healthy)
    battery_voltage = rng.normal(3.9, 0.08, size=n)
    battery_voltage = np.clip(battery_voltage, 3.0, 4.2)

    signal_strength = rng.normal(-65, 8, size=n)  # dBm, typical LTE/WiFi RSSI
    signal_strength = np.clip(signal_strength, -110, -30)

    return {
        "pm25": pm25,
        "pm10": pm10,
        "no2": no2,
        "co": co,
        "temperature": temperature,
        "humidity": humidity,
        "battery_voltage": battery_voltage,
        "signal_strength": signal_strength,
    }


# ----------------------------------------------------------------------
# Anomaly injectors
# ----------------------------------------------------------------------
def inject_outliers(df: pd.DataFrame, idx: np.ndarray, rng: np.random.Generator):
    """Sudden spikes or drops in pollutant readings (point anomalies)."""
    n = len(idx)
    subtypes = rng.choice(
        ["spike_high", "spike_low", "sensor_glitch_negative"],
        size=n, p=[0.55, 0.30, 0.15]
    )

    for i, subtype in zip(idx, subtypes):
        cols = rng.choice(["pm25", "pm10", "no2", "co"], size=rng.integers(1, 3), replace=False)
        if subtype == "spike_high":
            factor = rng.uniform(3.0, 8.0)
            for c in cols:
                df.at[i, c] = min(df.at[i, c] * factor, POLLUTANT_BOUNDS[c][1])
        elif subtype == "spike_low":
            factor = rng.uniform(0.05, 0.25)
            for c in cols:
                df.at[i, c] = max(df.at[i, c] * factor, POLLUTANT_BOUNDS[c][0] + 0.1)
        else:  # sensor_glitch_negative -> physically impossible negative reading
            for c in cols:
                df.at[i, c] = -abs(rng.uniform(1, 50))

        df.at[i, "anomaly_type"] = "outlier"
        df.at[i, "anomaly_subtype"] = subtype
        df.at[i, "is_anomaly"] = 1


def inject_missing(df: pd.DataFrame, idx: np.ndarray, rng: np.random.Generator):
    """Missing-data events: null sensor payload (communication/parse failure)."""
    value_cols = ["pm25", "pm10", "no2", "co", "temperature", "humidity"]
    subtypes = rng.choice(
        ["comm_timeout", "null_payload", "parse_error"],
        size=len(idx), p=[0.5, 0.35, 0.15]
    )
    for i, subtype in zip(idx, subtypes):
        for c in value_cols:
            df.at[i, c] = np.nan
        df.at[i, "is_missing"] = 1
        df.at[i, "anomaly_type"] = "missing"
        df.at[i, "anomaly_subtype"] = subtype
        df.at[i, "is_anomaly"] = 0  # tracked separately via is_missing


def _station_budgeted_runs(df: pd.DataFrame, n_target_rows: int, rng: np.random.Generator,
                            min_run: int, max_run: int):
    """
    Shared run-selection helper for per-station, chronologically-contiguous
    anomaly runs (used by flatline and drift). Draws each run from a
    single station's own currently-"normal" rows sorted by timestamp, so a
    "run" is a real sustained stretch for that station - not an arbitrary
    handful of unrelated rows scattered across the whole dataset (which a
    flat cross-dataset shuffle would produce, and which gives collective/
    sustained detectors like rolling-variance or CUSUM nothing real to find).
    Yields (run_idx, station_id) tuples until the row budget is spent.
    """
    remaining_budget = n_target_rows
    station_ids = df["station_id"].unique().tolist()
    guard, max_guard = 0, max(2000, n_target_rows * 20)

    while remaining_budget > 0 and station_ids and guard < max_guard:
        guard += 1
        station_id = station_ids[rng.integers(0, len(station_ids))]
        candidates = df.index[
            (df["station_id"] == station_id) & (df["anomaly_type"] == "normal")
        ]
        if len(candidates) < min_run:
            station_ids.remove(station_id)
            continue

        cand_sorted = df.loc[candidates].sort_values("timestamp").index.to_numpy()
        run_len = min(int(rng.integers(min_run, max_run + 1)), len(cand_sorted), remaining_budget)
        start_pos = int(rng.integers(0, len(cand_sorted) - run_len + 1))
        run_idx = cand_sorted[start_pos: start_pos + run_len]

        yield run_idx, station_id
        remaining_budget -= run_len


def inject_flatline_faults(df: pd.DataFrame, n_target_rows: int, rng: np.random.Generator):
    """
    Sensor faults / flatlines: value gets 'stuck' at a constant (or near-constant)
    reading for a run of consecutive samples from the same station - simulates a
    hardware fault. Runs are drawn from each station's own chronological
    sequence via `_station_budgeted_runs` so the flatline is a genuine
    sustained-variance-collapse a rolling-std detector can actually find.
    """
    subtypes_pool = ["stuck_sensor", "out_of_range_constant", "zero_reading"]
    value_cols = ["pm25", "pm10", "no2", "co"]

    for run_idx, _station_id in _station_budgeted_runs(df, n_target_rows, rng, min_run=3, max_run=12):
        subtype = rng.choice(subtypes_pool, p=[0.6, 0.25, 0.15])
        if subtype == "stuck_sensor":
            stuck_val = {c: df.at[run_idx[0], c] for c in value_cols}
        elif subtype == "out_of_range_constant":
            stuck_val = {c: POLLUTANT_BOUNDS[c][1] * rng.uniform(0.9, 1.0) for c in value_cols}
        else:  # zero_reading
            stuck_val = {c: 0.0 for c in value_cols}

        for i in run_idx:
            for c in value_cols:
                df.at[i, c] = stuck_val[c]
            df.at[i, "anomaly_type"] = "fault_flatline"
            df.at[i, "anomaly_subtype"] = subtype
            df.at[i, "is_anomaly"] = 1


def inject_drift(df: pd.DataFrame, n_target_rows: int, rng: np.random.Generator):
    """
    Drift / other slow anomalies: gradual calibration drift (multiplicative bias
    that grows over a run of samples) or slowly degrading battery/signal health.
    Runs are drawn from each station's own chronological sequence via
    `_station_budgeted_runs` so the drift is a genuine sustained ramp a
    CUSUM/EWMA detector can actually find, not scattered single points.
    """
    value_cols = ["pm25", "pm10", "no2"]
    subtypes_pool = ["calibration_drift_up", "calibration_drift_down", "battery_degradation"]

    for run_idx, _station_id in _station_budgeted_runs(df, n_target_rows, rng, min_run=5, max_run=20):
        subtype = rng.choice(subtypes_pool, p=[0.4, 0.35, 0.25])
        ramp = np.linspace(0, 1, len(run_idx))

        for pos, i in enumerate(run_idx):
            if subtype == "calibration_drift_up":
                factor = 1.0 + 1.5 * ramp[pos]
                for c in value_cols:
                    df.at[i, c] = min(df.at[i, c] * factor, POLLUTANT_BOUNDS[c][1])
            elif subtype == "calibration_drift_down":
                factor = 1.0 - 0.6 * ramp[pos]
                for c in value_cols:
                    df.at[i, c] = max(df.at[i, c] * factor, POLLUTANT_BOUNDS[c][0] + 0.1)
            else:  # battery_degradation -> slow voltage droop + noisier readings
                df.at[i, "battery_voltage"] = max(3.0, df.at[i, "battery_voltage"] - 0.6 * ramp[pos])
                for c in value_cols:
                    df.at[i, c] = df.at[i, c] * rng.normal(1.0, 0.05 + 0.1 * ramp[pos])

            df.at[i, "anomaly_type"] = "drift"
            df.at[i, "anomaly_subtype"] = subtype
            df.at[i, "is_anomaly"] = 1


def inject_comm_gaps(df: pd.DataFrame, n_target_rows: int, rng: np.random.Generator):
    """
    Communication gaps: the sensor's packet never arrives at all (as opposed to
    'missing', where a null payload DOES arrive). Since a true gap means no row
    exists, the selected rows are DROPPED from df in-place (via the returned
    boolean mask) and instead logged to a companion gap-log DataFrame with the
    station/time window/count of the readings that never showed up.

    Runs are built directly from each station's own chronological sequence of
    still-"normal" rows (not from a flat cross-dataset random sample), so a
    gap_start/gap_end in the log actually reflects a short, real, contiguous
    stretch of missed samples for that station rather than an arbitrary spread
    of unrelated timestamps.
    """
    drop_mask = pd.Series(False, index=df.index)
    gap_records = []
    remaining_budget = n_target_rows
    station_ids = df["station_id"].unique().tolist()

    guard = 0
    max_guard = max(2000, n_target_rows * 20)
    while remaining_budget > 0 and station_ids and guard < max_guard:
        guard += 1
        station_id = station_ids[rng.integers(0, len(station_ids))]
        candidates = df.index[
            (df["station_id"] == station_id)
            & (df["anomaly_type"] == "normal")
            & (~drop_mask)
        ]
        if len(candidates) < 2:
            station_ids.remove(station_id)
            continue

        cand_sorted = df.loc[candidates].sort_values("timestamp").index.to_numpy()
        run_len = min(int(rng.integers(2, 10)), len(cand_sorted), remaining_budget)
        start_pos = int(rng.integers(0, len(cand_sorted) - run_len + 1))
        run_idx = cand_sorted[start_pos: start_pos + run_len]

        drop_mask.loc[run_idx] = True
        run_rows = df.loc[run_idx].sort_values("timestamp")
        gap_records.append({
            "station_id": station_id,
            "gap_start": run_rows["timestamp"].iloc[0],
            "gap_end": run_rows["timestamp"].iloc[-1],
            "n_missing_expected": len(run_idx),
        })
        remaining_budget -= run_len

    gap_log = pd.DataFrame(gap_records)
    return drop_mask, gap_log


def inject_environmental_events(df: pd.DataFrame, stations: pd.DataFrame,
                                 n_target_rows: int, rng: np.random.Generator) -> np.ndarray:
    """
    Regional correlated environmental events (dust storm, stubble-burning smoke,
    festival fireworks): a real pollution spike affecting an epicenter station
    AND its geographic neighbors at the same time - a TRUE POSITIVE, not a
    sensor fault. Returns the array of row indices that were affected so the
    caller can exclude them from the generic per-row anomaly assignment pool.
    """
    subtypes_pool = ["regional_dust_storm", "stubble_burning_smoke", "festival_fireworks"]
    value_cols = ["pm25", "pm10", "no2"]

    affected_idx = []
    rows_used = 0
    station_ids = stations["station_id"].tolist()

    while rows_used < n_target_rows and station_ids:
        epicenter = station_ids[rng.integers(0, len(station_ids))]
        k = int(rng.integers(2, 6))
        neighbors = nearest_neighbors(stations, epicenter, k)
        event_stations = [epicenter] + neighbors

        subtype = subtypes_pool[rng.integers(0, len(subtypes_pool))]
        base_factor = rng.uniform(2.5, 6.0)

        # pick a contiguous 1-4 hour window anchored at a random timestamp
        # already present in the epicenter station's stream
        epicenter_rows = df.index[df["station_id"] == epicenter]
        if len(epicenter_rows) == 0:
            station_ids.remove(epicenter)
            continue
        anchor_i = epicenter_rows[rng.integers(0, len(epicenter_rows))]
        anchor_ts = df.at[anchor_i, "timestamp"]
        window_hours = rng.uniform(1.0, 4.0)
        window_start = anchor_ts
        window_end = anchor_ts + pd.Timedelta(hours=window_hours)

        event_row_idx = df.index[
            df["station_id"].isin(event_stations)
            & (df["timestamp"] >= window_start)
            & (df["timestamp"] <= window_end)
            & (df["anomaly_type"] == "normal")
        ]
        if len(event_row_idx) == 0:
            continue

        remaining_budget = n_target_rows - rows_used
        if len(event_row_idx) > remaining_budget:
            event_row_idx = event_row_idx[:remaining_budget]

        for i in event_row_idx:
            station_factor = base_factor * rng.normal(1.0, 0.08)
            for c in value_cols:
                df.at[i, c] = min(df.at[i, c] * max(station_factor, 1.2), POLLUTANT_BOUNDS[c][1])
            df.at[i, "anomaly_type"] = "environmental_event"
            df.at[i, "anomaly_subtype"] = subtype
            df.at[i, "is_anomaly"] = 0
            df.at[i, "is_regional_event"] = 1

        affected_idx.extend(event_row_idx.tolist())
        rows_used += len(event_row_idx)

    return np.array(affected_idx, dtype=df.index.dtype) if affected_idx else np.array([], dtype=df.index.dtype)


def inject_duplicates(df: pd.DataFrame, idx: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    """
    Duplicate messages: the same reading arrives twice (at-least-once delivery
    duplicate / re-transmit). Returns a DataFrame of extra rows to be appended
    to the main dataset immediately after their originals.
    """
    subtypes = rng.choice(
        ["exact_duplicate", "retransmit_duplicate"],
        size=len(idx), p=[0.6, 0.4]
    )
    dup_rows = df.loc[idx].copy()
    for pos, subtype in enumerate(subtypes):
        row_label = dup_rows.index[pos]
        if subtype == "retransmit_duplicate":
            dup_rows.at[row_label, "battery_voltage"] = max(
                3.0, dup_rows.at[row_label, "battery_voltage"] + rng.normal(0, 0.01)
            )
            dup_rows.at[row_label, "signal_strength"] = np.clip(
                dup_rows.at[row_label, "signal_strength"] + rng.normal(0, 1.5), -110, -30
            )
        dup_rows.at[row_label, "anomaly_type"] = "duplicate"
        dup_rows.at[row_label, "anomaly_subtype"] = subtype
        dup_rows.at[row_label, "is_anomaly"] = 1

    return dup_rows


# ----------------------------------------------------------------------
# Main generation pipeline
# ----------------------------------------------------------------------
def generate_dataset(n_records: int, n_stations: int, start_date: str,
                      interval_minutes: int, seed: int):
    rng = np.random.default_rng(seed)

    stations = generate_stations(n_stations, rng)

    # Assign each record to a station (round-robin-ish random assignment)
    station_choice_idx = rng.integers(0, n_stations, size=n_records)
    station_ids = stations["station_id"].values[station_choice_idx]
    lats = stations["latitude"].values[station_choice_idx]
    lons = stations["longitude"].values[station_choice_idx]
    baseline_mult = stations["baseline_mult"].values[station_choice_idx]

    # Generate timestamps: each station gets its own regular time series,
    # then we interleave & sort by station+time for a realistic stream.
    records_per_station = n_records // n_stations
    remainder = n_records % n_stations

    start_dt = pd.Timestamp(start_date)
    all_timestamps = []
    all_station_order = []
    for s_i, sid in enumerate(stations["station_id"].values):
        n_this = records_per_station + (1 if s_i < remainder else 0)
        ts = start_dt + pd.to_timedelta(
            np.arange(n_this) * interval_minutes, unit="m"
        )
        all_timestamps.append(ts)
        all_station_order.extend([sid] * n_this)

    timestamps = pd.to_datetime(np.concatenate([t.values for t in all_timestamps]))
    station_ids_full = np.array(all_station_order)

    # Rebuild lat/lon/baseline_mult aligned to station_ids_full
    station_lookup = stations.set_index("station_id")
    lats_full = station_lookup.loc[station_ids_full, "latitude"].values
    lons_full = station_lookup.loc[station_ids_full, "longitude"].values
    mult_full = station_lookup.loc[station_ids_full, "baseline_mult"].values

    n = len(timestamps)
    ts_series = pd.Series(timestamps)

    values = simulate_normal_values(ts_series, mult_full, rng)

    df = pd.DataFrame({
        "record_id": np.arange(1, n + 1),
        "station_id": station_ids_full,
        "latitude": lats_full,
        "longitude": lons_full,
        "timestamp": timestamps,
        **values,
    })

    # Sort by station then timestamp to create realistic per-station streams,
    # then shuffle station blocks together in time order (interleaved stream)
    df = df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)
    df["record_id"] = np.arange(1, len(df) + 1)

    # Ground-truth / metadata columns (defaults = normal)
    df["is_missing"] = 0
    df["is_regional_event"] = 0
    df["anomaly_type"] = "normal"
    df["anomaly_subtype"] = "none"
    df["is_anomaly"] = 0

    # ------------------------------------------------------------------
    # Assign anomaly categories to random index subsets (no overlap)
    # ------------------------------------------------------------------
    assert sum(DIST.values()) == n_records == len(df), \
        "Distribution counts must sum to n_records and match generated length"

    # Ordering matters here and is the fix for a real bug: run-based
    # categories (environmental_event, flatline, drift, comm_gap) MUST be
    # injected first, while every row is still "normal", because each of
    # them selects a contiguous run by filtering to anomaly_type=="normal"
    # and slicing a chronologically-sorted subset of that filtered result.
    # If a flat point-category (outlier/missing) were assigned first, its
    # scattered rows would silently vanish from later filters - meaning a
    # flatline/drift/gap "run" could look contiguous in the filtered index
    # while actually having a stray, already-labeled point-anomaly sitting
    # unseen inside its real timestamp span. Doing point-categories LAST,
    # sampled only from whatever is still genuinely "normal" at that point,
    # makes that collision structurally impossible instead of just unlikely.
    env_idx = inject_environmental_events(df, stations, DIST["environmental_event"], rng)
    inject_flatline_faults(df, DIST["fault_flatline"], rng)
    inject_drift(df, DIST["drift"], rng)
    drop_mask, gap_log = inject_comm_gaps(df, DIST["comm_gap"], rng)

    # NOW build the flat-random pool for the point categories, from
    # whatever is still genuinely "normal" and not already marked for
    # dropping (comm_gap) - guaranteed disjoint from every run-based
    # category above by construction, not by a shuffle that predates them.
    still_normal = (df["anomaly_type"] == "normal") & (~drop_mask)
    remaining_pool = df.index[still_normal].values.copy()
    rng.shuffle(remaining_pool)
    all_idx = remaining_pool
    ptr = 0

    outlier_idx = all_idx[ptr: ptr + DIST["outlier"]]; ptr += DIST["outlier"]
    missing_idx = all_idx[ptr: ptr + DIST["missing"]]; ptr += DIST["missing"]
    dup_idx = all_idx[ptr: ptr + DIST["duplicate"]]; ptr += DIST["duplicate"]
    normal_idx = all_idx[ptr:]  # everything left is normal

    inject_outliers(df, outlier_idx, rng)
    inject_missing(df, missing_idx, rng)
    # normal_idx rows are left untouched (already default "normal")
    dup_rows = inject_duplicates(df, dup_idx, rng)

    # Drop comm_gap rows (packet never arrived) and append duplicate rows
    # (packet arrived twice), then renumber record_id contiguously.
    df = df.loc[~drop_mask].copy()
    df = pd.concat([df, dup_rows], ignore_index=False)
    df = df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)
    df["record_id"] = np.arange(1, len(df) + 1)

    # Final column ordering
    cols = [
        "record_id", "station_id", "latitude", "longitude", "timestamp",
        "pm25", "pm10", "no2", "co", "temperature", "humidity",
        "battery_voltage", "signal_strength",
        "is_missing", "is_regional_event", "anomaly_type", "anomaly_subtype", "is_anomaly",
    ]
    df = df[cols]

    return df, gap_log


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate simulated environmental sensor dataset with labeled anomalies."
    )
    parser.add_argument("--output", type=str, default="sensor_data.csv",
                         help="Output file path (.csv or .parquet)")
    parser.add_argument("--format", type=str, choices=["csv", "parquet"], default=None,
                         help="Output format (inferred from --output extension if omitted)")
    parser.add_argument("--n_records", type=int, default=TOTAL_RECORDS,
                         help="Total number of records to generate (default: 1,000,000)")
    parser.add_argument("--n_stations", type=int, default=50,
                         help="Number of simulated sensor stations (default: 50)")
    parser.add_argument("--start_date", type=str, default="2025-01-01 00:00:00",
                         help="Start timestamp for the simulated stream")
    parser.add_argument("--interval_minutes", type=int, default=5,
                         help="Sampling interval per station in minutes (default: 5)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    if args.n_records != TOTAL_RECORDS:
        # Rescale distribution proportionally if a custom record count is requested
        global DIST
        scale = args.n_records / TOTAL_RECORDS
        DIST = {k: int(round(v * scale)) for k, v in DIST.items()}
        diff = args.n_records - sum(DIST.values())
        DIST["normal"] += diff  # absorb rounding remainder into normal class

    print(f"Generating {args.n_records:,} intended records across {args.n_stations} stations...")
    print(f"Target distribution: {DIST}")

    df, gap_log = generate_dataset(
        n_records=args.n_records,
        n_stations=args.n_stations,
        start_date=args.start_date,
        interval_minutes=args.interval_minutes,
        seed=args.seed,
    )

    out_format = args.format or ("parquet" if args.output.endswith(".parquet") else "csv")
    if out_format == "parquet":
        df.to_parquet(args.output, index=False)
    else:
        df.to_csv(args.output, index=False)

    gap_log_path = f"{os.path.splitext(args.output)[0]}_gap_log.csv"
    gap_log.to_csv(gap_log_path, index=False)

    n_dropped = int(gap_log["n_missing_expected"].sum()) if len(gap_log) else 0
    n_duplicated = int((df["anomaly_type"] == "duplicate").sum())

    print(f"\nSaved {len(df):,} records to: {args.output}")
    print(f"  ({n_dropped:,} rows dropped for comm_gap events, "
          f"{n_duplicated:,} duplicate rows appended)")
    print(f"Saved {len(gap_log):,} comm_gap events to: {gap_log_path}")
    print("\nLabel distribution (anomaly_type):")
    print(df["anomaly_type"].value_counts())
    print(f"\nMissing-data flag count (is_missing=1): {df['is_missing'].sum():,}")
    print(f"Regional-event flag count (is_regional_event=1): {df['is_regional_event'].sum():,}")
    print(f"Value-anomaly flag count (is_anomaly=1): {df['is_anomaly'].sum():,}")
    print("\nSample rows:")
    print(df.sample(5, random_state=1).to_string(index=False))


if __name__ == "__main__":
    main()
