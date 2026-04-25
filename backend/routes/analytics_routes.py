"""
PREDICTA – Analytics Routes
Trend analysis, energy consumption, health history, downtime, comparisons.
Uses SQLAlchemy ORM for SQLite + PostgreSQL compatibility.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta, date
from sqlalchemy import func, desc

from database import db
from models import SensorReading, FaultEvent, MaintenanceLog, EnergyDaily

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/health-trend/<device_id>", methods=["GET"])
@jwt_required()
def health_trend(device_id):
    days  = int(request.args.get("days", 7))
    since = datetime.utcnow() - timedelta(days=days)

    readings = (
        SensorReading.query
        .filter_by(device_id=device_id)
        .filter(SensorReading.timestamp >= since)
        .order_by(SensorReading.timestamp)
        .all()
    )

    # Bucket into hourly groups
    hourly = {}
    for r in readings:
        key = r.timestamp.strftime("%Y-%m-%dT%H:00")
        if key not in hourly:
            hourly[key] = {"health": [], "temp": [], "current": [], "vibration": [], "rpm": []}
        if r.health_score is not None: hourly[key]["health"].append(r.health_score)
        if r.motor_temp is not None:   hourly[key]["temp"].append(r.motor_temp)
        if r.current is not None:      hourly[key]["current"].append(r.current)
        if r.vibration_rms is not None:hourly[key]["vibration"].append(r.vibration_rms)
        if r.rpm is not None:          hourly[key]["rpm"].append(r.rpm)

    def avg(lst): return round(sum(lst) / len(lst), 3) if lst else 0

    result = [{
        "timestamp": k,
        "avg_health":    avg(v["health"]),
        "avg_temp":      avg(v["temp"]),
        "avg_current":   avg(v["current"]),
        "avg_vibration": avg(v["vibration"]),
        "avg_rpm":       int(avg(v["rpm"])),
    } for k, v in sorted(hourly.items())]

    return jsonify(result), 200


@analytics_bp.route("/energy/<device_id>", methods=["GET"])
@jwt_required()
def energy_analysis(device_id):
    days  = int(request.args.get("days", 30))
    since = datetime.utcnow() - timedelta(days=days)

    readings = (
        SensorReading.query
        .filter_by(device_id=device_id)
        .filter(SensorReading.timestamp >= since, SensorReading.motor_running == True)
        .order_by(SensorReading.timestamp)
        .all()
    )

    daily = {}
    for r in readings:
        key = r.timestamp.strftime("%Y-%m-%d")
        if key not in daily:
            daily[key] = {"power_vals": [], "energy": []}
        if r.power_kw:  daily[key]["power_vals"].append(r.power_kw)
        if r.energy_kwh: daily[key]["energy"].append(r.energy_kwh)

    result = []
    for day, v in sorted(daily.items()):
        powers = v["power_vals"]
        kwh = max(v["energy"]) - min(v["energy"]) if len(v["energy"]) > 1 else sum(powers) * (2 / 3600)
        result.append({
            "date":       day,
            "total_kwh":  round(max(0, kwh), 3),
            "peak_kw":    round(max(powers, default=0), 2),
            "avg_kw":     round(sum(powers) / len(powers), 2) if powers else 0,
            "run_hours":  round(len(powers) * 2 / 3600, 2),
            "cost_inr":   round(max(0, kwh) * 8.5, 2),
        })

    return jsonify(result), 200


@analytics_bp.route("/fault-summary/<device_id>", methods=["GET"])
@jwt_required()
def fault_summary(device_id):
    days  = int(request.args.get("days", 30))
    since = datetime.utcnow() - timedelta(days=days)

    faults = FaultEvent.query.filter(
        FaultEvent.device_id == device_id,
        FaultEvent.occurred_at >= since
    ).all()

    by_type = {}
    for f in faults:
        key = f"{f.fault_type}|{f.severity}"
        by_type[key] = by_type.get(key, 0) + 1

    active = sum(1 for f in faults if f.is_active)

    return jsonify({
        "total_faults":  len(faults),
        "active_faults": active,
        "by_type": [
            {"fault_type": k.split("|")[0], "severity": k.split("|")[1], "count": v}
            for k, v in sorted(by_type.items(), key=lambda x: -x[1])
        ],
    }), 200


@analytics_bp.route("/downtime/<device_id>", methods=["GET"])
@jwt_required()
def downtime_analysis(device_id):
    days = int(request.args.get("days", 30))
    since_date = date.today() - timedelta(days=days)

    logs = MaintenanceLog.query.filter(
        MaintenanceLog.device_id == device_id,
    ).all()

    total_downtime = sum(m.downtime_hours or 0 for m in logs)
    total_cost = sum(m.cost_inr or 0 for m in logs)
    predictive = [m for m in logs if m.maintenance_type == "Predictive"]
    avoided_hours = len(predictive) * 8
    avoided_loss = avoided_hours * 5000

    return jsonify({
        "total_downtime_hours":    total_downtime,
        "total_maintenance_cost_inr": total_cost,
        "predictive_actions":      len(predictive),
        "estimated_avoided_hours": avoided_hours,
        "estimated_avoided_loss_inr": avoided_loss,
        "maintenance_logs": [m.to_dict() for m in logs],
    }), 200


@analytics_bp.route("/comparison/<device_id>", methods=["GET"])
@jwt_required()
def period_comparison(device_id):
    now        = datetime.utcnow()
    week_start = now - timedelta(days=7)
    prev_start = now - timedelta(days=14)

    def _avg_period(since, until):
        rows = SensorReading.query.filter(
            SensorReading.device_id == device_id,
            SensorReading.timestamp.between(since, until)
        ).all()
        if not rows:
            return {"health": 0, "current": 0, "temp": 0, "vibration": 0, "efficiency": 0}
        n = len(rows)
        return {
            "health":     round(sum(r.health_score or 0 for r in rows) / n, 1),
            "current":    round(sum(r.current or 0 for r in rows) / n, 2),
            "temp":       round(sum(r.motor_temp or 0 for r in rows) / n, 1),
            "vibration":  round(sum(r.vibration_rms or 0 for r in rows) / n, 3),
            "efficiency": round(sum(r.efficiency or 0 for r in rows) / n, 1),
        }

    curr = _avg_period(week_start, now)
    prev = _avg_period(prev_start, week_start)

    def pct(a, b): return round((a - b) / b * 100, 1) if b else 0

    changes = {k: pct(curr[k], prev[k]) for k in curr}
    return jsonify({"current_week": curr, "previous_week": prev, "changes": changes}), 200


@analytics_bp.route("/performance-index/<device_id>", methods=["GET"])
@jwt_required()
def performance_index(device_id):
    since = datetime.utcnow() - timedelta(hours=24)
    readings = SensorReading.query.filter(
        SensorReading.device_id == device_id,
        SensorReading.timestamp >= since,
        SensorReading.motor_running == True
    ).all()

    if not readings:
        return jsonify({"oee": 0, "availability": 0, "performance": 0, "quality": 0,
                        "avg_health": 0, "avg_efficiency": 0, "suggestions": []}), 200

    n = len(readings)
    avg_health    = sum(r.health_score or 0 for r in readings) / n
    avg_efficiency= sum(r.efficiency  or 0 for r in readings) / n
    avg_current   = sum(r.current     or 0 for r in readings) / n
    avg_temp      = sum(r.motor_temp  or 0 for r in readings) / n
    avg_vib       = sum(r.vibration_rms or 0 for r in readings) / n

    healthy      = sum(1 for r in readings if (r.health_score or 0) >= 80)
    availability = healthy / n * 100
    performance  = min(100, avg_efficiency * 1.1)
    quality      = max(0, 100 - (avg_vib / 1.0 * 20))
    oee          = (availability / 100) * (performance / 100) * (quality / 100) * 100

    suggestions = []
    if avg_temp > 60:   suggestions.append(f"Motor temperature averaging {avg_temp:.1f}°C — inspect cooling ventilation.")
    if avg_vib > 0.3:   suggestions.append(f"Vibration trending up ({avg_vib:.3f}g) — schedule bearing inspection.")
    if avg_current > 3.8: suggestions.append(f"Current load {avg_current:.2f}A is above 80% FLC — check pump efficiency.")

    return jsonify({
        "availability":  round(availability, 1),
        "performance":   round(performance, 1),
        "quality":       round(quality, 1),
        "oee":           round(oee, 1),
        "avg_health":    round(avg_health, 1),
        "avg_efficiency":round(avg_efficiency, 1),
        "avg_current":   round(avg_current, 2),
        "avg_temp":      round(avg_temp, 1),
        "avg_vibration": round(avg_vib, 3),
        "readings_count":n,
        "suggestions":   suggestions,
    }), 200
