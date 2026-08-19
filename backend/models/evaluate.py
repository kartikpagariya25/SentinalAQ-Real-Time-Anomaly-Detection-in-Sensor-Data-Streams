"""
evaluate.py
============================================================
Evaluation framework for the baseline detectors, per Final_plan.md
Section 7: precision/recall/F1 per method, a dedicated false-positive
check on `environmental_event` rows (the fault-vs-real-event distinction
Respirer cares about most), and event-level recall/detection-delay for
the gap detector (compared against generate_sensor_dataset.py's own
ground-truth `_gap_log.csv`).
============================================================
"""

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, f1_score


def evaluate_binary_detector(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Standard precision/recall/F1 for a 0/1 prediction array against a 0/1 ground truth array."""
    return {
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "n_flagged": int(y_pred.sum()),
        "n_true": int(y_true.sum()),
    }


def environmental_event_false_positive_rate(df: pd.DataFrame, y_pred: np.ndarray) -> float:
    """
    The Respirer-critical stress test (Final_plan.md Section 2/7): of all
    rows that are a REAL regional environmental event (not a fault), what
    fraction did this detector incorrectly flag as anomalous?
    """
    is_event = (df["anomaly_type"] == "environmental_event").to_numpy()
    if is_event.sum() == 0:
        return float("nan")
    return float(y_pred[is_event].mean())


def evaluate_gap_detector(detected_gaps: pd.DataFrame, gap_log: pd.DataFrame) -> dict:
    """
    Event-level evaluation for the gap detector: a ground-truth gap
    (from gap_log) counts as "caught" if at least one detected gap for
    the same station overlaps its [gap_start, gap_end] window. Detection
    delay is measured as detected delta minus the true gap span.
    """
    if len(gap_log) == 0:
        return {"recall": float("nan"), "mean_detection_delay_minutes": float("nan"),
                "n_true_gaps": 0, "n_detected_gaps": len(detected_gaps)}

    caught = 0
    delays = []
    for _, true_gap in gap_log.iterrows():
        station_matches = detected_gaps[detected_gaps["station_id"] == true_gap["station_id"]]
        overlap = station_matches[
            (station_matches["gap_end"] >= true_gap["gap_start"])
            & (station_matches["gap_start"] <= true_gap["gap_end"])
        ]
        if len(overlap) > 0:
            caught += 1
            delays.append(overlap["detection_delay_minutes"].min())

    return {
        "recall": caught / len(gap_log),
        "mean_detection_delay_minutes": float(np.mean(delays)) if delays else float("nan"),
        "n_true_gaps": len(gap_log),
        "n_detected_gaps": len(detected_gaps),
    }


def build_comparison_table(results: dict) -> pd.DataFrame:
    """results: {method_name: {metric: value, ...}, ...} -> tidy comparison DataFrame."""
    return pd.DataFrame(results).T
