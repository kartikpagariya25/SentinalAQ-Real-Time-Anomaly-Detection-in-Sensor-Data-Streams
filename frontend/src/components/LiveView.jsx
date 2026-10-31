import { useEffect, useRef, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
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
  const sum = data.reduce((t, r) => ({ VALID: t.VALID + r.VALID, REVIEW: t.REVIEW + r.REVIEW, INVALID: t.INVALID + r.INVALID }), { VALID: 0, REVIEW: 0, INVALID: 0 });

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
        <Card title="Readings per hour by verdict (last 24 hours of the stream)" className="lg:col-span-2" right={<LiveTag last={stats?.last} />}>
          <div className="mb-2 grid grid-cols-4 gap-2 text-center text-xs">
            <Total label="Valid" value={sum.VALID} color={VERDICT.VALID.hex} />
            <Total label="Review" value={sum.REVIEW} color={VERDICT.REVIEW.hex} />
            <Total label="Invalid" value={sum.INVALID} color={VERDICT.INVALID.hex} />
            <Total label="Total (24h)" value={sum.VALID + sum.REVIEW + sum.INVALID} color="#0f172a" />
          </div>
          <div className="h-64">
            {data.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} margin={{ left: 4, right: 10, top: 6, bottom: 22 }} barCategoryGap="12%">
                  <CartesianGrid stroke="#eef0f3" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="hour" tick={{ fill: "#64748b", fontSize: 10 }} stroke="#e5e7eb" interval="preserveStartEnd" minTickGap={24}
                    label={{ value: "hour of arrival (MM-DD HH)", position: "insideBottom", offset: -12, fill: "#64748b", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#64748b", fontSize: 11 }} stroke="#e5e7eb" allowDecimals={false}
                    label={{ value: "number of readings", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11, style: { textAnchor: "middle" } }} />
                  <Tooltip cursor={{ fill: "#f1f5f9" }} />
                  <Legend verticalAlign="top" height={24} iconType="square" wrapperStyle={{ fontSize: 12 }} />
                  <Bar name="Valid" dataKey="VALID" stackId="a" fill={VERDICT.VALID.hex} />
                  <Bar name="Review" dataKey="REVIEW" stackId="a" fill={VERDICT.REVIEW.hex} />
                  <Bar name="Invalid" dataKey="INVALID" stackId="a" fill={VERDICT.INVALID.hex} />
                </BarChart>
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

function Total({ label, value, color }) {
  return (
    <div className="rounded-lg border border-line bg-canvas px-2 py-1.5">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="text-base font-bold tabular-nums" style={{ color }}>{num(value)}</div>
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
