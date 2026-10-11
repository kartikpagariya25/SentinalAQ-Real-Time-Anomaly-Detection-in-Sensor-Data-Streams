import json
import time

import pandas as pd

from . import ui
from .config import (DATA_END, DATA_FILE, DATA_START, DEVICES_FILE, MODEL_DIR, PROFILE_FILE,
                     SYN_DIR, TRAIN_END, VAL_END)
from .features import build_features
from .compare import fit_selected, run_bakeoff, show
from .generator import device_table, generate
from .model import calibrate, fit_model, prepare, registry, save_bundle, train_iforest, SoftVote
from .profile import build_profile, load_profile, save_profile


def cmd_profile():
    ui.title("Step 1 - Pattern extraction from real Atmos data")
    prof = build_profile()
    save_profile(prof)
    f = prof["faults"]
    ui.table(
        ["quantity", "value", "used for"],
        [
            ["rows / invalid rate", f"{prof['source_rows']} / {prof['invalid_rate']:.1%}", "fault rate sanity"],
            ["PM2.5 median / p99", f"{prof['pm']['median']:.1f} / {prof['pm']['p99']:.1f}", "normal PM level"],
            ["PM2.5 hour-to-hour autocorr", f"{prof['pm']['phi']:.2f}", "AR(1) persistence"],
            ["Temp daily range", f"{min(prof['temp']['hourly']):.1f} - {max(prof['temp']['hourly']):.1f} C", "diurnal curve"],
            ["RH vs Temp slope", f"{prof['rh']['beta_temp']:.2f} %/C", "T-RH coupling"],
            ["PM sentinel value", f"{f['sentinel']:g}", "stuck fault"],
            ["PM saturation range", f"{f['sat_min']:.0f} - {f['sat_max']:.0f}", "saturation fault"],
            ["Largest spike vs normal", f"{f['spike_ratio']:.0f}x", "spike magnitude"],
            ["T/RH probe fault", f"temp {f['th_temp'][0]:.1f}-{f['th_temp'][1]:.1f} C, RH 100", "th_fault"],
            ["Largest valid PM jump", f"{prof['event_ratio']:.0f}x", "event magnitude"],
        ],
    )
    ui.ok(f"profile saved -> {PROFILE_FILE}")


def cmd_generate(seed=7, fault_scale=1.0):
    ui.title("Step 2 - Synthetic network generation")
    prof = load_profile()
    t = time.time()
    df = generate(prof, DATA_START, DATA_END, seed=seed, fault_scale=fault_scale)
    SYN_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DATA_FILE, index=False)
    device_table().to_csv(DEVICES_FILE, index=False)
    ui.ok(f"{len(df):,} rows, {df.device_id.nunique()} devices, {df.city.nunique()} cities in {time.time() - t:.1f}s -> {DATA_FILE}")
    mix = df["fault_type"].value_counts()
    ui.table(["class", "rows", "share"], [[k, f"{v:,}", f"{v / len(df):.2%}"] for k, v in mix.items()])
    return df


def split(feats):
    ts = feats["timestamp"]
    return (
        feats[ts < TRAIN_END],
        feats[(ts >= TRAIN_END) & (ts < VAL_END)],
        feats[ts >= VAL_END],
    )


def load_feats():
    return build_features(pd.read_parquet(DATA_FILE))


def _show_split(tr, va, te):
    ui.table(["split", "from", "to", "rows"], [
        [n, str(d.timestamp.min().date()), str(d.timestamp.max().date()), f"{len(d):,}"]
        for n, d in (("train", tr), ("validation", va), ("test", te))
    ])


def cmd_compare(seed=7, resume=False):
    ui.title("Step 3 - Model bake-off (same data, same rule)")
    cache = MODEL_DIR / "_bakeoff_stage12.joblib"
    if cache.exists() and not resume:
        cache.unlink()
    t = time.time()
    feats = load_feats()
    ui.ok(f"features built: {feats.shape[1]} columns in {time.time() - t:.1f}s")
    tr, va, te = split(feats)
    _show_split(tr, va, te)
    rows, sel, _ = run_bakeoff(feats, tr, va, seed)
    show(rows, sel)
    return sel


def cmd_train(seed=7):
    ui.title("Step 4 - Train the selected model, calibrate, set the decision policy")
    sel_file = MODEL_DIR / "selection.json"
    if not sel_file.exists():
        raise SystemExit("run `python -m app.cli compare` first")
    sel = json.loads(sel_file.read_text())
    prof = load_profile()
    feats = load_feats()
    tr, va, te = split(feats)
    X, y, w, _ = prepare(tr, seed=seed, normal_ratio=4.0)
    t = time.time()
    est = fit_selected(sel, X, y, w)
    ui.ok(f"{sel['winner']} trained in {time.time() - t:.0f}s on {len(X):,} rows")
    iso, thr, policy = calibrate(est, va)
    ui.table(["policy item", "value"], [
        ["auto-valid below p(invalid)", f"{policy['lo']:.3f}"],
        ["auto-invalid above p(invalid)", f"{policy['hi']:.2f}"],
        ["readings decided automatically", f"{policy['coverage']:.2%}"],
        ["auto-invalid precision", f"{policy['inv_precision']:.4f}"],
        ["faults that slip through as VALID", f"{policy['miss_rate']:.2%}"],
        ["worst single fault type slipping through", f"{policy['worst_class_miss']:.2%}"],
        ["real events auto-rejected", f"{policy['event_reject']:.2%}"],
        ["all constraints met", str(policy["constraints_met"])],
    ])
    iforest = train_iforest(tr, va, seed)
    bundle = {"clf": est, "iso": iso, "thr_f1": thr, "policy": policy, "iforest": iforest, "faults": prof["faults"], "selection": sel}
    save_bundle(bundle)
    ui.ok("model saved -> models/detector.joblib")
    return bundle
