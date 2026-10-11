import numpy as np
import pandas as pd

from .config import HISTORY_HOURS
from .features import build_features
from .model import drivers, predict
from .reasons import explain

RAW_COLS = ["timestamp", "device_id", "city", "pm25", "temp", "rh"]


def _gap_lengths(hist, devices):
    out = {}
    for dev in devices:
        pm = hist.loc[hist["device_id"] == dev].sort_values("timestamp")["pm25"].to_numpy()
        n = 0
        for v in pm[::-1]:
            if np.isnan(v):
                n += 1
            else:
                break
        out[dev] = n
    return out


def annotate(bundle, feats, with_drivers=True, gaps=None):
    pred = predict(bundle, feats)
    res = feats[RAW_COLS + [c for c in ("pm_run", "pm_lr", "sp_pm", "sp_rh", "nbr_elev", "nbr_n", "sp_m72") if c in feats.columns]].copy()
    res = res.join(pred)
    if gaps is not None:
        res["gap_len"] = res["device_id"].map(gaps).fillna(1)
    res["reason"] = [explain(r) for r in res.to_dict("records")]
    res["drivers"] = ""
    if with_drivers:
        pick = (res["source"] == "model") & ((res["pred_class"] != "normal") | (res["verdict"] == "REVIEW"))
        if pick.any():
            res.loc[pick, "drivers"] = drivers(bundle, feats.loc[pick], res.loc[pick, "pred_class"].tolist())
    return res


class Detector:
    def __init__(self, bundle):
        self.bundle = bundle
        self.hist = None

    def _push(self, tick):
        t = tick[RAW_COLS]
        self.hist = t.copy() if self.hist is None else pd.concat([self.hist, t], ignore_index=True)
        cutoff = tick["timestamp"].max() - pd.Timedelta(hours=HISTORY_HOURS - 1)
        self.hist = self.hist[self.hist["timestamp"] >= cutoff]

    def warm(self, tick):
        self._push(tick)

    def process(self, tick):
        self._push(tick)
        now = tick["timestamp"].max()
        feats = build_features(self.hist)
        cur = feats[feats["timestamp"] == now]
        gaps = _gap_lengths(self.hist, cur.loc[cur["pm25"].isna(), "device_id"].unique())
        return annotate(self.bundle, cur, gaps=gaps).reset_index(drop=True)


def run_batch(bundle, df, with_drivers=False):
    feats = build_features(df)
    return feats, annotate(bundle, feats, with_drivers=with_drivers)
