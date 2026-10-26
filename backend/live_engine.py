"""
PREDICTA – Segment B: Live IoT Monitoring Engine

ESP32 / microcontroller devices stream readings continuously (HTTPS or the MQTT
bridge). This module stores them and re-evaluates each device on a rolling window
with the SAME analytics core used for uploaded files (Segment A):

  rules (Layer 1) → anomalies (Layer 2) → CUSUM change-points → trend forecast
  → composite risk (Layer 5) → fault hypotheses

and turns the result into the three answers an operator needs:
  1. Is the machine healthy right now?          → status
  2. Which way is it trending?                  → per-variable slope / direction
  3. When will it break down if nothing changes? → time to warning / critical limit
"""

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import pandas as pd
from flask import current_app

from database import db
from models import Machine, SensorReading, DeviceCredential, DeviceThreshold
from preprocess import compute_health_score, compute_efficiency, detect_anomalies
from analytics_engine import compute_time_series_features, compute_changepoints, TREND_VARIABLES
from ai_engine import (
    evaluate_layer1_rules, run_layer2_unsupervised_detection, compute_layer5_risk_score,
    merged_limits, DEFAULT_ENGINEERING_LIMITS
)
from trend_forecast import forecast_time_to_limits, trend_risk_score
from investigation import generate_fault_hypotheses
from notifications import dispatch_machine_alert

NUMERIC_FIELDS = [
    "voltage", "current", "power_kw", "energy_kwh", "power_factor",
    "motor_temp", "bearing_temp", "ambient_temp", "humidity",
    "vibration_rms", "vibration_x", "vibration_y", "vibration_z",
    "rpm", "pressure", "run_hours", "start_cycles",
]
BOOL_FIELDS = ["motor_running", "overload", "overheat", "high_vibration", "low_rpm"]
MAX_READINGS_PER_REQUEST = 500
CACHE_SECONDS = 15

_cache_lock = threading.Lock()
_assessment_cache: Dict[str, Dict[str, Any]] = {}


# ─── Device keys ──────────────────────────────────────────────────────────────

def hash_device_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def issue_device_key(device_id: str, created_by: Optional[str] = None) -> str:
    """Create or replace the device's key. Returns the plaintext key (shown once)."""
    key = "pdk_" + secrets.token_urlsafe(24)
    cred = DeviceCredential.query.filter_by(device_id=device_id).first()
    if not cred:
        cred = DeviceCredential(device_id=device_id)
        db.session.add(cred)
    cred.key_hash = hash_device_key(key)
    cred.key_prefix = key[:10]
    cred.is_active = True
    cred.created_at = datetime.utcnow()
    cred.created_by = created_by
    cred.last_used_at = None
    db.session.commit()
    return key


def verify_device_key(device_id: str, key: Optional[str]) -> bool:
    if not device_id or not key:
        return False
    cred = DeviceCredential.query.filter_by(device_id=device_id, is_active=True).first()
    if not cred or not hmac.compare_digest(cred.key_hash, hash_device_key(key)):
        return False
    cred.last_used_at = datetime.utcnow()
    return True


# ─── Ingest ───────────────────────────────────────────────────────────────────

def _parse_timestamp(value: Any) -> datetime:
    """ISO-8601 string or epoch seconds / milliseconds → naive UTC. Falls back to now."""
    now = datetime.utcnow()
    if value in (None, ""):
        return now
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000.0 if value > 1e11 else float(value)
            ts = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
        else:
            ts = pd.to_datetime(str(value), utc=True).to_pydatetime().replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return now
    # Devices without a synced clock: never accept readings from the future.
    return now if (ts - now).total_seconds() > 300 else ts


def _clean_reading(raw: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for field in NUMERIC_FIELDS:
        value = raw.get(field)
        if value is None or value == "":
            continue
        try:
            clean[field] = float(value)
        except (TypeError, ValueError):
            continue
    for field in BOOL_FIELDS:
        if field in raw and raw[field] is not None:
            clean[field] = bool(raw[field])
    return clean


def ingest_readings(device_id: str, readings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Stores readings for a registered device and, every N readings (or immediately on a
    critical rule hit), re-assesses the device and dispatches live alerts.
    Caller is responsible for authenticating the device.
    """
    machine = Machine.query.filter_by(device_id=device_id).first()
    if not machine:
        raise ValueError(f"Device '{device_id}' is not registered")

    every_n = max(1, int(current_app.config.get("LIVE_ASSESSMENT_EVERY_N_READINGS", 10)))
    count_before = SensorReading.query.filter_by(device_id=device_id).count()

    stored, immediate, last = 0, [], None
    for raw in readings[:MAX_READINGS_PER_REQUEST]:
        r = _clean_reading(raw)
        if not r:
            continue
        rule_hits = detect_anomalies(r)
        immediate.extend(rule_hits)
        last = SensorReading(
            device_id=device_id,
            timestamp=_parse_timestamp(raw.get("timestamp")),
            health_score=compute_health_score(r),
            efficiency=compute_efficiency(r, machine.rated_power or 1.5),
            rpm=int(r["rpm"]) if "rpm" in r else None,
            start_cycles=int(r["start_cycles"]) if "start_cycles" in r else None,
            motor_running=r.get("motor_running", True),
            overload=r.get("overload", any(a["type"] == "OVERCURRENT" for a in rule_hits)),
            overheat=r.get("overheat", any(a["type"] in ("OVERTEMPERATURE", "HIGH_TEMPERATURE") for a in rule_hits)),
            high_vibration=r.get("high_vibration", any("VIBRATION" in a["type"] for a in rule_hits)),
            low_rpm=r.get("low_rpm", any(a["type"] == "LOW_RPM" for a in rule_hits)),
            **{k: v for k, v in r.items() if k not in ("rpm", "start_cycles") and k not in BOOL_FIELDS},
        )
        db.session.add(last)
        stored += 1
    db.session.commit()

    result: Dict[str, Any] = {
        "accepted": stored,
        "rejected": len(readings) - stored,
        "health_score": last.health_score if last else None,
        "immediate_rule_hits": immediate[:10],
        "assessment": None,
        "alert": None,
    }
    if stored == 0:
        return result

    count_after = count_before + stored
    critical_hit = any(a.get("severity") == "CRITICAL" for a in immediate)
    if critical_hit or (count_before // every_n) != (count_after // every_n):
        assessment = assess_device(device_id, force=True)
        result["assessment"] = {k: assessment.get(k) for k in ("status", "headline", "risk_score", "time_to_breakdown")}
        result["alert"] = _maybe_alert(device_id, assessment)

    socketio = current_app.extensions.get("socketio")
    if socketio is not None and last is not None:
        try:
            socketio.emit("sensor_update", {
                "device_id": device_id,
                "data": last.to_dict(),
                "health_score": last.health_score,
                "status": (result["assessment"] or {}).get("status"),
            })
        except Exception:
            pass
    return result


def _maybe_alert(device_id: str, assessment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    status = assessment.get("status")
    if status not in ("DEGRADING", "CRITICAL") or not assessment.get("online"):
        return None
    severity = "CRITICAL" if status == "CRITICAL" else "WARNING"
    evidence = [assessment.get("headline", "")]
    evidence += [v["rule"] for v in assessment.get("layer1_rules", {}).get("violations", [])[:2]]
    return dispatch_machine_alert(
        asset_id=device_id,
        severity=severity,
        title=f"Live machine health {severity}",   # stable title → cooldown works
        evidence=[e for e in evidence if e],
        suggested_action=assessment.get("risk", {}).get("recommended_action", ""),
        is_historical=False,
    )


# ─── Assessment ───────────────────────────────────────────────────────────────

def device_limits(device_id: str) -> Dict[str, Dict[str, Any]]:
    """Engineering limits for a device: defaults, overridden by its DeviceThreshold row if configured."""
    t = DeviceThreshold.query.filter_by(device_id=device_id).first()
    if not t:
        return merged_limits()
    v = DEFAULT_ENGINEERING_LIMITS["voltage"]
    return merged_limits({
        "motor_temp": {"warn": t.temp_warning, "crit": t.temp_critical, "unit": "°C"},
        "vibration_rms": {"warn": t.vibration_warn, "crit": t.vibration_crit, "unit": "g"},
        "voltage": {"min_crit": v["min_crit"], "min_warn": t.voltage_min,
                    "max_warn": t.voltage_max, "max_crit": v["max_crit"], "unit": "V"},
        "rpm": {"min_warn": t.rpm_min, "max_warn": t.rpm_max, "unit": "RPM"},
    })


def _readings_frame(device_id: str, window: int) -> pd.DataFrame:
    rows = (SensorReading.query.filter_by(device_id=device_id)
            .order_by(SensorReading.timestamp.desc()).limit(window).all())
    if not rows:
        return pd.DataFrame()
    records = [{
        "timestamp": r.timestamp,
        "motor_running": 1 if r.motor_running else 0,
        "health_score": r.health_score,
        **{f: getattr(r, f) for f in ["voltage", "current", "power_kw", "motor_temp", "bearing_temp",
                                       "ambient_temp", "vibration_rms", "rpm", "pressure"]},
    } for r in reversed(rows)]
    return pd.DataFrame(records)


def _fmt_hours(hours: float) -> str:
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} days"


def _status_and_headline(risk: Dict[str, Any], forecast: Dict[str, Any]) -> Dict[str, Any]:
    variables = forecast.get("variables", [])
    exceeded = [v for v in variables if v.get("status") == "CRITICAL_LIMIT_EXCEEDED"]
    earliest_crit = forecast.get("earliest_critical")
    earliest_warn = forecast.get("earliest_warning")
    category = risk.get("risk_category", "NORMAL")

    if exceeded or category == "CRITICAL":
        status = "CRITICAL"
        names = ", ".join(v["variable"] for v in exceeded) or "multiple parameters"
        headline = f"Critical condition: {names} beyond safe limits. Inspect the machine now."
    elif (earliest_crit and earliest_crit["hours"] > 0) or category == "WARNING":
        status = "DEGRADING"
        if earliest_crit and earliest_crit["hours"] > 0:
            headline = (f"Degrading: {earliest_crit['variable']} will reach its critical limit "
                        f"({earliest_crit['limit']} {earliest_crit['unit']}) in about "
                        f"{_fmt_hours(earliest_crit['hours'])} if the current trend continues.")
        else:
            headline = "Degrading: abnormal readings and anomalies detected. Schedule an inspection."
    elif earliest_warn or category == "WATCH" or any(v.get("status") == "WARNING_LIMIT_EXCEEDED" for v in variables):
        status = "WATCH"
        if earliest_warn and earliest_warn["hours"] > 0:
            headline = (f"Watch: {earliest_warn['variable']} trending toward its warning limit "
                        f"(~{_fmt_hours(earliest_warn['hours'])}).")
        else:
            headline = "Watch: minor deviations from the normal operating envelope."
    else:
        status = "HEALTHY"
        headline = "Healthy: running within limits and no variable is trending toward a limit."

    time_to_breakdown = None
    if exceeded:
        time_to_breakdown = {"hours": 0.0, "variable": exceeded[0]["variable"], "ci_hours": None,
                             "basis": "Critical limit already exceeded"}
    elif earliest_crit:
        time_to_breakdown = {**earliest_crit, "basis": "Trend extrapolated to the critical engineering limit"}
    return {"status": status, "headline": headline, "time_to_breakdown": time_to_breakdown}


def assess_device(device_id: str, window: Optional[int] = None, force: bool = False) -> Dict[str, Any]:
    """Re-evaluates one device on its most recent readings (cached for a few seconds)."""
    window = window or int(current_app.config.get("LIVE_ASSESSMENT_WINDOW_READINGS", 720))
    cache_key = f"{device_id}:{window}"
    if not force:
        with _cache_lock:
            cached = _assessment_cache.get(cache_key)
            if cached and time.time() - cached["_computed_at"] < CACHE_SECONDS:
                return cached["result"]

    df = _readings_frame(device_id, window)
    if df.empty:
        return {"device_id": device_id, "status": "NO_DATA", "online": False,
                "headline": "No readings received from this device yet."}

    present = [v for v in TREND_VARIABLES if v in df.columns and df[v].notna().any()]
    mapping = {"timestamp": "timestamp", "motor_running": "motor_running", **{v: v for v in present}}
    features = compute_time_series_features(df, mapping=mapping, rolling_window=15)
    limits = device_limits(device_id)

    completeness = float(df[present].notna().mean().mean() * 100) if present else 0.0
    changepoints = compute_changepoints(features, timestamp_col="timestamp")
    l1 = evaluate_layer1_rules(features, custom_limits=limits)
    l2 = run_layer2_unsupervised_detection(
        features, contamination=current_app.config.get("ISOLATION_FOREST_CONTAMINATION", 0.03))
    # Live trends: fit the most recent quarter of the window so a new degradation is not
    # averaged away by hours of healthy history.
    forecast = forecast_time_to_limits(features, limits, timestamp_col="timestamp", recent_fraction=0.25)
    risk = compute_layer5_risk_score(l1, l2, {"available": False}, data_quality_score=completeness,
                                     trend_score=trend_risk_score(forecast))
    hypotheses = generate_fault_hypotheses(features, mapping, l1, l2, risk, changepoints=changepoints)

    last_ts = df["timestamp"].iloc[-1]
    age = (datetime.utcnow() - last_ts).total_seconds()
    online = age <= current_app.config.get("LIVE_OFFLINE_AFTER_SECONDS", 60)
    verdict = _status_and_headline(risk, forecast)

    step = max(1, len(df) // 300)
    sampled = df.iloc[::step]
    charts = {
        "timestamps": [ts.isoformat() for ts in sampled["timestamp"]],
        "variables": {v: [None if pd.isna(x) else round(float(x), 3) for x in sampled[v]] for v in present},
        "health_score": [None if pd.isna(x) else round(float(x), 1) for x in sampled["health_score"]],
    }

    result = {
        "device_id": device_id,
        **verdict,
        "online": online,
        "last_seen": last_ts.isoformat(),
        "seconds_since_last_reading": int(age),
        "readings_in_window": int(len(df)),
        "window_start": df["timestamp"].iloc[0].isoformat(),
        "risk_score": risk["risk_score"],
        "risk": risk,
        "trend_forecast": forecast,
        "changepoints": changepoints,
        "layer1_rules": l1,
        "layer2_unsupervised": {k: v for k, v in l2.items() if k != "anomaly_indices"},
        "hypotheses": sorted(hypotheses, key=lambda h: ["STRONG", "MODERATE", "WEAK", "INSUFFICIENT"].index(h["confidence"])),
        "latest": {k: (None if pd.isna(v) else float(v)) for k, v in df.iloc[-1].items() if k != "timestamp"},
        "charts": charts,
    }
    if not online:
        result["headline"] = f"Device offline for {_fmt_hours(age / 3600)}. Last known state – {result['headline']}"

    with _cache_lock:
        _assessment_cache[cache_key] = {"_computed_at": time.time(), "result": result}
    return result


def cached_status(device_id: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        for key, entry in _assessment_cache.items():
            if key.startswith(f"{device_id}:"):
                r = entry["result"]
                return {"status": r.get("status"), "headline": r.get("headline"),
                        "risk_score": r.get("risk_score"), "time_to_breakdown": r.get("time_to_breakdown")}
    return None


def fleet_summary() -> List[Dict[str, Any]]:
    offline_after = current_app.config.get("LIVE_OFFLINE_AFTER_SECONDS", 60)
    creds = {c.device_id: c for c in DeviceCredential.query.all()}
    # Segment B devices only: registered for streaming or with readings. Assets created by
    # Segment A file analyses share the machine registry but are not live devices.
    live_ids = set(creds) | {row[0] for row in db.session.query(SensorReading.device_id).distinct()}
    fleet = []
    for m in Machine.query.filter_by(is_active=True).order_by(Machine.device_id).all():
        if m.device_id not in live_ids:
            continue
        last = (SensorReading.query.filter_by(device_id=m.device_id)
                .order_by(SensorReading.timestamp.desc()).first())
        age = (datetime.utcnow() - last.timestamp).total_seconds() if last else None
        cred = creds.get(m.device_id)
        fleet.append({
            **m.to_dict(),
            "streaming_enabled": bool(cred and cred.is_active),
            "key_prefix": cred.key_prefix if cred and cred.is_active else None,
            "last_seen": last.timestamp.isoformat() if last else None,
            "online": age is not None and age <= offline_after,
            "health_score": last.health_score if last else None,
            "assessment": cached_status(m.device_id),
        })
    return fleet
