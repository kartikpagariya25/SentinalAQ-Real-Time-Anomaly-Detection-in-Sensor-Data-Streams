import { useEffect, useRef, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { AlertTriangle, Database } from "lucide-react";
import { api } from "../api";
import { Card, Kpi, Pill, VERDICT, num } from "./Shared";
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

  const data = stats?.by_hour || [];
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Verdicts per hour (last 24h)" className="lg:col-span-2" right={<LiveTag last={stats?.last} />}>
          <div className="h-64">
            {data.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data} margin={{ left: 4, right: 10, top: 6, bottom: 18 }}>
                  <defs>
                    {Object.entries(VERDICT).map(([k, v]) => (
                      <linearGradient key={k} id={`g${k}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={v.hex} stopOpacity={0.5} />
                        <stop offset="100%" stopColor={v.hex} stopOpacity={0.04} />
                      </linearGradient>
                    ))}
                  </defs>
                  <CartesianGrid stroke="#eef0f3" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="hour" tick={{ fill: "#94a3b8", fontSize: 10 }} stroke="#e5e7eb" interval="preserveStartEnd" minTickGap={28}
                    label={{ value: "hour (date · time)", position: "insideBottom", offset: -10, fill: "#94a3b8", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} stroke="#e5e7eb" allowDecimals={false}
                    label={{ value: "readings / hour", angle: -90, position: "insideLeft", fill: "#94a3b8", fontSize: 11, style: { textAnchor: "middle" } }} />
                  <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 12, color: "#0f172a", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }} />
                  <Legend verticalAlign="top" height={24} iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" name="Valid" dataKey="VALID" stackId="1" stroke={VERDICT.VALID.hex} fill="url(#gVALID)" />
                  <Area type="monotone" name="Review" dataKey="REVIEW" stackId="1" stroke={VERDICT.REVIEW.hex} fill="url(#gREVIEW)" />
                  <Area type="monotone" name="Invalid" dataKey="INVALID" stackId="1" stroke={VERDICT.INVALID.hex} fill="url(#gINVALID)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : <div className="flex h-full items-center justify-center text-sm text-muted">waiting for data…</div>}
          </div>
        </Card>

        <Card title="Anomaly feed" right={<span className="flex items-center gap-1 text-xs text-brand"><AlertTriangle size={13} /> {anomalies.length}</span>}>
          <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
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
      </div>

      <LogConsole />
    </div>
  );
}

function LiveTag({ last }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted">
      <span className="live-dot h-2 w-2 rounded-full bg-emerald-500" />
      live {last ? `· ${last.slice(5, 16).replace("T", " ")}` : ""}
    </span>
  );
}
