# Real-Time Anomaly Detection in Sensor Data Streams
## Production-Ready System Design & Implementation Plan (Respirer India — Field Monitoring Networks)

---

## 1. Problem Restatement & Success Criteria

**Goal:** Build a real-time anomaly detection framework for environmental sensor streams (PM2.5, PM10, NO2, CO, temperature, humidity, etc.) that:
1. Detects abnormal patterns, sensor faults, communication issues, and genuine environmental events.
2. Works on simulated data first, then deploys on live Respirer field networks.
3. Scales to a large number of concurrent sensor nodes with low latency.
4. Is measurable — accuracy, precision/recall, latency, uptime.

**Definition of Done (acceptance criteria):**
- p95 detection latency < 5 seconds from ingestion to alert, per sensor reading.
- System handles ≥ 10,000 messages/sec ingestion (horizontally scalable beyond).
- False positive rate < 5% on labeled validation set; recall > 90% on known fault injections.
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

This taxonomy matters because your system must **distinguish sensor malfunction from real environmental events** — a critical Respirer requirement, since flagging a real pollution spike as a "fault" is a serious failure mode.

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
- **Decoupled ingestion from processing** via a durable message broker so sensor bursts, network flakiness, and downstream failures don't cause data loss.
- **Stream processing engine** for stateful, windowed computation (rolling z-scores, EWMA, gap detection) — cannot be done reliably with simple polling scripts.
- **Feature store (Redis)** for low-latency access to rolling statistics per sensor (mean, std, last-seen timestamp) needed by multiple models concurrently.
- **Model ensemble layer**, not a single algorithm — different anomaly types need different detectors (see Section 5).
- **Separate raw data sink** (time-series DB) for audits, retraining, and historical analysis — decoupled from the hot path.

---

## 4. Detailed Component Design

### 4.1 Ingestion Layer
- **Protocol:** MQTT (lightweight, standard for IoT, supports QoS 1/2 for guaranteed delivery) — most low-cost sensor nodes (ESP32/Raspberry Pi based, common in Indian AQ monitoring deployments) speak MQTT natively. Fallback: HTTPS REST endpoint for nodes that push batched JSON.
- **Broker:** EMQX or Mosquitto cluster (MQTT) bridged into Kafka via Kafka Connect MQTT source connector, OR sensors publish directly to a lightweight HTTP gateway that writes to Kafka/Redpanda.
- **Schema validation at the edge:** JSON Schema / Protobuf validation immediately on ingest — reject/quarantine malformed payloads before they pollute the pipeline (this itself is anomaly signal #1: schema violations = comms/firmware issue).
- **Idempotency:** Each message carries `sensor_id + timestamp + sequence_no`; dedup via Redis SETNX with TTL to survive at-least-once delivery duplicates.

### 4.2 Message Backbone
- **Kafka (or Redpanda for lower ops overhead, Kafka-API compatible, better for smaller teams).**
- Partition key = `sensor_id` (or `station_id`) — guarantees per-sensor ordering, which is essential for time-series/windowed computations.
- Topics:
  - `sensor.raw.v1` — raw validated readings
  - `sensor.anomaly.v1` — detected anomalies with scores/labels
  - `sensor.dlq` — dead-letter queue for malformed/rejected messages
- Retention: 7 days hot (for replay/debugging), archived to S3/Parquet beyond that (cheap cold storage, used for retraining).

### 4.3 Stream Processing Engine
Choice depends on team size/ops maturity:

| Option | When to use |
|---|---|
| **Apache Flink** (PyFlink) | Best-in-class stateful stream processing, exactly-once semantics, complex event processing (CEP) for pattern-based anomalies. Higher ops complexity. |
| **Bytewax** (Python-native, Rust core) | Easiest for a Python-heavy student/research team; good throughput; simpler to deploy than Flink. **Recommended starting point.** |
| **Spark Structured Streaming** | Good if team already knows Spark / needs batch+stream unification; higher latency (micro-batch) than Flink/Bytewax. |
| **Kafka Streams / ksqlDB** | Good for simple rule-based windowed aggregation, less suited to ML model serving. |

**Recommendation:** Start with **Bytewax** for the pipeline (Python-native, fits the team's Python skillset, easy local dev), with a clear migration path to **Flink** if/when throughput or exactly-once guarantees demand it at Respirer's full network scale.

### 4.4 Feature Computation (Stateful, Windowed)
Maintain **per-sensor rolling state** in Redis / RocksDB (Flink state backend):
- Rolling mean/std (EWMA-based, decay factor tunable) — O(1) update, no need to store full window.
- Rolling min/max, rate-of-change (first derivative), rate-of-acceleration (second derivative).
- Time-since-last-reading (for gap/comms-loss detection).
- Cross-sensor spatial features: neighbor sensors within X km (via geo-index), used to distinguish local fault vs. regional event.
- Seasonal/contextual baseline: hour-of-day × day-of-week historical percentile bands (precomputed, refreshed daily via batch job).

### 4.5 Anomaly Detection Methods (Ensemble — Benchmark All, Deploy Best Combination)

This directly satisfies the "benchmarking multiple methodologies" deliverable.

**A. Statistical / Rule-Based (fast, interpretable, low compute — first line of defense)**
- Physical range checks (hard bounds per pollutant per WHO/CPCB standards).
- Z-score / Modified Z-score (median absolute deviation, robust to outliers) on rolling window.
- EWMA control charts / CUSUM for drift detection.
- Grubbs' test / IQR-based outlier flags.
- Flatline detection (variance ≈ 0 over N samples → stuck sensor).
- Gap detection (missed heartbeat/expected sample interval exceeded → comms issue).

**B. Time-Series Model-Based**
- **Seasonal-Trend decomposition (STL) + residual thresholding** — separates real seasonal pollution cycles (rush hour, etc.) from anomalies.
- **ARIMA/SARIMA** per-sensor forecasting — flag large forecast residuals.
- **Facebook Prophet** — good for daily/weekly seasonality with holidays (Diwali, festival burning spikes — important for Indian AQ data).
- **Exponential smoothing (Holt-Winters)** — lightweight, good baseline.

**C. Machine Learning (unsupervised, since labeled anomalies are scarce)**
- **Isolation Forest** — good general-purpose multivariate outlier detector, fast, scales well.
- **Local Outlier Factor (LOF)** — good for density-based local anomalies.
- **One-Class SVM** — baseline comparison.
- **Autoencoder (LSTM-AE or simple feedforward AE)** — learns normal multivariate sensor pattern (PM2.5, PM10, temp, humidity together); high reconstruction error = anomaly. Good at catching subtle multivariate faults (e.g., PM2.5 normal but humidity sensor drifting, causing correction algorithm errors).
- **Matrix Profile (STUMPY library)** — excellent for discord discovery in streaming time series without needing labeled training data; very well suited to this problem and underused — **recommend evaluating seriously**.

**D. Deep Learning / Advanced (stretch goal for later phase)**
- **LSTM/GRU-based forecasting** with prediction-interval anomaly scoring.
- **Temporal Convolutional Networks (TCN)**.
- **Transformer-based anomaly detectors** (e.g., Anomaly Transformer, TimesNet) — state of the art but heavier to deploy; consider only after simpler methods are benchmarked and a clear gap is identified.

**E. Cross-Sensor / Spatial Correlation (Recommended novel addition)**
- Since Respirer operates a *network* of sensors, use **spatial correlation checks**: if one sensor spikes but its geographic neighbors (within ~2-5 km) show no correlated spike, weight toward "sensor fault." If multiple neighboring sensors spike together, weight toward "real environmental event." This is a strong differentiator vs. single-sensor-only anomaly detection and should be a headline contribution of the project.

**Ensemble strategy:** Combine A (fast pre-filter, catches obvious faults cheaply) → B/C run in parallel on the stream for subtler anomalies → weighted voting or a lightweight meta-classifier (logistic regression / gradient boosted trees) trained on labeled fault-injection data to combine scores into a final severity + confidence + anomaly-type label.

### 4.6 Model Serving in the Streaming Pipeline
- Lightweight statistical/rule checks run **inline** in the stream processor (sub-millisecond).
- Heavier ML models (Isolation Forest, Autoencoder) served via a **model microservice** (FastAPI + ONNX Runtime or TorchServe/BentoML), called async/batched from the stream processor to avoid blocking.
- Batch scoring for non-latency-critical models (e.g., matrix profile recompute every 5 min) via a separate scheduled job (Airflow/Prefect).
- Model versioning via **MLflow Model Registry** — enables A/B testing new models against production without downtime.

### 4.7 Alerting & Deduplication
- Severity tiers: `INFO` / `WARNING` / `CRITICAL` based on ensemble confidence + anomaly type.
- **Deduplication/suppression window** (e.g., don't re-alert same sensor for same anomaly type within 15 min) to avoid alert fatigue — critical for field operations teams.
- Route: Slack/Email for WARNING+, SMS/PagerDuty-style for CRITICAL (e.g., total comms loss from a station cluster).
- Include **explainability** in every alert: which detector(s) fired, feature values, confidence score, and a link to the sensor's live dashboard — operators need to act, not just be notified.

### 4.8 Storage
- **Hot path:** Redis (rolling stats, last-N readings cache, dedup keys) — sub-ms reads.
- **Time-series storage:** TimescaleDB (Postgres-based, SQL-friendly, good for a research team) or InfluxDB — for raw readings + anomaly labels, used for dashboards and retraining.
- **Cold storage:** Parquet files on S3/MinIO, partitioned by date/sensor — cheap, used for offline benchmarking and model retraining pipelines.

### 4.9 Visualization & Dashboards
- **Grafana** connected to TimescaleDB/InfluxDB — real-time sensor value + anomaly overlay dashboards, per-station and network-wide heatmaps.
- **Streamlit or Plotly Dash app** for the research/benchmarking side — interactive comparison of detection methods, confusion matrices, ROC curves, per-method latency comparison (useful for the technical report deliverable).
- Map view (Leaflet/Mapbox via Grafana geomap panel or a custom React/Deck.gl frontend) showing live sensor network health + anomaly hotspots across Respirer's deployment.

### 4.10 Scalability & Reliability (satisfying "handle large loads")
- **Horizontal scaling:** Kafka partitions scale ingestion; stream processor workers scale independently (Kubernetes HPA based on consumer lag).
- **Backpressure handling:** Kafka naturally buffers; consumer lag alerts trigger autoscaling.
- **Exactly-once / at-least-once processing** with idempotent writes (dedup keys) to guarantee no data loss and no duplicate alerts.
- **Containerization:** Docker for every service; **Kubernetes** for orchestration in production — enables rolling deploys, autoscaling, self-healing.
- **Load testing:** Locust or k6 simulating N sensors × M msgs/sec before field deployment; target validated at 10k+ msg/sec sustained.
- **Circuit breakers / graceful degradation:** if the ML model service is down, fall back to statistical rules only (never drop anomaly detection entirely).
- **Multi-region/edge consideration:** for Indian field networks with unreliable connectivity, consider **edge pre-filtering** — lightweight rule-based anomaly flags computed on-device (or on a local gateway/Raspberry Pi) before transmission, reducing bandwidth needs and enabling detection even during connectivity gaps (store-and-forward on the edge device).

---

## 5. Suggested New/Modern Tech to Elevate This to Production Grade

| Area | Suggested Tech | Why it helps |
|---|---|---|
| Streaming backbone | **Redpanda** instead of vanilla Kafka | Kafka-API compatible, no ZooKeeper, much lower ops burden — good fit for a lean team |
| Stream processing | **Bytewax** (Python) with migration path to **Flink** | Native Python (fits team skills), easy to prototype, scalable later |
| Time-series discord detection | **STUMPY (Matrix Profile)** | State-of-the-art unsupervised streaming anomaly detection, no labels needed, well-suited to environmental time series |
| Feature store | **Redis** or **Feast** (feature store framework) | Consistent features between training and real-time serving — avoids train/serve skew |
| Model serving | **BentoML** or **ONNX Runtime** | Fast, standardized, framework-agnostic model serving with low latency |
| Experiment/model tracking | **MLflow** | Versioning, reproducibility, A/B testing between detection algorithm versions — directly supports the "benchmarking" deliverable |
| Observability | **Prometheus + Grafana + OpenTelemetry** | End-to-end tracing of pipeline latency, essential for meeting the p95 latency SLA |
| Data quality | **Great Expectations** or **Soda** | Automated data quality checks in the pipeline (a form of anomaly detection itself — schema drift, null spikes, etc.) |
| Edge computing | **TinyML on ESP32/RPi (TensorFlow Lite Micro)** | Pre-filter obvious faults at the sensor node itself before transmission — reduces load and works during connectivity loss |
| Container orchestration | **Kubernetes (K3s for lightweight field/edge gateway clusters)** | Production-grade scaling and resilience |
| CI/CD | **GitHub Actions + Docker + Helm charts** | Reproducible deployments, automated testing of detection pipeline changes |
| Alert routing | **Grafana OnCall** or **PagerDuty free tier** | Proper on-call/escalation workflow instead of ad-hoc notifications |
| Geo-spatial correlation | **PostGIS** extension on TimescaleDB | Efficient nearest-neighbor sensor queries for the cross-sensor correlation check (Section 4.5E) |

---

## 6. Handling the Specific Required Scenarios

| Requirement | How it's handled |
|---|---|
| **Normal observations** | Baseline model training data; used to validate false-positive rate stays low |
| **Missing data** | Gap detector (expected-interval tracking) in stream processor; imputation (forward-fill/interpolation) for downstream models with a "data quality" flag attached so imputed values are never silently treated as real |
| **Outliers** | Z-score/MAD + Isolation Forest catch these; physical bound checks as a fast first pass |
| **Sudden spikes** | Rate-of-change features + CUSUM; cross-checked against neighbor sensors to distinguish fault vs. real event (e.g., stubble burning) |
| **Communication interruptions** | Heartbeat/gap monitoring at the ingestion layer; distinct alert category from data-value anomalies; edge store-and-forward buffering to prevent data loss during outages |

---

## 7. Evaluation Framework (Deliverable: "Performance Evaluation Framework")

1. **Synthetic fault injection:** Programmatically inject known anomalies (spikes, flatlines, gaps, drift) into simulated streams at known timestamps → ground truth for precision/recall/F1 per detection method.
2. **Metrics to report per method:**
   - Precision, Recall, F1, AUC-ROC, AUC-PR (PR curve matters more given class imbalance — anomalies are rare).
   - **Detection delay** — time between anomaly onset and detection (critical for "real-time" claim).
   - Latency (p50/p95/p99) and throughput (msgs/sec) per method.
   - False positive rate under normal high-variance conditions (e.g., Diwali) — stress-tests the fault-vs-event distinction.
3. **Comparison table** across statistical, ML, and time-series methods (per Section 4.5) — this is the direct output for the technical report.
4. **Field validation phase:** Once deployed on real Respirer stations, cross-validate flagged anomalies against maintenance logs / known sensor service events / co-located reference-grade monitor data (if available) to compute real-world precision.

---

## 8. Implementation Plan / Phased Roadmap

### Phase 0 — Setup (Week 1-2)
- Finalize requirements with Respirer (data schema, sensor types, sampling rates, network topology, existing infra access).
- Set up dev environment: Docker Compose stack (Kafka/Redpanda, Redis, TimescaleDB, Grafana) for local development.
- Set up GitHub repo, CI pipeline skeleton.

### Phase 1 — Data Simulation & Exploration (Week 2-4)
- Build a **synthetic sensor data generator**: normal patterns + injectable anomalies (spikes, gaps, drift, flatline, comms loss) with configurable severity/frequency, mimicking real Respirer station behavior (diurnal PM2.5 patterns, seasonal effects).
- Exploratory Data Analysis on any available historical Respirer data (if accessible) to calibrate realistic simulation parameters.
- Define ground-truth labeling scheme for injected anomalies.

### Phase 2 — Algorithm Development & Benchmarking (Week 4-8)
- Implement all methods in Section 4.5 (A-D) against simulated streams (batch mode first, for fast iteration).
- Build the evaluation framework (Section 7); run benchmark suite.
- Select top 2-3 performing methods per anomaly category for the ensemble.
- Document trade-offs (accuracy vs. latency vs. compute cost) — key input to architecture decisions.

### Phase 3 — Streaming Pipeline Build (Week 8-12)
- Stand up Kafka/Redpanda + Bytewax pipeline with the selected ensemble running on simulated **live** (not batch) streams.
- Implement feature store, alerting, dedup logic.
- Build Grafana dashboards + Streamlit benchmarking UI.
- Load testing (Locust/k6) to validate throughput targets.

### Phase 4 — Field Integration (Week 12-16)
- Integrate with actual Respirer field network data feed (coordinate on API/MQTT credentials, data schema mapping).
- Shadow-mode deployment: run pipeline in parallel with existing monitoring, log-only (no alerts sent) to validate against real conditions without operational risk.
- Compare shadow-mode detections against Respirer's existing QA/maintenance records.

### Phase 5 — Production Cutover & Tuning (Week 16-20)
- Enable live alerting for a pilot subset of stations.
- Tune thresholds/ensemble weights based on field false-positive/negative feedback from Respirer operations team.
- Set up monitoring/observability (Prometheus/Grafana) for the pipeline itself (meta-monitoring).

### Phase 6 — Documentation & Handover (Week 20-22)
- Finalize technical report: methodology, benchmark results, architecture, deployment guide, runbooks.
- Knowledge transfer session with Respirer engineering team.
- Handover deployment artifacts (Docker/Helm charts, CI/CD pipelines, model registry).

---

## 9. Team Skill Mapping

| Skill (as required) | Where applied |
|---|---|
| Python programming | Entire pipeline (Bytewax processors, model code, simulation generator, dashboards) |
| Data Analytics & ML | Section 4.5 (B, C, D) — model development and benchmarking |
| Time-Series Analysis | STL decomposition, ARIMA/Prophet, matrix profile, rolling statistics |
| Data Visualization | Grafana dashboards, Streamlit/Plotly benchmarking UI, technical report figures |
| IoT/sensor networks understanding | MQTT ingestion design, edge pre-filtering, comms-loss handling, field deployment phase |

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Real Respirer data differs significantly from simulation assumptions | Get sample real data as early as possible (Phase 0); calibrate simulator iteratively |
| Field network connectivity is unreliable (rural/low-bandwidth areas common in India) | Edge pre-filtering + store-and-forward buffering; design for intermittent connectivity from day one |
| Alert fatigue from false positives undermines operator trust | Deduplication window, severity tiers, explainable alerts, shadow-mode validation before going live |
| Scaling assumptions untested until late | Load-test early (Phase 3), not just before final deployment |
| Labeled anomaly data is scarce for supervised evaluation | Rely primarily on unsupervised methods + synthetic fault injection for controlled evaluation; use field maintenance logs as a secondary real-world label source |

---

## 11. Summary

This design satisfies every explicit project requirement — simulated data with normal/missing/outlier/spike/comms-loss conditions, a multi-method benchmarked detection engine (statistical + ML + time-series), a scalable real-time architecture, a performance evaluation framework, and a path to real deployment on Respirer's field network — while adding production-hardening elements (Kafka/Redpanda backbone, Kubernetes scaling, edge pre-filtering, spatial cross-sensor correlation, MLflow model governance, and full observability) that go beyond a purely academic prototype and make it genuinely deployable at scale.
