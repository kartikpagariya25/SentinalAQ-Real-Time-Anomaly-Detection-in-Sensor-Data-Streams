import type { Severity } from "../lib/severity";

const SEVERITY_COLOR: Record<Severity, string> = {
  normal: "#1a7f4b",
  fault: "#d10e5c",
  drift: "#ff9900",
  event: "#3d71d9",
  unknown: "#383b42",
};

const SEVERITY_SIZE: Record<Severity, number> = {
  normal: 8,
  fault: 14,
  drift: 12,
  event: 12,
  unknown: 6,
};

export default function MapMarker({ severity }: { severity: Severity }) {
  return (
    <div
      className="rounded-pill border border-surface-base cursor-pointer"
      style={{
        backgroundColor: SEVERITY_COLOR[severity],
        width: SEVERITY_SIZE[severity],
        height: SEVERITY_SIZE[severity],
      }}
    />
  );
}
