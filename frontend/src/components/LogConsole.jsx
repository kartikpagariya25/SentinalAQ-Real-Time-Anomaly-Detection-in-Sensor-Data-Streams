import { useEffect, useRef, useState } from "react";
import { Terminal, Pause, Play } from "lucide-react";
import { api } from "../api";
import { VERDICT } from "./Shared";

const POLL_MS = 1500;
const REVEAL_MS = 120;
const MAX_LINES = 400;

function clock() {
  return new Date().toLocaleTimeString("en-GB");
}

export default function LogConsole() {
  const [lines, setLines] = useState([]);
  const [now, setNow] = useState(clock());
  const [rate, setRate] = useState(0);
  const [paused, setPaused] = useState(false);
  const seen = useRef(new Set());
  const queue = useRef([]);
  const stamps = useRef([]);
  const box = useRef(null);
  const pausedRef = useRef(false);

  useEffect(() => { pausedRef.current = paused; }, [paused]);

  useEffect(() => {
    async function poll() {
      if (pausedRef.current) return;
      try {
        const recent = await api.recent(60);
        for (const r of [...recent].reverse()) {
          const key = `${r.device_id}|${r.timestamp}`;
          if (seen.current.has(key)) continue;
          seen.current.add(key);
          queue.current.push(r);
        }
        if (seen.current.size > 4000) seen.current = new Set([...seen.current].slice(-2000));
      } catch {
        /* API not up yet */
      }
    }
    poll();
    const p = setInterval(poll, POLL_MS);
    const reveal = setInterval(() => {
      if (pausedRef.current || !queue.current.length) return;
      const r = queue.current.shift();
      const at = clock();
      stamps.current.push(Date.now());
      setLines((prev) => {
        const next = [...prev, { ...r, at }];
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
      });
    }, REVEAL_MS);
    const tick = setInterval(() => {
      setNow(clock());
      const cut = Date.now() - 60000;
      stamps.current = stamps.current.filter((t) => t >= cut);
      setRate(stamps.current.length);
    }, 1000);
    return () => { clearInterval(p); clearInterval(reveal); clearInterval(tick); };
  }, []);

  useEffect(() => {
    if (box.current && !pausedRef.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines]);

  return (
    <div className="rounded-2xl border border-line bg-surface shadow-card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line bg-canvas px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink/80">
          <Terminal size={15} className="text-brand" /> live stream · readings scored on arrival
        </div>
        <div className="flex items-center gap-4 text-xs text-muted">
          <span>{rate}/min</span>
          <span className="font-mono tabular-nums text-emerald-600">{now}</span>
          <button onClick={() => setPaused((v) => !v)} className="flex items-center gap-1 rounded px-2 py-0.5 text-ink/70 hover:bg-line/60">
            {paused ? <Play size={12} /> : <Pause size={12} />} {paused ? "resume" : "pause"}
          </button>
        </div>
      </div>
      <div ref={box} className="h-[22rem] overflow-y-auto bg-[#fbfcfd] px-4 py-2 font-mono text-[12.5px] leading-6">
        <div className="sticky top-0 -mx-4 mb-1 flex gap-2 whitespace-pre border-b border-line bg-[#fbfcfd] px-4 pb-1 text-[11px] uppercase tracking-wide text-slate-400">
          <span>{"arrival ".padEnd(8)}</span>
          <span>{"reading".padEnd(11)}</span>
          <span>{"device".padEnd(7)}</span>
          <span>{"pm2.5 / temp / rh".padEnd(24)}</span>
          <span>{"verdict".padEnd(7)}</span>
          <span>{"conf"}</span>
          <span>reason</span>
        </div>
        {lines.length === 0 && (
          <p className="text-muted">
            waiting for the feed… start it with <span className="text-brand">python -m app.cli live-feed --loop</span>
          </p>
        )}
        {lines.map((r, i) => {
          const v = VERDICT[r.verdict] || VERDICT.VALID;
          const vals = r.pm25 == null ? "NO DATA".padEnd(24) : `PM ${String(r.pm25.toFixed(1)).padStart(6)} T ${String((r.temp ?? 0).toFixed(1)).padStart(5)} RH ${String((r.rh ?? 0).toFixed(0)).padStart(3)}`;
          return (
            <div key={i} className="row-enter flex gap-2 whitespace-pre">
              <span className="text-slate-400">{r.at}</span>
              <span className="text-brand/70">{r.timestamp.slice(5, 16).replace("T", " ")}</span>
              <span className="text-ink/70">{r.device_id.padEnd(7)}</span>
              <span className="text-slate-500">{vals}</span>
              <span className={`font-semibold ${v.text}`}>{v.label.padEnd(7)}</span>
              <span className="text-slate-400">{r.confidence?.toFixed(2)}</span>
              <span className="text-slate-500 whitespace-pre-wrap">{r.reason}</span>
            </div>
          );
        })}
        {!paused && <span className="live-dot text-emerald-500">▋</span>}
      </div>
    </div>
  );
}
