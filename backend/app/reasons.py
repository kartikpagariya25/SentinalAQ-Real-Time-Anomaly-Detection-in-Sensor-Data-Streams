import numpy as np
import pandas as pd

from .config import ML_CLASSES
from .priors import CITIES, STRONG_PRESETS, festival_window, season_of


def preset_of(city):
    return CITIES.get(city, {}).get("preset", "central_plateau")


def event_cause(ts, city):
    ts = pd.Timestamp(ts)
    preset = preset_of(city)
    f = festival_window(ts)
    if f:
        return f["key"], f["label"]
    m, d, h = ts.month, ts.day, ts.hour
    if preset in STRONG_PRESETS and m in (12, 1, 2) and (h >= 20 or h <= 9):
        return "winter_inversion", "winter temperature inversion trapping pollutants"
    if preset == "north_plain" and ((m == 10 and d >= 15) or (m == 11 and d <= 25)):
        return "crop_residue_burning", "crop-residue (stubble) burning season"
    if preset in ("north_plain", "central_plateau") and m in (3, 4, 5, 6) and 11 <= h <= 17:
        return "dust_storm", "dust / heat-driven resuspension"
    if 7 <= h <= 10 or 17 <= h <= 21:
        return "local_source", "rush-hour traffic or local burning"
    return "local_source", "unattributed local source"


def _g(r, k, default=np.nan):
    v = r.get(k, default)
    return default if v is None else v


def explain(r):
    c = r["pred_class"]
    pm, t, rh = _g(r, "pm25"), _g(r, "temp"), _g(r, "rh")
    run = int(_g(r, "pm_run", 1) or 1)
    nbr_n = _g(r, "nbr_n", 0)
    has_nbr = nbr_n == nbr_n and nbr_n > 0
    ts = pd.Timestamp(r["timestamp"])

    if r.get("verdict") == "REVIEW":
        p = float(_g(r, "p_invalid", 0.5))
        lead = c if c not in ("normal", "pollution_event") else "a sensor fault"
        ratio = float(np.exp(_g(r, "pm_lr", 0.0)))
        tail = f"PM2.5 {pm:.0f} is {ratio:.1f}x its recent level"
        tail += ", nearby devices partly agree" if has_nbr and _g(r, "nbr_elev", 0.0) > 0.3 else ""
        return f"Needs review: {tail}; model leans {lead} ({p:.0%} fault probability) but cannot be sure"
    if c == "drift":
        return f"PM2.5 has drifted away from nearby devices over days (about {np.exp(abs(_g(r, 'sp_m72', 0.0))):.1f}x {'above' if _g(r, 'sp_m72', 0.0) > 0 else 'below'} the neighbours over 3 days) - sensor calibration drift"
    if c == "dropout":
        gap = int(_g(r, "gap_len", 1))
        return f"No reading received for {gap} consecutive hour(s) - communication or power dropout"
    if c == "stuck":
        if abs(pm - 3333.0) < 0.01 or pm >= 3000:
            return f"PM2.5 frozen at sentinel value {pm:g} - sensor lock-up, value is not a real measurement"
        return f"PM2.5 repeated exactly ({pm:g}) for {run} consecutive hours - flatline, sensor stuck"
    if c == "saturation":
        return f"PM2.5 {pm:.0f} ug/m3 is beyond the physical sensor range - optical chamber saturated"
    if c == "impossible_temp":
        return f"Temperature {t:.1f} C is outside any plausible ambient range - temperature probe fault"
    if c == "th_fault":
        return f"Temperature {t:.1f} C with humidity {rh:.0f}% while PM looks normal - T/RH probe failure"
    if c == "rh_fault":
        if rh >= 99.5:
            return f"Humidity pinned at {rh:.0f}% at {t:.1f} C - RH sensor saturated or condensation on probe"
        ref = rh - _g(r, "sp_rh", 0.0) if has_nbr else np.nan
        tail = f" vs neighbours ~{ref:.0f}%" if ref == ref else ""
        return f"Humidity {rh:.1f}%{tail} is implausible - RH sensor fault"
    if c == "spike":
        ratio = float(np.exp(_g(r, "pm_lr", 0.0)))
        tail = "while nearby devices stay normal" if has_nbr else "with no nearby device to confirm"
        hedge = " (a short local pollution burst cannot be ruled out)" if _g(r, "confidence", 1.0) < 0.85 else ""
        return f"PM2.5 {pm:.0f} is {ratio:.0f}x its recent level {tail} - isolated spike, likely sensor fault{hedge}"
    if c == "pollution_event":
        _, label = event_cause(ts, r.get("city", ""))
        if has_nbr and _g(r, "nbr_elev", 0.0) > 0.3:
            ratio = float(np.exp(_g(r, "nbr_elev", 0.0)))
            return f"Genuine pollution event, likely {label}; nearby devices also up ~{ratio:.1f}x"
        return f"Genuine pollution event, likely {label}"
    season = season_of(ts.month)
    part = "night" if (ts.hour >= 22 or ts.hour < 5) else "morning" if ts.hour < 11 else "afternoon" if ts.hour < 17 else "evening"
    return f"Consistent with recent hours{' and nearby devices' if has_nbr else ''} for a {season} {part}"
