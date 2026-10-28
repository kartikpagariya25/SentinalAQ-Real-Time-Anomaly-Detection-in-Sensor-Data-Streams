import { ShieldCheck, Layers, Database, Cpu } from "lucide-react";
import { Card } from "./Shared";

const STEPS = [
  "Physics rules catch the certain faults: missing data, impossible temperature, RH out of range, the 3333 sentinel, saturation.",
  "LightGBM reads the last 192 hours of the device and its city neighbours (40 features) and scores a fault probability.",
  "Isotonic calibration makes that probability honest — 70% means roughly 70%.",
  "A 3-way policy decides: VALID, INVALID, or REVIEW when the call is genuinely uncertain.",
];

export default function AboutView() {
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 text-brand" size={22} />
          <div>
            <h3 className="text-base font-semibold text-ink">About SentinelAQ</h3>
            <p className="mt-1 text-sm text-muted">
              A real-time anomaly detection pipeline for air-quality sensor streams. Every reading gets a verdict, a confidence, and a plain-language reason — so bad data never reaches reports and real pollution events are never thrown away.
            </p>
          </div>
        </div>
      </Card>

      <Card title="How a reading is judged">
        <ol className="space-y-2">
          {STEPS.map((s, i) => (
            <li key={i} className="flex gap-3 text-sm text-ink/80">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brandpale text-xs font-bold text-brand">{i + 1}</span>
              {s}
            </li>
          ))}
        </ol>
      </Card>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Card>
          <Cpu className="text-brand" size={18} />
          <div className="mt-2 text-sm font-semibold text-ink">Selected model</div>
          <p className="text-sm text-muted">LightGBM (tuned) — best fault ranking (PR-AUC 0.92), 99.3% of readings decided automatically, calibrated and stable over time.</p>
        </Card>
        <Card>
          <Database className="text-brand" size={18} />
          <div className="mt-2 text-sm font-semibold text-ink">Data</div>
          <p className="text-sm text-muted">Trained on a 3-year synthetic Atmos network (67 devices, 10 cities, ~1.76M rows) built from patterns in the real file.</p>
        </Card>
        <Card>
          <Layers className="text-brand" size={18} />
          <div className="mt-2 text-sm font-semibold text-ink">Stack</div>
          <p className="text-sm text-muted">FastAPI + SQLite serving, LightGBM + scikit-learn, React + Vite dashboard. One HTTP endpoint to ingest live readings.</p>
        </Card>
      </div>
    </div>
  );
}
