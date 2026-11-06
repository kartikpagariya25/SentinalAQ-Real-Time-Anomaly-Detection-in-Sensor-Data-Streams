# API reference

Start the service with `python -m app.cli serve` (default `http://127.0.0.1:8000`; add `--host 0.0.0.0` to accept remote devices). Interactive Swagger docs are at `/docs`.

## Conventions

- **Timestamps** are ISO 8601 strings. Naive times (`2026-09-16T09:00:00`) are used as given; times with an offset (`...Z`, `+05:30`) are converted to UTC. Readings are floored to the hour.
- **Errors:** malformed dates/timestamps return `400` with `{"detail": "..."}`; out-of-range or unknown query values (`limit`, `format`) return `422`; a missing or wrong API key returns `401`.
- **Auth (optional):** set `SENTINEL_API_KEY` before `serve`. `POST /ingest` and `POST /close-hour/{ts}` then require the header `X-API-Key: <key>`. Read endpoints stay open (the dashboard uses them).
- **CORS** is open to all origins so the dashboard can be hosted anywhere.

## Verdicts

| Verdict | Meaning |
|---|---|
| `VALID` | accepted. May still be a genuine pollution event (`detected_as = pollution_event`). |
| `INVALID` | rejected as a sensor fault; `detected_as` names the fault class. |
| `REVIEW` | the model cannot decide safely; a human or a second look is needed. |

Fault classes in `detected_as`: `spike`, `stuck`, `saturation`, `impossible_temp`, `th_fault`, `rh_fault`, `drift`, `dropout`. Valid classes: `normal`, `pollution_event`.
`source` is `rule` when a physics rule decided (confidence fixed at 0.99) and `model` otherwise.

## `POST /ingest`

Send a JSON array of readings. `pm25`, `temp` and `rh` may be `null`; a reading with any of the three missing is treated as a `dropout` by the rules.

```json
[{"timestamp": "2026-09-16T09:00:00", "device_id": "DEL-01", "city": "Delhi", "pm25": 3333, "temp": 31.2, "rh": 48}]
```

Response:

```json
{"received": 1, "duplicates": 0, "scored": 1, "late": 0}
```

- `duplicates`: readings whose `(device_id, hour)` is already stored. They are ignored, so resending a batch is safe.
- `late`: readings older than the newest one in the same batch. They are still scored and stored (backfilling is supported).
- An empty array returns `400`.

Verdicts are stored, not returned inline; read them back with `/readings` or `/readings/recent`.

## `POST /close-hour/{ts}`

Tells the service that hour `ts` is complete. Every device already known to the store that sent nothing for that hour is recorded as a `dropout`.

```json
{"dropouts_recorded": 3}
```

Call it after each hour's batch if you want dropouts detected.

## `GET /readings`

Stored readings for one day.

| Query | Default | Notes |
|---|---|---|
| `date` | required | any parseable date, e.g. `2026-09-16` |
| `device` | all | exact `device_id` |
| `verdict` | all | `valid`, `invalid` or `review` (case-insensitive) |
| `limit` | 200 | 1 to 5000 |

Each row: `timestamp, device_id, city, pm25, temp, rh, verdict, detected_as, confidence, p_invalid, source, reason, drivers`.

## `GET /readings/recent`

Newest readings by arrival order (this drives the live view). Query: `limit` (default 50, 1 to 5000), `verdict`.

## `GET /stats`

```json
{"total": 120000, "devices": 67, "last": "2026-09-30T23:00:00",
 "latest_window": {"valid": 480, "invalid": 12, "review": 8},
 "recent_anomalies": [ ... up to 20 non-VALID readings ... ],
 "by_hour": [{"hour": "09-30 22h", "VALID": 66, "REVIEW": 0, "INVALID": 1}]}
```

`latest_window` covers the 500 most recently arrived readings; `by_hour` the last 24 hours of stored data.

## Reports

### `GET /report/{date}`

One-day report. `format` = `json` (default), `csv` or `pdf`.

### `GET /report/range`

| Query | Default | Notes |
|---|---|---|
| `period` | `daily` | `daily`, `weekly` (Monday start), `monthly`, `yearly` |
| `date` | newest stored reading | any date inside the window you want |
| `format` | `json` | `json`, `csv`, `pdf` (csv/pdf are sent as attachments) |

JSON summary:

```json
{"period": "weekly", "start": "2026-09-28", "end": "2026-10-04",
 "readings": 11256, "valid": 11010, "invalid": 190, "review": 56,
 "pollution_events": 41, "mean_confidence": 0.987,
 "faults_by_type": {"stuck": 70, "spike": 12},
 "devices_reporting": 67,
 "by_device": [{"device": "DEL-03", "city": "Delhi", "invalid": 9, "review": 2, "total": 11, "top_fault": "stuck"}],
 "by_day": [{"day": "2026-09-28", "valid": 1600, "invalid": 20, "review": 8}]}
```

`end` is the last day included. `by_device` lists the 20 devices with the most flagged readings. An empty window returns zeros and empty lists, not an error.

## `GET /health`

```json
{"status": "ok", "model": "lightgbm_tuned", "stored_readings": 120000, "devices": 67, "auth": false,
 "first": "2023-10-01T00:00:00", "last": "2026-09-30T23:00:00"}
```

## Example client

`backend/examples/push_client.py` pushes a small batch, closes the hour and prints the day report.
