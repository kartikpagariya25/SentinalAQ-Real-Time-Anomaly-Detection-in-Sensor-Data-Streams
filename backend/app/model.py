import time

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import (ExtraTreesClassifier, HistGradientBoostingClassifier,
                              IsolationForest, RandomForestClassifier)
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import INVALID_CLASSES, ML_CLASSES, MODEL_DIR, MODEL_FILE, RULE_CONFIDENCE
from .features import FEATURES, SPATIAL
from .rules import apply_rules

try:
    import xgboost as xgb
except Exception:
    xgb = None

CLASS_IDX = {c: i for i, c in enumerate(ML_CLASSES)}
INV_IDX = [CLASS_IDX[c] for c in INVALID_CLASSES if c in CLASS_IDX]
VAL_IDX = [i for i in range(len(ML_CLASSES)) if i not in INV_IDX]
K = len(ML_CLASSES)


def _lgbm(**kw):
    base = dict(objective="multiclass", n_estimators=300, learning_rate=0.1, num_leaves=63, min_child_samples=30,
                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1, random_state=7, verbose=-1)
    return lgb.LGBMClassifier(**{**base, **kw})


def _xgb(**kw):
    base = dict(objective="multi:softprob", n_estimators=300, learning_rate=0.1, max_depth=7, subsample=0.8,
                colsample_bytree=0.8, tree_method="hist", n_jobs=-1, random_state=7, verbosity=0)
    return xgb.XGBClassifier(**{**base, **kw})


def _hgb(**kw):
    base = dict(max_iter=250, learning_rate=0.1, max_leaf_nodes=63, min_samples_leaf=30, l2_regularization=1.0, early_stopping=False, random_state=7)
    return HistGradientBoostingClassifier(**{**base, **kw})


def _rf(**kw):
    base = dict(n_estimators=150, min_samples_leaf=2, max_features="sqrt", n_jobs=-1, random_state=7)
    return Pipeline([("imp", SimpleImputer(strategy="constant", fill_value=-999.0)), ("clf", RandomForestClassifier(**{**base, **kw}))])


def _et(**kw):
    base = dict(n_estimators=150, min_samples_leaf=2, max_features="sqrt", n_jobs=-1, random_state=7)
    return Pipeline([("imp", SimpleImputer(strategy="constant", fill_value=-999.0)), ("clf", ExtraTreesClassifier(**{**base, **kw}))])


def _logreg(**kw):
    base = dict(max_iter=400, C=1.0)
    return Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)), ("sc", StandardScaler()), ("clf", LogisticRegression(**{**base, **kw}))])


def _mlp(**kw):
    base = dict(hidden_layer_sizes=(128, 64), early_stopping=True, max_iter=60, random_state=7)
    return Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)), ("sc", StandardScaler()), ("clf", MLPClassifier(**{**base, **kw}))])


def registry():
    reg = {
        "logreg": _logreg,
        "random_forest": _rf,
        "extra_trees": _et,
        "hist_gb": _hgb,
        "lightgbm": _lgbm,
        "mlp": _mlp,
    }
    if xgb is not None:
        reg["xgboost"] = _xgb
    return reg


SEARCH_SPACE = {
    "lightgbm": {"num_leaves": [31, 63, 127], "learning_rate": [0.05, 0.1], "n_estimators": [200, 300, 450], "min_child_samples": [20, 50, 100], "colsample_bytree": [0.6, 0.8, 1.0]},
    "xgboost": {"max_depth": [5, 7, 9], "learning_rate": [0.05, 0.1], "n_estimators": [200, 300, 450], "min_child_weight": [1, 5, 10], "colsample_bytree": [0.6, 0.8, 1.0]},
    "hist_gb": {"max_leaf_nodes": [31, 63, 127], "learning_rate": [0.05, 0.1], "max_iter": [200, 300, 400], "min_samples_leaf": [20, 50, 100]},
    "random_forest": {"n_estimators": [100, 150], "min_samples_leaf": [2, 4, 8]},
    "extra_trees": {"n_estimators": [100, 150], "min_samples_leaf": [2, 4, 8]},
    "mlp": {"hidden_layer_sizes": [(64, 32), (128, 64), (256, 128)], "alpha": [0.0001, 0.001, 0.01], "learning_rate_init": [0.001, 0.003]},
}


class SoftVote:
    def __init__(self, members):
        self.members = members

    def predict_proba(self, X):
        return np.mean([proba(m, X) for m in self.members], axis=0)


def fit_model(est, X, y, w):
    if isinstance(est, Pipeline):
        last = est.steps[-1][0]
        try:
            return est.fit(X, y, **{f"{last}__sample_weight": w})
        except (TypeError, ValueError):
            return est.fit(X, y)
    return est.fit(X, y, sample_weight=w)


def proba(est, X):
    p = est.predict_proba(X)
    classes = getattr(est, "classes_", None)
    if classes is None and isinstance(est, Pipeline):
        classes = est.steps[-1][1].classes_
    if classes is not None and p.shape[1] != K:
        full = np.zeros((p.shape[0], K))
        full[:, np.asarray(classes, int)] = p
        return full
    return p


def prepare(feats, mask_spatial=0.15, seed=0, normal_ratio=None):
    d = feats[feats["fault_type"].isin(CLASS_IDX)].copy()
    if normal_ratio:
        rng = np.random.default_rng(seed)
        non = d["fault_type"] != "normal"
        keep = non.to_numpy() | (rng.random(len(d)) < min(1.0, normal_ratio * non.sum() / max((~non).sum(), 1)))
        d = d[keep]
    if mask_spatial > 0:
        rng = np.random.default_rng(seed + 1)
        m = rng.random(len(d)) < mask_spatial
        d.loc[m, SPATIAL] = np.nan
    y = d["fault_type"].map(CLASS_IDX).to_numpy()
    counts = np.bincount(y, minlength=K).astype(float)
    w_class = np.clip((counts.max() / np.maximum(counts, 1)) ** 0.5, 1, 20)
    return d[FEATURES], y, w_class[y], d


def p_invalid(est, X):
    return proba(est, X)[:, INV_IDX].sum(axis=1)


def best_f1(p, y, grid=None):
    grid = np.linspace(0.02, 0.98, 97) if grid is None else grid
    scores = [f1_score(y, p >= t, zero_division=0) for t in grid]
    i = int(np.argmax(scores))
    return float(grid[i]), float(scores[i])


def score_candidate(est, X, y_inv, is_event, grid=None):
    p = p_invalid(est, X)
    thr, f1 = best_f1(p, y_inv, grid)
    flagged = p >= thr
    return {
        "pr_auc": float(average_precision_score(y_inv, p)),
        "f1": f1,
        "threshold": thr,
        "event_reject": float(flagged[is_event].mean()) if is_event.any() else 0.0,
        "false_alarm": float(flagged[y_inv == 0].mean()),
    }


def timed_fit(name, params, X, y, w):
    est = registry()[name](**params)
    t = time.time()
    fit_model(est, X, y, w)
    return est, time.time() - t


def train_iforest(train, val, seed=7):
    tr = train[train["fault_type"].isin(CLASS_IDX)]
    normal = tr[tr["fault_type"] == "normal"]
    fill = normal[FEATURES].median()
    sample = normal.sample(min(150000, len(normal)), random_state=seed)
    iso = IsolationForest(n_estimators=150, max_samples=4096, random_state=seed, n_jobs=-1)
    iso.fit(sample[FEATURES].fillna(fill))
    va = val[val["fault_type"] != "dropout"]
    score = -iso.decision_function(va[FEATURES].fillna(fill))
    lo, hi = np.percentile(score, [1, 99])
    y = (~va["fault_type"].isin(["normal", "pollution_event"])).astype(int)
    grid = np.linspace(lo, hi, 80)
    best = max(grid, key=lambda t: f1_score(y, score >= t, zero_division=0))
    return {"model": iso, "fill": fill, "threshold": float(best)}


def choose_policy(p, y_inv, is_event, ignore=None, cls=None, min_inv_precision=0.99, max_miss_rate=0.05, max_event_reject=0.03, max_class_miss=0.10):
    best = None
    groups = [] if cls is None else [np.asarray(cls) == c for c in sorted(set(cls) - {"normal", "pollution_event", "drift", "dropout"})]
    groups = [g for g in groups if g.sum() >= 20]
    ign = np.zeros(len(p), bool) if ignore is None else np.asarray(ignore, bool)
    y_pt = (np.asarray(y_inv) == 1) & ~ign
    for lo in np.concatenate(([0.0005, 0.001, 0.002, 0.004, 0.007], np.linspace(0.01, 0.45, 23))):
        for hi in np.linspace(0.55, 0.99, 23):
            inv = p >= hi
            val = p < lo
            decided = inv | val
            prec = y_inv[inv].mean() if inv.any() else 1.0
            err = y_inv[val].mean() if val.any() else 0.0
            ev = inv[is_event].mean() if is_event.any() else 0.0
            miss = y_pt[val].sum() / max(y_pt.sum(), 1)
            worst = max([(val & g).sum() / g.sum() for g in groups], default=0.0)
            ok = prec >= min_inv_precision and miss <= max_miss_rate and ev <= max_event_reject and worst <= max_class_miss
            cov = decided.mean()
            key = (ok, cov if ok else -(1 - prec) - miss - ev - worst)
            if best is None or key > best[0]:
                best = (key, lo, hi, cov, prec, err, ev, ok, miss, worst)
    return {"lo": float(best[1]), "hi": float(best[2]), "coverage": float(best[3]), "inv_precision": float(best[4]),
            "valid_error": float(best[5]), "event_reject": float(best[6]), "constraints_met": bool(best[7]), "miss_rate": float(best[8]), "worst_class_miss": float(best[9])}


def calibrate(est, val):
    va = val[val["fault_type"].isin(CLASS_IDX)]
    X = va[FEATURES]
    y_inv = np.isin(va["fault_type"], INVALID_CLASSES).astype(int)
    is_event = (va["fault_type"] == "pollution_event").to_numpy()
    raw = p_invalid(est, X)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, y_inv)
    cal = iso.predict(raw)
    thr, f1 = best_f1(cal, y_inv)
    return iso, thr, choose_policy(cal, y_inv, is_event, ignore=(va["fault_type"] == "drift").to_numpy(), cls=va["fault_type"].to_numpy())


def predict(bundle, feats, faults=None, use_rules=True, hide_neighbours=False):
    faults = faults or bundle["faults"]
    X = feats[FEATURES]
    if hide_neighbours:
        X = X.copy()
        X[SPATIAL] = np.nan
    pr = proba(bundle["clf"], X)
    p_raw = pr[:, INV_IDX].sum(axis=1)
    p_inv = bundle["iso"].predict(p_raw)
    classes = np.array(ML_CLASSES, dtype=object)
    pred = classes[pr.argmax(axis=1)].astype(object)
    inv_cls = classes[INV_IDX][pr[:, INV_IDX].argmax(axis=1)]
    pol = bundle["policy"]
    verdict = np.where(p_inv >= pol["hi"], "INVALID", np.where(p_inv < pol["lo"], "VALID", "REVIEW")).astype(object)
    pred = np.where(verdict == "INVALID", inv_cls, pred).astype(object)
    pred = np.where((verdict == "VALID") & np.isin(pred, INVALID_CLASSES), "normal", pred).astype(object)
    conf = np.clip(np.where(verdict == "INVALID", p_inv, np.where(verdict == "VALID", 1.0 - p_inv, np.maximum(p_inv, 1.0 - p_inv))), 0.01, 0.99)
    source = np.full(len(feats), "model", dtype=object)
    if use_rules:
        rule = apply_rules(feats, faults).to_numpy()
        hit = rule != ""
        pred[hit], verdict[hit], conf[hit], source[hit] = rule[hit], "INVALID", RULE_CONFIDENCE, "rule"
        p_inv = np.where(hit, 1.0, p_inv)
    return pd.DataFrame({
        "pred_class": pred, "verdict": verdict, "pred_valid": verdict == "VALID",
        "confidence": conf, "p_invalid": p_inv, "source": source,
    }, index=feats.index)


def _booster(bundle):
    est = bundle["clf"]
    members = est.members if isinstance(est, SoftVote) else [est]
    for m in members:
        if isinstance(m, lgb.LGBMClassifier):
            return "lgb", m.booster_
    for m in members:
        if xgb is not None and isinstance(m, xgb.XGBClassifier):
            return "xgb", m.get_booster()
    return None, None


def drivers(bundle, feats, classes, top=3):
    kind, booster = _booster(bundle)
    if booster is None:
        return [""] * len(classes)
    X = feats[FEATURES]
    if kind == "lgb":
        contrib = booster.predict(X, pred_contrib=True).reshape(len(X), K, len(FEATURES) + 1)
    else:
        contrib = booster.predict(xgb.DMatrix(X), pred_contribs=True)
    out = []
    for i, c in enumerate(classes):
        ci = CLASS_IDX.get(c)
        if ci is None:
            out.append("")
            continue
        vals = contrib[i, ci, :-1]
        order = np.argsort(-np.abs(vals))[:top]
        out.append(", ".join(f"{FEATURES[j]}{'+' if vals[j] > 0 else '-'}" for j in order))
    return out


def save_bundle(bundle):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL_FILE)


def load_bundle():
    return joblib.load(MODEL_FILE)
