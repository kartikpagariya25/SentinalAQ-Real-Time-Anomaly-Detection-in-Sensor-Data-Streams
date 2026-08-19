import { Card, CardContent } from "@/components/ui/card";

export default function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="bg-surface-raised border-border-weak">
      <CardContent className="px-4 py-3">
        <div className="text-2xl font-semibold text-text-maxContrast">{value}</div>
        <div className="text-xs text-text-secondary">{label}</div>
      </CardContent>
    </Card>
  );
}
