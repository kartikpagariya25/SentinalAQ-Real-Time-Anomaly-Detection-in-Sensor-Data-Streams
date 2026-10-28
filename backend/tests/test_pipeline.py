import numpy as np
import pandas as pd
import pytest

from app.config import RAW_FILE
from app.detector import Detector
from app.features import FEATURES, build_features
from app.generator import generate
from app.ingest import Ingestor, Store
from app.model import calibrate, fit_model, prepare, registry
from app.profile import build_profile
from app.rules import apply_rules

pytestmark = pytest.mark.skipif(not RAW_FILE.exists(), reason="real data file missing")


@pytest.fixture(scope="module")
def profile():
    return build_profile()


@pytest.fixture(scope="module")
def small(profile):
    return generate(profile, "2025-01-01", "2025-05-01", seed=3, cities=["Delhi", "Pune"], fault_scale=3.0)


def test_generator_is_reproducible(profile):
    a = generate(profile, "2025-01-01", "2025-01-15", seed=5, cities=["Pune"])
    b = generate(profile, "2025-01-01", "2025-01-15", seed=5, cities=["Pune"])
    pd.testing.assert_frame_equal(a, b)


def test_generator_labels_and_values(small):
    assert set(small["fault_type"]) <= {"normal", "pollution_event", "spike", "stuck", "saturation", "impossible_temp", "th_fault", "rh_fault", "drift", "dropout"}
    drop = small["fault_type"] == "dropout"
    assert small.loc[drop, ["pm25", "temp", "rh"]].isna().all().all()
    assert small.loc[~drop, ["pm25", "temp", "rh"]].notna().all().all()
    assert (small["is_valid"] == small["fault_type"].isin(["normal", "pollution_event"])).all()
    assert small.groupby("device_id")["timestamp"].apply(lambda s: s.is_monotonic_increasing).all()


def test_rules_catch_physical_impossibilities(profile):
    f = profile["faults"]
    df = pd.DataFrame({
        "pm25": [20.0, f["sentinel"], f["sat_floor"] + 100, 20.0, 20.0, np.nan, 20.0],
        "temp": [30.0, 30.0, 30.0, 80.0, 30.0, 30.0, 30.0],
        "rh": [70.0, 70.0, 70.0, 70.0, 101.0, 70.0, 70.0],
    })
    out = apply_rules(df, f).tolist()
    assert out == ["", "stuck", "saturation", "impossible_temp", "rh_fault", "dropout", ""]


def test_streaming_features_match_batch(small):
    full = build_features(small)
    last = small["timestamp"].max()
    window = small[small["timestamp"] > last - pd.Timedelta(hours=192)]
    part = build_features(window)
    key = ["device_id", "timestamp"]
    a = full[full["timestamp"] == last].set_index(key)[FEATURES].sort_index()
    b = part[part["timestamp"] == last].set_index(key)[FEATURES].sort_index()
    np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), rtol=1e-9, atol=1e-9, equal_nan=True)


@pytest.fixture(scope="module")
def bundle(profile, small):
    feats = build_features(small)
    ts = feats["timestamp"]
    tr, va = feats[ts < "2025-03-10"], feats[(ts >= "2025-03-10") & (ts < "2025-04-05")]
    X, y, w, _ = prepare(tr, normal_ratio=4.0)
    est = registry()["lightgbm"](n_estimators=60)
    fit_model(est, X, y, w)
    iso, thr, policy = calibrate(est, va)
    return {"clf": est, "iso": iso, "thr_f1": thr, "policy": policy, "faults": profile["faults"], "selection": {"winner": "lightgbm"}}


def test_stream_detector_agrees_with_truth(bundle, small):
    det = Detector(bundle)
    raw = small[small["timestamp"] >= "2025-04-05"]
    ticks = sorted(raw["timestamp"].unique())[:60]
    res = pd.concat([det.process(raw[raw["timestamp"] == t]) for t in ticks], ignore_index=True)
    truth = raw[raw["timestamp"].isin(ticks)].set_index(["timestamp", "device_id"])["is_valid"]
    sure = res[res["verdict"] != "REVIEW"].set_index(["timestamp", "device_id"])
    agree = (sure["pred_valid"].astype(int) == truth.reindex(sure.index)).mean()
    assert agree > 0.9
    assert set(res["verdict"]) <= {"VALID", "INVALID", "REVIEW"}
    assert res["confidence"].between(0, 1).all()
    assert res["reason"].str.len().min() > 10


def test_ingest_dedupes_and_handles_late_data(bundle, small):
    raw = small[small["timestamp"] >= "2025-04-05"][["timestamp", "device_id", "city", "pm25", "temp", "rh"]]
    ticks = sorted(raw["timestamp"].unique())[:6]
    ing = Ingestor(bundle, Store(":memory:"))
    first = ing.ingest(raw[raw["timestamp"].isin(ticks[2:])])
    again = ing.ingest(raw[raw["timestamp"].isin(ticks[2:])])
    late = ing.ingest(raw[raw["timestamp"].isin(ticks[:2])])
    assert first["scored"] > 0 and again["scored"] == 0 and again["duplicates"] == first["received"]
    assert late["scored"] > 0
    assert ing.store.count() == len(raw[raw["timestamp"].isin(ticks)])
    assert ing.summary(ticks[3])["readings"] > 0


def test_range_reports_and_pdf(bundle, small):
    from app.ingest import period_window
    from app.report_pdf import build_report_pdf

    raw = small[small["timestamp"] >= "2025-04-01"][["timestamp", "device_id", "city", "pm25", "temp", "rh"]]
    ing = Ingestor(bundle, Store(":memory:"))
    ing.ingest(raw)
    anchor = pd.Timestamp("2025-04-10")
    for period in ("daily", "weekly", "monthly", "yearly"):
        start, end = period_window(period, anchor)
        s = ing.summary_range(start, end, period)
        assert s["readings"] == s["valid"] + s["invalid"] + s["review"]
        assert isinstance(s["by_day"], list)
    weekly = ing.summary_range(*period_window("weekly", anchor), "weekly")
    assert build_report_pdf(weekly)[:4] == b"%PDF"
    assert len(ing.store.recent(5)) <= 5
