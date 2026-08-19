import { useLiveStream } from "../context/WebSocketProvider";
import { useStreamStatus } from "../lib/queryClient";
import { getSeverity } from "../lib/severity";
import StatTile from "../components/StatTile";
import SeverityTag from "../components/SeverityTag";
import StationCard from "../components/StationCard";

const SPEED_OPTIONS = [1, 10, 60, 300];

export default function LiveView() {
  const { stations, events, setSpeed, pause, resume } = useLiveStream();
  const { data: streamStatus } = useStreamStatus();
  const faultCount = Object.values(stations).filter((s) => getSeverity(s) === "fault").length;
  const eventCount = Object.values(stations).filter((s) => getSeverity(s) === "event").length;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => (streamStatus?.paused ? resume() : pause())}
          className="rounded-md bg-surface-raised border border-border-weak px-3 py-1.5 text-sm text-text-primary hover:text-text-maxContrast"
        >
          {streamStatus?.paused ? "Resume" : "Pause"}
        </button>
        <span className="text-xs text-text-secondary">Speed:</span>
        <div className="flex gap-1">
          {SPEED_OPTIONS.map((mult) => (
            <button
              key={mult}
              type="button"
              onClick={() => setSpeed(mult)}
              className={`rounded-md border px-2.5 py-1 text-xs ${
                streamStatus?.speed_multiplier === mult
                  ? "bg-surface-raised border-border-weak text-text-maxContrast"
                  : "border-border-weak text-text-secondary hover:text-text-primary"
              }`}
            >
              {mult}x
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-4 gap-4">
        <StatTile label="Rows Processed" value={streamStatus?.rows_processed ?? 0} />
        <StatTile label="Speed" value={`${streamStatus?.speed_multiplier ?? 1}x`} />
        <StatTile label="Active Faults" value={faultCount} />
        <StatTile label="Active Regional Events" value={eventCount} />
      </div>
      <div className="rounded-md border border-border-weak divide-y divide-border-weak">
        {events.slice(0, 20).map((e) => (
          <div key={e.seq} className="flex items-center justify-between px-4 py-2 text-sm">
            <span className="text-text-primary">{e.station_id}</span>
            <span className="text-text-secondary">{e.timestamp}</span>
            <SeverityTag severity={getSeverity(e)} />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-4 gap-3">
        {Object.entries(stations).map(([sid, latest]) => (
          <StationCard key={sid} stationId={sid} latest={latest} />
        ))}
      </div>
    </div>
  );
}
