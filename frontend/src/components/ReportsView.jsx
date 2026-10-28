import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { Download, FileText, Calendar } from "lucide-react";
import { api } from "../api";
import { Card, Kpi, VERDICT, num } from "./Shared";

const PERIODS = ["daily", "weekly", "monthly", "yearly"];

export default function ReportsView({ health }) {
  const [period, setPeriod] = useState("weekly");
  const [date, setDate] = useState("");
  const [rep, setRep] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!date && health?.last) setDate(health.last.slice(0, 10));
  }, [health]);

  async function load() {
    setLoading(true);
    try {
      setRep(await api.report(period, date || undefined));
      setErr(null);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (date) load();
  }, [period, date]);

  const pct = (x) => (rep?.readings ? `${((x / rep.readings) * 100).toFixed(1)}%` : "0%");
  const faults = rep?.faults_by_type ? Object.entries(rep.faults_by_type).map(([k, v]) => ({ type: k, count: v })) : [];

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-muted">Period</label>
            <div className="flex gap-1 rounded-xl border border-line bg-canvas p-1">
              {PERIODS.map((p) => (
                <button key={p} onClick={() => setPeriod(p)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium capitalize transition ${period === p ? "bg-brand text-white" : "text-muted hover:text-ink"}`}>
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 flex items-center gap-1 text-xs uppercase tracking-wider text-muted"><Calendar size={11} /> Anchor date</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
              className="rounded-xl border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-brand" />
          </div>
          <div className="ml-auto flex gap-2">
            <a href={api.downloadUrl(period, date || undefined, "csv")} target="_blank" rel="noreferrer"
              className="flex items-center gap-1.5 rounded-xl border border-line bg-surface px-3 py-2 text-sm font-medium text-ink/80 hover:border-brand hover:text-brand">
              <Download size={15} /> CSV
            </a>
            <a href={api.downloadUrl(period, date || undefined, "pdf")} target="_blank" rel="noreferrer"
              className="flex items-center gap-1.5 rounded-xl bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-branddark">
              <FileText size={15} /> PDF
            </a>
          </div>
        </div>
      </Card>

      {err && <div className="rounded-xl border border-red-200 bg-brandpale px-4 py-3 text-sm text-red-700">{err}</div>}

      {rep && (
        <>
          <div className="text-sm text-muted">
            {rep.start === rep.end ? rep.start : `${rep.start} → ${rep.end}`} · {loading ? "loading…" : `${num(rep.readings)} readings`}
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Valid" value={num(rep.valid)} sub={pct(rep.valid)} accent="text-emerald-600" />
            <Kpi label="Invalid" value={num(rep.invalid)} sub={pct(rep.invalid)} accent="text-red-600" />
            <Kpi label="Review" value={num(rep.review)} sub={pct(rep.review)} accent="text-amber-600" />
            <Kpi label="Pollution events" value={num(rep.pollution_events)} sub={`${rep.devices_reporting} devices`} accent="text-brand" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
            <Card title="Verdicts by day" className="lg:col-span-3">
              <div className="h-64">
                {rep.by_day?.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={rep.by_day} margin={{ left: -20, right: 8, top: 6 }}>
                      <CartesianGrid stroke="#eef0f3" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="day" tick={{ fill: "#94a3b8", fontSize: 11 }} stroke="#eef0f3" />
                      <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} stroke="#eef0f3" allowDecimals={false} />
                      <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 12, boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }} cursor={{ fill: "#f1f5f9" }} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="valid" stackId="a" fill={VERDICT.VALID.hex} radius={[0, 0, 0, 0]} />
                      <Bar dataKey="review" stackId="a" fill={VERDICT.REVIEW.hex} />
                      <Bar dataKey="invalid" stackId="a" fill={VERDICT.INVALID.hex} radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <Empty />}
              </div>
            </Card>

            <Card title="Rejected by fault type" className="lg:col-span-2">
              <div className="h-64">
                {faults.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={faults} layout="vertical" margin={{ left: 20, right: 12, top: 6 }}>
                      <CartesianGrid stroke="#eef0f3" strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} stroke="#eef0f3" allowDecimals={false} />
                      <YAxis type="category" dataKey="type" tick={{ fill: "#94a3b8", fontSize: 11 }} stroke="#eef0f3" width={90} />
                      <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 12, boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }} cursor={{ fill: "#f1f5f9" }} />
                      <Bar dataKey="count" fill={VERDICT.INVALID.hex} radius={[0, 3, 3, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <Empty msg="No rejected readings in this window." />}
              </div>
            </Card>
          </div>

          <Card title="Anomalies by device">
            {rep.by_device?.length ? (
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-left text-sm">
                  <thead className="sticky top-0 bg-surface text-xs uppercase tracking-wider text-muted">
                    <tr>
                      <th className="py-2 pr-3 font-medium">Device</th>
                      <th className="py-2 pr-3 font-medium">City</th>
                      <th className="py-2 pr-3 text-right font-medium">Invalid</th>
                      <th className="py-2 pr-3 text-right font-medium">Review</th>
                      <th className="py-2 pr-3 text-right font-medium">Total</th>
                      <th className="py-2 font-medium">Main fault</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rep.by_device.map((d) => (
                      <tr key={d.device} className="border-t border-line">
                        <td className="py-1.5 pr-3 font-mono text-xs font-medium text-ink">{d.device}</td>
                        <td className="py-1.5 pr-3 text-muted">{d.city}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-red-600">{d.invalid}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-amber-600">{d.review}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums font-semibold text-ink">{d.total}</td>
                        <td className="py-1.5 text-xs text-muted">{d.top_fault}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="py-6 text-center text-sm text-muted">No anomalies in this window.</p>}
          </Card>
        </>
      )}
    </div>
  );
}

function Empty({ msg = "No data for this window." }) {
  return <div className="flex h-full items-center justify-center text-sm text-muted">{msg}</div>;
}
