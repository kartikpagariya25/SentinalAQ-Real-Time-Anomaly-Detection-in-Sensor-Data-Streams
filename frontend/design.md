# SentinelAQ

## Mission
Create implementation-ready, token-driven UI guidance for the SentinelAQ live anomaly-detection dashboard, optimized for at-a-glance severity triage, live-data legibility, and fast delivery.

## Brand
- Product/brand: SentinelAQ
- Sponsor: Respirer Living Sciences
- Audience: field-operations / monitoring teams, technical
- Product surface: live sensor-anomaly dashboard (stream view, station map, benchmark/model view)

## Source
Foundational tokens below are adapted from Grafana's production dark theme (`grafana/grafana`, `packages/grafana-data/src/themes`) — the closest real-world analog to this project's UI problem (live, data-dense, severity-driven monitoring). Component-level rules are original to SentinelAQ.

## Style Foundations
- Visual style: dark, data-dense, severity-first — status color carries meaning before anything else on screen
- Main font style: `font.family.primary=Inter, Helvetica, Arial, sans-serif`, `font.family.mono=Roboto Mono, monospace`, `font.size.base=14px`, `font.lineHeight.base=22px`
- Typography scale: `font.size.h1=28px/32px`, `font.size.h2=24px/28px`, `font.size.h3=22px/24px`, `font.size.h4=18px/22px`, `font.size.h5=16px/22px`, `font.size.h6=14px/22px (medium)`, `font.size.body=14px/22px`, `font.size.bodySmall=12px/18px`, `font.size.code=14px/16px (mono)`
- Color palette (dark):
  - `color.surface.canvas=#111217`, `color.surface.base=#181b1f`, `color.surface.raised=#22252b`
  - `color.text.primary=rgb(204,204,220)`, `color.text.secondary=rgba(204,204,220,0.65)`, `color.text.disabled=rgba(204,204,220,0.61)`, `color.text.maxContrast=#ffffff`
  - `color.border.weak=rgba(204,204,220,0.12)`, `color.border.default=rgba(204,204,220,0.2)`, `color.border.strong=rgba(204,204,220,0.30)`
  - Semantic (map 1:1 to anomaly taxonomy, not generic success/error):
    - `color.status.normal=#1a7f4b` / text `#6ccf8e` — normal reading
    - `color.status.fault=#d10e5c` / text `#ff5286` — sensor fault (flatline, out-of-range, isolated spike)
    - `color.status.drift=#ff9900` / text `#fbad37` — drift / warning-tier anomaly
    - `color.status.event=#3d71d9` / text `#6e9fff` — real regional environmental event (spatially corrected, NOT a fault) — must be visually distinct from `fault`, never reuse red for this category
- Spacing scale (8px grid): `space.0_5=4px`, `space.1=8px`, `space.1_5=12px`, `space.2=16px`, `space.2_5=20px`, `space.3=24px`, `space.4=32px`, `space.5=40px`, `space.6=48px`
- Radius: `radius.sm=4px` (badges, tags, severity chips), `radius.md=6px` (buttons, inputs, cards, panels), `radius.lg=10px` (modals, containers), `radius.pill=9999px` (status pills, live badge)

## Accessibility
- Target: WCAG 2.2 AA
- Keyboard-first interactions required (map markers, table rows, and severity filters must all be tab-reachable).
- Focus-visible rules required.
- Contrast constraints required — status colors above are chosen for ≥3:1 against `surface.base`; verify before reuse at smaller sizes.
- Color must never be the only signal: every severity tag/marker also carries a text label or icon, since red/blue/orange color-only distinctions fail for color-blind users viewing an anomaly-severity map.

## Writing Tone
Concise, operational, calm under alert — this is a monitoring tool, not marketing. State what fired and why, not how impressive the detection was.

## Rules: Do
- Use semantic tokens (`color.status.*`), never raw hex, in component guidance.
- Every interactive component must define states for default, hover, focus-visible, active, disabled, loading, and error.
- Live-updating components (stream feed, map markers, stat tiles) must define an explicit "stale/disconnected" state, not just loading/loaded.
- Every anomaly-bearing component must show WHY it fired (which detector, spatial-correction outcome) — matches the project's standing "always state WHY" requirement, applied to the UI itself.
- Interactive components must document keyboard, pointer, and touch behavior.

## Rules: Don't
- Do not use `color.status.fault` (red) for a spatially-corrected `regional_agreement` event — that is exactly the false alarm this whole project exists to prevent.
- Do not allow low-contrast text or hidden focus indicators.
- Do not introduce one-off spacing or typography exceptions outside the scale above.
- Do not silently drop or hide flagged rows — a downgraded flag must show its corrected state, not disappear.

## Guideline Authoring Workflow
1. Restate design intent in one sentence.
2. Define foundations and semantic tokens.
3. Define component anatomy, variants, interactions, and state behavior.
4. Add accessibility acceptance criteria with pass/fail checks.
5. Add anti-patterns and edge-case handling.
6. End with a QA checklist.

## Core Components (SentinelAQ-specific)

- **LiveBadge** — pulsing dot + "LIVE" text, `color.status.normal` dot while connected, `color.text.disabled` + "DISCONNECTED" label on stream loss. Must not rely on animation alone (respect `prefers-reduced-motion`). Note: `SeverityTag`'s "sole consumer of `color.status.*`" rule (below) governs *severity classification* specifically — it exists to prevent a real regional event ever being shown as a sensor fault. `LiveBadge` reusing `color.status.normal` for WebSocket connection health is a deliberate exception: connection health isn't a severity classification and carries none of that risk.
- **SeverityTag** — pill (`radius.pill`), one of `normal / drift / fault / event`, background = status color at low opacity, text = status text color, always paired with a short label, never color-only.
- **StatTile** — KPI card (latency p95, throughput, env-event FP rate): value in `font.size.h2`, label in `bodySmall`/`color.text.secondary`, trend arrow optional.
- **StationCard** — station id, live reading, sparkline, current `SeverityTag`; expands to show which detector(s) fired and the spatial-correction verdict.
- **MapMarker** (MapLibre) — colored by `color.status.*`, size scales with severity not just color; clicking opens a `StationCard` popover.
- **BenchmarkTable** — model comparison (precision/recall/F1/env-FP), winning row visually distinguished (`color.status.normal` left-border accent), never re-sorted to hide a model's weak metric.

## Required Output Structure (for future component specs)
- Context and goals.
- Design tokens and foundations.
- Component-level rules (anatomy, variants, states, responsive behavior).
- Accessibility requirements and testable acceptance criteria.
- Content and tone standards with examples.
- Anti-patterns and prohibited implementations.
- QA checklist.

## Quality Gates
- Every non-negotiable rule must use "must".
- Every recommendation should use "should".
- Every accessibility rule must be testable in implementation.
- Status-color usage must be checked against the anti-pattern list above before any PR merges.
