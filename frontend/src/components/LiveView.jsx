import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Database } from "lucide-react";
import { api } from "../api";
import { Card, Kpi, Pill, num } from "./Shared";
import LogConsole from "./LogConsole";

const POLL_MS = 2000;

export default function LiveView({ health }) {
  const [stats, setStats] = useState(null);
  const [down, setDown] = useState(false);
  const fails = useRef(0);

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const s = await api.stats();
        if (!alive) return;
        setStats(s);
        fails.current = 0;
        setDown(false);
      } catch {
        if (!alive) return;
        fails.current += 1;
        if (fails.current >= 4) setDown(true);
      }
    }
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const w = stats?.latest_window || { valid: 0, invalid: 0, review: 0 };
  const anomalies = stats?.recent_anomalies || [];

  return (
    <div className="space-y-4">
      {down && (
        <div className="rounded-xl border border-red-200 bg-brandpale px-4 py-3 text-sm text-red-700">
          API not reachable at {api.base}. Start it with <code>python -m app.cli serve</code> (or run <code>.\run.ps1</code>).
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Stored readings" value={num(stats?.total)} sub={<span className="inline-flex items-center gap-1"><Database size={11} /> {num(health?.devices)} devices</span>} />
        <Kpi label="Valid (recent)" value={num(w.valid)} accent="text-emerald-600" />
        <Kpi label="Review (recent)" value={num(w.review)} accent="text-amber-600" />
        <Kpi label="Invalid (recent)" value={num(w.invalid)} accent="text-red-600" />
      </div>

      <Card title="Anomaly feed" right={<span className="flex items-center gap-1 text-xs text-brand"><AlertTriangle size={13} /> {anomalies.length}</span>}>
        <div className="grid max-h-96 grid-cols-1 gap-2 overflow-y-auto pr-1 md:grid-cols-2">
          {anomalies.length === 0 && <p className="text-sm text-muted">No anomalies in the recent window.</p>}
          {anomalies.map((a, i) => (
            <div key={i} className="row-enter rounded-xl border border-line bg-canvas p-2.5">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-ink/70">{a.device_id}</span>
                <Pill verdict={a.verdict} />
              </div>
              <p className="mt-1 text-xs leading-snug text-muted">{a.reason}</p>
            </div>
          ))}
        </div>
      </Card>

      <LogConsole />
    </div>
  );
}
