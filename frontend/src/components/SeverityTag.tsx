import { Badge } from "@/components/ui/badge";
import type { Severity } from "../lib/severity";

const STYLES: Record<Severity, string> = {
  normal: "bg-status-normal/20 text-status-normalText border-transparent",
  fault: "bg-status-fault/20 text-status-faultText border-transparent",
  drift: "bg-status-drift/20 text-status-driftText border-transparent",
  event: "bg-status-event/20 text-status-eventText border-transparent",
  unknown: "bg-border text-text-disabled border-transparent",
};

const LABELS: Record<Severity, string> = {
  normal: "Normal", fault: "Fault", drift: "Drift", event: "Regional Event", unknown: "Unknown",
};

export default function SeverityTag({ severity }: { severity: Severity }) {
  return (
    <Badge className={`rounded-pill font-medium ${STYLES[severity]}`}>
      {LABELS[severity]}
    </Badge>
  );
}
