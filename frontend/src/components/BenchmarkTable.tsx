import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import type { BenchmarkRow } from "../types";

export default function BenchmarkTable({ rows, winner }: { rows: BenchmarkRow[]; winner: string }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="border-border-weak">
          <TableHead className="text-text-secondary">Method</TableHead>
          <TableHead className="text-text-secondary">Precision</TableHead>
          <TableHead className="text-text-secondary">Recall</TableHead>
          <TableHead className="text-text-secondary">F1</TableHead>
          <TableHead className="text-text-secondary">Env-Event FP Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow
            key={r.method}
            className={`border-border-weak ${r.method === winner ? "border-l-4 border-l-status-normal" : ""}`}
          >
            <TableCell className="text-text-primary">{r.method}</TableCell>
            <TableCell className="text-text-secondary">{r.precision.toFixed(2)}</TableCell>
            <TableCell className="text-text-secondary">{r.recall.toFixed(2)}</TableCell>
            <TableCell className="text-text-secondary">{r.f1.toFixed(2)}</TableCell>
            <TableCell className="text-text-secondary">{r.env_event_fp_rate === null ? "n/a" : r.env_event_fp_rate.toFixed(2)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
