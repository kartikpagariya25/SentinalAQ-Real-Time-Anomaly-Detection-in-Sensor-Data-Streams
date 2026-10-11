let API = localStorage.getItem("sentinelaq_api") || "http://localhost:8000";
let ws, reconnectTimer;
let overviewChart, verdictChart, liveChart, anomalyChart;
let selectedDevice = null;
let liveMetric = "pm25";
let liveSeries = {}; // device_id -> {labels:[], values:[], raw:[]}
let streamRows = 0;

const COLORS = { teal: "#0f7a5c", blue: "#2563eb", green: "#15803d", amber: "#b45309", red: "#c0272d" };
const COLORS_DARK = { teal: "#27c78d", blue: "#5b9dff", green: "#35c97f", amber: "#e2a33b", red: "#ec5b5b" };

function palette() { return isDark() ? COLORS_DARK : COLORS; }
function isDark() { return document.documentElement.getAttribute("data-theme") === "dark"; }
function gridColor() { return isDark() ? "rgba(255,255,255,.06)" : "#eef2f0"; }
function tickColor() { return isDark() ? "#9aaba2" : "#5b6b63"; }

function wsURL() {
  try {
    const u = new URL(API);
    const proto = u.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${u.host}/ws/live`;
  } catch {
    return "ws://localhost:8000/ws/live";
  }
}

// ---------------- Theme ----------------
function applyTheme(mode) {
  document.documentElement.setAttribute("data-theme", mode);
  localStorage.setItem("sentinelaq_theme", mode);
  restyleCharts();
}
(function initTheme() {
  const saved = localStorage.getItem("sentinelaq_theme");
  applyTheme(saved === "dark" ? "dark" : "light");
})();
document.getElementById("themeToggle").addEventListener("click", () => {
  applyTheme(isDark() ? "light" : "dark");
});

function restyleCharts() {
  const p = palette();
  const g = gridColor(), t = tickColor();
  [overviewChart, liveChart, anomalyChart].forEach(c => {
    if (!c) return;
    if (c.options.scales?.x) { c.options.scales.x.grid.color = g; c.options.scales.x.ticks.color = t; }
    if (c.options.scales?.y) { c.options.scales.y.grid.color = g; c.options.scales.y.ticks.color = t; }
  });
  if (overviewChart) {
    overviewChart.data.datasets[0].borderColor = p.teal;
    overviewChart.data.datasets[0].backgroundColor = isDark() ? "rgba(39,199,141,.12)" : "rgba(15,122,92,.08)";
    overviewChart.update();
  }
  if (liveChart) {
    liveChart.data.datasets[0].borderColor = p.blue;
    liveChart.data.datasets[0].backgroundColor = isDark() ? "rgba(91,157,255,.14)" : "rgba(37,99,235,.08)";
    liveChart.update();
  }
  if (anomalyChart) { anomalyChart.data.datasets[0].backgroundColor = p.red; anomalyChart.update(); }
  if (verdictChart) {
    verdictChart.data.datasets[0].backgroundColor = [p.green, p.amber, p.red];
    verdictChart.options.plugins.legend.labels.color = t;
    verdictChart.update();
  }
}

// ---------------- API base config ----------------
const apiInput = document.getElementById("apiBase");
apiInput.value = API;
document.getElementById("apiSave").addEventListener("click", () => {
  API = apiInput.value.trim().replace(/\/$/, "");
  localStorage.setItem("sentinelaq_api", API);
  resetAndReconnect();
});

function resetAndReconnect() {
  if (ws) { try { ws.close(); } catch {} }
  liveSeries = {};
  document.getElementById("deviceSelect").innerHTML = "";
  document.querySelector("#streamTable tbody").innerHTML = "";
  streamRows = 0;
  document.getElementById("streamCount").textContent = "0 readings";
  toggleEmpty("streamEmpty", true);
  pollAggregates();
  connectWS();
}

// ---------------- Sidebar / nav ----------------
const sidebar = document.getElementById("sidebar");
const scrim = document.getElementById("scrim");
const titles = {
  overview: ["Overview", "Network health in the last hour"],
  stream: ["Live Stream", "Readings as they arrive from the socket"],
  devices: ["Devices", "Fleet status at a glance"],
  analysis: ["Analysis", "Anomaly breakdown and flagged events"],
};

function openNav(section) {
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.section === section));
  document.querySelectorAll(".panel").forEach(p => p.classList.add("hidden"));
  document.getElementById(section).classList.remove("hidden");
  const [title, sub] = titles[section] || [section, ""];
  document.getElementById("pageTitle").textContent = title;
  document.getElementById("pageSub").textContent = sub;
  closeSidebar();
}
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => openNav(btn.dataset.section));
});

function closeSidebar() { sidebar.classList.remove("open"); scrim.classList.remove("show"); }
document.getElementById("menuBtn").addEventListener("click", () => {
  sidebar.classList.toggle("open");
  scrim.classList.toggle("show");
});
scrim.addEventListener("click", closeSidebar);

// ---------------- Clock ----------------
function tickClock() {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString();
}
setInterval(tickClock, 1000);
tickClock();

// ---------------- Fetch helpers ----------------
async function getJSON(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(path + " failed: " + res.status);
  return res.json();
}

function fmt(n, d = 1) { return (n === null || n === undefined) ? "—" : Number(n).toFixed(d); }
function timeOnly(iso) { try { return new Date(iso).toLocaleTimeString(); } catch { return iso; } }
function toggleEmpty(id, show) { const el = document.getElementById(id); if (el) el.hidden = !show; }

// ---------------- Charts setup ----------------
function initCharts() {
  const g = gridColor(), t = tickColor(), p = palette();

  overviewChart = new Chart(document.getElementById("overviewChart"), {
    type: "line",
    data: { labels: [], datasets: [{ label: "Avg PM2.5", data: [], borderColor: p.teal, backgroundColor: "rgba(15,122,92,.08)", fill: true, tension: .35, pointRadius: 0, borderWidth: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      scales: { x: { grid: { color: g }, ticks: { maxTicksLimit: 8, color: t } }, y: { grid: { color: g }, ticks: { color: t }, beginAtZero: true } },
      plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
      interaction: { mode: "index", intersect: false } }
  });

  verdictChart = new Chart(document.getElementById("verdictChart"), {
    type: "doughnut",
    data: { labels: ["Valid", "Review", "Invalid"], datasets: [{ data: [0, 0, 0], backgroundColor: [p.green, p.amber, p.red], borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: "68%", plugins: { legend: { display: false } } }
  });

  liveChart = new Chart(document.getElementById("liveChart"), {
    type: "line",
    data: { labels: [], datasets: [{ label: "PM2.5", data: [], borderColor: p.blue, backgroundColor: "rgba(37,99,235,.08)", fill: true, tension: .3, pointRadius: 2, borderWidth: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      scales: { x: { grid: { color: g }, ticks: { maxTicksLimit: 10, color: t } }, y: { grid: { color: g }, ticks: { color: t } } },
      plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
      interaction: { mode: "index", intersect: false } }
  });

  anomalyChart = new Chart(document.getElementById("anomalyChart"), {
    type: "bar",
    data: { labels: [], datasets: [{ label: "Count", data: [], backgroundColor: p.red, borderRadius: 6, maxBarThickness: 46 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      scales: {
        x: { grid: { display: false }, ticks: { color: t, autoSkip: true, maxRotation: window.innerWidth < 680 ? 45 : 0, minRotation: 0, font: { size: window.innerWidth < 680 ? 10 : 12 } } },
        y: { grid: { color: g }, ticks: { color: t }, beginAtZero: true }
      },
      plugins: { legend: { display: false } } }
  });

  renderVerdictLegend();
}

function renderVerdictLegend() {
  const items = [["Valid", "var(--green)"], ["Review", "var(--amber)"], ["Invalid", "var(--red)"]];
  document.getElementById("verdictLegend").innerHTML = items.map(([label, color]) =>
    `<span style="display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted);font-weight:600;">
      <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;"></span>${label}
     </span>`).join("");
}

// ---------------- Overview ----------------
async function refreshOverview() {
  const o = await getJSON("/api/overview");
  document.getElementById("kpiDevices").textContent = o.devices;
  document.getElementById("kpiModel").textContent = "model: " + o.model;
  document.getElementById("kpiReadings").textContent = o.stored_readings;
  document.getElementById("kpiTicks").textContent = o.live_ticks + " live ticks";
  document.getElementById("kpiValidPct").textContent = o.valid_pct + "%";
  document.getElementById("kpiValidCount").textContent = o.valid + " valid readings";
  document.getElementById("kpiReview").textContent = o.review;
  document.getElementById("kpiInvalid").textContent = o.invalid;
  document.getElementById("kpiConfidence").textContent = fmt(o.mean_confidence, 2);
  document.getElementById("kpiEvents").textContent = o.pollution_events + " pollution events";

  verdictChart.data.datasets[0].data = [o.valid, o.review, o.invalid];
  verdictChart.update();
}

async function refreshOverviewSeries() {
  const rows = await getJSON("/api/timeseries?minutes=30&limit=800");
  const byTime = {};
  rows.forEach(r => {
    if (r.pm25 === null) return;
    const key = new Date(r.timestamp).toLocaleTimeString();
    (byTime[key] = byTime[key] || []).push(r.pm25);
  });
  const labels = Object.keys(byTime).slice(-40);
  const values = labels.map(k => {
    const arr = byTime[k];
    return arr.reduce((a, b) => a + b, 0) / arr.length;
  });
  overviewChart.data.labels = labels;
  overviewChart.data.datasets[0].data = values;
  overviewChart.update();
}

async function refreshCityTable() {
  const rows = await getJSON("/api/cities");
  const tbody = document.querySelector("#cityTable tbody");
  toggleEmpty("cityEmpty", rows.length === 0);
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td><strong>${r.city}</strong></td>
      <td>${r.readings}</td>
      <td>${fmt(r.avg_pm25)}</td>
      <td>${r.valid}</td>
      <td>${r.review}</td>
      <td>${r.invalid}</td>
    </tr>`).join("");
}

// ---------------- Devices ----------------
async function refreshDeviceSelect() {
  const devices = await getJSON("/api/devices");
  const sel = document.getElementById("deviceSelect");
  if (sel.options.length === 0 && devices.length) {
    sel.innerHTML = devices.map(d => `<option value="${d.device_id}">${d.device_id} — ${d.city || ""}</option>`).join("");
    selectedDevice = devices[0]?.device_id || null;
  }
  document.getElementById("deviceFleetSub").textContent = devices.length + " devices online";
  toggleEmpty("deviceEmpty", devices.length === 0);
  renderDeviceGrid(devices);
}

function renderDeviceGrid(devices) {
  const grid = document.getElementById("deviceGrid");
  grid.innerHTML = devices.map(d => {
    const r = d.latest;
    const badge = r ? `<span class="badge badge-${r.verdict}">${r.verdict}</span>` : `<span class="badge">—</span>`;
    return `
    <div class="device-card">
      <div class="dc-top"><span class="dc-id">${d.device_id}</span>${badge}</div>
      <span class="dc-city">${d.city || "—"}</span>
      <div class="dc-metrics">
        <div class="dc-metric"><div class="v">${r ? fmt(r.pm25) : "—"}</div><div class="l">PM2.5</div></div>
        <div class="dc-metric"><div class="v">${r ? fmt(r.temp) : "—"}</div><div class="l">Temp</div></div>
        <div class="dc-metric"><div class="v">${r ? fmt(r.rh) : "—"}</div><div class="l">RH</div></div>
      </div>
    </div>`;
  }).join("");
}

// ---------------- Live stream ----------------
document.getElementById("deviceSelect").addEventListener("change", e => { selectedDevice = e.target.value; redrawLiveChart(); });
document.getElementById("metricSelect").addEventListener("change", e => { liveMetric = e.target.value; redrawLiveChart(); });

function redrawLiveChart() {
  const s = liveSeries[selectedDevice] || { labels: [], values: [] };
  liveChart.data.labels = s.labels;
  liveChart.data.datasets[0].data = s.values;
  liveChart.data.datasets[0].label = { pm25: "PM2.5 (µg/m³)", temp: "Temperature (°C)", rh: "Humidity (%)" }[liveMetric];
  liveChart.update();
}

function pushLiveReading(r) {
  if (!liveSeries[r.device_id]) liveSeries[r.device_id] = { labels: [], values: [], raw: [] };
  const s = liveSeries[r.device_id];
  s.labels.push(timeOnly(r.timestamp));
  s.values.push(r[liveMetric]);
  s.raw.push(r);
  if (s.labels.length > 60) { s.labels.shift(); s.values.shift(); s.raw.shift(); }
}

function prependStreamRow(r) {
  toggleEmpty("streamEmpty", false);
  const tbody = document.querySelector("#streamTable tbody");
  const tr = document.createElement("tr");
  tr.className = "flash";
  tr.innerHTML = `
    <td>${timeOnly(r.timestamp)}</td>
    <td>${r.device_id}</td>
    <td>${r.city}</td>
    <td>${fmt(r.pm25)}</td>
    <td>${fmt(r.temp)}</td>
    <td>${fmt(r.rh)}</td>
    <td><span class="badge badge-${r.verdict}">${r.verdict}</span></td>
    <td>${r.detected_as}</td>
    <td>${fmt(r.confidence, 2)}</td>`;
  tbody.prepend(tr);
  while (tbody.children.length > 120) tbody.removeChild(tbody.lastChild);
  streamRows++;
  document.getElementById("streamCount").textContent = streamRows + " readings";
}

function prependAlertRow(r) {
  if (r.verdict === "VALID") return;
  toggleEmpty("alertEmpty", false);
  const tbody = document.querySelector("#alertTable tbody");
  const tr = document.createElement("tr");
  tr.className = "flash";
  tr.innerHTML = `
    <td>${timeOnly(r.timestamp)}</td>
    <td>${r.device_id}</td>
    <td><span class="badge badge-${r.verdict}">${r.verdict}</span></td>
    <td>${r.reason || ""}</td>`;
  tbody.prepend(tr);
  while (tbody.children.length > 60) tbody.removeChild(tbody.lastChild);
}

// ---------------- Analysis ----------------
async function refreshAnomalyChart() {
  const b = await getJSON("/api/anomalies/breakdown");
  anomalyChart.data.labels = Object.keys(b);
  anomalyChart.data.datasets[0].data = Object.values(b);
  anomalyChart.update();
}

// ---------------- WebSocket ----------------
function connectWS() {
  try { ws = new WebSocket(wsURL()); } catch { setConn(false); return; }
  ws.onopen = () => setConn(true);
  ws.onclose = () => { setConn(false); clearTimeout(reconnectTimer); reconnectTimer = setTimeout(connectWS, 2500); };
  ws.onerror = () => ws.close();
  ws.onmessage = ev => {
    const batch = JSON.parse(ev.data);
    batch.forEach(r => { pushLiveReading(r); prependStreamRow(r); prependAlertRow(r); });
    redrawLiveChart();
  };
}

function setConn(ok) {
  const pill = document.getElementById("connStatus");
  const label = document.getElementById("connLabel");
  pill.classList.toggle("down", !ok);
  label.textContent = ok ? "Live" : "Reconnecting…";
}

// ---------------- Poll (lower-frequency aggregates) ----------------
async function pollAggregates() {
  try {
    await Promise.all([refreshOverview(), refreshOverviewSeries(), refreshCityTable(), refreshDeviceSelect(), refreshAnomalyChart()]);
  } catch (e) { console.error("Dashboard: couldn't reach API at", API, e); setConn(false); }
}

// ---------------- Boot ----------------
(async function init() {
  initCharts();
  toggleEmpty("streamEmpty", true);
  await pollAggregates();
  connectWS();
  setInterval(pollAggregates, 5000);
})();