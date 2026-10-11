import numpy as np
import pandas as pd
from scipy.signal import lfilter

from .config import EVENT_MIN_MULT
from .priors import CITIES, FESTIVALS, PRESETS, STRONG_PRESETS

CITY_SHARE = 0.6
WEEKDAY = np.log([1.04, 1.05, 1.05, 1.05, 1.05, 1.0, 0.9])
FAULT_RATES = {
    "dropout": 0.0035,
    "stuck": 0.0015,
    "saturation": 0.0012,
    "th_fault": 0.0030,
    "rh_fault": 0.0030,
    "impossible_temp": 0.0015,
    "spike": 0.0020,
    "drift": 0.00006,
}
HELDOUT_RATES = {
    "dropout": 0.0035,
    "double_spike": 0.0020,
    "zero_stuck": 0.0012,
    "noise_burst": 0.0012,
    "temp_step": 0.0012,
    "rh_flat_high": 0.0012,
}


def _ar1(rng, n, sd, phi):
    eps = rng.normal(0.0, sd * np.sqrt(1 - phi ** 2), n)
    return lfilter([1.0], [1.0, -phi], eps)


def _loguniform(rng, lo, hi):
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


def _paint(lm, cause, start, dur, peak, name):
    n = len(lm)
    rise = max(1, int(round(0.25 * dur)))
    k = np.arange(dur)
    shape = np.where(k < rise, (k + 1) / rise, np.exp(-(k - rise) / max(1.0, (dur - rise) / 3.0)))
    seg = np.log(peak) * shape
    lo, hi = max(start, 0), min(n, start + dur)
    if hi <= lo:
        return
    seg = seg[lo - start: hi - start]
    better = seg > lm[lo:hi]
    lm[lo:hi] = np.where(better, seg, lm[lo:hi])
    cause[lo:hi] = np.where(better, name, cause[lo:hi])


def _episodes(rng, rate, dur_rng):
    n = len(rate)
    out = np.zeros(n)
    for s in np.flatnonzero(rng.random(n) < rate):
        d = int(rng.integers(dur_rng[0], dur_rng[1] + 1))
        bump = np.sin(np.pi * (np.arange(d) + 0.5) / d) ** 2 * rng.uniform(0.6, 1.0)
        e = min(n, s + d)
        out[s:e] = np.maximum(out[s:e], bump[: e - s])
    return out


def city_events(rng, idx, preset):
    n = len(idx)
    hour, month, day = idx.hour.to_numpy(), idx.month.to_numpy(), idx.day.to_numpy()
    lm = np.zeros(n)
    cause = np.full(n, "", dtype=object)

    def sample(rate, name, dur_rng, peak_rng):
        for s in np.flatnonzero(rng.random(n) < rate):
            dur = int(rng.integers(dur_rng[0], dur_rng[1] + 1))
            _paint(lm, cause, int(s), dur, _loguniform(rng, *peak_rng), name)

    sample(np.full(n, 0.0008), "local_source", (3, 18), (2.2, 12.0))
    if preset == "north_plain":
        burn = ((month == 10) & (day >= 15)) | ((month == 11) & (day <= 25))
        sample(np.where(burn, 0.004, 0.0), "crop_residue_burning", (8, 36), (2.5, 8.0))
    if preset in STRONG_PRESETS:
        inv = np.isin(month, [12, 1, 2]) & (hour >= 20)
        sample(np.where(inv, 0.015, 0.0), "winter_inversion", (6, 14), (2.2, 6.0))
    if preset in ("north_plain", "central_plateau", "semi_arid"):
        dust = np.isin(month, [3, 4, 5, 6]) & (hour >= 11) & (hour <= 16)
        sample(np.where(dust, 0.004, 0.0), "dust_storm", (3, 10), (2.5, 10.0))
    for f in FESTIVALS:
        start_ts = pd.Timestamp(f["date"]) + pd.Timedelta(hours=f["hour"])
        pos = int((start_ts - idx[0]) / pd.Timedelta(hours=1))
        if pos + f["dur"] <= 0 or pos >= n:
            continue
        rng_p = f["strong"] if preset in STRONG_PRESETS else f["weak"]
        _paint(lm, cause, pos, f["dur"], rng.uniform(*rng_p), f["key"])
    return lm, cause


def city_weather(rng, idx, preset):
    n = len(idx)
    hour, month = idx.hour.to_numpy(), idx.month.to_numpy()
    rain_rate = np.where(np.isin(month, [6, 7, 8, 9]), 0.012, np.where(np.isin(month, [5, 10]), 0.004, 0.001))
    rain = _episodes(rng, rain_rate, (2, 12))
    fog = np.zeros(n)
    if preset in ("north_plain", "east_delta", "semi_arid"):
        fog_rate = np.where(np.isin(month, [12, 1, 2]) & ((hour >= 21) | (hour <= 2)), 0.02, 0.0)
        fog = _episodes(rng, fog_rate, (5, 11))
    heat = np.zeros(n)
    if preset in ("north_plain", "central_plateau", "semi_arid"):
        heat = _episodes(rng, np.where(np.isin(month, [4, 5, 6]), 0.0015, 0.0), (48, 120))
    return rain, fog, heat


def _pick_tier(rng, share):
    return "subtle" if rng.random() < share else "canonical"


def _helpers(rng, s, scale):
    n = len(s["pm"])
    taken = s["taken"]

    def starts(rate):
        return np.flatnonzero(rng.random(n) < rate * scale)

    def span(i, length):
        if taken[i]:
            return None
        e = i + 1
        while e < min(n, i + length) and not taken[e]:
            e += 1
        return e

    def geom(mean, cap, floor=1):
        return int(min(cap, floor + rng.geometric(1.0 / max(mean, 1.0001)) - 1))

    return n, starts, span, geom


def _inject_standard(rng, s, F, scale, share):
    pm, temp, rh = s["pm"], s["temp"], s["rh"]
    c_pm, c_t, c_rh = s["clean"]
    label, tier, taken = s["label"], s["tier"], s["taken"]
    n, starts, span, geom = _helpers(rng, s, scale)

    def mark(i, e, name, t=""):
        label[i:e] = name
        tier[i:e] = t
        taken[i:e] = True

    for i in starts(FAULT_RATES["drift"]):
        ramp, hold = int(rng.integers(72, 241)), int(rng.integers(24, 97))
        if taken[i:min(n, i + ramp + hold)].any():
            continue
        g = _loguniform(rng, 1.4, 2.5)
        g = g if rng.random() < 0.5 else 1.0 / g
        gain = np.concatenate([np.exp(np.log(g) * (np.arange(ramp) + 1) / ramp), np.full(hold, g)])
        e = min(n, i + len(gain))
        gain = gain[: e - i]
        pm[i:e] = np.round(pm[i:e] * gain, 2)
        strong = np.abs(np.log(gain)) >= np.log(1.5)
        label[i:e] = np.where(strong, "drift", label[i:e])
        tier[i:e] = np.where(strong, "canonical", tier[i:e])
        taken[i:e] = True

    for i in starts(FAULT_RATES["dropout"]):
        e = span(i, geom(7, 72))
        if e is None:
            continue
        pm[i:e] = temp[i:e] = rh[i:e] = np.nan
        mark(i, e, "dropout")

    for i in starts(FAULT_RATES["stuck"]):
        t = _pick_tier(rng, share)
        e = span(i, geom(2, 5, 3) if t == "subtle" else geom(4, 24, 3))
        if e is None or e - i < 2:
            continue
        ref = max(i - 1, 0)
        if t == "canonical" and rng.random() < 0.5:
            pm[i:e] = F["sentinel"]
        else:
            pm[i:e] = round(float(c_pm[ref]), 2)
            if rng.random() < 0.3:
                temp[i:e] = round(float(c_t[ref]), 2)
                rh[i:e] = round(float(c_rh[ref]), 2)
        mark(i, e, "stuck", t)

    for i in starts(FAULT_RATES["saturation"]):
        t = _pick_tier(rng, share)
        e = span(i, geom(2.5, 6))
        if e is None:
            continue
        lo, hi = (1500.0, 2800.0) if t == "subtle" else (F["sat_min"] * 0.95, F["sat_max"] * 1.05)
        pm[i:e] = np.round(rng.uniform(lo, hi, e - i), 1)
        mark(i, e, "saturation", t)

    for i in starts(FAULT_RATES["th_fault"]):
        t = _pick_tier(rng, share)
        e = span(i, geom(1.8, 4))
        if e is None:
            continue
        if t == "subtle":
            temp[i:e] = np.round(c_t[i:e] - rng.uniform(12.0, 22.0, e - i), 2)
        else:
            temp[i:e] = np.round(rng.uniform(*F["th_temp"], e - i), 2)
        rh[i:e] = 100.0
        mark(i, e, "th_fault", t)

    for i in starts(FAULT_RATES["rh_fault"]):
        t = _pick_tier(rng, share)
        e = span(i, geom(1.8, 4))
        if e is None:
            continue
        if t == "subtle":
            sign = 1.0 if rng.random() < 0.5 else -1.0
            rh[i:e] = np.round(np.clip(c_rh[i:e] + sign * rng.uniform(25.0, 45.0), 3.0, 100.0), 2)
        elif rng.random() < F["rh_high_share"]:
            rh[i:e] = 100.0
        else:
            rh[i:e] = np.round(rng.uniform(*F["rh_low"], e - i), 2)
        mark(i, e, "rh_fault", t)

    for i in starts(FAULT_RATES["impossible_temp"]):
        t = _pick_tier(rng, share)
        e = span(i, geom(1.5, 3))
        if e is None:
            continue
        if t == "subtle":
            sign = 1.0 if rng.random() < 0.5 else -1.0
            temp[i:e] = np.round(c_t[i:e] + sign * rng.uniform(12.0, 25.0, e - i), 2)
        elif rng.random() < 0.7:
            temp[i:e] = np.round(rng.uniform(*F["imp_temp_high"], e - i), 2)
        else:
            temp[i:e] = np.round(rng.uniform(-45.0, -10.0, e - i), 2)
        mark(i, e, "impossible_temp", t)

    for i in starts(FAULT_RATES["spike"]):
        if taken[i]:
            continue
        t = _pick_tier(rng, share)
        mult = _loguniform(rng, 4.0, 8.0) if t == "subtle" else _loguniform(rng, 8.0, F["spike_ratio"] * 1.2)
        pm[i] = round(min(float(c_pm[i]) * mult, 2800.0), 2)
        mark(i, i + 1, "spike", t)


def _inject_heldout(rng, s, F, scale):
    pm, temp, rh = s["pm"], s["temp"], s["rh"]
    c_pm, c_t, c_rh = s["clean"]
    label, tier, taken = s["label"], s["tier"], s["taken"]
    n, starts, span, geom = _helpers(rng, s, scale)

    def mark(i, e, name):
        label[i:e] = name
        tier[i:e] = "heldout"
        taken[i:e] = True

    for i in starts(HELDOUT_RATES["dropout"]):
        e = span(i, geom(7, 72))
        if e is None:
            continue
        pm[i:e] = temp[i:e] = rh[i:e] = np.nan
        label[i:e] = "dropout"
        taken[i:e] = True
    for i in starts(HELDOUT_RATES["zero_stuck"]):
        e = span(i, int(rng.integers(3, 9)))
        if e is None:
            continue
        pm[i:e] = 0.0
        mark(i, e, "zero_stuck")
    for i in starts(HELDOUT_RATES["noise_burst"]):
        e = span(i, int(rng.integers(6, 25)))
        if e is None:
            continue
        k = e - i
        pm[i:e] = np.round(np.clip(c_pm[i:e] * np.exp(rng.normal(0, 0.9, k)), 1.0, 2800.0), 2)
        temp[i:e] = np.round(c_t[i:e] + rng.normal(0, 3.0, k), 2)
        rh[i:e] = np.round(np.clip(c_rh[i:e] + rng.normal(0, 12.0, k), 3.0, 100.0), 2)
        mark(i, e, "noise_burst")
    for i in starts(HELDOUT_RATES["double_spike"]):
        e = span(i, 2)
        if e is None or e - i < 2:
            continue
        mult = _loguniform(rng, 4.0, 30.0)
        pm[i:e] = np.round(np.minimum(c_pm[i:e] * mult, 2800.0), 2)
        mark(i, e, "double_spike")
    for i in starts(HELDOUT_RATES["temp_step"]):
        e = span(i, int(rng.integers(4, 25)))
        if e is None:
            continue
        sign = 1.0 if rng.random() < 0.5 else -1.0
        temp[i:e] = np.round(c_t[i:e] + sign * rng.uniform(10.0, 18.0), 2)
        mark(i, e, "temp_step")
    for i in starts(HELDOUT_RATES["rh_flat_high"]):
        e = span(i, int(rng.integers(4, 13)))
        if e is None:
            continue
        rh[i:e] = round(float(rng.uniform(97.0, 99.9)), 2)
        mark(i, e, "rh_flat_high")


def device_table(cities=None):
    rows = []
    for city, meta in CITIES.items():
        if cities is not None and city not in cities:
            continue
        for k in range(meta["devices"]):
            rows.append({"device_id": f"{meta['code']}-{k + 1:02d}", "city": city, "preset": meta["preset"], "location_source": "assumed"})
    return pd.DataFrame(rows)


def generate(profile, start, end, seed=7, cities=None, fault_scale=1.0, family="standard", subtle_share=0.4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="h", inclusive="left")
    n = len(idx)
    hour, mon, dow = idx.hour.to_numpy(), idx.month.to_numpy() - 1, idx.dayofweek.to_numpy()

    pmp, tp, rp = profile["pm"], profile["temp"], profile["rh"]
    pm_prof = np.array(pmp["hourly_log"])[hour]
    t_prof = np.array(tp["hourly"])
    t_mean = t_prof.mean()
    r_prof = np.array(rp["hourly"])[hour]
    F = profile["faults"]

    frames = []
    for city, meta in CITIES.items():
        if cities is not None and city not in cities:
            continue
        pre = PRESETS[meta["preset"]]
        t_off = np.array(pre["temp"])[mon] + meta["temp_shift"]
        r_off = np.array(pre["rh"])[mon]
        pm_mult = np.log(np.array(pre["pm"])[mon] * meta["pm_scale"]) + WEEKDAY[dow]
        amp = np.clip(1.0 + (-r_off) / 60.0, 0.9, 1.6)
        t_base = t_mean + (t_prof[hour] - t_mean) * amp + t_off

        c_pm = _ar1(rng, n, pmp["sd"] * np.sqrt(CITY_SHARE), pmp["phi"])
        c_t = _ar1(rng, n, tp["sd"] * np.sqrt(CITY_SHARE), tp["phi"])
        c_r = _ar1(rng, n, rp["sd"] * np.sqrt(CITY_SHARE), rp["phi"])
        lm_city, cause_city = city_events(rng, idx, meta["preset"])
        rain, fog, heat = city_weather(rng, idx, meta["preset"])

        for k in range(meta["devices"]):
            dev = f"{meta['code']}-{k + 1:02d}"
            d_pm = _ar1(rng, n, pmp["sd"] * np.sqrt(1 - CITY_SHARE), pmp["phi"])
            d_t = _ar1(rng, n, tp["sd"] * np.sqrt(1 - CITY_SHARE), tp["phi"])
            d_r = _ar1(rng, n, rp["sd"] * np.sqrt(1 - CITY_SHARE), rp["phi"])
            noise = rng.lognormal(0, 0.25)
            lag = int(rng.integers(0, 3))
            att = rng.uniform(0.75, 1.2)
            lm_c = np.zeros(n)
            cause = np.full(n, "", dtype=object)
            lm_c[lag:] = att * lm_city[: n - lag] if lag else att * lm_city
            cause[lag:] = cause_city[: n - lag] if lag else cause_city

            lm_p = np.zeros(n)
            pcause = np.full(n, "", dtype=object)
            for ps in np.flatnonzero(rng.random(n) < 0.0006):
                _paint(lm_p, pcause, int(ps), int(rng.integers(1, 4)), _loguniform(rng, 3.0, 25.0), "local_source")
            lm = np.maximum(lm_c, lm_p)
            scope = np.where(lm_p > lm_c, "pulse", "city")
            cause = np.where(lm_p > lm_c, pcause, cause)
            ev_mult = np.exp(lm)
            is_event = ev_mult >= EVENT_MIN_MULT

            log_pm = pm_prof + pm_mult + np.log(rng.lognormal(0, 0.2)) + c_pm + d_pm + lm + np.log(1 - 0.5 * rain) + np.log(1 + 0.3 * fog)
            pm_clean = np.clip(np.exp(log_pm + rng.normal(0, 0.05 * noise, n)), 2.0, 1800.0)
            temp_res = c_t + d_t
            t_clean = t_base + rng.normal(0, 0.4) + temp_res - 5.0 * rain - 2.0 * fog + 4.5 * heat + rng.normal(0, 0.15 * noise, n)
            rh_raw = r_prof + r_off + rp["beta_temp"] * temp_res + rng.normal(0, 1.5) + c_r + d_r + rng.normal(0, 0.6 * noise, n)
            rh_raw = rh_raw + (100.5 - rh_raw) * (0.78 * rain + 0.6 * fog) - 8.0 * heat
            rh_clean = np.clip(rh_raw, 8.0, 100.0)

            pm_clean, t_clean, rh_clean = np.round(pm_clean, 2), np.round(t_clean, 2), np.round(rh_clean, 2)
            st = {
                "pm": pm_clean.copy(), "temp": t_clean.copy(), "rh": rh_clean.copy(),
                "clean": (pm_clean, t_clean, rh_clean),
                "label": np.where(is_event, "pollution_event", "normal").astype(object),
                "tier": np.full(n, "", dtype=object),
                "taken": np.zeros(n, bool),
            }
            if family == "heldout":
                _inject_heldout(rng, st, F, fault_scale)
            else:
                _inject_standard(rng, st, F, fault_scale, subtle_share)
            label = st["label"]
            valid = np.isin(label, ["normal", "pollution_event"])
            frames.append(pd.DataFrame({
                "timestamp": idx,
                "device_id": dev,
                "city": city,
                "pm25": st["pm"],
                "temp": st["temp"],
                "rh": st["rh"],
                "fault_type": label,
                "is_valid": valid.astype(np.int8),
                "event_cause": np.where(label == "pollution_event", cause, ""),
                "event_mult": np.where(label == "pollution_event", ev_mult, 1.0).astype(np.float32),
                "event_scope": np.where(label == "pollution_event", scope, ""),
                "fault_tier": st["tier"],
            }))
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["device_id", "timestamp"]).reset_index(drop=True)
