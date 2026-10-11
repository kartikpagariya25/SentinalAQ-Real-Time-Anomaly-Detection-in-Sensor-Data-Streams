import json

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss

from . import ui
from .compare import fit_selected
from .config import (DATA_FILE, HOLDOUT_CITIES, INVALID_CLASSES, RAW_FILE,
                     RESULT_DIR, VALID_CLASSES)
from .detector import run_batch
from .features import FEATURES, SPATIAL, build_features
from .generator import generate
from .model import calibrate, load_bundle, predict, prepare
from .pipeline import split
from .profile import load_profile, load_raw
from .reasons import event_cause
from .rules import apply_rules

STAT_LIMITS = {"pm_z": 4.0, "temp_dm": 6.0, "rh_dm": 20.0, "pm_run": 3}


def _prf(true_inv, flag):
    tp = int((true_inv & flag).sum())
    fp = int((~true_inv & flag).sum())
    fn = int((true_inv & ~flag).sum())
    tn = int((~true_inv & ~flag).sum())
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return p, r, 2 * p * r / max(p + r, 1e-12), fp / max(fp + tn, 1)


def _truth(d):
    return (~d["fault_type"].isin(VALID_CLASSES)).to_numpy()


def _row(name, d, flag, score=None):
    t = _truth(d)
    p, r, f, fpr = _prf(t, flag)
    ev = (d["fault_type"] == "pollution_event").to_numpy()
    return {"method": name, "precision": p, "recall": r, "f1": f, "fpr": fpr,
            "event_fp": float(flag[ev].mean()) if ev.any() else 0.0,
            "pr_auc": float(average_precision_score(t, score)) if score is not None else np.nan}


def _fmt(x):
    return [x["method"], f"{x['precision']:.3f}", f"{x['recall']:.3f}", f"{x['f1']:.3f}", f"{x['fpr']:.4f}", f"{x['event_fp']:.1%}",
            "n/a" if x["pr_auc"] != x["pr_auc"] else f"{x['pr_auc']:.3f}"]


BENCH_HEAD = ["method", "precision", "recall", "F1", "false alarm rate", "real events wrongly flagged", "PR-AUC"]


def _stat_flag(d):
    f = (d["pm_z"].abs() > STAT_LIMITS["pm_z"]) | (d["temp_dm"].abs() > STAT_LIMITS["temp_dm"])
    f |= d["rh_dm"].abs() > STAT_LIMITS["rh_dm"]
    f |= d["pm_run"] >= STAT_LIMITS["pm_run"]
    return f.to_numpy()


def _iforest(bundle, d):
    ib = bundle["iforest"]
    s = -ib["model"].decision_function(d[FEATURES].fillna(ib["fill"]))
    return s >= ib["threshold"], s


def _bootstrap(d, flag, n=300, seed=1):
    t = _truth(d)
    codes, uniq = pd.factorize(d["timestamp"].dt.floor("D").to_numpy())
    k = len(uniq)
    tp = np.bincount(codes, (t & flag).astype(float), k)
    fp = np.bincount(codes, (~t & flag).astype(float), k)
    fn = np.bincount(codes, (t & ~flag).astype(float), k)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        i = rng.integers(0, k, k)
        a, b, c = tp[i].sum(), fp[i].sum(), fn[i].sum()
        p, r = a / max(a + b, 1), a / max(a + c, 1)
        out.append(2 * p * r / max(p + r, 1e-12))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def _calibration(p, y):
    edges = [0, 0.01, 0.05, 0.2, 0.5, 0.8, 0.95, 0.99, 1.0001]
    rows, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() == 0:
            continue
        gap = abs(p[m].mean() - y[m].mean())
        ece += gap * m.mean()
        rows.append([f"{lo:.2f}-{min(hi, 1):.2f}", int(m.sum()), p[m].mean(), y[m].mean()])
    return float(ece), rows


def _slices(d, flag):
    t = _truth(d)
    h, mo = d["timestamp"].dt.hour, d["timestamp"].dt.month
    g = {
        "night (22-05h)": ((h >= 22) | (h < 5)).to_numpy(), "day (05-22h)": ((h >= 5) & (h < 22)).to_numpy(),
        "winter (Jan-Feb)": mo.isin([1, 2]).to_numpy(), "summer (Mar-May)": mo.isin([3, 4, 5]).to_numpy(),
        "monsoon (Jun-Sep)": mo.isin([6, 7, 8, 9]).to_numpy(),
        "Holi days (3-4 Mar)": d["timestamp"].dt.strftime("%m-%d").isin(["03-03", "03-04"]).to_numpy(),
    }
    out = []
    for n, m in g.items():
        if m.sum():
            p, r, f, _ = _prf(t[m], flag[m])
            out.append([n, int(m.sum()), int(t[m].sum()), f"{p:.3f}", f"{r:.3f}", f"{f:.3f}"])
    return out


OP_HEAD = ["setting", "auto-INVALID precision", "faults auto-INVALID", "faults INVALID or REVIEW", "faults missed (excl. drift)", "REVIEW share of readings", "real events auto-rejected"]


def _op_row(name, d, verdict):
    v = np.asarray(verdict)
    t = _truth(d)
    drift = (d["fault_type"] == "drift").to_numpy()
    inv = v == "INVALID"
    pt = t & ~drift
    ev = (d["fault_type"] == "pollution_event").to_numpy()
    return [name, f"{(t[inv].mean() if inv.any() else 1.0):.3f}", f"{inv[t].mean():.1%}", f"{(v[t] != 'VALID').mean():.1%}",
            f"{(v[pt] == 'VALID').mean():.1%}", f"{(v == 'REVIEW').mean():.1%}", f"{(inv[ev].mean() if ev.any() else 0):.2%}"]


def _stress(bundle, name, **kw):
    s = generate(load_profile(), "2026-01-01", "2026-07-01", seed=99, **kw)
    f = build_features(s)
    f = f[f["fault_type"] != "dropout"].reset_index(drop=True)
    h = predict(bundle, f)
    flag = (h["verdict"] != "VALID").to_numpy()
    inv = (h["verdict"] == "INVALID").to_numpy()
    iff, ifs = _iforest(bundle, f)
    rows = [_row("rolling z-score / flatline", f, _stat_flag(f)), _row("isolation forest", f, iff, ifs),
            _row("final: INVALID only", f, inv, h["p_invalid"]), _row("final: INVALID or REVIEW", f, flag, h["p_invalid"])]
    ui.step(name)
    ui.table(BENCH_HEAD, [_fmt(r) for r in rows[:3]], highlight=lambda i, _: False)
    ui.table(OP_HEAD, [_op_row("final model", f, h["verdict"].to_numpy())])
    pc = []
    for c in sorted(set(f["fault_type"]) - {"normal", "pollution_event", "dropout"}):
        m = (f["fault_type"] == c).to_numpy()
        if m.any():
            pc.append([c, int(m.sum()), f"{inv[m].mean():.1%}", f"{(h['verdict'].to_numpy()[m] == 'REVIEW').mean():.1%}", f"{(h['verdict'].to_numpy()[m] == 'VALID').mean():.1%}"])
    ui.table(["variant of", "rows", "auto-invalid", "sent to review", "missed (valid)"], pc)
    return rows[3]


def real_check(bundle):
    raw = load_raw(RAW_FILE)
    d = raw.assign(device_id="REAL-01", city="Real")[["timestamp", "device_id", "city", "pm25", "temp", "rh", "is_valid"]]
    feats, res = run_batch(bundle, d.drop(columns="is_valid"))
    res = res.merge(d[["timestamp", "is_valid"]], on="timestamp")
    flag = (res["verdict"] != "VALID").to_numpy()
    t = (res["is_valid"] == 0).to_numpy()
    tp, fp, fn = int((t & flag).sum()), int((~t & flag).sum()), int((t & ~flag).sum())
    return {"tp": tp, "fp": fp, "fn": fn, "tn": int((~t & ~flag).sum())}, res[flag != t]


def evaluate(skip_lco=False):
    ui.title("Step 5 - Evaluation on the held-out test period (never used for training or tuning)")
    bundle = load_bundle()
    feats = build_features(pd.read_parquet(DATA_FILE))
    tr, va, te_all = split(feats)
    n_drop = int((te_all["fault_type"] == "dropout").sum())
    te = te_all[te_all["fault_type"] != "dropout"].reset_index(drop=True)
    ui.ok(f"model: {bundle['selection']['winner']} | test rows {len(te_all):,} ({n_drop:,} dropouts handled by the missing-data check)")

    hy = predict(bundle, te)
    raw_only = predict(bundle, te, use_rules=False)
    v = hy["verdict"].to_numpy()
    inv, rev = v == "INVALID", v == "REVIEW"
    flag = inv | rev
    rules_flag = (apply_rules(te, bundle["faults"]) != "").to_numpy()
    iff, ifs = _iforest(bundle, te)
    nn = te.copy()
    nn[SPATIAL] = np.nan
    ns = predict(bundle, nn)
    ev = (te["fault_type"] == "pollution_event").to_numpy()
    nm = (te["fault_type"] == "normal").to_numpy()

    rows = [
        _row("1. Rules only (physics limits)", te, rules_flag),
        _row("2. Rolling z-score / flatline", te, _stat_flag(te)),
        _row("3. Isolation Forest", te, iff, ifs),
        _row("4. ML only, no rules (INVALID or REVIEW)", te, (raw_only["verdict"] != "VALID").to_numpy(), raw_only["p_invalid"]),
        _row("5. FINAL, auto-INVALID only", te, inv, hy["p_invalid"]),
        _row("6. FINAL, INVALID or REVIEW", te, flag, hy["p_invalid"]),
        _row("7. FINAL without neighbour data", te, (ns["verdict"] != "VALID").to_numpy(), ns["p_invalid"]),
    ]
    ui.step("A. Benchmark: fault detection (fault = positive class)")
    ui.table(BENCH_HEAD, [_fmt(r) for r in rows], highlight=lambda i, _: i == 5)
    lo, hi = _bootstrap(te, flag)
    ui.ok(f"final F1 (INVALID or REVIEW) 95% CI over days: {rows[5]['f1']:.3f} [{lo:.3f}, {hi:.3f}]")
    ui.table(OP_HEAD, [_op_row("test period", te, v)])
    ui.table(["verdict", "share of readings", "of which really faulty", "of which real events"], [
        [k, f"{m.mean():.2%}", f"{_truth(te)[m].mean():.1%}" if m.any() else "-", f"{ev[m].mean():.2%}" if m.any() else "-"]
        for k, m in (("VALID (auto)", v == "VALID"), ("REVIEW (human/second look)", rev), ("INVALID (auto)", inv))])

    ui.step("B. Detection per fault type")
    tier = te["fault_tier"].fillna("") if "fault_tier" in te else pd.Series("", index=te.index)
    per_class, rr = {}, []
    for c in INVALID_CLASSES:
        if c == "dropout":
            continue
        m = (te["fault_type"] == c).to_numpy()
        if not m.any():
            continue
        d = {"n": int(m.sum()), "auto_invalid": float(inv[m].mean()), "review": float(rev[m].mean()), "missed": float((v[m] == "VALID").mean()),
             "type_correct": float((hy["pred_class"].to_numpy()[m] == c).mean())}
        for tn in ("canonical", "subtle"):
            mt = m & (tier.to_numpy() == tn)
            d[f"missed_{tn}"] = float((v[mt] == "VALID").mean()) if mt.any() else np.nan
        per_class[c] = d
        rr.append([c, d["n"], f"{d['auto_invalid']:.1%}", f"{d['review']:.1%}", f"{d['missed']:.1%}",
                   "-" if d["missed_canonical"] != d["missed_canonical"] else f"{d['missed_canonical']:.1%}",
                   "-" if d["missed_subtle"] != d["missed_subtle"] else f"{d['missed_subtle']:.1%}", f"{d['type_correct']:.1%}"])
    ui.table(["fault type", "rows", "auto-invalid", "review", "missed", "missed (obvious)", "missed (subtle)", "type named right"], rr)
    drop_ok = float((apply_rules(te_all, bundle["faults"])[te_all["fault_type"] == "dropout"] == "dropout").mean())
    ui.ok(f"dropout detection by missing-data check: {drop_ok:.1%} of {n_drop:,} rows")

    sp = (te["fault_type"] == "spike").to_numpy()
    ratio = np.exp(te["pm_lr"].to_numpy())
    bands = [(2, 4), (4, 6), (6, 10), (10, 30), (30, 1e9)]
    ui.table(["spike size vs recent level", "rows", "auto-invalid", "review", "missed"], [
        [f"{a}x - {b if b < 1e8 else 'up'}x", int((sp & (ratio >= a) & (ratio < b)).sum()), f"{inv[sp & (ratio >= a) & (ratio < b)].mean():.1%}",
         f"{rev[sp & (ratio >= a) & (ratio < b)].mean():.1%}", f"{(v[sp & (ratio >= a) & (ratio < b)] == 'VALID').mean():.1%}"]
        for a, b in bands if (sp & (ratio >= a) & (ratio < b)).any()])

    ui.step("C. Real pollution events (valid but unusual)")
    pred_ev = (hy["pred_class"] == "pollution_event").to_numpy()
    ui.table(["measure", "value"], [
        ["event rows in test", int(ev.sum())],
        ["auto-rejected as sensor fault (the costly error)", f"{inv[ev].mean():.1%}"],
        ["sent to review", f"{rev[ev].mean():.1%}"],
        ["accepted as valid", f"{(v[ev] == 'VALID').mean():.1%}"],
        ["named 'pollution event'", f"{pred_ev[ev].mean():.1%}"],
        ["normal rows wrongly auto-rejected", f"{inv[nm].mean():.3%}"],
        ["normal rows sent to review", f"{rev[nm].mean():.3%}"],
    ])
    scope = te["event_scope"].fillna("").to_numpy() if "event_scope" in te else np.full(len(te), "")
    mult = te["event_mult"].to_numpy()
    ev_rows = []
    for name, m in [("city-wide events", ev & (scope == "city")), ("single-device bursts (look like spikes)", ev & (scope == "pulse"))]:
        if m.any():
            ev_rows.append([name, int(m.sum()), f"{inv[m].mean():.1%}", f"{rev[m].mean():.1%}", f"{(v[m] == 'VALID').mean():.1%}"])
    for a, b in [(3, 5), (5, 10), (10, 1e9)]:
        m = ev & (mult >= a) & (mult < b)
        if m.any():
            ev_rows.append([f"strength {a}x - {b if b < 1e8 else 'up'}x", int(m.sum()), f"{inv[m].mean():.1%}", f"{rev[m].mean():.1%}", f"{(v[m] == 'VALID').mean():.1%}"])
    ui.table(["event type", "rows", "auto-rejected", "review", "accepted"], ev_rows)
    wide = ev & (te["nbr_elev"].to_numpy() > 0.5)
    nsv = ns["verdict"].to_numpy()
    ui.table(["WHY neighbours matter", "rows", "auto-rejected WITH neighbours", "auto-rejected WITHOUT"], [[
        "city-wide events", int(wide.sum()), f"{inv[wide].mean():.1%}", f"{(nsv[wide] == 'INVALID').mean():.1%}"]])

    evr = te_all[te_all["fault_type"] == "pollution_event"]
    pk = np.array([event_cause(t, c)[0] for t, c in zip(evr["timestamp"], evr["city"])])
    ok = pk == evr["event_cause"].to_numpy()
    by = evr.assign(ok=ok).groupby("event_cause")["ok"].agg(["mean", "size"])
    ui.step("D. Reason engine vs simulator ground truth (events only)")
    ui.table(["true cause", "events", "reason matched"], [[k, int(r["size"]), f"{r['mean']:.1%}"] for k, r in by.iterrows()])
    ui.ok(f"overall reason match {ok.mean():.1%} (rules encode the simulator's own assumptions: a consistency check, not real-world proof)")

    ui.step("E. Calibration: when the model says 80% fault, is it a fault 80% of the time?")
    yt = _truth(te).astype(float)
    ece, bins = _calibration(hy["p_invalid"].to_numpy(), yt)
    brier = float(brier_score_loss(yt, hy["p_invalid"].clip(0, 1)))
    ui.table(["p(fault) band", "readings", "avg predicted", "actual fault rate"], [[b[0], f"{b[1]:,}", f"{b[2]:.3f}", f"{b[3]:.3f}"] for b in bins])
    ui.ok(f"expected calibration error {ece:.4f}, Brier score {brier:.5f}")

    ui.step("F. Robustness slices (INVALID or REVIEW)")
    ui.table(["slice", "rows", "faulty rows", "precision", "recall", "F1"], _slices(te, flag))

    lco = None
    if not skip_lco:
        ui.step(f"G. Unseen cities: retrained without {', '.join(HOLDOUT_CITIES)}, tested on them")
        keep = lambda x: x[~x["city"].isin(HOLDOUT_CITIES)]
        X, y, w, _ = prepare(keep(tr), normal_ratio=4.0)
        est = fit_selected(bundle["selection"], X, y, w)
        iso, thr, pol = calibrate(est, keep(va))
        b2 = {**bundle, "clf": est, "iso": iso, "policy": pol}
        th = te[te["city"].isin(HOLDOUT_CITIES)].reset_index(drop=True)
        a = predict(b2, th)
        b = predict(bundle, th)
        lco = _row("unseen cities", th, (a["verdict"] != "VALID").to_numpy(), a["p_invalid"])
        sn = _row("same cities, seen in training", th, (b["verdict"] != "VALID").to_numpy(), b["p_invalid"])
        ui.table(OP_HEAD, [_op_row("unseen cities", th, a["verdict"].to_numpy()), _op_row("same cities, seen in training", th, b["verdict"].to_numpy())])

    s1 = _stress(bundle, "H. Fair stress test 1: only SUBTLE faults (small spikes, short flatlines, soft saturation, mild probe faults)", subtle_share=1.0)
    s2 = _stress(bundle, "I. Fair stress test 2: fault FAMILIES never seen in training (double spike, zero-stuck, noise burst, temp step, RH flat-high)", family="heldout")

    ui.step("J. Real Atmos data (168 hourly readings, one device, no neighbours)")
    real, miss = real_check(bundle)
    ui.table(["caught", "false alarms", "missed", "correct valid"], [[real["tp"], real["fp"], real["fn"], real["tn"]]])
    if len(miss):
        ui.warn("disagreements with the real labels:")
        ui.table(["time", "pm2.5", "temp", "rh", "model says", "conf", "why"], [
            [str(r.timestamp), f"{r.pm25:.1f}", f"{r.temp:.1f}", f"{r.rh:.1f}", f"{r.verdict}/{r.pred_class}", f"{r.confidence:.2f}", r.reason[:80]] for r in miss.itertuples()])
    ui.warn("only 12 invalid rows exist in the real file: a sanity check, not a headline metric")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RESULT_DIR / "benchmark.csv", index=False)
    pd.crosstab(te["fault_type"], hy["pred_class"]).to_csv(RESULT_DIR / "confusion_matrix.csv")
    pd.DataFrame(bins, columns=["band", "n", "avg_pred", "actual"]).to_csv(RESULT_DIR / "calibration.csv", index=False)
    miss_rows = te[_truth(te) & (v == "VALID")].assign(pred=hy["pred_class"].to_numpy()[_truth(te) & (v == "VALID")])
    miss_rows[["timestamp", "device_id", "city", "pm25", "temp", "rh", "fault_type", "pred"]].head(2000).to_csv(RESULT_DIR / "missed_faults.csv", index=False)
    (RESULT_DIR / "summary.json").write_text(json.dumps({
        "model": bundle["selection"], "final": rows[5], "auto_invalid_only": rows[4], "f1_ci95": [lo, hi], "per_class": per_class,
        "event_auto_reject": float(inv[ev].mean()), "event_review": float(rev[ev].mean()), "reason_match": float(ok.mean()),
        "ece": ece, "brier": brier, "unseen_cities": lco, "stress_subtle": s1, "stress_heldout": s2, "real_data": real,
    }, indent=2, default=float))
    ui.ok(f"saved -> {RESULT_DIR}")
    return rows
