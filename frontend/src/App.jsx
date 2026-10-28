import { useEffect, useState } from "react";
import { Wind, Radio, BarChart3, Database, Users, Building2, Info } from "lucide-react";
import { api } from "./api";
import LiveView from "./components/LiveView";
import ReportsView from "./components/ReportsView";
import DatasetView from "./components/DatasetView";
import TeamView from "./components/TeamView";
import RespirerView from "./components/RespirerView";
import AboutView from "./components/AboutView";
import ErrorBoundary from "./components/ErrorBoundary";

const NAV = [
  { id: "live", label: "Live stream", icon: Radio },
  { id: "reports", label: "Reports", icon: BarChart3 },
  { id: "dataset", label: "Dataset", icon: Database },
  { id: "team", label: "Team", icon: Users },
  { id: "respirer", label: "Respirer", icon: Building2 },
  { id: "about", label: "About", icon: Info },
];

export default function App() {
  const [tab, setTab] = useState("live");
  const [health, setHealth] = useState(null);
  const [online, setOnline] = useState(true);

  useEffect(() => {
    async function ping() {
      try {
        setHealth(await api.health());
        setOnline(true);
      } catch {
        setOnline(false);
      }
    }
    ping();
    const t = setInterval(ping, 10000);
    return () => clearInterval(t);
  }, []);

  const active = NAV.find((n) => n.id === tab);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 flex-col border-r border-line bg-surface px-3 py-5">
        <div className="mb-7 flex items-center gap-3 px-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-branddark shadow">
            <Wind size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-extrabold leading-none tracking-tight text-ink">SentinelAQ</h1>
            <p className="mt-1 text-[11px] text-muted">Respirer Atmos</p>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((n) => {
            const Icon = n.icon;
            const on = tab === n.id;
            return (
              <button key={n.id} onClick={() => setTab(n.id)}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${on ? "bg-brandpale text-brand" : "text-muted hover:bg-canvas hover:text-ink"}`}>
                <Icon size={18} /> {n.label}
                {on && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-brand" />}
              </button>
            );
          })}
        </nav>

        <div className="mt-4 rounded-xl border border-line bg-canvas px-3 py-2.5">
          <div className={`flex items-center gap-2 text-xs font-medium ${online ? "text-emerald-600" : "text-red-600"}`}>
            <span className={`h-2 w-2 rounded-full ${online ? "bg-emerald-500 live-dot" : "bg-red-500"}`} />
            {online ? "API online" : "API offline"}
          </div>
          <p className="mt-1 text-[11px] text-muted">
            {online ? `model: ${health?.model || "…"}` : "start: app.cli serve"}
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface/80 px-6 py-4 backdrop-blur">
          <div className="flex items-center gap-2">
            {active && <active.icon size={18} className="text-brand" />}
            <h2 className="text-base font-semibold text-ink">{active?.label}</h2>
          </div>
          <span className="text-xs text-muted">
            {health?.stored_readings != null ? `${health.stored_readings.toLocaleString()} readings · ${health.devices} devices` : ""}
          </span>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-6">
          <ErrorBoundary key={tab}>
            {tab === "live" && <LiveView health={health} />}
            {tab === "reports" && <ReportsView health={health} />}
            {tab === "dataset" && <DatasetView />}
            {tab === "team" && <TeamView />}
            {tab === "respirer" && <RespirerView />}
            {tab === "about" && <AboutView />}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
