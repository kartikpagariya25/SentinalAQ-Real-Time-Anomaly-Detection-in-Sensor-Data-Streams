# SentinelAQ

Real-time anomaly detection for air quality sensor networks, sponsored by [Respirer Living Sciences](https://www.respirer.in/).

SentinelAQ ingests a live stream of PM2.5/PM10 sensor readings from a network of stations, flags anomalies (sensor faults, drift, gaps, spikes), and — critically — tells the difference between a **broken sensor** and a **real regional pollution event**, so that a genuine smog event across a whole district is never mislabeled and dismissed as a hardware fault.

## Team

| Name | Role |
|---|---|
| Kartik Pagariya | Developer |

## Contents
- [What it does](#what-it-does)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [How it works](#how-it-works)
- [Getting started](#getting-started)
- [API reference](#api-reference)
- [Testing](#testing)
- [Design system](#design-system)
- [Key design decisions](#key-design-decisions)

## What it does

1. **Detects anomalies** in streaming sensor data using a layered ensemble: fast statistical rules (Z-score, flatline, CUSUM drift, duplicate/gap detectors) plus a benchmarked ML/time-series model.
2. **Distinguishes faults from real events.** A spatial-correlation layer checks whether neighboring stations agree — if a whole region moves together, it's a real environmental event, not a fault, and must never be shown in "fault" red.
3. **Streams it live.** A FastAPI backend replays a sensor dataset in true timestamp order over a WebSocket; a React dashboard shows live station status, a severity-colored map, and per-station history.
4. **Benchmarks its own models**, in the open, on the dashboard — three model families were built and evaluated, and the dashboard shows the comparison table plus the model actually running live, not just the "best" one on paper.

## Tech stack

**Backend** — Python, FastAPI (async REST + WebSocket), pandas/numpy, [PyOD](https://github.com/yzhao062/pyod) (Isolation Forest, LOF), statsmodels (STL decomposition), [river](https://riverml.xyz/) (incremental/online LOF for the live stream), scikit-learn, pytest.

**Frontend** — React 19 + TypeScript, Vite, TanStack Query, React Router, Tailwind CSS v3 + shadcn/ui, Recharts (sparklines), MapLibre GL (station map), Vitest.

**Why these choices, briefly** (full rationale in `Final_plan.md`):
- FastAPI over Flask/Django — native async WebSocket support, needed for the live broadcast loop.
- PyOD over hand-rolled sklearn wrappers — one consistent `fit`/`decision_function` API across every ML detector, which is what makes an apples-to-apples benchmark possible.
- river for the live path — incremental models score one row at a time without refitting on the whole history, which batch PyOD models can't do cheaply in a streaming loop.
- shadcn/ui + Tailwind v3 (not v4) — v4's Base UI rewrite broke compatibility with the component set used here; pinned deliberately, not accidentally.
- MapLibre over Leaflet/Google Maps — open-source, no API key, first-class React bindings via `react-map-gl`.

## Project structure

```
SentinelAQ/
├── backend/
│   ├── api/                  # FastAPI app: routes, WebSocket stream engine, in-memory state
│   ├── models/                # Detection logic: statistical rules + ML models + benchmarking
│   ├── streaming/              # Shared scoring logic + CLI streaming prototype
│   ├── tests/                 # pytest suite (routes, WebSocket, state, scoring, stream engine)
│   ├── generate_sensor_dataset.py   # Synthetic sensor dataset generator
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── routes/            # LiveView, MapView, BenchmarkView
│   │   ├── components/        # StationCard, SeverityTag, MapMarker, BenchmarkTable, etc.
│   │   ├── context/            # WebSocketProvider — live stream state
│   │   └── lib/                # TanStack Query hooks, severity classification
│   ├── tests/                 # Vitest unit tests
│   └── design.md               # Token-driven design system (Grafana-derived dark theme)
├── docs/superpowers/           # Design specs and implementation plans for both sub-projects
├── Final_plan.md               # Full benchmark results, model-selection rationale, architecture
└── Real-Time-Anomaly-Detection-Implementation-Plan.md
```

## How it works

**Detection ensemble** (`backend/models/detectors.py`):
- Statistical rules: Z-score outliers, flatline, CUSUM drift, duplicate rows, timestamp gaps.
- Three benchmarked model families: PyOD Isolation Forest, PyOD Local Outlier Factor (LOF), STL-residual (statsmodels).
- Spatial-correlation correction (`backend/models/spatial_correlation.py`): downgrades a flag to "environmental event" when neighboring stations show correlated readings, instead of hiding it.

**Model selection — LOF is the one wired into the live stream.** Isolation Forest scores the highest raw F1 (0.43), but its false-positive rate on real regional events is 0.86–0.94 — it would misclassify almost every genuine pollution event as a sensor fault, which is exactly the failure this project exists to prevent. LOF trades some raw recall for an env-event false-positive rate of 0.06–0.07 — roughly 12x better — which is the metric that matters for an alerting system operators need to trust. Full numbers and reasoning: `Final_plan.md`, "Model selection for the live stream."

| Method | Precision | Recall | F1 | Env-event FP rate |
|---|---|---|---|---|
| Isolation Forest | 0.41 | 0.45 | 0.43 | 0.86–0.94 |
| **LOF (live model)** | 0.23 | 0.25 | 0.24 | **0.06–0.07** |
| STL residual | ~0.35 | ~0.37 | ~0.36 | 0.43–0.49 |

**Live stream** (`backend/api/`): on startup, `StreamEngine` loads the dataset and replays it in true timestamp order at a configurable speed multiplier (default 60x), broadcasting each row's detection result to every connected WebSocket client. `AppState` holds all live state in memory — no database. The frontend's `WebSocketProvider` maintains per-station live readings and a rolling detection-event feed.

## Getting started

### Prerequisites
- Python 3.10+
- Node.js 18+

### Backend

```bash
cd backend
pip install -r requirements.txt

# (optional) regenerate the synthetic dataset
python generate_sensor_dataset.py --output ../sensor_data.csv --n_records 1000000 --n_stations 50

# (optional) re-run the model benchmark
python models/benchmark.py --input ../sensor_data.csv --sample-size 0 --output benchmark_results_v3.csv

# run the API + live stream (run this from inside backend/, not the repo root)
uvicorn api.main:create_app --factory --reload
```

The server starts on `http://127.0.0.1:8000`. It loads `../sensor_data.csv` (relative to `backend/`, i.e. the repo-root dataset) and `backend/benchmark_results_v3.csv` by default — override the dataset via `SENTINELAQ_DATASET=<path>`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` — requires the backend running (see above) for live data; `npm run build` and `npm test` also work standalone.

## API reference

| Endpoint | Description |
|---|---|
| `GET /api/stations` | Current snapshot of all stations (latest reading + status) |
| `GET /api/stations/{station_id}/history` | Historical readings for one station |
| `GET /api/benchmark` | Model comparison results (precision/recall/F1/env-FP per model) |
| `GET /api/stream/status` | Stream engine status: paused, speed multiplier, rows processed |
| `WS /ws/stream` | Live detection feed — snapshot on connect, then a message per replayed row |

## Testing

```bash
# backend
cd backend && pytest

# frontend
cd frontend && npm test        # Vitest unit tests
cd frontend && npx tsc -b --noEmit   # typecheck
cd frontend && npm run build   # production build
```

## Design system

`frontend/design.md` defines the full token-driven design system: a dark, data-dense theme adapted from Grafana's production theme, with a severity taxonomy (`normal` / `fault` / `drift` / `event` / `unknown`) and one non-negotiable rule — a real regional environmental event must never be rendered in the same color as a sensor fault. See that file for the complete component spec (`SeverityTag`, `StationCard`, `MapMarker`, `BenchmarkTable`, etc.), accessibility requirements, and anti-patterns.

## Key design decisions

A standalone document covering the WHY behind every major decision (model choice, architecture, library choices) across the whole project is tracked as a deliverable and will be added once the project reaches feature-complete status. In the meantime, `Final_plan.md` contains the detailed benchmark methodology and model-selection reasoning referenced above.
