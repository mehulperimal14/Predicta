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
from preprocess import compute_health_score, compute_efficiency
from prediction import predict_fault
from alerts import send_alert

sensor_bp = Blueprint("sensor", __name__)


@sensor_bp.route("/ingest", methods=["POST"])
def ingest_sensor_data():
    """
    POST /api/sensor/ingest
    Accepts raw sensor data from ESP32 or MQTT bridge.
    No auth required (uses device_id for identification).
    Runs ML prediction and saves to DB.

    Body: SensorReading JSON object
    """
    data = request.get_json()
    if not data or not data.get("device_id"):
        return jsonify({"error": "device_id required"}), 400

    device_id = data["device_id"]

    # Ensure machine is registered
    machine = Machine.query.filter_by(device_id=device_id).first()
    if not machine:
        # Auto-register new device
        machine = Machine(
            device_id=device_id,
            name=f"Machine {device_id}",
            machine_type="induction_motor",
            rated_power=1.5,
            rated_current=3.5,
            rated_voltage=415,
            rated_rpm=1440,
        )
        db.session.add(machine)
        db.session.flush()

    # Compute derived fields
    health_score = compute_health_score(data)
    efficiency   = compute_efficiency(data, machine.rated_power or 1.5)

    # Save reading
    reading = SensorReading(
        device_id     = device_id,
        timestamp     = datetime.utcnow(),
        voltage       = data.get("voltage"),
        current       = data.get("current"),
        power_kw      = data.get("power_kw"),
        energy_kwh    = data.get("energy_kwh"),
        motor_temp    = data.get("motor_temp"),
        bearing_temp  = data.get("bearing_temp"),
        ambient_temp  = data.get("ambient_temp"),
        humidity      = data.get("humidity"),
        vibration_rms = data.get("vibration_rms"),
        rpm           = data.get("rpm"),
        pressure      = data.get("pressure"),
        run_hours     = data.get("run_hours"),
        start_cycles  = data.get("start_cycles"),
        motor_running = data.get("motor_running", True),
        overload      = data.get("overload", False),
        overheat      = data.get("overheat", False),
        high_vibration= data.get("high_vibration", False),
        low_rpm       = data.get("low_rpm", False),
        health_score  = health_score,
        efficiency    = efficiency,
    )
    db.session.add(reading)

    # Run ML prediction every 10th reading (to reduce load)
    prediction_result = None
    count = SensorReading.query.filter_by(device_id=device_id).count()
    if count % 10 == 0 or data.get("overload") or data.get("overheat") or data.get("high_vibration"):
        prediction_result = predict_fault(data)

        # Trigger alert if fault detected
        if prediction_result.get("severity") in ("HIGH", "CRITICAL", "MEDIUM"):
            send_alert(
                device_id=device_id,
                fault_type=prediction_result.get("fault_type", "Unknown"),
                severity=prediction_result.get("severity"),
                message=prediction_result.get("anomalies", [{}])[0].get("message", "") if prediction_result.get("anomalies") else "",
                prediction=prediction_result
            )

    db.session.commit()

    return jsonify({
        "status": "ok",
        "reading_id": reading.id,
        "health_score": health_score,
        "efficiency": efficiency,
        "prediction": prediction_result,
    }), 201


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
