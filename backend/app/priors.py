import pandas as pd

PRESETS = {
    "north_plain": {
        "temp": [-16, -13, -7, 0, 4, 5, 2, 1, 0, -4, -10, -15],
        "rh": [0, -5, -17, -27, -25, -15, 5, 8, 0, -10, -5, 0],
        "pm": [4.5, 3.0, 2.0, 1.8, 1.8, 1.6, 0.8, 0.7, 1.0, 2.5, 5.0, 5.0],
    },
    "coastal": {
        "temp": [-4, -3, -1, 0.5, 1.5, 0, -2, -2, 0, 0.5, -1, -3],
        "rh": [-10, -10, -8, -5, -3, 3, 8, 8, 0, -3, -5, -8],
        "pm": [1.8, 1.6, 1.3, 1.1, 1.0, 0.8, 0.5, 0.5, 1.0, 1.3, 1.8, 2.0],
    },
    "central_plateau": {
        "temp": [-8, -5, 0, 5, 9, 5, 0, 0, 0, 0, -4, -7],
        "rh": [-12, -18, -22, -25, -20, -5, 5, 7, 0, -8, -12, -12],
        "pm": [2.2, 1.8, 1.4, 1.2, 1.2, 0.9, 0.6, 0.6, 1.0, 1.5, 2.2, 2.5],
    },
    "semi_arid": {
        "temp": [-9, -6, -1, 4, 7, 5, 0, 0, 0, 0, -4, -8],
        "rh": [-15, -20, -25, -28, -22, -5, 8, 10, 0, -10, -12, -14],
        "pm": [2.0, 1.7, 1.5, 1.4, 1.4, 1.0, 0.6, 0.6, 1.0, 1.6, 2.2, 2.4],
    },
    "east_delta": {
        "temp": [-9, -6, -2, 2, 3, 2, 0, 0, 0, -1, -5, -8],
        "rh": [-5, -8, -8, -5, -2, 2, 5, 5, 0, -3, -5, -6],
        "pm": [3.5, 2.5, 1.5, 1.1, 1.0, 0.7, 0.5, 0.5, 1.0, 1.5, 2.5, 3.5],
    },
}

CITIES = {
    "Delhi": {"code": "DEL", "preset": "north_plain", "devices": 8, "pm_scale": 1.8, "temp_shift": 0.0},
    "Lucknow": {"code": "LKO", "preset": "north_plain", "devices": 6, "pm_scale": 1.5, "temp_shift": 0.5},
    "Mumbai": {"code": "BOM", "preset": "coastal", "devices": 8, "pm_scale": 0.9, "temp_shift": 0.0},
    "Chennai": {"code": "MAA", "preset": "coastal", "devices": 6, "pm_scale": 0.8, "temp_shift": 1.5},
    "Pune": {"code": "PNQ", "preset": "central_plateau", "devices": 8, "pm_scale": 1.0, "temp_shift": -1.0},
    "Nagpur": {"code": "NAG", "preset": "central_plateau", "devices": 6, "pm_scale": 1.2, "temp_shift": 1.5},
    "Kolkata": {"code": "CCU", "preset": "east_delta", "devices": 7, "pm_scale": 1.6, "temp_shift": 0.0},
    "Bengaluru": {"code": "BLR", "preset": "central_plateau", "devices": 6, "pm_scale": 0.7, "temp_shift": -3.0},
    "Hyderabad": {"code": "HYD", "preset": "central_plateau", "devices": 6, "pm_scale": 1.1, "temp_shift": 0.5},
    "Ahmedabad": {"code": "AMD", "preset": "semi_arid", "devices": 6, "pm_scale": 1.3, "temp_shift": 1.0},
}

STRONG_PRESETS = {"north_plain", "east_delta"}

FESTIVALS = [
    {"key": "dussehra", "label": "Dussehra effigy burning", "date": "2023-10-24", "hour": 19, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
    {"key": "diwali", "label": "Diwali fireworks", "date": "2023-11-12", "hour": 18, "dur": 16, "strong": (5.0, 10.0), "weak": (3.0, 4.5)},
    {"key": "new_year_eve", "label": "New Year's Eve fireworks", "date": "2023-12-31", "hour": 22, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
    {"key": "holi", "label": "Holika Dahan bonfires", "date": "2024-03-24", "hour": 19, "dur": 6, "strong": (3.0, 4.2), "weak": (2.2, 3.2)},
    {"key": "diwali", "label": "Diwali fireworks", "date": "2024-11-01", "hour": 18, "dur": 16, "strong": (5.0, 10.0), "weak": (3.0, 4.5)},
    {"key": "diwali", "label": "Diwali fireworks", "date": "2025-10-20", "hour": 18, "dur": 16, "strong": (5.0, 10.0), "weak": (3.0, 4.5)},
    {"key": "diwali", "label": "Diwali fireworks", "date": "2026-11-08", "hour": 18, "dur": 16, "strong": (5.0, 10.0), "weak": (3.0, 4.5)},
    {"key": "dussehra", "label": "Dussehra effigy burning", "date": "2024-10-12", "hour": 19, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
    {"key": "dussehra", "label": "Dussehra effigy burning", "date": "2025-10-02", "hour": 19, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
    {"key": "dussehra", "label": "Dussehra effigy burning", "date": "2026-10-20", "hour": 19, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
    {"key": "holi", "label": "Holika Dahan bonfires", "date": "2025-03-13", "hour": 19, "dur": 6, "strong": (3.0, 4.2), "weak": (2.2, 3.2)},
    {"key": "holi", "label": "Holika Dahan bonfires", "date": "2026-03-03", "hour": 19, "dur": 6, "strong": (3.0, 4.2), "weak": (2.2, 3.2)},
    {"key": "new_year_eve", "label": "New Year's Eve fireworks", "date": "2024-12-31", "hour": 22, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
    {"key": "new_year_eve", "label": "New Year's Eve fireworks", "date": "2025-12-31", "hour": 22, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
    {"key": "new_year_eve", "label": "New Year's Eve fireworks", "date": "2026-12-31", "hour": 22, "dur": 5, "strong": (3.0, 4.5), "weak": (2.2, 3.2)},
]


def festival_window(ts):
    ts = pd.Timestamp(ts)
    for f in FESTIVALS:
        start = pd.Timestamp(f["date"]) + pd.Timedelta(hours=f["hour"])
        if start <= ts < start + pd.Timedelta(hours=f["dur"] + 6):
            return f
    return None


def season_of(month):
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "summer"
    if month in (6, 7, 8, 9):
        return "monsoon"
    return "post-monsoon"
