import { useBenchmark } from "../lib/queryClient";
import BenchmarkTable from "../components/BenchmarkTable";

export default function BenchmarkView() {
  const { data, isLoading, isError, refetch } = useBenchmark();

  if (isLoading) return <div className="text-text-secondary">Loading benchmark...</div>;
  if (isError || !data)
    return (
      <div className="flex items-center gap-3">
        <div className="text-status-faultText">Failed to load benchmark data.</div>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded-md bg-surface-raised border border-border-weak px-3 py-1 text-sm text-text-primary hover:text-text-maxContrast"
        >
          Retry
        </button>
      </div>
    );

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
