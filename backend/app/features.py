import warnings

import numpy as np
import pandas as pd

from .config import RUN_CAP

SPATIAL = ["sp_pm", "sp_temp", "sp_rh", "nbr_elev", "nbr_n", "nbr_sd", "sp_pm_1", "sp_pm_2", "sp_m24", "sp_m72", "sp_m168", "sp_slope"]
FEATURES = [
    "pm25", "temp", "rh", "pm_med24",
    "pm_lr", "pm_lr6", "pm_z", "pm_d1", "pm_l24", "pm_run", "pm_lr_1", "pm_lr_2", "pm_vol6", "pm_trend72",
    "temp_dm", "temp_d1", "temp_l24", "temp_run", "temp_dm_1",
    "rh_dm", "rh_d1", "rh_l24", "rh_run", "rh_dm_1",
    *SPATIAL,
    "hour_sin", "hour_cos", "month_sin", "month_cos",
]


def _run_len(df, col):
    s = df[col]
    prev = s.groupby(df["device_id"], sort=False).shift(1)
    new = (s != prev) | s.isna()
    run_id = new.groupby(df["device_id"], sort=False).cumsum()
    run = df.groupby([df["device_id"], run_id], sort=False).cumcount() + 1
    return run.where(s.notna(), 0).clip(upper=RUN_CAP)


def _roll(g, col, fn, window, minp, shift=1):
    return g[col].transform(lambda s: getattr(s.shift(shift).rolling(window, min_periods=minp), fn)() if shift else getattr(s.rolling(window, min_periods=minp), fn)())


def _loo(wide):
    a = wide.to_numpy(dtype=float)
    med = np.full_like(a, np.nan)
    sd = np.full_like(a, np.nan)
    cnt = np.zeros_like(a)
    if a.shape[1] < 2:
        return med, sd, cnt
    valid = ~np.isnan(a)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for j in range(a.shape[1]):
            rest = np.delete(a, j, axis=1)
            med[:, j] = np.nanmedian(rest, axis=1)
            sd[:, j] = np.nanstd(rest, axis=1)
    cnt = (valid.sum(axis=1, keepdims=True) - valid).astype(float)
    return med, sd, cnt


def _spatial(df):
    n = len(df)
    res = {k: np.full(n, np.nan) for k in ("_nbr_lpm", "_nbr_t", "_nbr_rh", "nbr_sd", "nbr_n")}
    for _, sub in df.groupby("city", sort=False):
        pos = sub.index.to_numpy()
        for key, col in (("_nbr_lpm", "_lpm"), ("_nbr_t", "temp"), ("_nbr_rh", "rh")):
            wide = sub.pivot(index="timestamp", columns="device_id", values=col)
            med, sd, cnt = _loo(wide)
            ti = wide.index.get_indexer(sub["timestamp"])
            dj = wide.columns.get_indexer(sub["device_id"])
            res[key][pos] = med[ti, dj]
            if key == "_nbr_lpm":
                res["nbr_sd"][pos] = sd[ti, dj]
                res["nbr_n"][pos] = cnt[ti, dj]
    return res


def build_features(df):
    d = df.sort_values(["device_id", "timestamp"]).reset_index(drop=True).copy()
    d["_lpm"] = np.log1p(d["pm25"])
    g = d.groupby("device_id", sort=False)

    lpm_med = _roll(g, "_lpm", "median", 24, 6)
    lpm_mean = _roll(g, "_lpm", "mean", 24, 6)
    lpm_std = _roll(g, "_lpm", "std", 24, 6)
    d["pm_med24"] = np.expm1(lpm_med)
    d["pm_lr"] = d["_lpm"] - lpm_med
    d["pm_lr6"] = d["_lpm"] - _roll(g, "_lpm", "median", 6, 3)
    d["pm_z"] = (d["_lpm"] - lpm_mean) / (lpm_std + 0.1)
    d["pm_d1"] = d["_lpm"] - g["_lpm"].shift(1)
    d["pm_l24"] = d["_lpm"] - g["_lpm"].shift(24)
    d["pm_run"] = _run_len(d, "pm25")
    d["pm_vol6"] = d.groupby("device_id", sort=False)["pm_d1"].transform(lambda s: s.rolling(6, min_periods=4).std())

    for col in ("temp", "rh"):
        d[f"{col}_dm"] = d[col] - _roll(g, col, "median", 24, 6)
        d[f"{col}_d1"] = d[col] - g[col].shift(1)
        d[f"{col}_l24"] = d[col] - g[col].shift(24)
        d[f"{col}_run"] = _run_len(d, col)

    g = d.groupby("device_id", sort=False)
    m24 = g["_lpm"].transform(lambda x: x.rolling(24, min_periods=12).mean())
    d["pm_trend72"] = m24 - m24.groupby(d["device_id"], sort=False).shift(72)
    d["pm_lr_1"] = g["pm_lr"].shift(1)
    d["pm_lr_2"] = g["pm_lr"].shift(2)
    d["temp_dm_1"] = g["temp_dm"].shift(1)
    d["rh_dm_1"] = g["rh_dm"].shift(1)

    sp = _spatial(d)
    d["sp_pm"] = d["_lpm"] - sp["_nbr_lpm"]
    d["sp_temp"] = d["temp"] - sp["_nbr_t"]
    d["sp_rh"] = d["rh"] - sp["_nbr_rh"]
    d["nbr_elev"] = sp["_nbr_lpm"] - lpm_med
    d["nbr_n"] = sp["nbr_n"]
    d["nbr_sd"] = sp["nbr_sd"]
    g = d.groupby("device_id", sort=False)
    d["sp_pm_1"] = g["sp_pm"].shift(1)
    d["sp_pm_2"] = g["sp_pm"].shift(2)
    d["sp_m24"] = g["sp_pm"].transform(lambda x: x.rolling(24, min_periods=12).mean())
    d["sp_m72"] = g["sp_pm"].transform(lambda x: x.rolling(72, min_periods=36).mean())
    d["sp_m168"] = g["sp_pm"].transform(lambda x: x.rolling(168, min_periods=72).mean())
    d["sp_slope"] = d["sp_m24"] - d.groupby("device_id", sort=False)["sp_m24"].shift(72)
    d.loc[d["nbr_n"] == 0, SPATIAL] = np.nan

    h = d["timestamp"].dt.hour.to_numpy()
    m = d["timestamp"].dt.month.to_numpy()
    d["hour_sin"] = np.sin(2 * np.pi * h / 24)
    d["hour_cos"] = np.cos(2 * np.pi * h / 24)
    d["month_sin"] = np.sin(2 * np.pi * m / 12)
    d["month_cos"] = np.cos(2 * np.pi * m / 12)
    return d.drop(columns=["_lpm"])
