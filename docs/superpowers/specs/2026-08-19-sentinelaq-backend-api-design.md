# SentinelAQ Backend API — Design Spec

## Context and goals

The dashboard sub-project (React + shadcn/Tailwind + Recharts + MapLibre, per prior brainstorm) needs something to talk to. Today the backend only produces batch CSVs (`benchmark.py`) and a standalone CLI simulation (`streaming/live_stream.py`) — no API exists. This spec covers **sub-project 1 only**: a FastAPI service that exposes the Phase 2/3 detection work over HTTP + WebSocket. The dashboard itself is a separate, later spec.

Success criteria: a dashboard client can (1) watch live simulated detections stream in, (2) see all 50 stations on a map with current status, (3) see the Phase 2 benchmark comparison table with the stated model-selection rationale — all from one local FastAPI process, no auth, no external DB.

## Architecture

- **FastAPI app**, single process, run via `uvicorn` for local dev.
- **StreamEngine**: an asyncio background task started on app startup. Loads the dataset once, sorts globally by timestamp (true arrival order, matching `live_stream.py`), then loops through rows, sleeping between rows by `real_delta_seconds / speed_multiplier`. Default `speed_multiplier = 60` (5-minute sensor interval → ~5 simulated seconds between readings from the same station — visibly live without being an unreadable blur); adjustable at runtime via the WebSocket control message below.
- Each row is scored using the **same logic as `live_stream.py`**: Z-score + flatline (statistical first pass) + incremental LOF (`river`, matching the Phase 2 benchmark winner) + spatial-correlation correction layer.
- **Refactor requirement**: `live_stream.py` currently has this scoring logic inlined in `main()` (lines ~127-168 as of this spec). It must be extracted into a standalone `score_row(state, neighbor_states, row, t) -> (flag, spatial_label, detector_fired, z_pm25)` function, importable by both the existing CLI script and the new API service, so the two never drift out of sync. `StationState`, `zscore()`, and `spatial_correlation.build_neighbor_map()` are already reusable as-is.
- Each scored row fans out to two places: (a) the WebSocket broadcast set (all connected clients), (b) that station's **in-memory ring buffer** (last 500 readings, `collections.deque(maxlen=500)`) — no database. History resets on server restart; acceptable for local-dev MVP per the plan's own "avoid infra until proven necessary" philosophy (`Final_plan.md` Section 5).
- Dataset looping: when the StreamEngine reaches the end of the sorted dataset, it restarts from row 0 rather than stopping — keeps a long-running local demo alive indefinitely.

## Data flow

```
sensor_data.csv (loaded once at startup)
   -> sorted globally by timestamp
   -> StreamEngine loop (asyncio task)
        -> score_row() [reused from live_stream.py]
        -> broadcast to all WebSocket clients
        -> append to station's ring buffer (deque, maxlen=500)
REST endpoints read from: ring buffers, station metadata (loaded once), benchmark_results_v3.csv
```

## WebSocket protocol — `/ws/stream`

- On connect: server sends one `snapshot` message — every station's last-known reading + current severity, so a client joining mid-stream isn't blank.
- Then a `detection` message per scored row:
  ```json
  {
    "type": "detection",
    "station_id": "RESP-0007",
    "timestamp": "...",
    "readings": {"pm25": ..., "pm10": ..., "no2": ..., "co": ..., "temperature": ..., "humidity": ...},
    "flag": 0 | 1,
    "spatial_label": "" | "isolated_fault" | "regional_agreement",
    "detectors_fired": ["zscore", "flatline", "lof"]
  }
  ```
- Client → server control messages (affect the single shared stream for everyone, since there is one StreamEngine, not one per client):
  - `{"action": "set_speed", "value": <multiplier>}`
  - `{"action": "pause"}` / `{"action": "resume"}`
- A client that fails to receive (slow consumer / dead socket) is dropped from the broadcast set on write failure — must never block the StreamEngine loop.

## REST endpoints

- `GET /api/stations` — id, lat/lon, profile, current status. Backs the map's initial paint.
- `GET /api/stations/{id}/history` — last N readings from that station's ring buffer. Backs a station-detail sparkline/chart.
- `GET /api/benchmark` — the Phase 2 comparison table (raw + spatially-corrected, all 3 model families: Isolation Forest, LOF, STL-residual), read from `backend/benchmark_results_v3.csv`, plus a `winner: "lof"` field and a `why` string sourced from `Final_plan.md` Section 8's reasoning — so the dashboard and the plan doc never say different things about which model won.
- `GET /api/stream/status` — running/paused, current speed multiplier, rows processed since start, wall-clock started-at.

## Error handling

- Per-row exceptions inside the StreamEngine loop are caught and logged, not fatal — one bad row must not kill the simulation for every connected client.
- WebSocket send failures drop that client from the broadcast set; they do not raise into the loop.
- Missing-data rows (NaN feature values) are handled exactly as `live_stream.py` already does — skipped for scoring, latency still recorded.
- If `sensor_data.csv` (or the configured dataset path) is missing at startup, the app must fail fast with a clear error rather than start with an empty StreamEngine.

## Testing

No existing test suite in `backend/` to extend. Verification will be manual for this MVP: run `uvicorn`, connect a small WebSocket test client (or browser devtools) and `curl` the REST endpoints, and cross-check a short run's flag/precision numbers against `live_stream.py`'s standalone CLI output on the same input to confirm the refactor didn't change behavior.

## Out of scope (explicitly)

- Authentication — not required per direct instruction.
- Persistent database — in-memory only, by design (see Architecture).
- Deployment beyond localhost — local dev only, per direct instruction.
- The React dashboard itself — separate spec, sub-project 2.
