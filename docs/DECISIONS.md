# Decisions, results and limits

## What the system does
Rules (physics limits) -> ML classifier (LightGBM) -> isotonic calibration -> 3-way policy.
Verdict: VALID (p_fault < 0.29), INVALID (p_fault > 0.83), REVIEW (in between). Rules always win: missing data, temp outside -10..55 C, RH outside 0..100, PM = 3333 sentinel, PM above saturation floor.

## Why this design
- Rules: certain physical facts need no learning and are 100% explainable.
- ML: faults like spikes, probe faults and flatlines depend on context (recent hours, nearby devices, season, hour), which rules cannot express.
- Neighbour features: if nearby devices rise together it is a real event; if one device jumps alone it is a fault. This is why city-wide events are almost never rejected (0.0% auto-rejected).
- Calibration: so "confidence" means what it says (ECE 0.0005 on the test period).
- REVIEW state: a single-device burst and a spike look identical in hourly data. Forcing a call there is a coin flip, so those go to REVIEW.
- Causal features only (past data), same code for batch and stream (tested), 192 h buffer.

## Why synthetic data, and what is assumed
The real file is 168 rows from one device. It gives patterns only (PM level, autocorrelation, diurnal curve, T-RH coupling, sentinel 3333, saturation ~3300, T/RH probe fault signature). Everything else is assumed: 10 cities / 67 devices (the real file has no location), climate presets, festival dates and strengths, fault rates. Device 'city' is a modelling grouping, not a fact.
Added in this version: rain/fog/heat episodes (RH 100 is not always a fault), weekday effect, measurement noise, drift fault, subtle fault tier, single-device bursts, 3 years of data, fault families held out of training for testing.
Slow drift counts as a fault only when it exceeds +-50% (typical PM sensor tolerance is 25-30%).

## Model bake-off (validation months, same data, same rule)
Rule: maximise the share of readings decided automatically while: auto-INVALID precision >= 0.99, <= 5% of faults (<= 10% of any one fault type) slip through as VALID, <= 3% of real events auto-rejected. Ties (within 0.3 pt) go to higher PR-AUC, then lower latency.
First version of the rule used F1 minus event-rejection; it picked an MLP that decided only 83% of readings. The rule was changed after seeing that, and applied to all models.

| model | decided automatically | PR-AUC | note |
|---|---|---|---|
| LightGBM (tuned) | 99.3% | 0.923 | winner |
| soft-vote top 3 | 99.4% | 0.915 | slower, no gain |
| random forest | 99.1% | 0.916 | |
| HistGB / XGBoost | 99.3% / 99.2% | 0.912 / 0.911 | |
| MLP | 97.0% | 0.916 | more reviews |
| extra trees | 99.5% | 0.882 | weaker ranking |
| logistic regression | ~0% | 0.569 | linear model cannot do this |

The top tree models are statistically close (rolling-CV sd about 0.03). LightGBM is chosen by the tie-break, not by a large margin. The real gain over the first version came from features and data, not from the model.

## Test results (Jan-Sep 2026, never used for training or tuning)
- Auto-INVALID precision 0.994; 73.5% of faults auto-INVALID, 85.3% INVALID or REVIEW; faults missed excluding drift: 1.0%.
- REVIEW is 0.7% of readings.
- Real events: 0.5% auto-rejected, 12.5% to REVIEW, 86.9% accepted. City-wide events: 0.0% rejected, 99.7% accepted.
- Unseen cities (retrained without Nagpur, Kolkata): auto-INVALID precision 0.959, faults missed 0.8%.
- Rolling z-score F1 0.70, Isolation Forest 0.60, final 0.85-0.86.
- Real Atmos file: 12 of 12 invalid rows caught, 1 flagged for REVIEW (the 566 ug/m3 reading), 0 missed.
- Learning curve: PR-AUC 0.84 (3 months) -> 0.92 (12 months) -> 0.925 (18 months). More data of the same kind will help little.

## Serving architecture (how it runs in production)
- Ingestion is push: the upstream pipeline sends batches to `POST /ingest` (FastAPI) and gets a verdict per reading back. Same scoring path as batch (dedupe, late data, 192 h history, features, detector), so there is no train/serve gap. Optional `X-API-Key` auth.
- Storage is SQLite; each reading is kept with its verdict, confidence, reason and source. Swap for Postgres when device count grows.
- Reports are computed on the stored verdicts for any daily/weekly/monthly/yearly window, served as JSON, CSV or PDF (`/report/range`), and can be emailed on a schedule.
- The dashboard is a React (Vite + Tailwind + Recharts) app that polls the API: a live stream view and a reports view. It holds no logic of its own, so the API stays the single source of truth.
- Why push over a broker/poll: Atmos pipelines already do HTTP, one endpoint is the least for Respirer to integrate, and it needs no extra infrastructure. MQTT/Kafka can be added as another front-end to the same `ingest()` later.

## Known limits (honest)
- Slow drift: 76% of drift rows are not flagged. Early drift is as large as natural device-to-device differences. Needs a device-level weekly check against a reference monitor.
- Single-device bursts vs spikes cannot be separated from hourly data. They land in REVIEW.
- Fault families never seen in training (noise burst, double spike): 35% missed. The model only knows what it was trained on. Real labelled faults from Respirer are the fix.
- Subtle-only faults: 64.5% auto-INVALID, 78.9% INVALID or REVIEW.
- Reason engine matches the simulator 86% because both use the same assumptions. It is a consistency check, not proof.
- Policy thresholds drift with seasons. Recalibrate on the latest months regularly.
- Without neighbours (single device) the model is weaker (F1 0.81 vs 0.86).

## Needed from Respirer
Device-to-location mapping, multi-device real data, labelled faults, and confirmation whether the 566 ug/m3 reading on 2026-09-16 09:00 was a real event.
