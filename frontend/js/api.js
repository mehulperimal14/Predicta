/**
 * PREDICTA – Centralized API Client
 * Backend: http://localhost:5000
 */
const API = (() => {
  const BASE = "http://localhost:5000/api";

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

  async function request(method, path, body = null, retry = true) {
    const token = getToken();
    const opts = {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "Authorization": `Bearer ${token}` } : {})
      },
      ...(body ? { body: JSON.stringify(body) } : {})
    };
    try {
      let res = await fetch(`${BASE}${path}`, opts);

      // Auto-refresh expired token
      if (res.status === 401 && retry) {
        const refreshed = await _refresh();
        if (refreshed) return request(method, path, body, false);
        else { clearTokens(); window.location.href = "login.html"; return null; }
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        return { error: err.error || `Request failed: ${res.status}` };
      }
      // Handle empty response (e.g. 204)
      const text = await res.text();
      return text ? JSON.parse(text) : {};
    } catch (e) {
      console.error("[API]", method, path, e);
      return { error: e.message || "Network error" };
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
    return { success: false, error: data.error };
  }

  function getUser() {
    try { return JSON.parse(localStorage.getItem("predicta_user")); } catch(_) { return null; }
  }

  return {
    getToken, getRefresh, setTokens, clearTokens, getUser, login,
    get:    (path)        => request("GET",    path),
    post:   (path, body)  => request("POST",   path, body),
    patch:  (path, body)  => request("PATCH",  path, body),
    delete: (path)        => request("DELETE", path),

    // Convenience methods
    getLatest:       (did) => request("GET", `/sensor/latest/${did}`),
    getHistory:      (did, hours=24)  => request("GET", `/sensor/history/${did}?hours=${hours}`),
    getMachineStatus:(did) => request("GET", `/sensor/status/${did}`),
    runPrediction:   (did) => request("GET", `/predict/run/${did}`),
    getSchedule:     (did) => request("GET", `/predict/maintenance-schedule/${did}`),
    getFaults:       (did) => request("GET", `/predict/faults/${did}?active_only=true`),
    getHealthTrend:  (did, days=7) => request("GET", `/analytics/health-trend/${did}?days=${days}`),
    getEnergy:       (did, days=30)=> request("GET", `/analytics/energy/${did}?days=${days}`),
    getPerformance:  (did) => request("GET", `/analytics/performance-index/${did}`),
    getComparison:   (did) => request("GET", `/analytics/comparison/${did}`),
    getAlerts:       (did) => request("GET", `/alerts/history/${did}`),
    downloadReport:  (did, days=7) => {
      const a = document.createElement("a");
      a.href = `${BASE}/reports/generate/${did}?days=${days}&token=${getToken()}`;
      a.download = `predicta_report_${did}.pdf`;
      a.click();
    }
  };
})();
