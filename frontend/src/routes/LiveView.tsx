import { useLiveStream } from "../context/WebSocketProvider";
import { getSeverity } from "../lib/severity";
import LiveBadge from "../components/LiveBadge";
import StatTile from "../components/StatTile";
import SeverityTag from "../components/SeverityTag";
import StationCard from "../components/StationCard";

export default function LiveView() {
  const { stations, events, status } = useLiveStream();
  const faultCount = Object.values(stations).filter((s) => getSeverity(s) === "fault").length;
  const eventCount = Object.values(stations).filter((s) => getSeverity(s) === "event").length;

  return (
    <div className="space-y-6">
      <LiveBadge status={status} />
      <div className="grid grid-cols-4 gap-4">
        <StatTile label="Stations Seen" value={Object.keys(stations).length} />
        <StatTile label="Events Received" value={events.length} />
        <StatTile label="Active Faults" value={faultCount} />
        <StatTile label="Active Regional Events" value={eventCount} />
      </div>
      <div className="rounded-md border border-border-weak divide-y divide-border-weak">
        {events.slice(0, 20).map((e, i) => (
          <div key={i} className="flex items-center justify-between px-4 py-2 text-sm">
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
