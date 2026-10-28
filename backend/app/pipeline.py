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


# short label, full form, and a 2-3 line description. Every model here is a CLASSIFIER.
MODELS = {
    "logreg": ("Logistic Regression", "Logistic Regression",
               "Simplest, linear classifier - separates classes with a straight boundary. Fast but cannot capture feature interactions (RH jump while temp is flat), so it decides almost nothing safely here."),
    "random_forest": ("Random Forest", "Random Forest",
                      "Many decision trees on random samples/features; the majority vote decides. Robust and low-overfit, but slower to train and its fault ranking trails the boosting models."),
    "extra_trees": ("Extra Trees", "Extremely Randomized Trees",
                    "Like Random Forest but split points are random too, so it trains very fast. Highest coverage, but the weakest PR-AUC - weaker at ranking faults above good readings."),
    "extra_trees_tuned": ("Extra Trees (tuned)", "Extremely Randomized Trees (tuned)",
                          "Hyper-parameter-tuned Extra Trees. Scores stayed almost identical - tuning did not move the needle here."),
    "hist_gb": ("Hist Gradient Boosting", "Histogram-based Gradient Boosting",
                "Gradient boosting that buckets features into histograms for speed; trees are added one by one, each fixing the previous errors. A solid, fast all-rounder."),
    "xgboost": ("XGBoost", "Extreme Gradient Boosting",
                "Popular, highly optimised gradient boosting. Very fast at scoring and strong overall, but its PR-AUC here was just below LightGBM."),
    "mlp": ("MLP (neural net)", "Multi-Layer Perceptron (neural network)",
            "A small neural network. Good ranking, but it pushes more readings to REVIEW (lower coverage) and needs scaling/tuning care - no better than trees on this tabular data."),
    "lightgbm": ("LightGBM", "Light Gradient Boosting Machine",
                 "Microsoft's gradient boosting with leaf-wise tree growth - fast and accurate. Best auto-INVALID precision and strong PR-AUC."),
    "lightgbm_tuned": ("LightGBM (tuned)", "Light Gradient Boosting Machine (tuned)",
                       "Tuned LightGBM - the WINNER. Best PR-AUC (ranks faults above good readings best), clears every safety limit, and stays fast."),
    "soft_vote_top3": ("Soft Vote (top 3)", "Soft-Voting Ensemble of the top 3 models",
                       "Not a new model - it averages the probabilities of the three best models. Slightly steadier but 5x slower with no real gain, so it was rejected."),
}
NAMES = {k: v[0] for k, v in MODELS.items()}


def _info(key):
    return MODELS.get(key) or (key, key, "")


def cmd_models(info=False):
    sel_file = MODEL_DIR / "selection.json"
    if not sel_file.exists():
        raise SystemExit("no selection.json yet - run `python -m app.cli compare`")
    sel = json.loads(sel_file.read_text())
    winner = sel["winner"]

    ui.title("Trained models and their metrics  (all are CLASSIFICATION models)")
    comp = MODEL_DIR.parent / "reports" / "evaluation" / "model_comparison.csv"
    if not comp.exists():
        comp = MODEL_DIR / "model_comparison.csv"
    if comp.exists():
        df = pd.read_csv(comp).sort_values("coverage", ascending=False)
        rows, win_idx = [], None
        for i, r in enumerate(df.itertuples()):
            if r.model == winner:
                win_idx = i
            short, full, _ = _info(r.model)
            rows.append([
                short, full, "classification",
                f"{r.coverage:.1%}", f"{r.inv_precision:.3f}", f"{r.miss_rate:.1%}",
                f"{r.slip_next_months:.1%}", f"{r.pr_auc:.3f}", f"{r.f1:.3f}",
                f"{r.fit_s:.0f}s", f"{r.ms_per_row:.3f}", "yes" if r.constraints_held else "NO",
            ])
        ui.table(
            ["model", "full form", "type", "auto-decided", "inv precision", "faults missed", "slip next mo", "PR-AUC", "F1", "fit", "ms/row", "limits ok"],
            rows, highlight=lambda i, _: i == win_idx,
        )
        ui.step("auto-decided = share of readings the model decides without a human (higher is better)")
        ui.step("inv precision = when it says INVALID, how often it is truly a fault (safety floor 0.99)")
        ui.step("faults missed = faults let through as VALID | PR-AUC = how well faults rank above good readings")
        ui.step("run with --info for a short description of each model")
    else:
        ui.warn("model_comparison.csv not found - run `python -m app.cli evaluate` for full metrics")

    if info:
        ui.title("Model guide  (what each one is)")
        order = list(df["model"]) if comp.exists() else list(MODELS)
        for key in order:
            short, full, desc = _info(key)
            tag = "  <-- selected" if key == winner else ""
            print(ui.paint(f"  {short}  ({full}) [classification]{tag}", ui.BOLD))
            print(f"    {desc}\n")

    ui.title("Selected model")
    params = ", ".join(f"{k}={v}" for k, v in (sel.get("params") or {}).items())
    ui.table(["item", "value"], [
        ["winner", NAMES.get(winner, winner)],
        ["base family", NAMES.get(sel.get("base", winner), sel.get("base", "-"))],
        ["hyper-parameters", params or "defaults"],
        ["selection score (coverage)", f"{sel.get('score', 0):.4f}"],
    ])
    ui.step("Why this one:")
    print("  " + sel.get("rule", "").replace("; ", "\n  - ").replace("while ", "while\n  - "))
