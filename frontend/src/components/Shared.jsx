export const VERDICT = {
  VALID: { label: "VALID", text: "text-emerald-700", bg: "bg-emerald-50", dot: "bg-emerald-500", hex: "#16a34a" },
  REVIEW: { label: "REVIEW", text: "text-amber-700", bg: "bg-amber-50", dot: "bg-amber-500", hex: "#d97706" },
  INVALID: { label: "INVALID", text: "text-red-700", bg: "bg-red-50", dot: "bg-red-500", hex: "#dc2626" },
};

export function Card({ title, right, children, className = "" }) {
  return (
    <div className={`rounded-2xl border border-line bg-surface shadow-card p-4 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between">
          {title && <h3 className="text-sm font-semibold text-ink/80 tracking-wide">{title}</h3>}
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Kpi({ label, value, sub, accent = "text-ink" }) {
  return (
    <div className="rounded-2xl border border-line bg-surface shadow-card p-4">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${accent}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Pill({ verdict }) {
  const v = VERDICT[verdict] || VERDICT.VALID;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${v.bg} ${v.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${v.dot}`} />
      {v.label}
    </span>
  );
}

export function num(n) {
  return typeof n === "number" ? n.toLocaleString() : n ?? "—";
}
