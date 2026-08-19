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
