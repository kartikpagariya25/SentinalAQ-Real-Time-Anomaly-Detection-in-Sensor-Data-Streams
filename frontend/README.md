# SentinelAQ Frontend

Vite + React + TypeScript dashboard for the SentinelAQ live anomaly-detection system.

- **Stack:** Vite, React, TypeScript, Tailwind CSS, shadcn/ui, React Router, TanStack Query.
- **Design tokens:** see `design.md` for the full token reference (dark theme only, adapted from Grafana's production dark theme).
- **Routes:** `/live` (live stream), `/map` (station map), `/benchmark` (model benchmark).

## Quick start

Requires the backend running first (see root `README.md`).

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Routes: `/live`, `/map`, `/benchmark`.

## Testing

Pure-logic unit tests only (`npm test`) — severity mapping and the WebSocket
message reducer. Everything else is manually verified in a running browser
against the real backend (no automated UI/component test suite, by design).
