import json

import numpy as np
import pandas as pd

from .config import PROFILE_FILE, RAW_FILE, SYN_DIR


def _smooth(a):
    a = np.asarray(a, float)
    for _ in range(2):
        a = 0.25 * np.roll(a, 1) + 0.5 * a + 0.25 * np.roll(a, -1)
    return a


def _lag1(res):
    a, b = res[:-1], res[1:]
    m = ~np.isnan(a) & ~np.isnan(b)
    if m.sum() < 10:
        return 0.8
    return float(np.corrcoef(a[m], b[m])[0, 1])


def load_raw(path=RAW_FILE):
    d = pd.read_excel(path)
    d = d.rename(columns={d.columns[0]: "timestamp", "pm2.5cnc": "pm25", "humidity": "rh", "data_validity": "is_valid"})
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    return d.sort_values("timestamp").reset_index(drop=True)


def _hourly(values, hours, how):
    s = pd.Series(values).groupby(hours).agg(how).reindex(range(24))
    return s.interpolate(limit_direction="both").to_numpy()


def build_profile(path=RAW_FILE):
    d = load_raw(path)
    d["hour"] = d.timestamp.dt.hour
    good = d[(d.is_valid == 1) & (d.pm25 < 200)].copy()
    bad = d[d.is_valid == 0]

    lpm = np.log(good.pm25.to_numpy())
    pm_prof = _smooth(_hourly(lpm, good.hour.to_numpy(), "median"))
    d["lpm_res"] = np.where((d.is_valid == 1) & (d.pm25 < 200), np.log(d.pm25.clip(lower=1e-3)) - pm_prof[d.hour], np.nan)
    pm_sd = float(1.4826 * np.nanmedian(np.abs(d.lpm_res - np.nanmedian(d.lpm_res))))
    pm_phi_raw = _lag1(d.lpm_res.to_numpy())

    t_prof = _smooth(_hourly(good.temp.to_numpy(), good.hour.to_numpy(), "mean"))
    r_prof = _smooth(_hourly(good.rh.to_numpy(), good.hour.to_numpy(), "mean"))
    d["t_res"] = np.where(d.is_valid == 1, d.temp - t_prof[d.hour], np.nan)
    d["r_res"] = np.where(d.is_valid == 1, d.rh - r_prof[d.hour], np.nan)
    t_sd, r_sd = float(np.nanstd(d.t_res)), float(np.nanstd(d.r_res))
    t_phi_raw, r_phi_raw = _lag1(d.t_res.to_numpy()), _lag1(d.r_res.to_numpy())
    m = d.t_res.notna() & d.r_res.notna()
    beta = float(np.cov(d.r_res[m], d.t_res[m])[0, 1] / np.var(d.t_res[m]))

    big = bad[bad.pm25 > 1000].pm25.round(2)
    rep = big.value_counts()
    sentinel = float(rep[rep >= 2].index[0]) if (rep >= 2).any() else 3333.0
    sat = bad[(bad.pm25 >= 3000) & (bad.pm25.round(2) != sentinel)].pm25
    sat_min = float(sat.min()) if len(sat) else 3200.0
    sat_max = float(sat.max()) if len(sat) else 3500.0
    sat_floor = 0.9 * float(bad[bad.pm25 >= 3000].pm25.min()) if (bad.pm25 >= 3000).any() else 2900.0

    spikes = bad[(bad.pm25 > 200) & (bad.pm25 < 0.9 * sat_floor)]
    spike_ratio = float((spikes.pm25 / np.exp(pm_prof[spikes.hour])).max()) if len(spikes) else 60.0

    low_t = bad[bad.temp < 10].temp
    high_t = bad[bad.temp > 50].temp
    rh_bad = bad[((bad.rh >= 99.9) & (bad.temp >= 10)) | (bad.rh < 15)]
    rh_low = rh_bad[rh_bad.rh < 15].rh
    rh_high_share = float((rh_bad.rh >= 99.9).mean()) if len(rh_bad) else 0.5

    ev = good.copy()
    allv = d[(d.is_valid == 1)]
    event_ratio = float((allv.pm25 / np.exp(pm_prof[allv.hour])).max())

    prof = {
        "source_rows": int(len(d)),
        "valid_rows": int((d.is_valid == 1).sum()),
        "invalid_rate": float((d.is_valid == 0).mean()),
        "start": str(d.timestamp.min()),
        "end": str(d.timestamp.max()),
        "pm": {"hourly_log": pm_prof.tolist(), "sd": pm_sd, "phi_raw": pm_phi_raw, "phi": float(np.clip(pm_phi_raw, 0.6, 0.95)), "median": float(good.pm25.median()), "p99": float(good.pm25.quantile(0.99))},
        "temp": {"hourly": t_prof.tolist(), "sd": t_sd, "phi_raw": t_phi_raw, "phi": float(np.clip(t_phi_raw, 0.6, 0.95)), "min": float(good.temp.min()), "max": float(good.temp.max())},
        "rh": {"hourly": r_prof.tolist(), "sd": r_sd, "phi_raw": r_phi_raw, "phi": float(np.clip(r_phi_raw, 0.6, 0.95)), "beta_temp": beta, "min": float(good.rh.min()), "max": float(good.rh.max())},
        "faults": {
            "sentinel": sentinel,
            "sat_min": sat_min,
            "sat_max": sat_max,
            "sat_floor": sat_floor,
            "spike_ratio": spike_ratio,
            "th_temp": [float(low_t.min() * 0.7), float(low_t.max() * 1.5)] if len(low_t) else [2.0, 5.0],
            "imp_temp_high": [float(high_t.min() * 0.75), float(high_t.max() * 1.25)] if len(high_t) else [60.0, 99.0],
            "rh_low": [float(rh_low.min() * 0.4), float(rh_low.max() * 1.6)] if len(rh_low) else [3.0, 12.0],
            "rh_high_share": rh_high_share,
        },
        "event_ratio": event_ratio,
    }
    return prof


def save_profile(prof):
    SYN_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(prof, indent=2))


def load_profile():
    return json.loads(PROFILE_FILE.read_text())
