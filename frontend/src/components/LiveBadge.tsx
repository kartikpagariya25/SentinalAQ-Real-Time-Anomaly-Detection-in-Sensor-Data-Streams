export default function LiveBadge({ status }: { status: "connected" | "disconnected" | "reconnecting" }) {
  if (status === "connected") {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-status-normalText">
        <span className="h-2 w-2 rounded-pill bg-status-normal motion-safe:animate-pulse" />
        LIVE
      </span>
    );
  }
  return <span className="text-sm text-text-disabled">DISCONNECTED</span>;
}
