export interface Reading {
  pm25: number; pm10: number; no2: number; co: number;
  temperature: number; humidity: number;
}

export interface DetectionEvent {
  type: "detection";
  station_id: string;
  timestamp: string;
  readings: Reading | null;
  flag: 0 | 1;
  spatial_label: "" | "isolated_fault" | "regional_agreement";
  detectors_fired: string[];
}

export interface StationMeta {
  station_id: string;
  latitude: number;
  longitude: number;
  status: "normal" | "fault" | "unknown";
}

export interface BenchmarkRow {
  method: string;
  precision: number;
  recall: number;
  f1: number;
  env_event_fp_rate: number | null;
}

export interface BenchmarkResponse {
  table: BenchmarkRow[];
  winner: string;
  why: string;
}

export interface StreamStatus {
  paused: boolean;
  speed_multiplier: number;
  rows_processed: number;
  started_at: string;
}
