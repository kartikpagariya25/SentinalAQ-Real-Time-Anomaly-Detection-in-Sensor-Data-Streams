from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_FILE = ROOT / "data" / "raw" / "device_with_anomaly.xlsx"
SYN_DIR = ROOT / "data" / "synthetic"
MODEL_DIR = ROOT / "models"
REPORT_DIR = ROOT / "reports"
PROFILE_FILE = SYN_DIR / "profile.json"
DATA_FILE = SYN_DIR / "sensor_data.parquet"
MODEL_FILE = MODEL_DIR / "detector.joblib"

DATA_START = "2023-10-01"
DATA_END = "2026-10-01"
TRAIN_END = "2025-07-01"
VAL_END = "2026-01-01"
HOLDOUT_CITIES = ["Nagpur", "Kolkata"]

CLASSES = [
    "normal",
    "pollution_event",
    "spike",
    "stuck",
    "saturation",
    "impossible_temp",
    "th_fault",
    "rh_fault",
    "drift",
    "dropout",
]
VALID_CLASSES = ["normal", "pollution_event"]
INVALID_CLASSES = [c for c in CLASSES if c not in VALID_CLASSES]
ML_CLASSES = [c for c in CLASSES if c != "dropout"]

HISTORY_HOURS = 192
RUN_CAP = 24
TEMP_MAX = 55.0
TEMP_MIN = -10.0
EVENT_MIN_MULT = 3.0
RULE_CONFIDENCE = 0.99

DEVICES_FILE = SYN_DIR / "devices.csv"
RESULT_DIR = REPORT_DIR / "evaluation"
