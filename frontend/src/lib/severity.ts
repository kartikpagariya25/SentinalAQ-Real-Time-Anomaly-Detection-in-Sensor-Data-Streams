export type Severity = "normal" | "fault" | "drift" | "event" | "unknown";

export function getSeverity(
  entry: { flag: 0 | 1; spatial_label: string } | null
): Severity {
  if (!entry) return "unknown";
  if (entry.spatial_label === "regional_agreement") return "event";
  if (entry.flag === 1) return "fault";
  return "normal";
}
