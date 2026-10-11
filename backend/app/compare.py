import json
import time

import joblib

import numpy as np
import pandas as pd

from . import ui
from .config import INVALID_CLASSES, MODEL_DIR, RESULT_DIR
from .features import FEATURES
from .model import (SEARCH_SPACE, SoftVote, choose_policy, p_invalid, prepare,
                    registry, score_candidate, timed_fit)
from sklearn.isotonic import IsotonicRegression

CV_CUTS = ["2024-07-01", "2025-01-01", "2025-07-01"]
CV_MONTHS = 6
NORMAL_RATIO = 4.0
TUNE_TRIALS = 5


def j_score(m):
    return m["f1"] - 0.5 * m["event_reject"]


def policy_eval(est, va):
    d = va[va["fault_type"] != "dropout"]
    X, y, e = eval_set(d)
    raw = p_invalid(est, X)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, y)
    dr = (d["fault_type"] == "drift").to_numpy()
    pol = choose_policy(iso.predict(raw), y, e, ignore=dr, cls=d["fault_type"].to_numpy())
    cut = d["timestamp"].min() + (d["timestamp"].max() - d["timestamp"].min()) / 2
    first = (d["timestamp"] < cut).to_numpy()
    ia = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw[first], y[first])
    pa = choose_policy(ia.predict(raw[first]), y[first], e[first], ignore=dr[first], cls=d["fault_type"].to_numpy()[first])
    pb = ia.predict(raw[~first])
    val_b = pb < pa["lo"]
    yb = (y[~first] == 1) & ~dr[~first]
    slip = float(yb[val_b].sum() / max(yb.sum(), 1))
    return {"coverage": pol["coverage"], "inv_precision": pol["inv_precision"], "miss_rate": pol["miss_rate"],
            "event_auto_reject": pol["event_reject"], "constraints_held": pol["constraints_met"], "slip_next_months": slip,
            "score": pol["coverage"] if pol["constraints_met"] else pol["coverage"] - 1.0}


def eval_set(feats):
    d = feats[feats["fault_type"] != "dropout"]
    y = np.isin(d["fault_type"], INVALID_CLASSES).astype(int)
    return d[FEATURES], y, (d["fault_type"] == "pollution_event").to_numpy()


def latency_ms(est, X, n=20000):
    s = X.iloc[:n]
    t = time.time()
    est.predict_proba(s)
    return (time.time() - t) / len(s) * 1000


def stage1(tr, va, seed):
    X, y, w, _ = prepare(tr, seed=seed, normal_ratio=NORMAL_RATIO)
    Xv, yv, ev = eval_set(va)
    rows, fitted = [], {}
    for name in registry():
        est, secs = timed_fit(name, {}, X, y, w)
        m = score_candidate(est, Xv, yv, ev)
        m.update(model=name, fit_s=secs, ms_per_row=latency_ms(est, Xv), J=j_score(m), **policy_eval(est, va))
        rows.append(m)
        fitted[name] = est
        ui.ok(f"{name:<14} decided automatically {m['coverage']:.1%} (faults slipping through {m['miss_rate']:.1%})  F1 {m['f1']:.4f}  fit {secs:.0f}s")
    return rows, fitted, (X, y, w)


def stage2(feats, names, seed):
    out = {}
    for name in names:
        js, f1s = [], []
        for cut in CV_CUTS:
            c0 = pd.Timestamp(cut)
            c1 = c0 + pd.DateOffset(months=CV_MONTHS)
            tr = feats[feats["timestamp"] < c0]
            te = feats[(feats["timestamp"] >= c0) & (feats["timestamp"] < c1)]
            X, y, w, _ = prepare(tr, seed=seed, normal_ratio=NORMAL_RATIO)
            est, _ = timed_fit(name, {}, X, y, w)
            Xt, yt, et = eval_set(te)
            m = score_candidate(est, Xt, yt, et)
            js.append(j_score(m))
            f1s.append(m["f1"])
        out[name] = {"cv_J_mean": float(np.mean(js)), "cv_J_std": float(np.std(js)), "cv_F1_mean": float(np.mean(f1s))}
        ui.ok(f"{name:<14} rolling CV  J {np.mean(js):.4f} +/- {np.std(js):.4f}  F1 {np.mean(f1s):.4f}")
    return out


def stage3(name, tr, va, seed, trials=TUNE_TRIALS):
    space = SEARCH_SPACE.get(name)
    trials = trials if space else 1
    X, y, w, _ = prepare(tr, seed=seed, normal_ratio=NORMAL_RATIO)
    Xv, yv, ev = eval_set(va)
    rng = np.random.default_rng(seed)
    best = None
    for k in range(trials):
        params = {key: vals[rng.integers(len(vals))] for key, vals in space.items()} if space else {}
        est, secs = timed_fit(name, params, X, y, w)
        m = score_candidate(est, Xv, yv, ev)
        m.update(J=j_score(m), params=params, fit_s=secs, **policy_eval(est, va))
        ui.ok(f"trial {k + 1}/{trials}  decided {m['coverage']:.1%}  slip-through {m['miss_rate']:.1%}  F1 {m['f1']:.4f}  {params}")
        if best is None or m["score"] > best[0]["score"]:
            best = (m, est, params)
    return best


def run_bakeoff(feats, tr, va, seed=7):
    t0 = time.time()
    cache = MODEL_DIR / "_bakeoff_stage12.joblib"
    if cache.exists():
        rows, cv, top = joblib.load(cache)
        ui.ok("resumed stage 1 and 2 from cache")
    else:
        rows, cv, top = _stage12(feats, tr, va, seed)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump((rows, cv, top), cache)
    Xv, yv, ev = eval_set(va)
    ui.step("Stage 3: random-search tuning of the top 2 single models (fair chance for each)")
    tuned = []
    for name in top[:2]:
        m, est, params = stage3(name, tr, va, seed)
        m.update(model=f"{name}_tuned", ms_per_row=latency_ms(est, Xv), cv_J_mean=cv[name]["cv_J_mean"], cv_J_std=cv[name]["cv_J_std"], cv_F1_mean=cv[name]["cv_F1_mean"])
        rows.append(m)
        tuned.append((f"{name}_tuned", name, params))
    return _finish(rows, tuned, top, t0)


def _stage12(feats, tr, va, seed):
    ui.step(f"Stage 1: {len(registry())} model families on the same data, scored on unseen validation months")
    rows, fitted, _ = stage1(tr, va, seed)
    rows.sort(key=lambda r: (-(r["score"] // 0.003), -r["pr_auc"]))
    top = [r["model"] for r in rows[:3]]
    Xv, yv, ev = eval_set(va)
    ens = SoftVote([fitted[n] for n in top])
    me = score_candidate(ens, Xv, yv, ev)
    me.update(**policy_eval(ens, va))
    me.update(model="soft_vote_top3", fit_s=sum(r["fit_s"] for r in rows if r["model"] in top), ms_per_row=sum(r["ms_per_row"] for r in rows if r["model"] in top), J=j_score(me))
    rows.append(me)
    ui.step("Stage 2: rolling-origin CV (train on past, test on the next 6 months) for the top 3")
    cv = stage2(feats, top, seed)
    for r in rows:
        r.update(cv.get(r["model"], {}))
    return rows, cv, top


def _finish(rows, tuned, top, t0):
    pool = rows
    top_s = max(r["score"] for r in pool)
    close = [r for r in pool if top_s - r["score"] <= 0.003]
    winner = max(close, key=lambda r: (round(r["pr_auc"], 3), -r["ms_per_row"]))
    info = {t[0]: t for t in tuned}
    sel = {"winner": winner["model"], "base": info[winner["model"]][1] if winner["model"] in info else winner["model"], "params": info[winner["model"]][2] if winner["model"] in info else {},
           "score": winner["score"], "rule": "maximise share of readings decided automatically (coverage) while the safety limits (invalid precision >= 0.99, <= 5% of faults (and <= 10% of any single fault type) slipping through as VALID, <= 3% of real events auto-rejected) are met on validation; candidates within 0.003 coverage are separated by PR-AUC (how well faults are ranked above good readings), then lowest latency",
           "members": top if winner["model"] == "soft_vote_top3" else [], "seconds": time.time() - t0}
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).drop(columns=["params"], errors="ignore").to_csv(RESULT_DIR / "model_comparison.csv", index=False)
    (MODEL_DIR / "selection.json").write_text(json.dumps(sel, indent=2))
    return rows, sel, None


def show(rows, sel):
    rows = sorted(rows, key=lambda r: (-(r["score"] // 0.003), -r["pr_auc"]))
    ui.table(
        ["model", "decided automatically", "faults slipping through", "slip-through on next months", "F1", "PR-AUC", "CV J (mean +/- sd)", "fit s", "ms / 1000 rows"],
        [[r["model"], f"{r['coverage']:.1%}" + ("" if r["constraints_held"] else " (limits not met)"), f"{r['miss_rate']:.1%}", f"{r['slip_next_months']:.1%}", f"{r['f1']:.4f}", f"{r['pr_auc']:.4f}",
          f"{r['cv_J_mean']:.4f} +/- {r['cv_J_std']:.4f}" if "cv_J_mean" in r and r["cv_J_mean"] == r["cv_J_mean"] else "-",
          f"{r['fit_s']:.0f}", f"{r['ms_per_row'] * 1000:.1f}"] for r in rows],
    )
    ui.ok(f"winner: {sel['winner']}  (automatic coverage {sel['score']:.1%})")


def fit_selected(sel, X, y, w):
    from .model import fit_model
    if sel["winner"] == "soft_vote_top3":
        est = SoftVote([registry()[n]() for n in sel["members"]])
        for m in est.members:
            fit_model(m, X, y, w)
        return est
    est = registry()[sel["base"]](**sel["params"])
    fit_model(est, X, y, w)
    return est


def learning_curve(seed=7):
    from .config import MODEL_DIR
    from .pipeline import load_feats, split
    sel = json.loads((MODEL_DIR / "selection.json").read_text())
    feats = load_feats()
    tr, va, _ = split(feats)
    Xv, yv, ev = eval_set(va)
    t0 = tr["timestamp"].min()
    rows = []
    for months in (3, 6, 9, 12, 18):
        sub = tr[tr["timestamp"] < t0 + pd.DateOffset(months=months)]
        X, y, w, _ = prepare(sub, seed=seed, normal_ratio=NORMAL_RATIO)
        est = fit_selected(sel, X, y, w)
        m = score_candidate(est, Xv, yv, ev)
        rows.append([f"{months} months", f"{len(sub):,}", f"{m['f1']:.4f}", f"{m['event_reject']:.3f}", f"{m['pr_auc']:.4f}", f"{j_score(m):.4f}"])
        ui.ok(f"{months} months: F1 {m['f1']:.4f}")
    ui.table(["training history", "rows", "F1", "event wrongly flagged", "PR-AUC", "J"], rows)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["history", "rows", "f1", "event_reject", "pr_auc", "J"]).to_csv(RESULT_DIR / "learning_curve.csv", index=False)
