/**
 * PREDICTA – Segment B Live Monitor Controller
 * Device selection, live telemetry, health verdict, trend forecast, device registration.
 * Shows only real readings: when a device has no data the page says so (no simulated values).
 */

// ─── Config ────────────────────────────────────────────────────────────────
let DEVICE_ID = API.getSelectedDevice();
const POLL_INTERVAL = 3000;         // latest reading
const ASSESS_INTERVAL = 15000;      // full re-evaluation (server caches for 15 s)

// ─── Chart instances (initialized in charts.js) ────────────────────────────
let chartCV, chartTemp, chartVib, chartRadar, chartFaultProb;

// ─── State ─────────────────────────────────────────────────────────────────
let latestData = {};
let predictionData = null;
let alertCount = 0;
let lastReadingId = null;
let fleet = [];

// ─── Auth Guard ────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  if (!API.getToken()) {
    API.toLogin();
    return;
  }
  const user = API.getUser();
  if (user) document.getElementById("user-name").textContent = user.username || "User";
  if (!user || !["admin", "engineer"].includes(user.role)) {
    document.querySelectorAll("[onclick='openRegisterModal()'], #btn-rotate-key").forEach(b => b.style.display = "none");
  }

  initCharts();
  startClock();
  await loadFleet();
  selectDevice(DEVICE_ID);
  setInterval(fetchAndUpdate, POLL_INTERVAL);
  setInterval(loadAssessment, ASSESS_INTERVAL);
  setInterval(loadFleet, 30000);
  connectWebSocket();
});

function logout() {
  API.clearTokens();
  API.toLogin(true);
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

// ─── Fleet & device selection ──────────────────────────────────────────────
async function loadFleet() {
  const data = await API.getFleet();
  if (!Array.isArray(data)) return;
  fleet = data;
  const select = document.getElementById("device-select");
  const current = DEVICE_ID;
  select.innerHTML = fleet.map(d => {
    const status = d.assessment?.status || (d.last_seen ? "" : "no data");
    const dot = d.online ? "● " : "○ ";
    return `<option value="${API.esc(d.device_id)}">${dot}${API.esc(d.device_id)} – ${API.esc(d.name)}${status ? " (" + API.esc(status) + ")" : ""}</option>`;
  }).join("");
  if (fleet.some(d => d.device_id === current)) select.value = current;
  else if (fleet.length) DEVICE_ID = fleet[0].device_id;
  renderDeviceInfo();
}

function renderDeviceInfo() {
  const d = fleet.find(x => x.device_id === DEVICE_ID);
  const badge = document.getElementById("device-online-badge");
  const keyInfo = document.getElementById("device-key-info");
  if (!d) { badge.textContent = "—"; keyInfo.textContent = ""; return; }
  badge.textContent = d.online ? "ONLINE" : (d.last_seen ? "OFFLINE" : "NO DATA");
  badge.style.color = d.online ? "var(--green)" : "var(--text-muted)";
  badge.style.background = d.online ? "rgba(0,255,136,0.12)" : "rgba(255,255,255,0.05)";
  keyInfo.textContent = d.streaming_enabled
    ? `Streaming key ${d.key_prefix}… · last seen ${d.last_seen ? new Date(d.last_seen + "Z").toLocaleString("en-IN") : "never"}`
    : "No streaming key – register this device to accept telemetry";
}

function selectDevice(deviceId) {
  if (!deviceId) return;
  DEVICE_ID = deviceId;
  API.setSelectedDevice(deviceId);
  document.getElementById("sidebar-device-id").textContent = deviceId;
  lastReadingId = null;
  [chartCV, chartTemp, chartVib].forEach(c => {
    if (!c) return;
    c.data.labels = [];
    c.data.datasets.forEach(ds => ds.data = []);
    c.update("none");
  });
  renderDeviceInfo();
  fetchAndUpdate();
  loadAssessment(true);
  loadMaintenanceSchedule();
  loadActiveFaults();
}

// ─── Live Data Polling ─────────────────────────────────────────────────────
async function fetchAndUpdate() {
  const data = await API.getLatest(DEVICE_ID);
  if (!data || data.error) {
    showNoData();
    return;
  }
  if (data.id === lastReadingId) return;   // nothing new
  lastReadingId = data.id;
  latestData = data;
  updateDashboard(data);
}

function showNoData() {
  document.getElementById("health-score").textContent = "--";
  document.getElementById("health-status-text").textContent =
    "No readings from this device yet. Register it and start streaming (ESP32 firmware or backend/simulator.py).";
  document.getElementById("sidebar-status-dot").className = "status-dot offline";
  document.getElementById("sidebar-status-text").textContent = "No data";
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

  // Health status text (instantaneous reading; the verdict above covers trends)
  let statusText = "Latest reading within normal range";
  let bannerClass = "";
  if (score < 60) { statusText = "⚠ Latest reading critical – immediate attention"; bannerClass = "critical"; }
  else if (score < 80) { statusText = "⚠ Latest reading degraded – inspection advised"; bannerClass = "warning"; }
  document.getElementById("health-status-text").textContent = statusText;
  document.getElementById("health-banner").className = "health-banner " + bannerClass;

  // Status badges
  updateBadge("badge-overload",  d.overload,       "FAULT", "OK");
  updateBadge("badge-overheat",  d.overheat,       "HOT",   "OK");
  updateBadge("badge-vibration", d.high_vibration, "HIGH",  "OK");
  updateBadge("badge-running",   !d.motor_running, "STOPPED","RUNNING", false);

  // Sidebar status
  document.getElementById("sidebar-status-dot").className = "status-dot " + (d.motor_running ? "online" : "offline");
  document.getElementById("sidebar-status-text").textContent = d.motor_running ? "Running" : "Stopped";

  // KPI Cards
  // Limits match the analytics engine's DEFAULT_ENGINEERING_LIMITS
  updateKPI("kpi-voltage",  "kpi-voltage-val",  "kpi-voltage-bar",  d.voltage, 340, 500, 1, { warn: 440, crit: 460, lowWarn: 380, lowCrit: 360 });
  updateKPI("kpi-current",  "kpi-current-val",  "kpi-current-bar",  d.current, 0, 6, 2, { warn: 4.2, crit: 5.0 });
  updateKPI("kpi-temp",     "kpi-temp-val",     "kpi-temp-bar",     d.motor_temp, 0, 120, 1, { warn: 75, crit: 85 });
  updateKPI("kpi-vibration","kpi-vib-val",      "kpi-vib-bar",      d.vibration_rms, 0, 2.0, 3, { warn: 0.45, crit: 0.9 });
  updateKPI("kpi-rpm",      "kpi-rpm-val",      "kpi-rpm-bar",      d.rpm, 0, 2000, 0, { warn: 1580, lowWarn: 1250 });
  updateKPI("kpi-power",    "kpi-power-val",    "kpi-power-bar",    d.power_kw, 0, 2.0, 2, { warn: 1.5, crit: 1.8 });
  updateKPI("kpi-bearing",  "kpi-bearing-val",  "kpi-bearing-bar",  d.bearing_temp, 0, 100, 1, { warn: 70, crit: 80 });
  updateKPI("kpi-pressure", "kpi-pressure-val", "kpi-pressure-bar", d.pressure, 0, 700, 0, { warn: 550, lowWarn: 80 });

  // Reading time (server stores UTC without zone)
  const readingTime = d.timestamp ? new Date(d.timestamp + "Z") : new Date();
  document.getElementById("last-update-time").textContent =
    readingTime.toLocaleTimeString("en-IN", { hour12: false });

  // Update charts
  const ts = readingTime.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  updateLiveChart(chartCV,   ts, d.current, d.voltage != null ? d.voltage / 100 : null);
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

function updateKPI(cardId, valId, barId, value, min, max, decimals, limits) {
  if (value == null) return;
  const card = document.getElementById(cardId);
  const valEl = document.getElementById(valId);
  const barEl = document.getElementById(barId);

  valEl.textContent = value.toFixed(decimals);
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  barEl.style.width = pct + "%";

  const { warn = Infinity, crit = Infinity, lowWarn = -Infinity, lowCrit = -Infinity } = limits;
  const isCrit = value >= crit || value <= lowCrit;
  const isWarn = value >= warn || value <= lowWarn;
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
  const normalize = (v, max) => Math.min(100, Math.max(0, ((v || 0) / max) * 100));
  chart.data.datasets[0].data = [
    100 - normalize(Math.abs((d.voltage || 415) - 415), 35),
    100 - normalize(d.current, 4.5) * 1.2,
    100 - normalize(d.motor_temp, 85),
    100 - normalize(d.vibration_rms, 1.0) * 100,
    normalize(d.rpm || 1440, 1440),
    normalize(d.efficiency || 87, 100),
  ];
  chart.update("none");
}

// Chart range buttons: the live charts show the latest readings; history is on Health Trends
function setTimeRange(btn, range) {
  window.location.href = "analytics.html";
}

// ─── Health verdict & breakdown forecast ───────────────────────────────────
async function loadAssessment(refresh = false) {
  const a = await API.getAssessment(DEVICE_ID, refresh);
  if (!a || a.error) return;

  const statusEl = document.getElementById("verdict-status");
  const status = a.status || "NO_DATA";
  statusEl.textContent = status.replace("_", " ");
  statusEl.className = "verdict-status st-" + status;
  document.getElementById("verdict-headline").textContent = a.headline || "";
  document.getElementById("assessment-time").textContent = new Date().toLocaleTimeString("en-IN", { hour12: false });

  const ttb = a.time_to_breakdown;
  const ttbValue = document.getElementById("ttb-value");
  const ttbCi = document.getElementById("ttb-ci");
  if (ttb) {
    ttbValue.textContent = ttb.hours === 0 ? "Limit exceeded" : "≈ " + API.fmtHours(ttb.hours);
    ttbValue.style.color = ttb.hours === 0 ? "var(--red)" : "var(--orange)";
    const ci = ttb.ci_hours;
    ttbCi.textContent = `${ttb.variable}${ttb.limit != null ? " → " + ttb.limit + " " + (ttb.unit || "") : ""}` +
      (ci && ci[0] != null ? ` · 95% range ${API.fmtHours(ci[0])} – ${ci[1] != null ? API.fmtHours(ci[1]) : "longer"}` : "");
  } else {
    ttbValue.textContent = status === "NO_DATA" ? "—" : "No breakdown trend";
    ttbValue.style.color = status === "NO_DATA" ? "#fff" : "var(--green)";
    ttbCi.textContent = "";
  }

  renderTrendTable(a.trend_forecast, a.latest || {});
  renderCauses(a.hypotheses || []);

  if (a.status === "CRITICAL") alertCount = Math.max(alertCount, 1);
  document.getElementById("alert-count").textContent = alertCount;
}

function renderTrendTable(forecast, latest) {
  const tbody = document.getElementById("trend-tbody");
  const vars = (forecast && forecast.variables) || [];
  if (!vars.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-live">${API.esc(forecast?.reason || "Not enough readings to fit a trend yet.")}</td></tr>`;
    document.getElementById("trend-window").textContent = "";
    return;
  }
  const colors = {
    CRITICAL_LIMIT_EXCEEDED: "var(--red)", WARNING_LIMIT_EXCEEDED: "var(--orange)",
    APPROACHING_LIMIT: "var(--yellow)", DRIFTING: "var(--accent)", STABLE: "var(--green)", INSUFFICIENT_DATA: "var(--text-muted)",
  };
  const first = vars.find(v => v.window_hours != null);
  document.getElementById("trend-window").textContent = first ? `fitted on last ${API.fmtHours(first.window_hours)} of running data` : "";
  tbody.innerHTML = vars.map(v => {
    const now = latest[v.variable] != null ? latest[v.variable] : v.latest_value;
    // Not statistically significant → "flat", rather than a noisy number next to STABLE
    const slope = v.slope_per_hour == null ? "—"
      : v.direction === "STABLE" ? "flat"
      : (v.slope_per_hour > 0 ? "+" : "") + v.slope_per_hour.toFixed(3);
    return `<tr>
      <td style="color:#fff;">${API.esc(v.variable.replace(/_/g, " "))}</td>
      <td>${now != null ? Number(now).toFixed(2) : "—"} ${API.esc(v.unit || "")}</td>
      <td>${slope}${v.direction && v.direction !== "STABLE" ? " " + API.esc(v.unit || "") + " (" + v.direction.toLowerCase() + ")" : ""}</td>
      <td style="color:${colors[v.status] || "#fff"};font-weight:600;">${API.esc((v.status || "").replace(/_/g, " "))}</td>
      <td>${API.fmtHours(v.hours_to_warning)}</td>
      <td>${API.fmtHours(v.hours_to_critical)}</td>
    </tr>`;
  }).join("");
}

function renderCauses(hypotheses) {
  const el = document.getElementById("cause-list");
  const supported = hypotheses.filter(h => h.applicable);
  if (!supported.length) {
    el.innerHTML = `<div class="empty-live">No failure signature is supported by the current data (${hypotheses.length} evaluated).</div>`;
    return;
  }
  const color = { STRONG: "var(--red)", MODERATE: "var(--orange)", WEAK: "var(--yellow)" };
  el.innerHTML = supported.map(h => `
    <div class="cause-card">
      <div style="display:flex;justify-content:space-between;gap:8px;margin-bottom:6px;">
        <strong>${API.esc(h.hypothesis)}</strong>
        <span style="color:${color[h.confidence] || "#fff"};font-weight:700;font-size:11px;">${API.esc(h.confidence)}</span>
      </div>
      <div style="color:var(--text-dim);line-height:1.5;">${h.supporting_evidence.slice(0, 2).map(API.esc).join("<br/>")}</div>
      <div style="color:var(--green);margin-top:6px;">→ ${API.esc(h.recommended_actions[0] || "")}</div>
    </div>`).join("");
}

// ─── Device registration ───────────────────────────────────────────────────
function openRegisterModal() {
  document.getElementById("register-form").style.display = "";
  document.getElementById("register-result").style.display = "none";
  document.getElementById("register-modal").classList.add("open");
}

function closeRegisterModal() {
  document.getElementById("register-modal").classList.remove("open");
  document.getElementById("reg-key").textContent = "";
}

function showKey(deviceId, key) {
  document.getElementById("reg-key").textContent = key;
  document.getElementById("reg-curl").textContent =
    `curl -X POST ${API.BASE}/live/ingest -H "Content-Type: application/json" -H "X-Device-Key: ${key}" ` +
    `-d '{"device_id":"${deviceId}","motor_temp":55.2,"current":3.3,"vibration_rms":0.14}'`;
  document.getElementById("register-form").style.display = "none";
  document.getElementById("register-result").style.display = "";
  document.getElementById("register-modal").classList.add("open");
}

async function registerDevice() {
  const deviceId = document.getElementById("reg-device-id").value.trim();
  if (!deviceId) { showToast("warning", "Device ID required", "Use the same ID as in the firmware."); return; }
  const res = await API.registerDevice({
    device_id: deviceId,
    name: document.getElementById("reg-name").value.trim() || undefined,
    location: document.getElementById("reg-location").value.trim() || undefined,
  });
  if (!res || res.error) { showToast("error", "Registration failed", res?.error || "Unknown error"); return; }
  showKey(deviceId, res.device_key);
  await loadFleet();
  document.getElementById("device-select").value = deviceId;
  selectDevice(deviceId);
}

async function rotateKey() {
  if (!confirm(`Issue a new key for ${DEVICE_ID}? The current key stops working immediately.`)) return;
  const res = await API.rotateDeviceKey(DEVICE_ID);
  if (!res || res.error) { showToast("error", "Key rotation failed", res?.error || "Unknown error"); return; }
  showKey(DEVICE_ID, res.device_key);
  loadFleet();
}

// ─── Experimental fault-type classifier ────────────────────────────────────
async function runPrediction() {
  const btn = document.getElementById("btn-run-prediction");
  btn.textContent = "⏳ Running Model…";
  btn.disabled = true;

  const result = await API.runPrediction(DEVICE_ID);
  btn.textContent = "🤖 Classify Latest Reading";
  btn.disabled = false;

  if (!result || result.error) {
    showToast("error", "Classifier unavailable", result?.error || "No readings for this device yet.");
    return;
  }

  predictionData = result;
  updatePredictionPanel(result);

  if (result.severity === "CRITICAL" || result.severity === "HIGH") {
    showToast("error", "Fault Detected", result.fault_type);
  } else {
    showToast("success", "Classification Complete", "Machine: " + result.fault_type);
  }
}

function updatePredictionPanel(r) {
  const faultEl  = document.getElementById("pred-fault-type");
  const rootEl   = document.getElementById("pred-root-cause");
  const probFill = document.getElementById("pred-prob-fill");
  const sevEl    = document.getElementById("pred-severity");
  const urgEl    = document.getElementById("pred-urgency");

  faultEl.textContent = r.fault_type || "Normal Operation";
  faultEl.className   = "pred-fault-type " +
    (r.severity === "CRITICAL" ? "fault" : r.severity === "HIGH" ? "fault" : r.severity === "MEDIUM" ? "warn" : "");

  rootEl.textContent = r.root_cause || "—";

  document.getElementById("pred-failure-prob").textContent = (r.failure_prob || 0).toFixed(1) + "%";
  document.getElementById("pred-confidence").textContent   = (r.confidence || 0).toFixed(1) + "%";
  document.getElementById("pred-rul").textContent          = r.rul_days != null ? r.rul_days + " days" : "Unavailable";
  document.getElementById("pred-score").textContent        = "Score: " + (r.severity_score || 0);
  document.getElementById("pred-recommendation").textContent = r.recommendation || "—";

  probFill.style.width      = Math.min(100, r.failure_prob || 0) + "%";
  probFill.style.background = r.failure_prob > 60 ? "var(--red)" :
                              r.failure_prob > 30 ? "var(--yellow)" : "var(--green)";

  sevEl.textContent = r.severity || "NORMAL";
  sevEl.className   = "pred-severity-val " + (r.severity || "").toLowerCase();

  urgEl.textContent = (r.maintenance_urgency || "SCHEDULED").replace(/_/g, " ");

  if (r.all_probabilities && chartFaultProb) {
    chartFaultProb.data.labels = Object.keys(r.all_probabilities).map(k => k.split(" ")[0]);
    chartFaultProb.data.datasets[0].data = Object.values(r.all_probabilities);
    chartFaultProb.update();
  }
}

// ─── Active Faults ─────────────────────────────────────────────────────────
async function loadActiveFaults() {
  const faults = await API.getFaults(DEVICE_ID);
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
      <div class="alert-sev-dot ${API.esc(f.severity)}"></div>
      <div>
        <div class="alert-fault">${API.esc(f.fault_type)}</div>
        <div class="alert-msg">${API.esc(f.root_cause || "")}</div>
        <div class="alert-time">${new Date(f.occurred_at).toLocaleString("en-IN")}</div>
      </div>
    </div>
  `).join("");
}

// ─── Maintenance Schedule ──────────────────────────────────────────────────
async function loadMaintenanceSchedule() {
  const data = await API.getSchedule(DEVICE_ID);
  const listEl = document.getElementById("maintenance-list");

  if (!data || data.error || !data.schedule) {
    listEl.innerHTML = '<div class="loading-text">No schedule available for this device</div>';
    return;
  }

  listEl.innerHTML = data.schedule.slice(0, 5).map(item => `
    <div class="maintenance-item">
      <span class="maint-priority ${API.esc(item.priority)}">${API.esc(item.priority)}</span>
      <div>
        <div class="maint-task">${API.esc(item.task)}</div>
        <div class="maint-due">Due in ${API.esc(item.due_in_days || "?")} days</div>
      </div>
    </div>
  `).join("");
}

// ─── WebSocket (Socket.IO, same origin) ────────────────────────────────────
function connectWebSocket() {
  if (typeof io === "undefined" || !window.location.protocol.startsWith("http")) return;
  try {
    const socket = io(window.location.origin);
    socket.on("sensor_update", (msg) => {
      if (msg.device_id === DEVICE_ID && msg.data && msg.data.id !== lastReadingId) {
        lastReadingId = msg.data.id;
        updateDashboard(msg.data);
      }
    });
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
      <div class="toast-title">${API.esc(title)}</div>
      <div class="toast-msg">${API.esc(msg)}</div>
    </div>`;
  tc.appendChild(toast);
  setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 300); }, 4000);
}

// Make available globally
window.logout        = logout;
window.runPrediction = runPrediction;
window.setTimeRange  = setTimeRange;
window.selectDevice  = selectDevice;
