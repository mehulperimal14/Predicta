/**
 * PREDICTA 2.0 – Centralized API Client
 * Dynamically resolves to current host or http://localhost:5000
 */
const API = (() => {
  const BASE = (window.location.protocol.startsWith("http"))
    ? `${window.location.origin}/api`
    : "http://localhost:5000/api";

  function getToken()    { return localStorage.getItem("predicta_token"); }
  function getRefresh()  { return localStorage.getItem("predicta_refresh"); }
  function setTokens(a, r) {
    localStorage.setItem("predicta_token", a);
    if (r) localStorage.setItem("predicta_refresh", r);
  }
  function clearTokens() {
    localStorage.removeItem("predicta_token");
    localStorage.removeItem("predicta_refresh");
    localStorage.removeItem("predicta_user");
  }

  async function request(method, path, body = null, retry = true, isFormData = false) {
    const token = getToken();
    const headers = {};
    if (!isFormData) {
      headers["Content-Type"] = "application/json";
    }
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const opts = {
      method,
      headers,
      body: isFormData ? body : (body ? JSON.stringify(body) : undefined)
    };

    try {
      let res = await fetch(`${BASE}${path}`, opts);

      // Auto-refresh expired token
      if (res.status === 401 && retry) {
        const refreshed = await _refresh();
        if (refreshed) return request(method, path, body, false, isFormData);
        else {
          clearTokens();
          if (!window.location.pathname.endsWith("login.html")) {
            toLogin();
          }
          return null;
        }
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        return { error: err.error || err.message || `Request failed: ${res.status}` };
      }
      const text = await res.text();
      return text ? JSON.parse(text) : {};
    } catch (e) {
      console.error("[API]", method, path, e);
      return { error: e.message || "Network error. Backend unreachable." };
    }
  }

  async function _refresh() {
    const rtoken = getRefresh();
    if (!rtoken) return false;
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${rtoken}`, "Content-Type": "application/json" }
      });
      if (res.ok) {
        const data = await res.json();
        setTokens(data.access_token, null);
        return true;
      }
    } catch (_) {}
    return false;
  }

  async function login(username, password) {
    const res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setTokens(data.access_token, data.refresh_token);
      localStorage.setItem("predicta_user", JSON.stringify(data.user));
      return { success: true, user: data.user };
    }
    return { success: false, error: data.error || "Login failed" };
  }

  function getUser() {
    try { return JSON.parse(localStorage.getItem("predicta_user")); } catch(_) { return null; }
  }

  // Open access (PUBLIC_ACCESS=true on the server): password-less "Visitor" session.
  // Returns "ok", "disabled" (the server refused with 403) or "unreachable"
  // (asleep, restarting or offline - worth retrying).
  async function startVisitorSession() {
    try {
      const res = await fetch(`${BASE}/auth/visitor`, { method: "POST" });
      if (res.status === 403) return "disabled";
      if (!res.ok) return "unreachable";
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      localStorage.setItem("predicta_user", JSON.stringify(data.user));
      return "ok";
    } catch (_) {
      return "unreachable";
    }
  }

  // Go to the login page, which enters automatically when open access is on and then
  // returns to this page. signin=true shows the sign-in form instead (after logout).
  function toLogin(signin = false) {
    if (signin) { window.location.href = "login.html?signin=1"; return; }
    const page = window.location.pathname.split("/").pop() || "index.html";
    window.location.href = "login.html?next=" + encodeURIComponent(page + window.location.search);
  }

  // Segment B: the live device chosen on the Live Monitor page, shared by the other pages
  function getSelectedDevice() {
    try { return localStorage.getItem("predicta_device") || "MOTOR_01"; } catch (_) { return "MOTOR_01"; }
  }
  function setSelectedDevice(deviceId) {
    try { localStorage.setItem("predicta_device", deviceId); } catch (_) {}
  }

  // Authenticated file download (the API only accepts the token in a header, never in the URL)
  async function download(path, filename) {
    const res = await fetch(`${BASE}${path}`, { headers: { "Authorization": `Bearer ${getToken()}` } });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return { error: err.error || err.msg || `Download failed: HTTP ${res.status}` };
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return { success: true };
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function fmtHours(h) {
    if (h === null || h === undefined) return "—";
    if (h === 0) return "now";
    if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
    if (h < 48) return `${h.toFixed(1)} h`;
    return `${(h / 24).toFixed(1)} days`;
  }

  return {
    BASE,
    getToken, getRefresh, setTokens, clearTokens, getUser, login, startVisitorSession, toLogin,
    getSelectedDevice, setSelectedDevice, download, esc, fmtHours,
    get:    (path)        => request("GET",    path),
    post:   (path, body)  => request("POST",   path, body),
    patch:  (path, body)  => request("PATCH",  path, body),
    delete: (path)        => request("DELETE", path),

    // Ingestion & Tag Mapping (Predicta 2.0)
    uploadDataset: (formData) => request("POST", "/ingest/upload", formData, true, true),
    getDatasets:   () => request("GET", "/ingest/datasets"),
    getDataset:    (id) => request("GET", `/ingest/datasets/${id}`),
    getMappings:   () => request("GET", "/ingest/mappings"),
    saveMapping:   (data) => request("POST", "/ingest/mappings", data),
    runAnalysis:   (datasetId, payload) => request("POST", `/ingest/analyze/${datasetId}`, payload),
    getAnalysis:   (analysisId) => request("GET", `/ingest/analysis/${analysisId}`),
    getAnalyses:   (limit=10) => request("GET", `/ingest/analyses?limit=${limit}`),
    getSamples:    () => request("GET", "/ingest/samples"),

    // Segment B: Live IoT Monitoring
    getFleet:          () => request("GET", "/live/fleet"),
    getAssessment:     (did, refresh=false) => request("GET", `/live/devices/${encodeURIComponent(did)}/assessment${refresh ? "?refresh=1" : ""}`),
    registerDevice:    (data) => request("POST", "/live/devices", data),
    rotateDeviceKey:   (did) => request("POST", `/live/devices/${encodeURIComponent(did)}/rotate-key`, {}),

    // Notifications (Telegram & SMS)
    getNotificationConfig:  () => request("GET", "/notifications/config"),
    saveNotificationConfig: (data) => request("POST", "/notifications/config", data),
    testTelegram:           () => request("POST", "/notifications/test-telegram", {}),
    testSMS:                () => request("POST", "/notifications/test-sms", {}),
    getNotificationHistory: () => request("GET", "/notifications/history"),

    // Machines & Sensor Data
    getLatest:       (did) => request("GET", `/sensor/latest/${did}`),
    getHistory:      (did, hours=24) => request("GET", `/sensor/history/${did}?hours=${hours}`),
    getMachines:     () => request("GET", "/sensor/machines"),
    getMachineStatus:(did) => request("GET", `/sensor/status/${did}`),
    runPrediction:   (did) => request("GET", `/predict/run/${did}`),
    getSchedule:     (did) => request("GET", `/predict/maintenance-schedule/${did}`),
    getFaults:       (did) => request("GET", `/predict/faults/${did}?active_only=true`),
    acknowledgeFault:(fid) => request("POST", `/predict/faults/${fid}/acknowledge`, {}),
    getHealthTrend:  (did, days=7) => request("GET", `/analytics/health-trend/${did}?days=${days}`),
    getEnergy:       (did, days=30)=> request("GET", `/analytics/energy/${did}?days=${days}`),
    getAlerts:       (did) => request("GET", `/alerts/history/${did}`),
    getMaintenance:  (did=null) => request("GET", `/alerts/maintenance${did ? '?device_id=' + did : ''}`),
    createMaintenance:(data) => request("POST", "/alerts/maintenance", data),
    completeMaintenance:(id, data) => request("POST", `/alerts/maintenance/${id}/complete`, data),

    // Reports
    downloadReport:       (did, days=7) => download(`/reports/generate/${encodeURIComponent(did)}?days=${days}`, `predicta_report_${did}.pdf`),
    downloadTelemetryCSV: (did, days=7) => download(`/reports/telemetry/${encodeURIComponent(did)}.csv?days=${days}`, `predicta_telemetry_${did}_${days}d.csv`),
    downloadAnalysisCSV:  (id) => download(`/reports/analysis/${id}.csv`, `predicta_analysis_${id}.csv`),
  };
})();


// Sidebar: show the live device the user last selected on the Live Monitor page
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-selected-device]").forEach(el => { el.textContent = API.getSelectedDevice(); });
});
