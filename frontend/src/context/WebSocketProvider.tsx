import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { DetectionEvent } from "../types";

const EVENTS_CAP = 200;

export interface StreamEvent extends DetectionEvent {
  seq: number;
}

export interface StreamState {
  stations: Record<string, DetectionEvent | null>;
  events: StreamEvent[];
}

export const initialStreamState: StreamState = { stations: {}, events: [] };

type IncomingMessage =
  | { type: "snapshot"; stations: Record<string, DetectionEvent | null> }
  | (DetectionEvent & { type: "detection" });

// Monotonically-incrementing sequence counter. Backend can emit multiple detections
// for the same station at the same timestamp, so station_id+timestamp is not a safe
// unique identity for React list keys — this counter guarantees one is always available.
let nextSeq = 0;

export function applyMessage(state: StreamState, msg: IncomingMessage): StreamState {
  if (msg.type === "snapshot") {
    return { ...state, stations: { ...msg.stations } };
  }
  const stamped: StreamEvent = { ...msg, seq: nextSeq++ };
  const events = [stamped, ...state.events];
  if (events.length > EVENTS_CAP) events.length = EVENTS_CAP;
  return {
    stations: { ...state.stations, [msg.station_id]: msg },
    events,
  };
}

type Status = "connected" | "disconnected" | "reconnecting";

interface LiveStreamContextValue extends StreamState {
  status: Status;
  setSpeed: (value: number) => void;
  pause: () => void;
  resume: () => void;
}

const LiveStreamContext = createContext<LiveStreamContextValue | null>(null);

const WS_URL = "ws://127.0.0.1:8000/ws/stream";

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StreamState>(initialStreamState);
  const [status, setStatus] = useState<Status>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retryDelay = 1000;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => { setStatus("connected"); retryDelay = 1000; };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as IncomingMessage;
        setState((s) => applyMessage(s, msg));
      };
      ws.onclose = () => {
        if (cancelled) return;
        setStatus("reconnecting");
        setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
      ws.onerror = () => ws.close();
    }
    connect();
    return () => { cancelled = true; wsRef.current?.close(); };
  }, []);

  function send(action: Record<string, unknown>) {
    wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send(JSON.stringify(action));
  }

  const value: LiveStreamContextValue = {
    ...state,
    status,
    setSpeed: (value) => send({ action: "set_speed", value }),
    pause: () => send({ action: "pause" }),
    resume: () => send({ action: "resume" }),
  };

  return <LiveStreamContext.Provider value={value}>{children}</LiveStreamContext.Provider>;
}

export function useLiveStream(): LiveStreamContextValue {
  const ctx = useContext(LiveStreamContext);
  if (!ctx) throw new Error("useLiveStream must be used within WebSocketProvider");
  return ctx;
}
