# SentinelAQ Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React dashboard (sub-project 2) that consumes the already-merged SentinelAQ backend API — live detection stream, station map, benchmark comparison — styled per `frontend/design.md`.

**Architecture:** Vite + React + TypeScript SPA. A single `WebSocketProvider` owns the one `/ws/stream` connection and exposes `useLiveStream()` to every route. TanStack Query handles REST (`/api/stations`, `/api/stations/{id}/history`, `/api/benchmark`). React Router serves three routes: `/live`, `/map`, `/benchmark`.

**Tech Stack:** Vite, React, TypeScript, Tailwind CSS, shadcn/ui, React Router, TanStack Query, Recharts, MapLibre GL, Vitest (for pure-logic unit tests only — no automated UI/component test suite, per spec).

**Spec:** `docs/superpowers/specs/2026-08-19-sentinelaq-dashboard-design.md`

## Global Constraints

- No authentication anywhere in this app.
- No backend changes in this plan — only consumes the already-merged API.
- Local dev only (`npm run dev`) — no deployment config.
- `SeverityTag`'s mapping function is the ONLY place `color.status.*` tokens get consumed; every other component renders severity through it. It must map `flag=0 & spatial_label=""` → `normal`; `flag=1 & spatial_label="isolated_fault"` → `fault`; `flag=0 & spatial_label="regional_agreement"` → `event`; no history → `unknown`. **Never** map `event` to the same color as `fault` — this is the project's core anti-pattern.
- One shared WebSocket connection for the whole app (not one per route/component).
- No automated UI/component test suite (spec's explicit Out of Scope) — verify each task's UI manually in a running browser against the real backend. Pure, non-UI logic (severity mapping, the WS message reducer) DOES get Vitest unit tests, since that's where the project's core correctness rule lives.

---

## File Structure

```
frontend/
  package.json, vite.config.ts, tsconfig.json, tailwind.config.ts, index.html
  src/
    main.tsx                    - app entry, router + providers
    App.tsx                     - route definitions + nav shell
    types.ts                    - shared TS types
    lib/
      severity.ts               - pure severity-mapping function (Global Constraint)
      queryClient.ts            - TanStack Query client + fetch wrappers
    context/
      WebSocketProvider.tsx     - WS connection, useLiveStream() hook, message reducer
    components/
      LiveBadge.tsx
      SeverityTag.tsx
      StatTile.tsx
      StationCard.tsx
      MapMarker.tsx
      BenchmarkTable.tsx
    routes/
      LiveView.tsx               - /live
      MapView.tsx                 - /map
      BenchmarkView.tsx           - /benchmark
  tests/
    severity.test.ts
    wsReducer.test.ts
```

---

### Task 1: Scaffold — Vite + Tailwind + shadcn/ui + router shell

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`

**Interfaces:**
- Produces: a running Vite dev server with React Router mounted, 3 empty placeholder routes (`/live`, `/map`, `/benchmark`) and a nav bar linking them. Tailwind configured with `design.md`'s tokens as CSS variables (dark theme, no light-mode toggle needed — this is a single-theme ops tool).

- [ ] **Step 1: Scaffold the Vite project**

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npm install react-router-dom @tanstack/react-query
npx shadcn@latest init -d
npx shadcn@latest add card badge table
```

- [ ] **Step 2: Wire `design.md`'s tokens into `tailwind.config.ts`**

```ts
// frontend/tailwind.config.ts
import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#111217",
        surface: { base: "#181b1f", raised: "#22252b" },
        text: {
          primary: "rgb(204,204,220)",
          secondary: "rgba(204,204,220,0.65)",
          disabled: "rgba(204,204,220,0.61)",
          maxContrast: "#ffffff",
        },
        border: {
          weak: "rgba(204,204,220,0.12)",
          DEFAULT: "rgba(204,204,220,0.2)",
          strong: "rgba(204,204,220,0.30)",
        },
        status: {
          normal: "#1a7f4b",
          normalText: "#6ccf8e",
          fault: "#d10e5c",
          faultText: "#ff5286",
          drift: "#ff9900",
          driftText: "#fbad37",
          event: "#3d71d9",
          eventText: "#6e9fff",
        },
      },
      fontFamily: {
        sans: ["Inter", "Helvetica", "Arial", "sans-serif"],
        mono: ["Roboto Mono", "monospace"],
      },
      borderRadius: { sm: "4px", md: "6px", lg: "10px", pill: "9999px" },
    },
  },
  plugins: [],
} satisfies Config;
```

```css
/* frontend/src/index.css - append */
html { @apply dark; }
body { @apply bg-canvas text-text-primary font-sans; }
```

- [ ] **Step 3: Write the router shell**

```tsx
// frontend/src/App.tsx
import { Routes, Route, NavLink } from "react-router-dom";
import LiveView from "./routes/LiveView";
import MapView from "./routes/MapView";
import BenchmarkView from "./routes/BenchmarkView";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 rounded-md text-sm ${isActive ? "bg-surface-raised text-text-maxContrast" : "text-text-secondary hover:text-text-primary"}`;

export default function App() {
  return (
    <div className="min-h-screen bg-canvas">
      <nav className="flex gap-2 border-b border-border bg-surface-base px-6 py-3">
        <span className="text-text-maxContrast font-semibold mr-4">SentinelAQ</span>
        <NavLink to="/live" className={navClass}>Live Stream</NavLink>
        <NavLink to="/map" className={navClass}>Map</NavLink>
        <NavLink to="/benchmark" className={navClass}>Benchmark</NavLink>
      </nav>
      <main className="p-6">
        <Routes>
          <Route path="/live" element={<LiveView />} />
          <Route path="/map" element={<MapView />} />
          <Route path="/benchmark" element={<BenchmarkView />} />
          <Route path="*" element={<LiveView />} />
        </Routes>
      </main>
    </div>
  );
}
```

```tsx
// frontend/src/main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
);
```

Create placeholder `frontend/src/routes/LiveView.tsx`, `MapView.tsx`, `BenchmarkView.tsx`, each just `export default function X() { return <div className="text-text-secondary">X — coming soon</div>; }` for now (later tasks fill these in).

- [ ] **Step 4: Verify in browser**

Run: `cd frontend && npm run dev`
Expected: dev server starts, opening `http://localhost:5173` shows the dark nav bar and three clickable links, each rendering its placeholder text with no console errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold Vite dashboard with design.md tokens and router shell"
```

---

### Task 2: Shared types + severity mapping (pure logic, unit tested)

**Files:**
- Create: `frontend/src/types.ts`, `frontend/src/lib/severity.ts`
- Test: `frontend/tests/severity.test.ts`

**Interfaces:**
- Produces: `type Severity = "normal" | "fault" | "drift" | "event" | "unknown"`, `function getSeverity(entry: { flag: 0 | 1; spatial_label: string } | null): Severity`. This is THE function every later component calls for color — no other file picks a `color.status.*` token directly.

- [ ] **Step 1: Install Vitest**

```bash
cd frontend
npm install -D vitest
```

Add to `frontend/package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 2: Write the failing test**

```ts
// frontend/tests/severity.test.ts
import { describe, it, expect } from "vitest";
import { getSeverity } from "../src/lib/severity";

describe("getSeverity", () => {
  it("returns unknown for no data yet", () => {
    expect(getSeverity(null)).toBe("unknown");
  });
  it("returns normal for an unflagged reading", () => {
    expect(getSeverity({ flag: 0, spatial_label: "" })).toBe("normal");
  });
  it("returns fault for an isolated flagged reading", () => {
    expect(getSeverity({ flag: 1, spatial_label: "isolated_fault" })).toBe("fault");
  });
  it("returns event (never fault) for a spatially-corrected regional agreement", () => {
    expect(getSeverity({ flag: 0, spatial_label: "regional_agreement" })).toBe("event");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module '../src/lib/severity'`

- [ ] **Step 4: Write types and the severity function**

```ts
// frontend/src/types.ts
export interface Reading {
  pm25: number; pm10: number; no2: number; co: number;
  temperature: number; humidity: number;
}

export interface DetectionEvent {
  type: "detection";
  station_id: string;
  timestamp: string;
  readings: Reading | null;
  flag: 0 | 1;
  spatial_label: "" | "isolated_fault" | "regional_agreement";
  detectors_fired: string[];
}

export interface StationMeta {
  station_id: string;
  latitude: number;
  longitude: number;
  status: "normal" | "fault" | "unknown";
}

export interface BenchmarkRow {
  method: string;
  precision: number;
  recall: number;
  f1: number;
  env_event_fp_rate: number | null;
}

export interface BenchmarkResponse {
  table: BenchmarkRow[];
  winner: string;
  why: string;
}
```

```ts
// frontend/src/lib/severity.ts
export type Severity = "normal" | "fault" | "drift" | "event" | "unknown";

export function getSeverity(
  entry: { flag: 0 | 1; spatial_label: string } | null
): Severity {
  if (!entry) return "unknown";
  if (entry.spatial_label === "regional_agreement") return "event";
  if (entry.flag === 1) return "fault";
  return "normal";
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/lib/severity.ts frontend/tests/severity.test.ts frontend/package.json
git commit -m "feat: add shared types and the single severity-mapping function"
```

---

### Task 3: WebSocketProvider + useLiveStream (pure reducer, unit tested)

**Files:**
- Create: `frontend/src/context/WebSocketProvider.tsx`
- Test: `frontend/tests/wsReducer.test.ts`

**Interfaces:**
- Consumes: `DetectionEvent`, `Reading` types (Task 2).
- Produces: `function useLiveStream(): { stations: Record<string, DetectionEvent | null>; events: DetectionEvent[]; status: "connected"|"disconnected"|"reconnecting"; setSpeed(n: number): void; pause(): void; resume(): void }`, exported `WebSocketProvider` component, and an exported pure `applyMessage(state, message)` reducer function used internally AND unit-tested directly.

- [ ] **Step 1: Write the failing test for the pure reducer**

```ts
// frontend/tests/wsReducer.test.ts
import { describe, it, expect } from "vitest";
import { applyMessage, initialStreamState } from "../src/context/WebSocketProvider";

describe("applyMessage", () => {
  it("snapshot seeds all stations", () => {
    const state = applyMessage(initialStreamState, {
      type: "snapshot",
      stations: { "RESP-0001": null, "RESP-0002": { flag: 0, spatial_label: "" } as any },
    });
    expect(Object.keys(state.stations)).toEqual(["RESP-0001", "RESP-0002"]);
  });

  it("detection updates that station and prepends to events", () => {
    const detection = { type: "detection", station_id: "RESP-0001", flag: 1, spatial_label: "isolated_fault" } as any;
    const state = applyMessage(initialStreamState, detection);
    expect(state.stations["RESP-0001"]).toEqual(detection);
    expect(state.events[0]).toEqual(detection);
  });

  it("caps events at 200", () => {
    let state = initialStreamState;
    for (let i = 0; i < 250; i++) {
      state = applyMessage(state, { type: "detection", station_id: "X", flag: 0, spatial_label: "", timestamp: String(i) } as any);
    }
    expect(state.events.length).toBe(200);
    expect(state.events[0].timestamp).toBe("249");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module '../src/context/WebSocketProvider'`

- [ ] **Step 3: Write the provider, hook, and reducer**

```tsx
// frontend/src/context/WebSocketProvider.tsx
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { DetectionEvent } from "../types";

const EVENTS_CAP = 200;

export interface StreamState {
  stations: Record<string, DetectionEvent | null>;
  events: DetectionEvent[];
}

export const initialStreamState: StreamState = { stations: {}, events: [] };

type IncomingMessage =
  | { type: "snapshot"; stations: Record<string, DetectionEvent | null> }
  | (DetectionEvent & { type: "detection" });

export function applyMessage(state: StreamState, msg: IncomingMessage): StreamState {
  if (msg.type === "snapshot") {
    return { ...state, stations: { ...msg.stations } };
  }
  const events = [msg, ...state.events];
  if (events.length > EVENTS_CAP) events.length = EVENTS_CAP;
  return {
    stations: { ...state.stations, [msg.station_id]: msg },
    events,
  };
}

type Status = "connected" | "disconnected" | "reconnecting";

interface LiveStreamContextValue extends StreamState {
  status: Status;
  setSpeed: (value: number) => void;
  pause: () => void;
  resume: () => void;
}

const LiveStreamContext = createContext<LiveStreamContextValue | null>(null);

const WS_URL = "ws://127.0.0.1:8000/ws/stream";

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StreamState>(initialStreamState);
  const [status, setStatus] = useState<Status>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retryDelay = 1000;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => { setStatus("connected"); retryDelay = 1000; };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as IncomingMessage;
        setState((s) => applyMessage(s, msg));
      };
      ws.onclose = () => {
        if (cancelled) return;
        setStatus("reconnecting");
        setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
      ws.onerror = () => ws.close();
    }
    connect();
    return () => { cancelled = true; wsRef.current?.close(); };
  }, []);

  function send(action: Record<string, unknown>) {
    wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send(JSON.stringify(action));
  }

  const value: LiveStreamContextValue = {
    ...state,
    status,
    setSpeed: (value) => send({ action: "set_speed", value }),
    pause: () => send({ action: "pause" }),
    resume: () => send({ action: "resume" }),
  };

  return <LiveStreamContext.Provider value={value}>{children}</LiveStreamContext.Provider>;
}

export function useLiveStream(): LiveStreamContextValue {
  const ctx = useContext(LiveStreamContext);
  if (!ctx) throw new Error("useLiveStream must be used within WebSocketProvider");
  return ctx;
}
```

Wrap `App` with `WebSocketProvider` in `main.tsx` (inside `BrowserRouter`, around `<App />`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/context/WebSocketProvider.tsx frontend/src/main.tsx frontend/tests/wsReducer.test.ts
git commit -m "feat: add WebSocketProvider with reconnect and tested message reducer"
```

---

### Task 4: TanStack Query client + REST hooks

**Files:**
- Create: `frontend/src/lib/queryClient.ts`

**Interfaces:**
- Consumes: `StationMeta`, `BenchmarkResponse`, `Reading` types (Task 2).
- Produces: `queryClient` (TanStack Query client instance), `useStations()`, `useStationHistory(stationId: string)`, `useBenchmark()` hooks.

- [ ] **Step 1: Write the query client and hooks**

```ts
// frontend/src/lib/queryClient.ts
import { QueryClient, useQuery } from "@tanstack/react-query";
import type { StationMeta, BenchmarkResponse, DetectionEvent } from "../types";

export const queryClient = new QueryClient();

const API_BASE = "http://127.0.0.1:8000";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

export function useStations() {
  return useQuery({
    queryKey: ["stations"],
    queryFn: () => fetchJson<StationMeta[]>("/api/stations"),
  });
}

export function useStationHistory(stationId: string) {
  return useQuery({
    queryKey: ["station-history", stationId],
    queryFn: () => fetchJson<DetectionEvent[]>(`/api/stations/${stationId}/history`),
    enabled: !!stationId,
  });
}

export function useBenchmark() {
  return useQuery({
    queryKey: ["benchmark"],
    queryFn: () => fetchJson<BenchmarkResponse>("/api/benchmark"),
  });
}
```

Wrap `App` with `QueryClientProvider` in `main.tsx` (import `QueryClientProvider` from `@tanstack/react-query` and `queryClient` from this file — place it as the outermost provider, around `WebSocketProvider`).

- [ ] **Step 2: Verify in browser**

Run: `cd frontend && npm run dev`, with the backend running (`cd backend && uvicorn api.main:create_app --factory --reload`). Temporarily add `const { data } = useStations(); console.log(data);` to `LiveView.tsx` and confirm the browser console logs the real 50-station array with no errors. Remove the temporary line after confirming.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/queryClient.ts frontend/src/main.tsx
git commit -m "feat: add TanStack Query client and REST hooks for stations/history/benchmark"
```

---

### Task 5: LiveView — LiveBadge, StatTile, SeverityTag, live feed

**Files:**
- Create: `frontend/src/components/LiveBadge.tsx`, `frontend/src/components/SeverityTag.tsx`, `frontend/src/components/StatTile.tsx`
- Modify: `frontend/src/routes/LiveView.tsx`

**Interfaces:**
- Consumes: `useLiveStream()` (Task 3), `getSeverity()` (Task 2).
- Produces: `<LiveBadge status={...} />`, `<SeverityTag severity={...} />`, `<StatTile label={...} value={...} />` — all three used by later tasks (`MapMarker`, `StationCard`, `BenchmarkTable` all import `SeverityTag`).

- [ ] **Step 1: Write the components**

```tsx
// frontend/src/components/SeverityTag.tsx
import { Badge } from "@/components/ui/badge";
import type { Severity } from "../lib/severity";

const STYLES: Record<Severity, string> = {
  normal: "bg-status-normal/20 text-status-normalText border-transparent",
  fault: "bg-status-fault/20 text-status-faultText border-transparent",
  drift: "bg-status-drift/20 text-status-driftText border-transparent",
  event: "bg-status-event/20 text-status-eventText border-transparent",
  unknown: "bg-border text-text-disabled border-transparent",
};

const LABELS: Record<Severity, string> = {
  normal: "Normal", fault: "Fault", drift: "Drift", event: "Regional Event", unknown: "Unknown",
};

export default function SeverityTag({ severity }: { severity: Severity }) {
  return (
    <Badge className={`rounded-pill font-medium ${STYLES[severity]}`}>
      {LABELS[severity]}
    </Badge>
  );
}
```

Uses shadcn's `Badge` primitive (installed in Task 1) restyled with `design.md`'s tokens via `className` override, rather than shadcn's default badge color variants — matches the stack decision (shadcn/ui components you fully own and restyle) without inventing a parallel styling system.

```tsx
// frontend/src/components/LiveBadge.tsx
export default function LiveBadge({ status }: { status: "connected" | "disconnected" | "reconnecting" }) {
  if (status === "connected") {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-status-normalText">
        <span className="h-2 w-2 rounded-pill bg-status-normal motion-safe:animate-pulse" />
        LIVE
      </span>
    );
  }
  return <span className="text-sm text-text-disabled">DISCONNECTED</span>;
}
```

```tsx
// frontend/src/components/StatTile.tsx
import { Card, CardContent } from "@/components/ui/card";

export default function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="bg-surface-raised border-border-weak">
      <CardContent className="px-4 py-3">
        <div className="text-2xl font-semibold text-text-maxContrast">{value}</div>
        <div className="text-xs text-text-secondary">{label}</div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Wire into `LiveView`**

```tsx
// frontend/src/routes/LiveView.tsx
import { useLiveStream } from "../context/WebSocketProvider";
import { getSeverity } from "../lib/severity";
import LiveBadge from "../components/LiveBadge";
import StatTile from "../components/StatTile";
import SeverityTag from "../components/SeverityTag";

export default function LiveView() {
  const { stations, events, status } = useLiveStream();
  const faultCount = Object.values(stations).filter((s) => getSeverity(s) === "fault").length;
  const eventCount = Object.values(stations).filter((s) => getSeverity(s) === "event").length;

  return (
    <div className="space-y-6">
      <LiveBadge status={status} />
      <div className="grid grid-cols-4 gap-4">
        <StatTile label="Stations Seen" value={Object.keys(stations).length} />
        <StatTile label="Events Received" value={events.length} />
        <StatTile label="Active Faults" value={faultCount} />
        <StatTile label="Active Regional Events" value={eventCount} />
      </div>
      <div className="rounded-md border border-border-weak divide-y divide-border-weak">
        {events.slice(0, 20).map((e, i) => (
          <div key={i} className="flex items-center justify-between px-4 py-2 text-sm">
            <span className="text-text-primary">{e.station_id}</span>
            <span className="text-text-secondary">{e.timestamp}</span>
            <SeverityTag severity={getSeverity(e)} />
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify in browser**

Run backend + `npm run dev`, open `/live`. Expected: `LIVE` badge, 4 stat tiles with real numbers, and a feed list that visibly updates every few seconds as new detections stream in, each row showing a correctly-colored `SeverityTag`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/LiveBadge.tsx frontend/src/components/SeverityTag.tsx frontend/src/components/StatTile.tsx frontend/src/routes/LiveView.tsx
git commit -m "feat: build LiveView with badge, stat tiles, and live detection feed"
```

---

### Task 6: StationCard with Recharts sparkline

**Files:**
- Create: `frontend/src/components/StationCard.tsx`
- Modify: `frontend/src/routes/LiveView.tsx`

**Interfaces:**
- Consumes: `useStationHistory()` (Task 4), `SeverityTag`/`getSeverity` (Tasks 2/5).
- Produces: `<StationCard stationId={...} latest={...} />` — reused as-is by Task 7's map popover.

- [ ] **Step 1: Install Recharts**

```bash
cd frontend && npm install recharts
```

- [ ] **Step 2: Write `StationCard`**

```tsx
// frontend/src/components/StationCard.tsx
import { useState } from "react";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import { useStationHistory } from "../lib/queryClient";
import { getSeverity } from "../lib/severity";
import SeverityTag from "./SeverityTag";
import type { DetectionEvent } from "../types";

export default function StationCard({ stationId, latest }: { stationId: string; latest: DetectionEvent | null }) {
  const [expanded, setExpanded] = useState(false);
  const { data: history } = useStationHistory(stationId);
  const severity = getSeverity(latest);
  const sparkData = (history ?? []).filter((h) => h.readings).map((h) => ({ pm25: h.readings!.pm25 }));

  return (
    <Card className="bg-surface-raised border-border-weak">
      <CardContent className="p-3">
        <div className="flex items-center justify-between cursor-pointer" onClick={() => setExpanded((e) => !e)}>
          <span className="text-sm text-text-primary">{stationId}</span>
          <SeverityTag severity={severity} />
        </div>
        {sparkData.length > 1 && (
          <div className="h-10 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparkData}>
                <Line type="monotone" dataKey="pm25" stroke="#6e9fff" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {expanded && (
          <div className="mt-2 text-xs text-text-secondary space-y-1">
            <div>Detectors fired: {latest?.detectors_fired?.join(", ") || "none"}</div>
            <div>Spatial verdict: {latest?.spatial_label || "n/a"}</div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: Add a station grid to `LiveView`**

Add below the feed list in `LiveView.tsx`:

```tsx
import StationCard from "../components/StationCard";
// ...
<div className="grid grid-cols-4 gap-3">
  {Object.entries(stations).map(([sid, latest]) => (
    <StationCard key={sid} stationId={sid} latest={latest} />
  ))}
</div>
```

- [ ] **Step 4: Verify in browser**

With both servers running, `/live` should now show a grid of station cards below the feed, each with a `SeverityTag`, a sparkline once ≥2 history points exist, and expandable detector/spatial-verdict detail on click.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StationCard.tsx frontend/src/routes/LiveView.tsx frontend/package.json
git commit -m "feat: add StationCard with Recharts sparkline and expandable detail"
```

---

### Task 7: MapView — MapLibre + MapMarker

**Files:**
- Create: `frontend/src/components/MapMarker.tsx`
- Modify: `frontend/src/routes/MapView.tsx`

**Interfaces:**
- Consumes: `useStations()` (Task 4), `useLiveStream()` (Task 3), `getSeverity`/`SeverityTag` (Tasks 2/5), `StationCard` (Task 6, reused for the popover).
- Produces: a working map at `/map`.

- [ ] **Step 1: Install MapLibre**

```bash
cd frontend && npm install maplibre-gl react-map-gl
```

- [ ] **Step 2: Write `MapView`**

```tsx
// frontend/src/routes/MapView.tsx
import { useState } from "react";
import Map, { Marker, Popup } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { useStations } from "../lib/queryClient";
import { useLiveStream } from "../context/WebSocketProvider";
import { getSeverity } from "../lib/severity";
import StationCard from "../components/StationCard";

const SEVERITY_COLOR: Record<string, string> = {
  normal: "#1a7f4b", fault: "#d10e5c", drift: "#ff9900", event: "#3d71d9", unknown: "#383b42",
};
const SEVERITY_SIZE: Record<string, number> = {
  normal: 8, fault: 14, drift: 12, event: 12, unknown: 6,
};

export default function MapView() {
  const { data: stationsMeta } = useStations();
  const { stations: liveStations } = useLiveStream();
  const [selected, setSelected] = useState<string | null>(null);

  if (!stationsMeta) return <div className="text-text-secondary">Loading stations...</div>;

  return (
    <div className="h-[70vh] rounded-md overflow-hidden border border-border-weak">
      <Map
        initialViewState={{ longitude: 78, latitude: 22, zoom: 3.5 }}
        mapStyle="https://demotiles.maplibre.org/style.json"
      >
        {stationsMeta.map((s) => {
          const severity = getSeverity(liveStations[s.station_id]);
          return (
            <Marker
              key={s.station_id}
              longitude={s.longitude}
              latitude={s.latitude}
              onClick={(e) => { e.originalEvent.stopPropagation(); setSelected(s.station_id); }}
            >
              <div
                className="rounded-pill border border-surface-base cursor-pointer"
                style={{
                  backgroundColor: SEVERITY_COLOR[severity],
                  width: SEVERITY_SIZE[severity],
                  height: SEVERITY_SIZE[severity],
                }}
              />
            </Marker>
          );
        })}
        {selected && (() => {
          const s = stationsMeta.find((x) => x.station_id === selected)!;
          return (
            <Popup longitude={s.longitude} latitude={s.latitude} onClose={() => setSelected(null)} closeButton>
              <StationCard stationId={s.station_id} latest={liveStations[s.station_id]} />
            </Popup>
          );
        })()}
      </Map>
    </div>
  );
}
```

`MapMarker.tsx` as a separate file was in the original component list; the inline `<div>` above IS the marker's visual — extract it to `frontend/src/components/MapMarker.tsx` as a small presentational component (`{ severity }: { severity: Severity }`) and import it into `MapView` in place of the inline div, so `MapMarker` exists as its own reusable file matching `design.md`'s component list.

- [ ] **Step 3: Verify in browser**

`/map` should render a world/India-region map with ~50 colored dots (mostly green/`normal`, some larger red/`fault` or blue/`event` dots as detections stream in), and clicking a dot opens a popover showing that station's `StationCard`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MapMarker.tsx frontend/src/routes/MapView.tsx frontend/package.json
git commit -m "feat: add MapView with MapLibre markers colored by severity"
```

---

### Task 8: BenchmarkView — BenchmarkTable

**Files:**
- Create: `frontend/src/components/BenchmarkTable.tsx`
- Modify: `frontend/src/routes/BenchmarkView.tsx`

**Interfaces:**
- Consumes: `useBenchmark()` (Task 4).
- Produces: the `/benchmark` route fully implemented.

- [ ] **Step 1: Write `BenchmarkTable`**

```tsx
// frontend/src/components/BenchmarkTable.tsx
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import type { BenchmarkRow } from "../types";

export default function BenchmarkTable({ rows, winner }: { rows: BenchmarkRow[]; winner: string }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="border-border-weak">
          <TableHead className="text-text-secondary">Method</TableHead>
          <TableHead className="text-text-secondary">Precision</TableHead>
          <TableHead className="text-text-secondary">Recall</TableHead>
          <TableHead className="text-text-secondary">F1</TableHead>
          <TableHead className="text-text-secondary">Env-Event FP Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow
            key={r.method}
            className={`border-border-weak ${r.method === winner ? "border-l-4 border-l-status-normal" : ""}`}
          >
            <TableCell className="text-text-primary">{r.method}</TableCell>
            <TableCell className="text-text-secondary">{r.precision.toFixed(2)}</TableCell>
            <TableCell className="text-text-secondary">{r.recall.toFixed(2)}</TableCell>
            <TableCell className="text-text-secondary">{r.f1.toFixed(2)}</TableCell>
            <TableCell className="text-text-secondary">{r.env_event_fp_rate === null ? "n/a" : r.env_event_fp_rate.toFixed(2)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 2: Wire into `BenchmarkView`**

```tsx
// frontend/src/routes/BenchmarkView.tsx
import { useBenchmark } from "../lib/queryClient";
import BenchmarkTable from "../components/BenchmarkTable";

export default function BenchmarkView() {
  const { data, isLoading, isError } = useBenchmark();

  if (isLoading) return <div className="text-text-secondary">Loading benchmark...</div>;
  if (isError || !data) return <div className="text-status-faultText">Failed to load benchmark data.</div>;

  return (
    <div className="space-y-4">
      <div className="rounded-md bg-surface-raised border border-border-weak p-4">
        <div className="text-text-maxContrast font-semibold mb-1">Winner: {data.winner}</div>
        <div className="text-sm text-text-secondary">{data.why}</div>
      </div>
      <BenchmarkTable rows={data.table} winner={data.winner} />
    </div>
  );
}
```

- [ ] **Step 3: Verify in browser**

`/benchmark` should show the winner callout with the WHY text, and the full comparison table with the `lof` row's left border highlighted, matching exactly what `Final_plan.md` Section 8 states.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BenchmarkTable.tsx frontend/src/routes/BenchmarkView.tsx
git commit -m "feat: add BenchmarkView with model comparison table and winner callout"
```

---

### Task 9: Polish — README, full manual smoke test

**Files:**
- Create: `frontend/README.md`
- Modify: `README.md:1` (root quick-start)

**Interfaces:**
- None (wrap-up task).

- [ ] **Step 1: Write `frontend/README.md`**

```markdown
# SentinelAQ Dashboard

React/Vite dashboard for the SentinelAQ backend API.

## Quick start

Requires the backend running first (see root README.md).

\`\`\`
cd frontend
npm install
npm run dev
\`\`\`

Open http://localhost:5173. Routes: /live, /map, /benchmark.

## Testing

Pure-logic unit tests only (`npm test`) — severity mapping and the WebSocket
message reducer. Everything else is manually verified in a running browser
against the real backend (no automated UI/component test suite, by design).
```

- [ ] **Step 2: Update root `README.md`**

Add a "Frontend quick start" section after the existing "Backend quick start" block:

```markdown
## Frontend quick start
\`\`\`
cd frontend
npm install
npm run dev
\`\`\`
Open http://localhost:5173 (requires the backend running — see above).
```

- [ ] **Step 3: Full manual smoke test**

With backend (`cd backend && uvicorn api.main:create_app --factory --reload`) and frontend (`cd frontend && npm run dev`) both running: visit `/live` and confirm the feed updates and station cards populate over ~30 seconds; visit `/map` and confirm colored markers matching `/live`'s severities; visit `/benchmark` and confirm the table matches the backend's real `/api/benchmark` response; kill the backend process and confirm `LiveBadge` shows `DISCONNECTED` within a few seconds, then restart the backend and confirm it reconnects automatically.

- [ ] **Step 4: Run the unit test suite one final time**

Run: `cd frontend && npm test`
Expected: PASS (7 tests total — 4 severity + 3 reducer)

- [ ] **Step 5: Commit**

```bash
git add frontend/README.md README.md
git commit -m "chore: add frontend README and root quick-start section"
```
