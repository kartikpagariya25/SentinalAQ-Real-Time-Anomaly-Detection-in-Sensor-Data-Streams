import { QueryClient, useQuery } from "@tanstack/react-query";
import type { StationMeta, BenchmarkResponse, DetectionEvent } from "../types";

export const queryClient = new QueryClient();

const API_BASE = "http://127.0.0.1:8000";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

export function useStations() {
  return useQuery({
    queryKey: ["stations"],
    queryFn: () => fetchJson<StationMeta[]>("/api/stations"),
  });
}

export function useStationHistory(stationId: string) {
  return useQuery({
    queryKey: ["station-history", stationId],
    queryFn: () => fetchJson<DetectionEvent[]>(`/api/stations/${stationId}/history`),
    enabled: !!stationId,
  });
}

export function useBenchmark() {
  return useQuery({
    queryKey: ["benchmark"],
    queryFn: () => fetchJson<BenchmarkResponse>("/api/benchmark"),
  });
}
