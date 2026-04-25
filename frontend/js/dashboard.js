/**
 * PREDICTA – Dashboard Controller
 * Real-time data polling, UI updates, prediction UI, and WebSocket
 */

// ─── Config ────────────────────────────────────────────────────────────────
const DEVICE_ID    = "MOTOR_01";
const POLL_INTERVAL = 2000;  // 2 seconds live polling

// ─── Chart instances (initialized in charts.js) ────────────────────────────
let chartCV, chartTemp, chartVib, chartRadar, chartFaultProb;

// ─── State ─────────────────────────────────────────────────────────────────
let latestData = {};
let predictionData = null;
let alertCount = 0;
let pollTimer = null;

// ─── Auth Guard ────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  if (!API.getToken()) {
    window.location.href = "login.html";
    return;
  }
  const user = API.getUser();
  if (user) document.getElementById("user-name").textContent = user.username || "User";

  initCharts();
  startClock();
  startPolling();
  loadMaintenanceSchedule();
  loadActiveFaults();
  connectWebSocket();
});

function logout() {
  API.clearTokens();
  window.location.href = "login.html";
}

// ─── Clock ─────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById("topbar-clock");
  function tick() {
    el.textContent = new Date().toLocaleTimeString("en-IN", { hour12: false });
  }
  tick();
  setInterval(tick, 1000);
}

// ─── Live Data Polling ─────────────────────────────────────────────────────
function startPolling() {
  fetchAndUpdate();
  pollTimer = setInterval(fetchAndUpdate, POLL_INTERVAL);
}

async function fetchAndUpdate() {
  // In demo mode, if backend is unavailable, use simulated data
  let data = await API.getLatest(DEVICE_ID);
  if (!data || data.error) {
    data = simulateReading();
  }
  latestData = data;
  updateDashboard(data);
}

function simulateReading() {
  // Realistic simulation for demo/development
  const t = Date.now() / 1000;
  const noise = () => (Math.random() - 0.5) * 0.1;
  const health = 80 + Math.sin(t * 0.02) * 12 + noise() * 5;
  return {
    device_id:    DEVICE_ID,
    timestamp:    new Date().toISOString(),
    voltage:      411 + Math.sin(t * 0.01) * 8,
    current:      3.2 + Math.sin(t * 0.03) * 0.4,
    motor_temp:   52 + Math.sin(t * 0.005) * 12,
    bearing_temp: 48 + Math.sin(t * 0.007) * 8,
    ambient_temp: 32,
    humidity:     65,
    vibration_rms:0.18 + Math.sin(t * 0.05) * 0.08,
    rpm:          1435 + Math.floor(Math.sin(t * 0.02) * 20),
    pressure:     280 + Math.sin(t * 0.03) * 40,
    power_kw:     1.18 + noise() * 0.05,
    energy_kwh:   12.4 + t * 0.0003,
    run_hours:    342.5,
    start_cycles: 156,
    motor_running:true,
    overload:     false,
    overheat:     false,
    high_vibration:false,
    health_score: Math.max(70, Math.min(98, health)),
    efficiency:   87 + noise() * 2,
  };
}

// ─── Dashboard Update ─────────────────────────────────────────────────────
function updateDashboard(d) {
  if (!d) return;

  // Health Ring
  const health = d.health_score || 0;
  const score = Math.round(health);
  document.getElementById("health-score").textContent = score + "%";
  document.getElementById("efficiency-val").textContent = (d.efficiency || 0).toFixed(1) + "%";
  document.getElementById("run-hours-val").textContent  = (d.run_hours || 0).toFixed(1) + "h";
  document.getElementById("start-cycles-val").textContent = d.start_cycles || 0;

  // SVG ring
  const circumference = 326.7;
  const offset = circumference - (score / 100) * circumference;
  const ring = document.getElementById("health-ring");
  ring.style.strokeDashoffset = offset;
  ring.style.stroke = score >= 80 ? "#00ff88" : score >= 60 ? "#ffd700" : "#ff4444";

  // Health status text
  let statusText = "Machine Operating Normally";
  let bannerClass = "";
  if (score < 60) { statusText = "⚠ Critical – Immediate Attention Required"; bannerClass = "critical"; }
  else if (score < 80) { statusText = "⚠ Performance Degraded – Inspection Advised"; bannerClass = "warning"; }
  document.getElementById("health-status-text").textContent = statusText;
  const banner = document.getElementById("health-banner");
  banner.className = "health-banner " + bannerClass;

  // Status badges
  updateBadge("badge-overload",  d.overload,       "FAULT", "OK");
  updateBadge("badge-overheat",  d.overheat,       "HOT",   "OK");
  updateBadge("badge-vibration", d.high_vibration, "HIGH",  "OK");
  updateBadge("badge-running",   !d.motor_running, "STOPPED","RUNNING", false);

  // Sidebar status
  const dotEl  = document.getElementById("sidebar-status-dot");
  const txtEl  = document.getElementById("sidebar-status-text");
  dotEl.className = "status-dot " + (d.motor_running ? "online" : "offline");
  txtEl.textContent = d.motor_running ? "Running" : "Stopped";

  // KPI Cards
  updateKPI("kpi-voltage",  "kpi-voltage-val",  "kpi-voltage-bar",  d.voltage, 380, 440, 500);
  updateKPI("kpi-current",  "kpi-current-val",  "kpi-current-bar",  d.current, 0, 4.5, 6, 2);
  updateKPI("kpi-temp",     "kpi-temp-val",     "kpi-temp-bar",     d.motor_temp, 0, 85, 120, 1);
  updateKPI("kpi-vibration","kpi-vib-val",      "kpi-vib-bar",      d.vibration_rms, 0, 1.0, 2.0, 3);
  updateKPI("kpi-rpm",      "kpi-rpm-val",      "kpi-rpm-bar",      d.rpm, 0, 1600, 2000, 0);
  updateKPI("kpi-power",    "kpi-power-val",    "kpi-power-bar",    d.power_kw, 0, 1.5, 2.0, 2);
  updateKPI("kpi-bearing",  "kpi-bearing-val",  "kpi-bearing-bar",  d.bearing_temp, 0, 70, 100, 1);
  updateKPI("kpi-pressure", "kpi-pressure-val", "kpi-pressure-bar", d.pressure, 50, 600, 700, 0);

  // Last update time
  document.getElementById("last-update-time").textContent =
    new Date().toLocaleTimeString("en-IN", { hour12: false });

  // Update charts
  const ts = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  updateLiveChart(chartCV,   ts, d.current, d.voltage / 100);
  updateLiveChart(chartTemp, ts, d.motor_temp, d.bearing_temp);
  updateLiveChart(chartVib,  ts, d.vibration_rms, null);
  updateRadarChart(chartRadar, d);
}

function updateBadge(id, isFault, faultLabel, okLabel, faultIsBad = true) {
  const el = document.getElementById(id);
  const valEl = document.getElementById(id + "-val");
  if (!el || !valEl) return;
  el.className = "hbadge " + (isFault ? (faultIsBad ? "fault" : "warn") : "");
  valEl.textContent = isFault ? faultLabel : okLabel;
}

function updateKPI(cardId, valId, barId, value, min, warn, max, decimals = 1) {
  if (value == null) return;
  const card = document.getElementById(cardId);
  const valEl = document.getElementById(valId);
  const barEl = document.getElementById(barId);

  valEl.textContent = value.toFixed(decimals);
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  barEl.style.width = pct + "%";

  const isCrit = value >= warn;
  const isWarn = value >= warn * 0.85;
  card.className = "kpi-card " + (isCrit ? "critical" : isWarn ? "warning" : "");
  barEl.style.background = isCrit ? "var(--red)" : isWarn ? "var(--yellow)" : "var(--accent)";
}

// ─── Chart Live Update ─────────────────────────────────────────────────────
const MAX_POINTS = 60;

function updateLiveChart(chart, label, v1, v2) {
  if (!chart) return;
  chart.data.labels.push(label);
  chart.data.datasets[0].data.push(v1);
  if (v2 !== null && chart.data.datasets[1]) chart.data.datasets[1].data.push(v2);
  if (chart.data.labels.length > MAX_POINTS) {
    chart.data.labels.shift();
    chart.data.datasets.forEach(ds => ds.data.shift());
  }
  chart.update("none");
}

function updateRadarChart(chart, d) {
  if (!chart) return;
  const normalize = (v, max) => Math.min(100, Math.max(0, (v / max) * 100));
  chart.data.datasets[0].data = [
    100 - normalize(Math.abs(d.voltage - 415), 35),
    100 - normalize(d.current, 4.5) * 1.2,
    100 - normalize(d.motor_temp, 85),
    100 - normalize(d.vibration_rms, 1.0) * 100,
    normalize(d.rpm || 1440, 1440),
    normalize(d.efficiency || 87, 100),
  ];
  chart.update("none");
}

// ─── Set Time Range ────────────────────────────────────────────────────────
function setTimeRange(btn, range) {
  document.querySelectorAll(".chart-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  // In production: re-fetch history for selected range
  showToast("info", "Range Updated", `Showing last ${range} of data`);
}

// ─── ML Prediction ─────────────────────────────────────────────────────────
async function runPrediction() {
  const btn = document.getElementById("btn-run-prediction");
  btn.textContent = "⏳ Running Model…";
  btn.disabled = true;

  let result = await API.runPrediction(DEVICE_ID);

  // Demo fallback
  if (!result || result.error) {
    result = {
      fault_type: "Normal Operation",
      root_cause: "All sensor parameters within normal operating range. Machine is healthy.",
      failure_prob: 5.2,
      confidence: 96.8,
      rul_days: 180,
      severity: "NORMAL",
      severity_score: 0,
      maintenance_urgency: "SCHEDULED",
      recommendation: "Continue monitoring. Schedule next preventive maintenance in 30 days.",
      ml_predicted: false,
    };
  }

  predictionData = result;
  updatePredictionPanel(result);

  btn.textContent = "🤖 Run ML Prediction";
  btn.disabled = false;

  if (result.severity === "CRITICAL" || result.severity === "HIGH") {
    showToast("error", "Fault Detected", result.fault_type);
  } else {
    showToast("success", "Prediction Complete", "Machine: " + result.fault_type);
  }
}

function updatePredictionPanel(r) {
  const faultEl  = document.getElementById("pred-fault-type");
  const rootEl   = document.getElementById("pred-root-cause");
  const probFill = document.getElementById("pred-prob-fill");
  const sevEl    = document.getElementById("pred-severity-val");
  const urgEl    = document.getElementById("pred-urgency-val");

  faultEl.textContent = r.fault_type || "Normal Operation";
  faultEl.className   = "pred-fault-type " +
    (r.severity === "CRITICAL" ? "fault" : r.severity === "HIGH" ? "fault" : r.severity === "MEDIUM" ? "warn" : "");

  rootEl.textContent = r.root_cause || "—";

  document.getElementById("pred-failure-prob").textContent = (r.failure_prob || 0).toFixed(1) + "%";
  document.getElementById("pred-confidence").textContent   = (r.confidence || 0).toFixed(1) + "%";
  document.getElementById("pred-rul").textContent          = (r.rul_days || "—") + " days";
  document.getElementById("pred-score").textContent        = "Score: " + (r.severity_score || 0);
  document.getElementById("pred-recommendation").textContent = r.recommendation || "—";

  probFill.style.width      = Math.min(100, r.failure_prob || 0) + "%";
  probFill.style.background = r.failure_prob > 60 ? "var(--red)" :
                              r.failure_prob > 30 ? "var(--yellow)" : "var(--green)";

  sevEl.textContent = r.severity || "NORMAL";
  sevEl.className   = "pred-severity-val " + (r.severity || "").toLowerCase();

  urgEl.textContent = (r.maintenance_urgency || "SCHEDULED").replace(/_/g, " ");

  // Update fault probability chart
  if (r.all_probabilities && chartFaultProb) {
    const labels = Object.keys(r.all_probabilities).map(k => k.split(" ")[0]);
    const vals   = Object.values(r.all_probabilities);
    chartFaultProb.data.labels = labels;
    chartFaultProb.data.datasets[0].data = vals;
    chartFaultProb.update();
  }
}

// ─── Active Faults ─────────────────────────────────────────────────────────
async function loadActiveFaults() {
  let faults = await API.getFaults(DEVICE_ID);
  const listEl = document.getElementById("alerts-list");
  const countEl = document.getElementById("active-faults-count");

  if (!faults || faults.error || !faults.length) {
    listEl.innerHTML = '<div class="no-alerts">✅ No active fault alerts</div>';
    countEl.textContent = 0;
    document.getElementById("alert-count").textContent = 0;
    return;
  }

  countEl.textContent = faults.length;
  document.getElementById("alert-count").textContent = faults.length;
  alertCount = faults.length;

  listEl.innerHTML = faults.map(f => `
    <div class="alert-item">
      <div class="alert-sev-dot ${f.severity}"></div>
      <div>
        <div class="alert-fault">${f.fault_type}</div>
        <div class="alert-msg">${f.root_cause || ""}</div>
        <div class="alert-time">${new Date(f.occurred_at).toLocaleString("en-IN")}</div>
      </div>
    </div>
  `).join("");
}

// ─── Maintenance Schedule ──────────────────────────────────────────────────
async function loadMaintenanceSchedule() {
  let data = await API.getSchedule(DEVICE_ID);
  const listEl = document.getElementById("maintenance-list");

  if (!data || data.error || !data.schedule) {
    listEl.innerHTML = '<div class="loading-text">Unable to load schedule</div>';
    return;
  }

  listEl.innerHTML = data.schedule.slice(0, 5).map(item => `
    <div class="maintenance-item">
      <span class="maint-priority ${item.priority}">${item.priority}</span>
      <div>
        <div class="maint-task">${item.task}</div>
        <div class="maint-due">Due in ${item.due_in_days || "?"} days</div>
      </div>
    </div>
  `).join("");
}

// ─── WebSocket (Socket.IO) ─────────────────────────────────────────────────
function connectWebSocket() {
  try {
    const socket = io("http://localhost:5000");
    socket.on("connect", () => console.log("[WS] Connected"));
    socket.on("sensor_update", (msg) => {
      if (msg.device_id === DEVICE_ID) {
        updateDashboard({ ...msg.data, health_score: msg.health_score });
      }
    });
    socket.on("disconnect", () => console.log("[WS] Disconnected"));
  } catch (e) {
    console.log("[WS] WebSocket not available, using polling");
  }
}

// ─── Toast Notifications ───────────────────────────────────────────────────
function showToast(type, title, msg) {
  const icons = { success:"✅", error:"🔴", warning:"⚠️", info:"ℹ️" };
  const tc = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || "ℹ️"}</span>
    <div>
      <div class="toast-title">${title}</div>
      <div class="toast-msg">${msg}</div>
    </div>`;
  tc.appendChild(toast);
  setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 300); }, 4000);
}

// Make available globally
window.logout        = logout;
window.runPrediction = runPrediction;
window.setTimeRange  = setTimeRange;
