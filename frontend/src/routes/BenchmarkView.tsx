import { useBenchmark } from "../lib/queryClient";
import BenchmarkTable from "../components/BenchmarkTable";

export default function BenchmarkView() {
  const { data, isLoading, isError } = useBenchmark();

  if (isLoading) return <div className="text-text-secondary">Loading benchmark...</div>;
  if (isError || !data) return <div className="text-status-faultText">Failed to load benchmark data.</div>;

  return (
    <div className="space-y-4">
      <div className="rounded-md bg-surface-raised border border-border-weak p-4">
        <div className="text-text-maxContrast font-semibold mb-1">Winner: {data.winner}</div>
        <div className="text-sm text-text-secondary">{data.why}</div>
      </div>
      <BenchmarkTable rows={data.table} winner={data.winner} />
    </div>
  );
}
