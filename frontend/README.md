# SentinelAQ dashboard

React 18 + Vite + Tailwind + Recharts. It only renders what the API returns; all detection logic is in the backend.

## Run

Easiest: `.\run.ps1` from the repo root (builds and serves it with the API and a demo feed).

Manually:

```powershell
cd frontend
npm install
copy .env.example .env      # set VITE_API_URL if the API is not on 127.0.0.1:8000
npm run dev                 # http://127.0.0.1:5173 with hot reload
npm run build ; npm run preview   # production build, same port
```

Port 5173 is fixed (`strictPort`); if it is busy the command fails instead of picking another port, so the URL printed by the scripts is always right.

`VITE_API_URL` is read at build time. Rebuild after changing it (`dashboard.ps1 -Rebuild`).

## Tabs

| Tab | Source | Notes |
|---|---|---|
| Live stream | `GET /stats` every 2 s, `GET /readings/recent` | KPIs, verdicts per hour, anomaly feed, console. Shows an "API not reachable" banner after 4 failed polls. |
| Reports | `GET /report/range` | daily/weekly/monthly/yearly, CSV and PDF download links |
| Dataset, Team, Respirer, About | static | describe the data, people and project |

## Code map

| File | Role |
|---|---|
| `src/api.js` | `fetch` wrapper with an 8 s timeout; one function per endpoint |
| `src/App.jsx` | layout, navigation, `/health` ping every 10 s |
| `src/components/LiveView.jsx`, `LogConsole.jsx` | live tab |
| `src/components/ReportsView.jsx` | reports tab |
| `src/components/Shared.jsx` | cards, KPIs, verdict colours |
| `src/components/ErrorBoundary.jsx` | keeps one broken tab from blanking the app |

`dashboard.py` is a separate, older Streamlit explorer (`streamlit run frontend/dashboard.py`) that simulates a stream directly from the model without the API.
