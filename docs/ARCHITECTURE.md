# Architecture

How a reading becomes a verdict, and where each step lives in the code. For *why* the design looks like this, see [DECISIONS.md](DECISIONS.md).

## Data flow

```
 Respirer pipeline / live-feed
          │  POST /ingest  (JSON batch)
          ▼
   api.py ──► ingest.Ingestor.ingest
                │ 1. floor to the hour, drop duplicates inside the batch
                │ 2. Store.known: skip (device, hour) pairs already stored
                │ 3. Store.history: last 192 h of the affected cities
                │ 4. features.build_features(history + new rows)
                │ 5. detector.annotate  ──►  model.predict ──► reasons.explain
                ▼
          SQLite (data/live/readings.db)  ◄── GET /readings, /stats, /report/*
                                               ▲
                              React dashboard / CSV / PDF / email
```

Batch scoring (`detector.run_batch`, used by `evaluate`) and streaming scoring (`Detector`, `Ingestor`) call the **same** `build_features` and `annotate`. A test (`test_streaming_features_match_batch`) proves a 192-hour window gives identical features to the full history, so there is no train/serve gap.

## Backend modules (`backend/app`)

| Module | Responsibility |
|---|---|
| `config.py` | Paths, date splits, class lists, constants (`HISTORY_HOURS=192`, `TEMP_MAX=55`, `TEMP_MIN=-10`, `RULE_CONFIDENCE=0.99`). |
| `profile.py` | Step 1. Reads the real Atmos Excel file and extracts PM level, autocorrelation, diurnal curves, T-RH coupling and fault signatures into `profile.json`. |
| `priors.py` | Assumed world: 5 climate presets, 10 cities (67 devices), festival calendar, seasons. |
| `generator.py` | Step 2. Builds the synthetic network (AR(1) noise, city events, weather, injected faults with labels and tiers). Deterministic for a given seed. |
| `features.py` | The 40 causal features (see below). |
| `rules.py` | Physics rules that override the model. |
| `model.py` | Model registry (7 families), class weights, isotonic calibration, `choose_policy`, `predict`, `drivers`. |
| `compare.py` | Step 3. Bake-off, rolling CV, tuning, selection rule, `fit_selected`. |
| `pipeline.py` | Step 4 `cmd_train`, time-based split, `cmd_models`. |
| `evaluate.py` | Step 5. Held-out test report. |
| `detector.py` | `annotate`, `Detector` (tick-by-tick), `run_batch`. |
| `reasons.py` | Plain-language reason and event-cause text. |
| `ingest.py` | `Store` (SQLite), `Ingestor`, period windows and summaries. |
| `api.py` | FastAPI app. |
| `report_pdf.py`, `mailer.py` | PDF report and scheduled email. |
| `live.py`, `stream.py` | HTTP demo feed; console replay and ingestion simulation. |
| `explore.py`, `ui.py`, `cli.py` | Dataset browser, console helpers, command entry point. |

## Decision logic (`model.predict`)

1. **Features → model.** The classifier outputs a probability for 9 classes (`ML_CLASSES`, everything except `dropout`).
2. **p(invalid)** is the sum over the fault classes, then passed through the isotonic calibrator fitted on the validation period, so it behaves like a real probability.
3. **Policy** (`policy["lo"]`, `policy["hi"]` stored in the model bundle, chosen on validation by `choose_policy`):
   - `p < lo` → `VALID`
   - `p >= hi` → `INVALID`
   - otherwise → `REVIEW`

   The thresholds are *learned*, not fixed: they are the pair with the highest automatic coverage that still meets the precision, miss-rate and event-rejection limits. Retraining can move them (the README quotes the reference run).
4. **Class name:** INVALID takes the most likely fault class; VALID with a fault-looking argmax is relabelled `normal`.
5. **Rules override** (`rules.apply_rules`), first match wins: missing value → `dropout`; temp ≥ 55 or ≤ -10 → `impossible_temp`; RH outside 0 to 100 → `rh_fault`; PM equal to the sentinel (3333) → `stuck`; PM ≥ saturation floor → `saturation`. A rule hit forces `INVALID`, confidence 0.99, `source = "rule"`.
6. **Reason** is generated from the final class and the features that mattered (`reasons.explain`); for model decisions that are not plain `normal`/VALID, the top-3 LightGBM/XGBoost feature contributions are stored as `drivers`.

## Features

All features use only the past, so they can be computed live.

| Group | Examples | Purpose |
|---|---|---|
| Level and change | `pm25, temp, rh, pm_d1, pm_l24` | raw value and 1 h / 24 h change |
| Robust baseline | `pm_med24, pm_lr, pm_lr6, pm_z` | how far PM is from the device's own recent median (log ratio, z-score) |
| Flatline | `pm_run, temp_run, rh_run` | length of a run of identical values (capped at `RUN_CAP=24`) |
| Volatility / trend | `pm_vol6, pm_trend72` | short-term noise, 3-day trend |
| Lags | `pm_lr_1, pm_lr_2, temp_dm_1, rh_dm_1` | what the previous hours looked like |
| Neighbours | `sp_pm, sp_temp, sp_rh, nbr_elev, nbr_n, nbr_sd, sp_m24/72/168, sp_slope` | leave-one-out comparison with other devices of the same city at the same hour: this separates a real city-wide event from a lone fault, and exposes drift |
| Calendar | `hour_sin/cos, month_sin/cos` | daily and seasonal cycle |

When a city has a single device in an hour, the neighbour block is `NaN`; training masks it in 15% of rows so the model also works alone.

## Storage

One SQLite table, `readings`, keyed by `(device_id, ts)`:

`device_id, ts, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason, drivers, received_at`

WAL mode and a 30 s busy timeout allow the API and the feed to write concurrently. `INSERT OR REPLACE` plus the duplicate check make ingestion idempotent. `:memory:` is supported for tests.

## Files produced at runtime (all git-ignored)

| Path | Created by | Content |
|---|---|---|
| `backend/data/synthetic/profile.json` | `profile` | learned patterns |
| `backend/data/synthetic/sensor_data.parquet`, `devices.csv` | `generate` | the synthetic network |
| `backend/models/detector.joblib` | `train` | classifier, calibrator, policy, isolation forest, fault constants |
| `backend/models/selection.json` | `compare` | winner and hyper-parameters (committed) |
| `backend/reports/evaluation/*` | `evaluate`, `compare` | benchmark, calibration, confusion matrix, summary |
| `backend/reports/daywise/*` | `stream` | one CSV per simulated day |
| `backend/data/live/readings.db` | API | live store |

## Frontend (`frontend/src`)

A React single-page app with no business logic. `api.js` wraps `fetch` with a timeout; `App.jsx` pings `/health` every 10 s; `LiveView` polls `/stats` every 2 s; `ReportsView` calls `/report/range` and links to the CSV/PDF downloads. `frontend/dashboard.py` is an older Streamlit explorer that streams straight from the model, kept for offline demos.
