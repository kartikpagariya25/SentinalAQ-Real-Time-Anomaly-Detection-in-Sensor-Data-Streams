"""
live_stream.py
============================================================
Phase 3: river-based online scoring prototype (Final_plan.md Section 8).
Replays the dataset in TRUE timestamp order (interleaved across stations,
not grouped) to simulate live arrival, scoring each row with the models
selected in Section 8: incremental LOF (river) as the primary model,
Z-score + flatline as cheap first-pass rules, spatial correlation as the
correction layer. Reports per-row latency (p50/p95/p99) and throughput.

Usage:
    python streaming/live_stream.py --input ../sensor_data.csv --sample-size 20000
============================================================
"""

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "models"))
import evaluate as ev
import scoring


def load_stream_order(path: str, sample_size: int, rng: np.random.Generator) -> pd.DataFrame:
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=["timestamp"])

    if sample_size and sample_size < len(df):
        sizes = df.groupby("station_id").size().sample(frac=1.0, random_state=rng.integers(0, 2**31))
        chosen, total = [], 0
        for sid, n in sizes.items():
            if total >= sample_size:
                break
            chosen.append(sid)
            total += n
        df = df[df["station_id"].isin(chosen)]

    # True arrival order: sorted by time only, stations interleaved.
    return df.sort_values("timestamp").reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="Phase 3 river-based online scoring prototype.")
    parser.add_argument("--input", type=str, default="../sensor_data.csv")
    parser.add_argument("--sample-size", type=int, default=20000)
    parser.add_argument("--output", type=str, default="stream_results.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    df = load_stream_order(args.input, args.sample_size, rng)
    print(f"Streaming {len(df):,} rows across {df['station_id'].nunique()} stations, in arrival order...")

    neighbor_map = scoring.build_neighbor_map(df, scoring.SPATIAL_RADIUS_KM)

    n = len(df)
    stations = df["station_id"].to_numpy()
    ts_ns = df["timestamp"].values.astype("datetime64[ns]").astype("int64")
    values_by_col = {c: df[c].to_numpy(dtype=float) for c in scoring.FEATURE_COLS}
    nan_mask = df[scoring.FEATURE_COLS[:4]].isna().any(axis=1).to_numpy()

    states = {}
    flags = np.zeros(n, dtype=int)
    spatial_labels = np.full(n, "", dtype=object)
    latencies = np.empty(n, dtype=float)

    t_start = time.perf_counter()
    for i in range(n):
        t0 = time.perf_counter()
        sid = stations[i]
        t = ts_ns[i]
        state = states.setdefault(sid, scoring.StationState())

        if nan_mask[i]:
            latencies[i] = time.perf_counter() - t0
            continue

        values = {c: values_by_col[c][i] for c in scoring.FEATURE_COLS}
        flag, spatial_label, detectors_fired, _ = scoring.score_row(
            sid, t, values, False, state, states, neighbor_map
        )
        flags[i] = flag
        spatial_labels[i] = spatial_label

        latencies[i] = time.perf_counter() - t0

    wall_time = time.perf_counter() - t_start
    latencies_ms = latencies * 1000

    value_anomaly_true = df["anomaly_type"].isin(["outlier", "fault_flatline", "drift"]).astype(int).to_numpy()
    result = ev.evaluate_binary_detector(value_anomaly_true, flags)
    result["env_event_fp_rate"] = ev.environmental_event_false_positive_rate(df, flags)

    print("\n=== Live ensemble (Z-score + flatline + incremental LOF + spatial correction) ===")
    for k, v in result.items():
        print(f"  {k}: {v}")

    print("\n=== Per-row scoring latency (ms) ===")
    print(f"  p50: {np.percentile(latencies_ms, 50):.3f}  "
          f"p95: {np.percentile(latencies_ms, 95):.3f}  "
          f"p99: {np.percentile(latencies_ms, 99):.3f}")
    print(f"  throughput: {n / wall_time:.1f} msgs/sec (wall time {wall_time:.1f}s for {n:,} rows)")

    out = df[["record_id", "station_id", "timestamp"]].copy()
    out["flag"] = flags
    out["spatial_label"] = spatial_labels
    out.to_csv(args.output, index=False)
    print(f"\nSaved per-row stream results to: {args.output}")


if __name__ == "__main__":
    main()
