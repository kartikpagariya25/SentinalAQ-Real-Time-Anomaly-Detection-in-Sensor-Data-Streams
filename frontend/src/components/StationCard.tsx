import { useState } from "react";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import { useStationHistory } from "../lib/queryClient";
import { getSeverity } from "../lib/severity";
import SeverityTag from "./SeverityTag";
import type { DetectionEvent } from "../types";

export default function StationCard({ stationId, latest }: { stationId: string; latest: DetectionEvent | null }) {
  const [expanded, setExpanded] = useState(false);
  const { data: history } = useStationHistory(stationId);
  const severity = getSeverity(latest);
  const sparkData = (history ?? []).filter((h) => h.readings).map((h) => ({ pm25: h.readings!.pm25 }));

  return (
    <Card className="bg-surface-raised border-border-weak">
      <CardContent className="p-3">
        <div className="flex items-center justify-between cursor-pointer" onClick={() => setExpanded((e) => !e)}>
          <span className="text-sm text-text-primary">{stationId}</span>
          <SeverityTag severity={severity} />
        </div>
        {sparkData.length > 1 && (
          <div className="h-10 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparkData}>
                <Line type="monotone" dataKey="pm25" stroke="#6e9fff" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {expanded && (
          <div className="mt-2 text-xs text-text-secondary space-y-1">
            <div>Detectors fired: {latest?.detectors_fired?.join(", ") || "none"}</div>
            <div>Spatial verdict: {latest?.spatial_label || "n/a"}</div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
