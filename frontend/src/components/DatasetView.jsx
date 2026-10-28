import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { FileSpreadsheet, Network, SplitSquareHorizontal, Info } from "lucide-react";
import { Card, Kpi } from "./Shared";

const CLASSES = [
  { name: "normal", share: 94.33 },
  { name: "dropout", share: 2.36 },
  { name: "stuck", share: 0.69 },
  { name: "drift", share: 0.53 },
  { name: "rh_fault", share: 0.5 },
  { name: "th_fault", share: 0.48 },
  { name: "pollution_event", share: 0.44 },
  { name: "saturation", share: 0.28 },
  { name: "impossible_temp", share: 0.2 },
  { name: "spike", share: 0.19 },
];

const REAL = [
  ["Rows", "168 hourly (one week)"],
  ["Devices", "1"],
  ["Columns", "PM2.5, temperature, humidity, validity"],
  ["PM2.5", "median 24.5, p99 62.9 µg/m³"],
  ["Autocorrelation", "0.81 (changes slowly hour to hour)"],
  ["Sentinel / saturation", "3333 / ~3300"],
  ["Use", "pattern learning + final reality check only"],
];

const SPLITS = [
  ["Train", "before 2025-07-01"],
  ["Validation", "2025-07-01 → 2026-01-01"],
  ["Test", "2026-01-01 onward (never trained/tuned on)"],
  ["Held-out cities", "Nagpur, Kolkata"],
  ["Held-out fault families", "double_spike, zero_stuck, noise_burst, temp_step, rh_flat_high"],
];

function KV({ rows }) {
  return (
    <div className="divide-y divide-line">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 py-2 text-sm">
          <span className="text-muted">{k}</span>
          <span className="text-right font-medium text-ink">{v}</span>
        </div>
      ))}
    </div>
  );
}

export default function DatasetView() {
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start gap-3">
          <Network className="mt-0.5 text-brand" size={22} />
          <div>
            <h3 className="text-base font-semibold text-ink">Dataset</h3>
            <p className="mt-1 text-sm text-muted">
              The real Atmos file is only 168 rows from one device — too small to train on. It is used to learn patterns, then a 3-year synthetic Atmos network is generated from those patterns to train and test the model.
            </p>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Synthetic rows" value="1.76M" accent="text-brand" />
        <Kpi label="Devices" value="67" accent="text-brand" />
        <Kpi label="Cities" value="10" accent="text-brand" />
        <Kpi label="Span" value="3 years" sub="2023-10 → 2026-09, hourly" accent="text-brand" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Real Atmos file">
          <div className="mb-2 flex items-center gap-2 text-xs text-muted">
            <FileSpreadsheet size={14} className="text-brand" /> device_with_anomaly.xlsx
          </div>
          <KV rows={REAL} />
        </Card>

        <Card title="Class distribution (synthetic)">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={CLASSES} layout="vertical" margin={{ left: 30, right: 16, top: 4 }}>
                <CartesianGrid stroke="#eef0f3" strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} stroke="#e5e7eb" unit="%" />
                <YAxis type="category" dataKey="name" tick={{ fill: "#94a3b8", fontSize: 11 }} stroke="#e5e7eb" width={100} />
                <Tooltip formatter={(v) => `${v}%`} contentStyle={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 12, boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }} cursor={{ fill: "#f1f5f9" }} />
                <Bar dataKey="share" fill="#dc2626" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1 text-xs text-muted">~94% of readings are normal; faults and real events make up the rest.</p>
        </Card>
      </div>

      <Card title="Splits (by time, no shuffling)">
        <div className="mb-2 flex items-center gap-2 text-xs text-muted">
          <SplitSquareHorizontal size={14} className="text-brand" /> time-based so the future never leaks into training
        </div>
        <KV rows={SPLITS} />
      </Card>

      <Card>
        <div className="flex items-start gap-3">
          <Info className="mt-0.5 shrink-0 text-brand" size={18} />
          <div>
            <div className="text-sm font-semibold text-ink">What is assumed</div>
            <p className="text-sm text-muted">
              The real file has no location, so the 10 cities, 67 devices, climate presets, festival strengths and fault rates are modelling assumptions, not facts. Scope is PM2.5 (temperature and humidity are used as context). Replacing these with real device-to-location data from Respirer is the main next step.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
