const BASE = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

async function get(path, timeout = 8000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeout);
  try {
    const r = await fetch(`${BASE}${path}`, { signal: ctrl.signal });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  } finally {
    clearTimeout(t);
  }
}

export const api = {
  base: BASE,
  health: () => get("/health"),
  stats: () => get("/stats"),
  recent: (limit = 60) => get(`/readings/recent?limit=${limit}`),
  report: (period, date) => get(`/report/range?period=${period}${date ? `&date=${date}` : ""}`),
  downloadUrl: (period, date, format) =>
    `${BASE}/report/range?period=${period}${date ? `&date=${date}` : ""}&format=${format}`,
};
