# SentinelAQ

Real-time validity check for air-quality sensor readings (Respirer Atmos). Every reading gets a verdict (VALID / INVALID / REVIEW), a confidence and a plain-language reason.

## Setup (Windows PowerShell)

```
cd F:\SentinalAQ\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Put `device_with_anomaly.xlsx` in `backend/data/raw/`.

## Run, in order

```
python -m app.cli profile          # learn patterns from the real file
python -m app.cli generate         # build synthetic network (3 years, 67 devices, 10 cities)
python -m app.cli peek             # look at the synthetic data
python -m app.cli compare          # optional, ~45 min. models/selection.json (the winner) is already included
python -m app.cli train            # train the winner, calibrate, set the policy (~1 min)
python -m app.cli evaluate         # full test report, saved to reports/evaluation
python -m app.cli learning-curve   # does more data help?
python -m pytest -q
```

## Use it

```
python -m app.cli peek --city Delhi --faults-only --rows 30
python -m app.cli peek --device DEL-01 --start 2025-11-01 --end 2025-11-04 --rows 72
python -m app.cli stream --days 2 --cities Delhi,Pune --delay 0.3
python -m app.cli ingest-sim --days 2 --cities Delhi,Pune
python -m app.cli serve                     # API on http://127.0.0.1:8000/docs
streamlit run ..\frontend\dashboard.py      # live view + synthetic data explorer
```

API: `POST /ingest` (list of readings), `POST /close-hour/{ts}` (records dropouts), `GET /readings?date=`, `GET /report/{date}?format=csv`, `GET /health`.

## Layout

```
backend/app/   profile, priors, generator, features, rules, model, compare, evaluate,
               detector, reasons, ingest (SQLite), api (FastAPI), stream, explore, cli
frontend/      dashboard.py
docs/          DECISIONS.md  (why each choice, results, limits)
```

City and device locations are assumed. The real Atmos file has no location. Replace `data/synthetic/devices.csv` logic with the real mapping once Respirer shares it.
