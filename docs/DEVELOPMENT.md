# Development guide

## Setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Python 3.10+ (developed on 3.11 to 3.14). Node.js 18+ is only needed for the dashboard (`cd frontend ; npm install`).

The real source file `device_with_anomaly.xlsx` goes in `backend/data/raw/`. It is not in the repo. Without it, the tests that depend on it are skipped; the API, period and explore tests still run.

## Tests

```powershell
cd backend
python -m pytest -q
```

| File | Needs data file? | Covers |
|---|---|---|
| `test_pipeline.py` | yes (skipped without) | generator determinism and labels, rules, stream-equals-batch features, detector accuracy, ingestion dedupe/late data, reports and PDF, live view ordering |
| `test_api.py` | no | status codes for bad input, limit bounds, formats, API key |
| `test_periods.py` | no | daily/weekly/monthly/yearly windows |
| `test_explore.py` | no | `peek` filtering and export |

The model-dependent tests train a small LightGBM on a 4-month synthetic slice (about 20 s), so they do not need `detector.joblib`.

## CLI reference

Run from `backend/` as `python -m app.cli <command>`.

| Command | What it does |
|---|---|
| `profile` | learn patterns from the real file -> `data/synthetic/profile.json` |
| `generate [--seed 7] [--fault-scale 1.0]` | build the synthetic network (1.76 M rows) |
| `compare [--resume]` | 9-model bake-off (about 45 min), writes `models/selection.json` |
| `learning-curve` | PR-AUC versus months of training data |
| `train` | train the selected model, calibrate, choose the policy -> `models/detector.joblib` |
| `models [--info]` | table of all models and metrics, plus the selected one |
| `evaluate [--skip-unseen-cities]` | full held-out report -> `reports/evaluation` |
| `all` | `profile`, `generate`, `train`, `evaluate` in order |
| `peek [--city --device --start --end --fault --faults-only --rows N --export FILE]` | browse or export the synthetic data |
| `stream [--start --days --cities --delay --only-flagged --out DIR]` | replay a period through the detector in the console |
| `ingest-sim [--start --days --cities --db FILE]` | feed simulated hours through the same path as the API |
| `serve [--port 8000] [--host 127.0.0.1] [--email-period daily --email-hour 6]` | run the API, optionally with scheduled email |
| `live-feed [--url --api-key --replay-days --cities --delay --seed --loop]` | push demo readings to a running API |
| `email-report [--period --date --to]` | send one report now (exit code 1 on failure) |

`--cities all` selects all 10 cities. `--replay-days 0` turns the dataset-history stream off.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `SENTINEL_API_KEY` | `serve` | if set, `/ingest` and `/close-hour` require `X-API-Key` |
| `SENTINEL_URL` | `examples/push_client.py` | API base URL |
| `SMTP_HOST`, `SMTP_PORT` (587) | mailer | server; port 465 uses implicit TLS, others use STARTTLS |
| `SMTP_USER`, `SMTP_PASS` | mailer | login (optional if the server needs none) |
| `REPORT_FROM` | mailer | sender, defaults to `SMTP_USER` |
| `REPORT_TO` | mailer | comma-separated recipients (or pass `--to`) |
| `VITE_API_URL` | frontend | API URL baked into the build (`frontend/.env`) |

## Typical workflows

**Retrain after changing features or data**

```powershell
python -m app.cli generate
python -m app.cli train
python -m app.cli evaluate
```

`train` reads `models/selection.json`; run `compare` only when you want to re-run the model selection.

**Add a new fault type**

1. Add the class to `CLASSES` in `config.py` (and `INVALID_CLASSES` follows automatically).
2. Inject it in `generator.py` (`FAULT_RATES` and `_inject_standard`).
3. If it is a certain physical fact, add it to `rules.py`; otherwise the model learns it after `generate` and `train`.
4. Add a branch in `reasons.explain` so the verdict has a readable reason.
5. Add it to the lists in `evaluate.py` / `stream.py` that name fault columns.

**Add a feature**

Add it in `features.py` and to `FEATURES`. Keep it causal (shift or trailing window only). `test_streaming_features_match_batch` fails if a feature looks at the future or needs more than 192 hours.

**Add a model family**

Add a factory to `model.registry()` and, optionally, a search space in `SEARCH_SPACE`. Add a description to `MODELS` in `pipeline.py` so `models --info` can explain it.

## Conventions

- Time-based splits only (`TRAIN_END`, `VAL_END` in `config.py`); never shuffle.
- Business logic lives in the backend; the dashboard only renders API output.
- `.gitattributes` normalises line endings; PowerShell scripts stay CRLF.
- Commit style: `type(scope): summary` (`fix`, `feat`, `docs`, `test`, `refactor`, `build`, `chore`).
