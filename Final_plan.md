# Real-Time Anomaly Detection in Sensor Data Streams
## Final Implementation Plan — Merged & Pragmatized (Respirer India — Field Monitoring Networks)

> This document merges the team's original production-architecture plan
> (`Real-Time-Anomaly-Detection-Implementation-Plan.md`, authored by Vikrant)
> with a second-opinion review of build pragmatics and prior-art tooling.
> The two were ~90% aligned on *what* to build (taxonomy, architecture shape,
> evaluation methodology); the merge below keeps the original as the
> production target and layers in concrete libraries, a leaner MVP build
> order, and explicit scope boundaries so the team ships something real
> inside an internship timeline instead of stalling on infrastructure.

---

## 0. Scope Statement (new)

**In scope:** the anomaly-detection *brain* — a synthetic data generator,
a benchmarked ensemble of detection methods, and a pluggable scoring
service that can sit inside whatever ingestion/storage/alerting stack
Respirer already runs or stands up.

**Out of scope:** sensor hardware, firmware/calibration code, and building
Respirer's production monitoring company dashboard from scratch. The
deliverable is a service that plugs into their stack, not a replacement
for it. This boundary matters for the tech-stack decisions in Section 5 —
default to the lightest tool that satisfies the requirement, escalate to
heavier infrastructure only when a benchmark or a stated scale requirement
proves the lighter one insufficient.

---

## 1. Problem Restatement & Success Criteria

**Goal:** Build a real-time anomaly detection framework for environmental
sensor streams (PM2.5, PM10, NO2, CO, temperature, humidity, etc.) that:
1. Detects abnormal patterns, sensor faults, communication issues, and
   genuine environmental events.
2. Works on simulated data first, then deploys on live Respirer field
   networks.
3. Scales to a large number of concurrent sensor nodes with low latency.
4. Is measurable — accuracy, precision/recall, latency, uptime.

In plain words: Respirer's field boxes report a number every few minutes.
Hardware is messy — sensors drift, go silent, spike, or freeze — and the
job is to tell "the sensor is broken" apart from "the air genuinely got
bad," continuously, without a human staring at a graph.

**Definition of Done (acceptance criteria):**
- p95 detection latency < 5 seconds from ingestion to alert, per sensor
  reading (once the streaming layer is built — see Section 8 build order).
- System handles ≥ 10,000 messages/sec ingestion (horizontally scalable
  beyond) — target for the production-scale build, not the MVP.
- False positive rate < 5% on labeled validation set; recall > 90% on
  known fault injections.
- Zero data loss on ingestion (at-least-once delivery guarantee).
- Dashboards + alerting operational with < 1 min end-to-end alert delivery.
- Documented, reproducible benchmark comparing ≥ 4 detection approaches.

---

## 2. Types of Anomalies to Detect (Taxonomy)

| Category | Examples | Typical Signature |
|---|---|---|
| **Point anomalies** | Sudden spike/dip in PM2.5 reading | Single value far from local distribution |
| **Contextual anomalies** | Normal value at wrong time (e.g., traffic-hour pattern at 3 AM) | Value normal globally, abnormal given context (time/season/location) |
| **Collective anomalies** | Sustained drift over hours (e.g., filter clogging) | Pattern change over a window, not a single point |
| **Sensor faults** | Flatlining (stuck sensor), impossible values (negative PM2.5), out-of-range | Value fails physical plausibility bounds or variance ≈ 0 |
| **Communication issues** | Missing data, delayed timestamps, packet gaps, duplicate messages | Gaps in ingestion timeline, timestamp skew |
| **Calibration drift** | Gradual bias vs. co-located reference sensor | Slow trend divergence from correlated sensors |
| **Environmental events (true positives, not faults)** | Dust storm, stubble burning, fireworks (Diwali spike) | Regional correlated spike across multiple sensors — must NOT be flagged as "fault" |

This taxonomy matters because the system must **distinguish sensor
malfunction from real environmental events** — flagging a real pollution
spike as a "fault" is a serious failure mode, and it's the single most
Respirer-specific requirement in this whole project.

> Status: the synthetic generator (`generate_sensor_dataset.py`) currently
> implements every row of this table except **contextual anomalies** and
> **timestamp-skew/delayed-timestamp** communication issues — tracked as a
> follow-up (Section 9).

---

## 3. High-Level Architecture

```
┌─────────────┐   MQTT/HTTP   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
│ Field Sensors│ ────────────▶│ Ingestion Gw │──▶│ Message Broker │──▶│ Stream        │
│ (Respirer    │               │ (MQTT broker/│   │ (Kafka/        │   │ Processing    │
│  nodes)      │               │  REST API)   │   │  Redpanda)     │   │ Engine (Flink/│
└─────────────┘               └──────────────┘   └───────────────┘   │ Spark/Bytewax)│
                                                                        └──────┬────────┘
                                                                               │
                              ┌────────────────────────────────────────────────┤
                              ▼                        ▼                       ▼
                     ┌────────────────┐      ┌──────────────────┐    ┌────────────────┐
                     │ Feature Store /│      │ Anomaly Detection │    │ Raw Data Sink   │
                     │ Rolling Stats  │      │ Models (ensemble) │    │ (TimescaleDB /  │
                     │ (Redis)        │      │                   │    │  InfluxDB/S3)   │
                     └────────────────┘      └────────┬──────────┘    └────────────────┘
                                                        ▼
                                         ┌──────────────────────────┐
                                         │ Alerting & Orchestration │
                                         │ (rules + severity + dedup)│
                                         └────────┬─────────────────┘
                                                   ▼
                                 ┌──────────────────────────────────┐
                                 │ Notification (Slack/Email/SMS/  │
                                 │ Webhook) + Dashboard (Grafana)  │
                                 └──────────────────────────────────┘
```

### Why this shape
- **Decoupled ingestion from processing** via a durable message broker so
  sensor bursts, network flakiness, and downstream failures don't cause
  data loss.
- **Stream processing engine** for stateful, windowed computation (rolling
  z-scores, EWMA, gap detection) — cannot be done reliably with simple
  polling scripts.
- **Feature store (Redis)** for low-latency access to rolling statistics
  per sensor (mean, std, last-seen timestamp) needed by multiple models
  concurrently.
- **Model ensemble layer**, not a single algorithm — different anomaly
  types need different detectors (see Section 5).
- **Separate raw data sink** (time-series DB) for audits, retraining, and
  historical analysis — decoupled from the hot path.

> **MVP note:** this diagram is the production target, reachable in
> stages. The current build (Section 8) runs the "Anomaly Detection
> Models" box as a **batch benchmark** directly against files from the
> synthetic generator — no broker, no stream engine yet. That's
> intentional: prove detection quality on labeled data before investing
> in streaming infrastructure.

---

## 4. Detailed Component Design

### 4.1 Ingestion Layer
- **Protocol:** MQTT (lightweight, standard for IoT, supports QoS 1/2 for
  guaranteed delivery) — most low-cost sensor nodes (ESP32/Raspberry Pi
  based, common in Indian AQ monitoring deployments) speak MQTT natively.
  Fallback: HTTPS REST endpoint for nodes that push batched JSON.
- **Broker (MVP):** a single **Mosquitto** instance is sufficient to prove
  the pipeline end-to-end. **Broker (scale-up):** EMQX/Mosquitto cluster
  bridged into Kafka via Kafka Connect MQTT source connector, OR sensors
  publish directly to a lightweight HTTP gateway that writes to
  Kafka/Redpanda — only once message volume or fan-out actually demands it.
- **Schema validation at the edge:** JSON Schema / Protobuf validation
  immediately on ingest — reject/quarantine malformed payloads before
  they pollute the pipeline (this itself is anomaly signal #1: schema
  violations = comms/firmware issue).
- **Idempotency:** Each message carries `sensor_id + timestamp +
  sequence_no`; dedup via Redis SETNX with TTL to survive at-least-once
  delivery duplicates.

### 4.2 Message Backbone
- **MVP:** none — files/batch, or a direct MQTT→scoring-service hookup.
- **Scale-up:** Kafka (or Redpanda for lower ops overhead, Kafka-API
  compatible, better for smaller teams).
- Partition key = `sensor_id` (or `station_id`) — guarantees per-sensor
  ordering, which is essential for time-series/windowed computations.
- Topics: `sensor.raw.v1` (raw validated readings), `sensor.anomaly.v1`
  (detected anomalies with scores/labels), `sensor.dlq` (dead-letter
  queue for malformed/rejected messages).
- Retention: 7 days hot (for replay/debugging), archived to S3/Parquet
  beyond that (cheap cold storage, used for retraining).

### 4.3 Stream Processing Engine

| Option | When to use |
|---|---|
| **river** (Python, online ML) | **Recommended MVP starting point.** Purpose-built for "score one reading, update state, discard" — no cluster to run, trivial to unit-test against the labeled synthetic data, and it's the natural home for the statistical/rolling detectors in Section 5A once they need to run live instead of in batch. |
| **Bytewax** (Python-native, Rust core) | Natural next step once you outgrow a single-process river loop — same language, adds true distributed stream semantics. |
| **Apache Flink** (PyFlink) | Best-in-class stateful stream processing, exactly-once semantics, CEP for pattern-based anomalies. Reach for this only once Respirer's real network scale demands it. |
| **Spark Structured Streaming** | Only if the team already knows Spark / needs batch+stream unification. |
| **Kafka Streams / ksqlDB** | Simple rule-based windowed aggregation; not suited to ML model serving. |

**Recommendation:** MVP on **river** (single-process, no infra), migrate
to **Bytewax** once the pipeline needs to run across multiple
sensors/partitions concurrently at real throughput, with **Flink** as the
final escalation if Respirer's full network scale demands exactly-once
guarantees river/Bytewax can't give cheaply.

### 4.4 Feature Computation (Stateful, Windowed)
Maintain **per-sensor rolling state**:
- Rolling mean/std (EWMA-based, decay factor tunable) — O(1) update, no
  need to store full window.
- Rolling min/max, rate-of-change (first derivative), rate-of-acceleration
  (second derivative).
- Time-since-last-reading (for gap/comms-loss detection).
- Cross-sensor spatial features: neighbor sensors within X km (via
  geo-index), used to distinguish local fault vs. regional event.
- Seasonal/contextual baseline: hour-of-day × day-of-week historical
  percentile bands (precomputed, refreshed daily via batch job).
- **MVP:** computed in-process with pandas groupby/rolling over the
  synthetic dataset (see `models/detectors.py`). **Scale-up:** moved into
  Redis / Flink state backend for O(1) live updates per reading.

### 4.5 Anomaly Detection Methods (Ensemble — Benchmark All, Deploy Best Combination)

This directly satisfies the "benchmarking multiple methodologies"
deliverable.

**A. Statistical / Rule-Based (fast, interpretable, low compute — first line of defense)**
- Physical range checks (hard bounds per pollutant per WHO/CPCB standards).
- Z-score / Modified Z-score (median absolute deviation, robust to
  outliers) on rolling window.
- EWMA control charts / CUSUM for drift detection.
- Grubbs' test / IQR-based outlier flags.
- Flatline detection (variance ≈ 0 over N samples → stuck sensor).
- Gap detection (missed heartbeat/expected sample interval exceeded →
  comms issue) — validated against the generator's `_gap_log.csv` ground
  truth.

**B. Time-Series Model-Based**
- Seasonal-Trend decomposition (STL) + residual thresholding — separates
  real seasonal pollution cycles (rush hour, etc.) from anomalies.
- ARIMA/SARIMA per-sensor forecasting — flag large forecast residuals.
- Facebook Prophet — good for daily/weekly seasonality with holidays
  (Diwali, festival burning spikes).
- Exponential smoothing (Holt-Winters) — lightweight, good baseline.

**C. Machine Learning (unsupervised, since labeled anomalies are scarce
in the field — though the synthetic generator *does* give us labels for
benchmarking)**
- **Use [PyOD](https://github.com/yzhao062/pyod) as the implementation
  library for this whole bucket** rather than hand-rolling each algorithm
  — one consistent `fit`/`decision_function` API across Isolation Forest,
  LOF, One-Class SVM, and more, which makes the ≥4-method benchmark
  requirement (Section 1) far cheaper to produce and keep consistent.
- Isolation Forest — general-purpose multivariate outlier detector, fast,
  scales well. **MVP baseline, alongside statistical rules.**
- Local Outlier Factor (LOF) — density-based local anomalies. **MVP.**
- One-Class SVM — baseline comparison.
- Autoencoder (LSTM-AE or simple feedforward AE) — learns normal
  multivariate sensor pattern; high reconstruction error = anomaly.
- **[Merlion](https://github.com/salesforce/Merlion)** (Salesforce) — a
  time-series-anomaly-specific library with built-in benchmarking
  utilities; worth adopting directly for Section 7's evaluation harness
  instead of writing one from scratch, and its API is close enough to
  PyOD's that both slot into the same ensemble interface.
- Matrix Profile ([STUMPY](https://github.com/TDAmeritrade/stumpy)) —
  excellent for discord discovery in streaming time series without
  labeled training data.

**D. Deep Learning / Advanced (stretch goal for later phase)**
- LSTM/GRU-based forecasting with prediction-interval anomaly scoring.
- Temporal Convolutional Networks (TCN).
- Transformer-based anomaly detectors (Anomaly Transformer, TimesNet) —
  consider only after simpler methods are benchmarked and a clear gap is
  identified. Don't reach for these first — a rolling Z-score with
  seasonal adjustment catches the large majority of the same cases for a
  fraction of the compute cost; jumping straight to deep learning without
  that comparison in hand is the most common time-sink in projects like
  this.

**E. Cross-Sensor / Spatial Correlation (headline contribution)**
- Since Respirer operates a *network* of sensors, use spatial correlation
  checks: if one sensor spikes but its geographic neighbors (within ~2-5
  km) show no correlated spike, weight toward "sensor fault." If multiple
  neighboring sensors spike together, weight toward "real environmental
  event." This is a strong differentiator vs. single-sensor-only anomaly
  detection and should be a headline contribution of the project — the
  synthetic generator's `environmental_event` category exists specifically
  to give this a labeled benchmark target (see `is_regional_event` column).

**Ensemble strategy:** Combine A (fast pre-filter, catches obvious faults
cheaply) → B/C run in parallel for subtler anomalies → weighted voting or
a lightweight meta-classifier (logistic regression / gradient boosted
trees) trained on labeled fault-injection data to combine scores into a
final severity + confidence + anomaly-type label.

**Pragmatic MVP build order (new):** don't implement A-E in one pass.
1. Statistical rules (A) — cheap, explainable, catches most obvious faults.
2. Isolation Forest + LOF via PyOD (subset of C) — general multivariate
   coverage with almost no extra code.
3. Only if the benchmark (Section 7) shows a real gap these two don't
   cover, add STL/Prophet residuals (B) or an autoencoder (C/D).
This mirrors the "start simple, prove the gap before reaching for
something heavier" principle and keeps the benchmarking deliverable
achievable inside a normal internship timeline.

### 4.6 Model Serving in the Streaming Pipeline
- Lightweight statistical/rule checks run **inline** in the stream
  processor (sub-millisecond).
- Heavier ML models (Isolation Forest, Autoencoder) served via a **model
  microservice** (FastAPI + ONNX Runtime or TorchServe/BentoML), called
  async/batched from the stream processor to avoid blocking.
- Batch scoring for non-latency-critical models (e.g., matrix profile
  recompute every 5 min) via a separate scheduled job (**Prefect**
  recommended over Airflow for a small team — lighter to run locally;
  Airflow is the fallback if Respirer already standardizes on it).
- Model versioning via **MLflow Model Registry** — enables A/B testing
  new models against production without downtime.

### 4.7 Alerting & Deduplication
- Severity tiers: `INFO` / `WARNING` / `CRITICAL` based on ensemble
  confidence + anomaly type.
- Deduplication/suppression window (e.g., don't re-alert same sensor for
  same anomaly type within 15 min) to avoid alert fatigue.
- Route: Slack/Email for WARNING+, SMS/PagerDuty-style for CRITICAL.
- Include explainability in every alert: which detector(s) fired, feature
  values, confidence score, and a link to the sensor's live dashboard.

### 4.8 Storage
- **Hot path:** Redis (rolling stats, last-N readings cache, dedup keys).
- **Time-series storage:** TimescaleDB (Postgres-based, SQL-friendly,
  good for a research team) or InfluxDB.
- **Cold storage:** Parquet files on S3/MinIO, partitioned by date/sensor.
- **MVP:** the synthetic dataset already ships as CSV + Parquet
  (`sensor_data.csv` / `sensor_data.parquet`) — no DB needed to start
  benchmarking.

### 4.9 Visualization & Dashboards
- Grafana connected to TimescaleDB/InfluxDB — real-time sensor value +
  anomaly overlay dashboards.
- Streamlit or Plotly Dash app for the research/benchmarking side —
  interactive comparison of detection methods, confusion matrices, ROC/PR
  curves, per-method latency comparison.
- Map view (Leaflet/Mapbox via Grafana geomap panel) for network-wide
  anomaly hotspots.

### 4.10 Scalability & Reliability
- Horizontal scaling via Kafka partitions + Kubernetes HPA on consumer lag.
- Exactly-once/at-least-once processing with idempotent writes.
- Docker for every service; Kubernetes for production orchestration.
- Load testing (Locust/k6) targeting 10k+ msg/sec sustained.
- Circuit breakers: if the ML model service is down, fall back to
  statistical rules only.
- Edge pre-filtering for unreliable Indian field connectivity — lightweight
  rule-based checks on-device before transmission, with store-and-forward
  buffering during outages.

---

## 5. Tech Stack (Merged)

| Layer | MVP choice | Scale-up choice | Why |
|---|---|---|---|
| Device→server messaging | MQTT (Mosquitto) | EMQX cluster / Kafka Connect bridge | Standard for flaky IoT devices |
| Stream processing | **river** | Bytewax → Flink | river needs no cluster; clear escalation path |
| Anomaly detection library | **PyOD** (Isolation Forest, LOF) | + Merlion, STUMPY | Unified API, don't hand-roll every algorithm |
| Feature store | pandas rolling (batch) | Redis / Feast | Avoids train/serve skew once live |
| Model serving | FastAPI | + ONNX Runtime / BentoML | Lightweight, async, Python-native |
| Model tracking | MLflow | MLflow | Same at both stages |
| Storage | CSV/Parquet files | TimescaleDB + S3/MinIO cold storage | Files are enough pre-deployment |
| Dashboard | matplotlib/Streamlit tables | Grafana | Grafana once there's a live DB to point at |
| Data quality | pandas assertions | Great Expectations / Soda | Formalize once schema stabilizes |
| Containerization | — | Docker + docker-compose → Kubernetes | Portability once deploying to Respirer infra |
| Retraining orchestration | manual script re-run | Prefect (or Airflow) | Cron-like scheduling for periodic re-benchmarking |
| Observability | print/log statements | Prometheus + Grafana + OpenTelemetry | Needed once the p95 latency SLA is live |

Everything here is Python-first, matching the required skill set, and
nothing in the MVP column requires infrastructure beyond a laptop with
Python installed.

---

## 6. Handling the Specific Required Scenarios

| Requirement | How it's handled |
|---|---|
| **Normal observations** | Baseline model training data; validates false-positive rate stays low |
| **Missing data** | Trivial rule detector (null-payload check) + gap detector (expected-interval tracking) for true comms gaps; imputation flagged, never silently treated as real |
| **Outliers** | Z-score/MAD + Isolation Forest/LOF; physical bound checks as a fast first pass |
| **Sudden spikes** | Rate-of-change features + CUSUM; cross-checked against neighbor sensors (Section 4.5E) to distinguish fault vs. real event |
| **Communication interruptions** | Heartbeat/gap monitoring; distinct alert category from data-value anomalies; edge store-and-forward buffering |
| **Duplicate messages** | Exact/near-duplicate row detector keyed on `(station_id, timestamp)` |
| **Environmental events** | Cross-sensor correlation check (Section 4.5E) — explicitly benchmarked as a false-positive stress test, not just a detection target |

---

## 7. Evaluation Framework

1. **Synthetic fault injection:** the dataset generator programmatically
   injects known anomalies (spikes, flatlines, gaps, drift, duplicates,
   environmental events) with ground-truth labels — this is what makes
   precision/recall/F1 measurable at all, since labeled field data won't
   exist for a long time.
2. **Metrics to report per method:**
   - Precision, Recall, F1, **AUC-PR** (not AUC-ROC — anomalies are rare,
     so PR curves are the honest metric under class imbalance).
   - Detection delay — time between anomaly onset and detection.
   - Latency (p50/p95/p99) and throughput (msgs/sec) per method.
   - **False positive rate specifically on `environmental_event` rows** —
     this directly stress-tests the fault-vs-event distinction Respirer
     cares about most.
3. **Comparison table** across statistical, ML, and time-series methods —
   the direct output for the technical report.
4. **Reference methodology:** align the evaluation harness with the
   [**NAB (Numenta Anomaly Benchmark)**](https://github.com/numenta/NAB)
   scoring approach rather than inventing one from scratch — it's a
   standardized, well-understood methodology for exactly this kind of
   streaming anomaly detection benchmark, and citing it strengthens the
   technical report's grounding.
5. **Field validation phase:** once deployed on real Respirer stations,
   cross-validate flagged anomalies against maintenance logs / known
   sensor service events / co-located reference-grade monitor data.

**Prior art worth reading (not copying) while building this:** PyOD,
Merlion, [Orion/Sintel](https://github.com/sintel-dev/Orion) (MIT
Data-to-AI Lab's end-to-end TS anomaly benchmarking pipeline, conceptually
close to this whole project), NAB, STUMPY, river, the
[TICK stack](https://www.influxdata.com/time-series-platform/) (ingest →
store → alert reference implementation), and domain siblings
[AirQo](https://airqo.net/) / [OpenAQ](https://openaq.org/) /
[Sensor.Community](https://sensor.community/) for realistic low-cost
air-quality sensor fault patterns worth calibrating the simulator against.

---

## 8. Implementation Plan / Phased Roadmap (Merged)

### Phase 0 — Setup (Week 1)
- Finalize requirements with Respirer (data schema, sensor types, sampling
  rates, network topology, existing infra access).
- GitHub repo, CI pipeline skeleton. No Docker Compose stack yet — deferred
  until Phase 3 actually needs Kafka/Redis/TimescaleDB.

### Phase 1 — Data Simulation & Exploration (Week 1-2) ✅ **done**
- `generate_sensor_dataset.py`: normal patterns + injectable anomalies
  (spikes, gaps, drift, flatline, comms loss, duplicates, environmental
  events) with configurable severity/frequency via `--n_records`.
- Ground-truth labeling scheme: `anomaly_type`, `anomaly_subtype`,
  `is_anomaly`, `is_missing`, `is_regional_event` columns + companion
  `_gap_log.csv`.
- Outputs: `sensor_data.csv` (229MB) / `sensor_data.parquet` (70MB),
  996,000 rows at the 1M-record default.
- Remaining gap: contextual anomalies and timestamp-skew are not yet
  injected (Section 9).

### Phase 2 — Algorithm Development & Benchmarking (Week 2-4) ← **current phase**
- Implement the MVP build order from Section 4.5: statistical rules (A)
  first, then PyOD Isolation Forest + LOF.
- Build the evaluation framework (Section 7) using the labels already in
  the dataset; run the benchmark suite; produce the comparison table.
- Only add STL/Prophet/autoencoder methods if the benchmark shows a
  concrete gap the first two buckets don't cover.
- Deliverable: `models/` directory (`detectors.py`, `evaluate.py`,
  `benchmark.py`) + a benchmark report.

**Baseline results (100k-row stratified sample, 6 stations):**

| Method | Precision | Recall | F1 | Env-event FP rate |
|---|---|---|---|---|
| missing (rule) | 1.00 | 1.00 | 1.00 | n/a |
| Z-score outlier | 0.36 | 0.88 | 0.51 | 0.08 |
| flatline (rolling std) | 0.71 | 0.57 | 0.64 | 0.23 |
| CUSUM drift | 0.05 | 0.07 | 0.06 | 0.05 |
| duplicate (rule) | 0.50\* | 1.00 | 0.67 | n/a |
| Isolation Forest (PyOD) | 0.36 | 0.40 | 0.38 | **0.88** |
| LOF (PyOD) | 0.28 | 0.31 | 0.29 | **0.19** |
| Gap detector | recall 1.00, mean delay ≈24 min (event-level, vs `_gap_log.csv`) | | | |

\* duplicate precision is capped at 0.5 by construction — a `(station_id,
timestamp)` key match correctly flags both rows in the pair, but only the
appended copy carries the `duplicate` ground-truth label.

**What this run already validates (headline finding):** Isolation
Forest's environmental-event false-positive rate (0.88) confirms the plan's
Section 4.5E argument empirically — a single-sensor multivariate detector
genuinely cannot tell a real regional pollution event from a fault; both
look like a multivariate outlier from one station's point of view. LOF's
much lower rate (0.19) is a useful secondary finding for method selection.
This is the concrete evidence for the "cross-sensor correlation is the
headline contribution" claim, not just an assertion.

**What this run exposed as a real bug (not a benchmark artifact):**
building this benchmark caught that `inject_flatline_faults` and
`inject_drift` in `generate_sensor_dataset.py` were building "runs" from a
flat, cross-dataset shuffle rather than each station's own chronological
sequence (the same class of bug already fixed for `comm_gap` earlier) - so
flatline/drift rows were scattered single-row events with no real
sustained signal for a rolling-variance or CUSUM detector to find. Fixed
by reusing the per-station budgeted-run selection approach, and the full
dataset was regenerated. This is a good example of why building the
benchmark harness early (Phase 2) surfaces problems in Phase 1's output
that a purely visual/statistical check of the generator would miss.

**CUSUM's weak precision (0.05) is an honest MVP finding, not a bug**
(see docstring in `models/detectors.py`): the ~12-18% multiplicative
sensor noise plus strong diurnal swings the generator injects dominate the
small early signal of a gradual drift ramp for a plain EWMA/CUSUM
baseline. This is exactly the kind of gap the "pragmatic MVP build order"
is designed to surface before reaching for STL-decomposition + residual
thresholding (Section 4.5B), which removes the diurnal component first
and should perform meaningfully better - a concrete, evidence-backed
next step for Phase 2 rather than a speculative one.

### Phase 3 — Streaming Pipeline Build (Week 4-6)
- Wrap the best-performing detectors in a **river**-based online scoring
  loop that replays the dataset row-by-row to simulate live arrival.
- Only escalate to MQTT + Bytewax/Kafka if the river prototype's
  throughput genuinely can't keep up with a realistic message rate.
- Feature store, alerting, dedup logic; Streamlit benchmarking UI.

### Phase 4 — Field Integration (Week 6-10)
- Integrate with actual Respirer field network data feed.
- Shadow-mode deployment: log-only, no alerts sent, validate against real
  conditions without operational risk.
- Compare shadow-mode detections against Respirer's existing QA/maintenance
  records; recalibrate the simulator against real data patterns found here.

### Phase 5 — Production Cutover & Tuning
- Enable live alerting for a pilot subset of stations.
- Tune thresholds/ensemble weights based on field feedback.
- Set up monitoring/observability (Prometheus/Grafana) for the pipeline
  itself.

### Phase 6 — Documentation & Handover
- Finalize technical report: methodology, benchmark results, architecture,
  deployment guide, runbooks.
- Knowledge transfer session with Respirer engineering team.
- Handover deployment artifacts.

---

## 9. Known Gaps / Follow-ups

- **Contextual anomalies** (normal value, wrong time/season/location) are
  not yet injected by the generator — would need a detector that compares
  a reading against an hour-of-day × season baseline rather than a global
  one.
- **Timestamp skew / delayed timestamps** — distinct from packet gaps and
  duplicates, not yet simulated.
- Streaming (river/Bytewax) prototype not yet built — Phase 3.
- Real Respirer data not yet available to calibrate simulation parameters
  against (Phase 0/4 risk, tracked below).

---

## 10. Team Skill Mapping

| Skill (as required) | Where applied |
|---|---|
| Python programming | Entire pipeline (simulation generator, detectors, benchmarking, dashboards) |
| Data Analytics & ML | Section 4.5 (A-D) — model development and benchmarking |
| Time-Series Analysis | STL decomposition, ARIMA/Prophet, matrix profile, rolling statistics |
| Data Visualization | Grafana dashboards, Streamlit/Plotly benchmarking UI, technical report figures |
| IoT/sensor networks understanding | MQTT ingestion design, edge pre-filtering, comms-loss handling, field deployment phase |

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Real Respirer data differs significantly from simulation assumptions | Get sample real data as early as possible (Phase 0); calibrate simulator iteratively; compare against AirQo/OpenAQ real-world fault patterns in the meantime |
| Field network connectivity is unreliable (rural/low-bandwidth areas) | Edge pre-filtering + store-and-forward buffering; design for intermittent connectivity from day one |
| Alert fatigue from false positives undermines operator trust | Deduplication window, severity tiers, explainable alerts, shadow-mode validation before going live |
| Scaling assumptions untested until late | Load-test early (once Phase 3 exists), not just before final deployment |
| Labeled anomaly data is scarce for supervised evaluation in the field | Rely primarily on unsupervised methods + synthetic fault injection for controlled evaluation; use field maintenance logs as a secondary real-world label source |
| Over-building infrastructure before proving detection quality | MVP build order (Section 4.5, Section 8) explicitly defers Kafka/K8s/Redis until a benchmark or scale requirement proves the lighter option insufficient |

---

## 12. Summary

This plan satisfies every explicit project requirement — simulated data
covering normal/missing/outlier/spike/comms-loss/duplicate/environmental
conditions, a multi-method benchmarked detection engine (statistical + ML
+ time-series), a scalable real-time architecture, a performance
evaluation framework grounded in standard methodology (NAB), and a path to
real deployment on Respirer's field network — while keeping the actual
build order realistic for an internship timeline: prove detection quality
in batch on labeled synthetic data first (Phase 1-2, done/current), then
earn each layer of infrastructure (streaming, Kafka, Kubernetes, edge
TinyML) only once a concrete requirement demands it, rather than building
the full production architecture speculatively up front.
