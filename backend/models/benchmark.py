"""
benchmark.py
============================================================
Phase 2 deliverable (Final_plan.md Section 8): batch benchmark of the
baseline MVP detector ensemble against the labeled synthetic dataset
produced by generate_sensor_dataset.py.

Usage:
    python models/benchmark.py --input sensor_data.parquet --sample-size 100000
    python models/benchmark.py --input sensor_data.csv --sample-size 0   # full dataset

Runs the statistical detectors (Z-score, flatline, CUSUM drift,
duplicate, gap) and the PyOD ML detectors (Isolation Forest, LOF),
scores each against ground truth, and prints/saves a comparison table
plus the environmental-event false-positive stress test.
============================================================
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import detectors as det
import evaluate as ev
import spatial_correlation as sc


def load_dataset(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)


def stratified_station_sample(df: pd.DataFrame, sample_size: int, rng: np.random.Generator) -> pd.DataFrame:
    """
    Sample whole stations (not individual rows) so every rolling/CUSUM
    detector still sees a contiguous per-station time series - random
    row sampling would break the temporal context those detectors need.
    """
    if sample_size <= 0 or sample_size >= len(df):
        return df

    station_sizes = df.groupby("station_id").size().sample(frac=1.0, random_state=rng.integers(0, 2**31))
    chosen, running_total = [], 0
    for station_id, n in station_sizes.items():
        if running_total >= sample_size:
            break
        chosen.append(station_id)
        running_total += n

    return df[df["station_id"].isin(chosen)].sort_values(["station_id", "timestamp"]).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="Benchmark baseline MVP anomaly detectors.")
    parser.add_argument("--input", type=str, default="sensor_data.parquet",
                         help="Path to the generated dataset (.csv or .parquet)")
    parser.add_argument("--gap-log", type=str, default=None,
                         help="Path to the companion gap log (default: inferred from --input)")
    parser.add_argument("--sample-size", type=int, default=100_000,
                         help="Approx rows to benchmark on, sampled by whole station (0 = full dataset)")
    parser.add_argument("--interval-minutes", type=int, default=5,
                         help="Expected per-station sampling interval used by the gap detector")
    parser.add_argument("--contamination", type=float, default=0.04,
                         help="Expected anomaly fraction passed to the PyOD detectors")
    parser.add_argument("--output", type=str, default="benchmark_results.csv",
                         help="Where to save the comparison table")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    gap_log_path = args.gap_log or f"{os.path.splitext(args.input)[0]}_gap_log.csv"

    print(f"Loading {args.input} ...")
    df = load_dataset(args.input)
    print(f"  {len(df):,} rows, {df['station_id'].nunique()} stations")

    df = stratified_station_sample(df, args.sample_size, rng)
    print(f"Benchmarking on {len(df):,} rows across {df['station_id'].nunique()} stations "
          f"(sample_size={args.sample_size or 'full'})")

    gap_log = pd.DataFrame()
    if os.path.exists(gap_log_path):
        gap_log = pd.read_csv(gap_log_path, parse_dates=["gap_start", "gap_end"])
        gap_log = gap_log[gap_log["station_id"].isin(df["station_id"].unique())].reset_index(drop=True)
        print(f"  Loaded {len(gap_log):,} ground-truth gap events for the sampled stations")
    else:
        print(f"  WARNING: gap log not found at {gap_log_path}; gap detector will be skipped")

    # ------------------------------------------------------------------
    # Ground truth
    # ------------------------------------------------------------------
    missing_true = df["is_missing"].to_numpy()
    outlier_true = (df["anomaly_type"] == "outlier").astype(int).to_numpy()
    flatline_true = (df["anomaly_type"] == "fault_flatline").astype(int).to_numpy()
    drift_true = (df["anomaly_type"] == "drift").astype(int).to_numpy()
    duplicate_true = (df["anomaly_type"] == "duplicate").astype(int).to_numpy()
    value_anomaly_true = df["anomaly_type"].isin(
        ["outlier", "fault_flatline", "drift"]
    ).astype(int).to_numpy()

    # ------------------------------------------------------------------
    # Run detectors
    # ------------------------------------------------------------------
    print("\nRunning detectors...")
    results = {}

    print("  missing (rule)...")
    missing_pred = det.detect_missing(df)
    results["missing_rule"] = ev.evaluate_binary_detector(missing_true, missing_pred)

    print("  rolling Z-score (outliers)...")
    zscore_pred = det.detect_zscore_outliers(df)
    results["zscore_outlier"] = ev.evaluate_binary_detector(outlier_true, zscore_pred)
    results["zscore_outlier"]["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, zscore_pred)

    print("  flatline (rolling std)...")
    flatline_pred = det.detect_flatline(df)
    results["flatline_rule"] = ev.evaluate_binary_detector(flatline_true, flatline_pred)
    results["flatline_rule"]["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, flatline_pred)

    print("  CUSUM drift...")
    cusum_pred = det.detect_cusum_drift(df)
    results["cusum_drift"] = ev.evaluate_binary_detector(drift_true, cusum_pred)
    results["cusum_drift"]["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, cusum_pred)

    print("  duplicate (rule)...")
    duplicate_pred = det.detect_duplicates(df)
    results["duplicate_rule"] = ev.evaluate_binary_detector(duplicate_true, duplicate_pred)

    print("  STL residual (statsmodels)...")
    stl_pred = det.detect_stl_residual(df)
    results["stl_residual"] = ev.evaluate_binary_detector(value_anomaly_true, stl_pred)
    results["stl_residual"]["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, stl_pred)

    print("  Isolation Forest (PyOD)...")
    if_pred = det.detect_isolation_forest(df, contamination=args.contamination)
    results["isolation_forest"] = ev.evaluate_binary_detector(value_anomaly_true, if_pred)
    results["isolation_forest"]["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, if_pred)

    print("  Local Outlier Factor (PyOD)...")
    lof_pred = det.detect_lof(df, contamination=args.contamination)
    results["lof"] = ev.evaluate_binary_detector(value_anomaly_true, lof_pred)
    results["lof"]["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, lof_pred)

    # ------------------------------------------------------------------
    # Spatial-correction pass: does each of the 3 model families still
    # clear the env-event false-positive bar once composed with the
    # spatial-correlation correction layer? This is what actually decides
    # which model is fit to wire into the live stream, not the raw scores.
    # ------------------------------------------------------------------
    print("  applying spatial correction to stl/isolation_forest/lof...")
    for name, pred in [("stl_residual", stl_pred), ("isolation_forest", if_pred), ("lof", lof_pred)]:
        corrected, _ = sc.apply_spatial_correction(df, pred)
        results[f"{name}_corrected"] = ev.evaluate_binary_detector(value_anomaly_true, corrected)
        results[f"{name}_corrected"]["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, corrected)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    table = ev.build_comparison_table(results)
    print("\n" + "=" * 78)
    print("Comparison table (precision/recall/F1 vs each method's target label,")
    print("env_event_fp_rate = fraction of REAL environmental-event rows wrongly flagged)")
    print("=" * 78)
    print(table.to_string(float_format=lambda x: f"{x:.4f}"))
    table.to_csv(args.output)
    print(f"\nSaved comparison table to: {args.output}")

    if len(gap_log) > 0:
        print("  gap detector (event-level)...")
        detected_gaps = det.detect_gaps(df, expected_interval_minutes=args.interval_minutes)
        gap_eval = ev.evaluate_gap_detector(detected_gaps, gap_log)
        print("\n" + "=" * 78)
        print("Gap detector (event-level recall / detection delay vs generator's gap log)")
        print("=" * 78)
        for k, v in gap_eval.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
