"""
PREDICTA – Sensor Data Ingestion Routes
Handles real-time sensor data from ESP32 via HTTP POST and MQTT.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from datetime import datetime, timedelta
from sqlalchemy import desc

from database import db
from models import SensorReading, Machine, DeviceThreshold

sensor_bp = Blueprint("sensor", __name__)


@sensor_bp.route("/ingest", methods=["POST"])
def ingest_sensor_data():
    """
    POST /api/sensor/ingest – kept for older firmware; identical to POST /api/live/ingest.
    Requires the device's X-Device-Key (devices are no longer auto-registered, which let
    anyone inject fake telemetry). Register devices via POST /api/live/devices.
    """
    from routes.live_routes import ingest
    return ingest()


@sensor_bp.route("/latest/<device_id>", methods=["GET"])
@jwt_required()
def get_latest(device_id):
    """GET /api/sensor/latest/<device_id> – Most recent sensor reading."""
    reading = (
        SensorReading.query
        .filter_by(device_id=device_id)
        .order_by(desc(SensorReading.timestamp))
        .first()
    )
    if not reading:
        return jsonify({"error": "No data found"}), 404
    return jsonify(reading.to_dict()), 200


@sensor_bp.route("/history/<device_id>", methods=["GET"])
@jwt_required()
def get_history(device_id):
    """
    GET /api/sensor/history/<device_id>
    Query params: hours (default 24), limit (default 500)
    """
    hours = int(request.args.get("hours", 24))
    limit = min(int(request.args.get("limit", 500)), 5000)

    since = datetime.utcnow() - timedelta(hours=hours)
    readings = (
        SensorReading.query
        .filter_by(device_id=device_id)
        .filter(SensorReading.timestamp >= since)
        .order_by(SensorReading.timestamp)
        .limit(limit)
        .all()
    )
    return jsonify([r.to_dict() for r in readings]), 200


@sensor_bp.route("/machines", methods=["GET"])
@jwt_required()
def get_machines():
    """GET /api/sensor/machines – List all registered machines."""
    machines = Machine.query.filter_by(is_active=True).all()
    return jsonify([m.to_dict() for m in machines]), 200


@sensor_bp.route("/machines/<device_id>", methods=["GET"])
@jwt_required()
def get_machine(device_id):
    machine = Machine.query.filter_by(device_id=device_id).first_or_404()
    return jsonify(machine.to_dict()), 200


@sensor_bp.route("/status/<device_id>", methods=["GET"])
@jwt_required()
def get_machine_status(device_id):
    """
    GET /api/sensor/status/<device_id>
    Returns live health score, efficiency, last reading time, online status.
    """
    reading = (
        SensorReading.query
        .filter_by(device_id=device_id)
        .order_by(desc(SensorReading.timestamp))
        .first()
    )
    if not reading:
        return jsonify({"online": False, "health_score": None}), 200

    # Consider offline if no data in last 30 seconds
    age_seconds = (datetime.utcnow() - reading.timestamp).total_seconds()
    online = age_seconds < 30

    return jsonify({
        "device_id": device_id,
        "online": online,
        "last_seen": reading.timestamp.isoformat(),
        "age_seconds": int(age_seconds),
        "health_score": reading.health_score,
        "efficiency": reading.efficiency,
        "motor_running": reading.motor_running,
        "overload": reading.overload,
        "overheat": reading.overheat,
        "high_vibration": reading.high_vibration,
    }), 200
