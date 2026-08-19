# SentinelAQ Dashboard — Design Spec

## Context and goals

Sub-project 2 (the React dashboard) consuming sub-project 1's backend API (merged to `main`: `GET /api/stations`, `GET /api/stations/{id}/history`, `GET /api/benchmark`, `GET /api/stream/status`, `WS /ws/stream`). Success criteria: a browser client shows (1) the live simulated detection stream updating in real time, (2) a station map colored by current severity, (3) the Phase 2 benchmark comparison with the model-selection rationale — all sharing one WebSocket connection, styled per `frontend/design.md`'s token system, no auth, local dev only.

## Stack

- **Vite** + React + TypeScript — SPA, no SSR/deployment need for a local ops dashboard (`Final_plan.md`'s "lightest tool that satisfies the requirement" philosophy).
- **React Router** — separate routes `/live`, `/map`, `/benchmark`, so a specific view is bookmarkable/shareable.
- **shadcn/ui + Tailwind** — component primitives, styled per `design.md`'s tokens.
- **Recharts** — station sparklines, any time-series charts.
- **MapLibre GL** — the station map (no API key needed, free).
- **TanStack Query** — REST data fetching (`/api/stations`, `/api/stations/{id}/history`, `/api/benchmark`) with built-in caching/retry.
- **A single WebSocket Context** (not a state library) — `WebSocketProvider` owns the one `/ws/stream` connection; `useLiveStream()` hook exposes it to all three routes. State shape is simple enough (per-station latest reading + a capped event log) that Zustand/Redux would be unjustified weight.

## Architecture

- `WebSocketProvider` wraps the app root, opens `/ws/stream` on mount, reconnects with backoff on drop, and exposes: `{ stations: Record<string, LatestReading>, events: DetectionEvent[], status: "connected"|"disconnected"|"reconnecting", setSpeed(n), pause(), resume() }`.
- On receiving the initial `snapshot` message, all 50 stations are seeded into `stations` (guaranteed non-empty per every station, now that the backend pre-populates history — see below). Each subsequent `detection` message updates that station's entry in place and prepends to a capped (~200) `events` array for the live feed.
- `/live`, `/map`, `/benchmark` are independent route components; only `/live` and `/map` read from `useLiveStream()`. `/benchmark` reads only from TanStack Query (`GET /api/benchmark`), no live component needed there.

## Component breakdown (implements `frontend/design.md`'s Core Components section)

- **`LiveBadge`** — pulsing dot in `color.status.normal` while connected; falls back to `color.text.disabled` + "DISCONNECTED" text when `status !== "connected"`. Never animation-only (accessibility rule — respects `prefers-reduced-motion`).
- **`SeverityTag`** — the single place `color.status.*` tokens are consumed. One mapping function: `flag=0 & spatial_label=""` → `normal`; `flag=1 & spatial_label="isolated_fault"` → `fault`; `flag=0 & spatial_label="regional_agreement"` → `event` (never `fault` — this is `design.md`'s explicit anti-pattern rule, enforced in exactly one place so every consumer inherits it for free); no history yet → `unknown`. Every other component (station cards, map markers, feed rows) renders severity through this component, never by picking a color directly.
- **`StatTile`** — `/live`'s top row: `rows_processed`, current speed multiplier, active fault count, active event count (all derived from `useLiveStream()`'s `stations`/`events`).
- **`StationCard`** — per-station latest reading + Recharts sparkline (fed by `GET /api/stations/{id}/history`) + `SeverityTag`; expands to show `detectors_fired` and the spatial-correction verdict straight from the WebSocket message.
- **`MapMarker`** (MapLibre) — colored AND sized by `SeverityTag`'s severity (never color-only, per `design.md`'s accessibility rule); clicking opens a `StationCard` popover — the same component, not a second implementation.
- **`BenchmarkTable`** — `/benchmark`'s table; winning row gets the `color.status.normal` left-border accent `design.md` specifies; `winner`/`why` fields render verbatim from the backend response so the UI can never claim a different model than `Final_plan.md` does.

## Data flow

```
WebSocketProvider mounts
  -> WS /ws/stream: snapshot (seeds all 50 stations, now guaranteed non-empty)
  -> WS /ws/stream: detection... (updates stations[sid], prepends to events)

/live, /map  <- useLiveStream() (shared context, one socket)
/map         <- GET /api/stations (TanStack Query, static lat/lon for pins)
/benchmark   <- GET /api/benchmark (TanStack Query, table + winner + why)
StationCard  <- GET /api/stations/{id}/history (TanStack Query, on-demand when a card expands)
```

## Error handling

- WebSocket disconnect: `LiveBadge` reflects it immediately; `WebSocketProvider` retries with exponential backoff; `/map`'s markers freeze at last-known severity rather than disappearing.
- REST failures: TanStack Query's built-in retry/error state; a failed `/api/benchmark` fetch shows a retry affordance, not a blank page.
- A station with no processed rows yet renders `SeverityTag`'s `unknown` state (backend now returns `[]`/`"unknown"` status instead of 404, per the backend's final-review fix) — never a broken/error card.

## Testing

No dataset to fake for a UI — verification is manual, per the "test in a browser" requirement for frontend work: `npm run dev` against the real running backend (`uvicorn api.main:create_app --factory --reload --app-dir backend`), checking the golden path (live feed updating, map coloring correctly and matching feed severity, benchmark table matching the backend's JSON exactly) and the disconnect/reconnect edge case (kill the backend mid-session, confirm `LiveBadge` and stale-marker behavior).

## Out of scope

- Authentication — not required per direct instruction.
- Any backend changes — this spec only consumes the already-merged API.
- Deployment beyond `npm run dev` — local dev only, per direct instruction.
- Automated UI test suite — manual browser verification only, per spec's Testing section above.
