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
            window.location.href = "login.html";
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

  return {
    BASE,
    getToken, getRefresh, setTokens, clearTokens, getUser, login,
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
    getSamples:    () => request("GET", "/ingest/samples"),

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
    downloadReport:  (did, days=7) => {
      const a = document.createElement("a");
      a.href = `${BASE}/reports/generate/${did}?days=${days}&token=${getToken()}`;
      a.target = "_blank";
      a.download = `predicta_report_${did}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  };
})();

