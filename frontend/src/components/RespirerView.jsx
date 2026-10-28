import { Building2, Radar, MapPin, Cpu, Info } from "lucide-react";
import { Card, Kpi } from "./Shared";

export default function RespirerView() {
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start gap-3">
          <Building2 className="mt-0.5 text-brand" size={22} />
          <div>
            <h3 className="text-base font-semibold text-ink">Respirer Living Sciences</h3>
            <p className="mt-1 text-sm text-muted">
              Respirer builds the Atmos range of low-cost IoT air-quality monitors deployed across India. SentinelAQ validates their live sensor streams — separating real sensor faults from genuine pollution events, automatically.
            </p>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Kpi label="Atmos devices" value="2,500+" accent="text-brand" />
        <Kpi label="Indian cities" value="25+" accent="text-brand" />
        <Kpi label="Scope (this project)" value="PM2.5" sub="temp + RH used as context" accent="text-brand" />
      </div>

      <Card title="Atmos devices">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex gap-3">
            <Cpu className="mt-0.5 shrink-0 text-brand" size={18} />
            <div>
              <div className="text-sm font-semibold text-ink">Variants</div>
              <p className="text-sm text-muted">base, STAT, MOBI, Mapie — fixed and mobile units for different deployments.</p>
            </div>
          </div>
          <div className="flex gap-3">
            <Radar className="mt-0.5 shrink-0 text-brand" size={18} />
            <div>
              <div className="text-sm font-semibold text-ink">Parameters</div>
              <p className="text-sm text-muted">PM1 / PM2.5 / PM10, NO₂ and Ozone over NB-IoT; some units also report temperature, humidity and CO.</p>
            </div>
          </div>
          <div className="flex gap-3">
            <MapPin className="mt-0.5 shrink-0 text-brand" size={18} />
            <div>
              <div className="text-sm font-semibold text-ink">Deployment</div>
              <p className="text-sm text-muted">A dense network across many cities, which is what makes nearby-device cross-checking possible.</p>
            </div>
          </div>
          <div className="flex gap-3">
            <Info className="mt-0.5 shrink-0 text-brand" size={18} />
            <div>
              <div className="text-sm font-semibold text-ink">Note</div>
              <p className="text-sm text-muted">Exact per-device parameters are to be confirmed with the sponsor. This project works on PM2.5, temperature and humidity.</p>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
