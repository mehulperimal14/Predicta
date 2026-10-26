"""
PREDICTA – Prediction Routes
ML-powered fault prediction and maintenance urgency endpoints.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta
from sqlalchemy import desc

from database import db
from models import SensorReading, FaultEvent
from prediction import predict_fault

prediction_bp = Blueprint("prediction", __name__)


@prediction_bp.route("/run/<device_id>", methods=["GET"])
@jwt_required()
def run_prediction(device_id):
    """
    GET /api/predict/run/<device_id>
    Fetches latest reading and runs ML prediction immediately.
    """
    reading = (
        SensorReading.query
        .filter_by(device_id=device_id)
        .order_by(desc(SensorReading.timestamp))
        .first()
    )
    if not reading:
        return jsonify({"error": "No sensor data available"}), 404

    result = predict_fault(reading.to_dict())

    # Save fault event if fault detected
    if result.get("fault_class", 0) != 0 or result.get("severity") in ("HIGH", "CRITICAL"):
        _save_fault_event(device_id, result)

    return jsonify(result), 200


@prediction_bp.route("/manual", methods=["POST"])
@jwt_required()
def manual_prediction():
    """
    POST /api/predict/manual
    Run prediction on manually-provided sensor values (for testing/demo).
    Body: sensor reading JSON
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Sensor data required"}), 400

    result = predict_fault(data)
    return jsonify(result), 200


@prediction_bp.route("/faults/<device_id>", methods=["GET"])
@jwt_required()
def get_faults(device_id):
    """
    GET /api/predict/faults/<device_id>?active_only=true&days=30
    Returns fault event history.
    """
    active_only = request.args.get("active_only", "false").lower() == "true"
    days = int(request.args.get("days", 30))
    since = datetime.utcnow() - timedelta(days=days)

    query = FaultEvent.query.filter(
        FaultEvent.device_id == device_id,
        FaultEvent.occurred_at >= since
    )
    if active_only:
        query = query.filter(FaultEvent.is_active == True)

    faults = query.order_by(desc(FaultEvent.occurred_at)).limit(100).all()
    return jsonify([f.to_dict() for f in faults]), 200


@prediction_bp.route("/faults/<int:fault_id>/acknowledge", methods=["POST"])
@jwt_required()
def acknowledge_fault(fault_id):
    """POST /api/predict/faults/<id>/acknowledge"""
    from flask_jwt_extended import get_jwt_identity
    fault = FaultEvent.query.get_or_404(fault_id)
    fault.acknowledged_by = get_jwt_identity()
    fault.is_active = False
    fault.resolved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"status": "acknowledged", "fault_id": fault_id}), 200


@prediction_bp.route("/maintenance-schedule/<device_id>", methods=["GET"])
@jwt_required()
def maintenance_schedule(device_id):
    """
    GET /api/predict/maintenance-schedule/<device_id>
    Returns upcoming and overdue maintenance items based on ML predictions + run hours.
    """
    from models import Machine, MaintenanceLog
    from datetime import date

    machine = Machine.query.filter_by(device_id=device_id).first()
    if not machine:
        return jsonify({"error": "Machine not found"}), 404

    latest = (
        SensorReading.query
        .filter_by(device_id=device_id)
        .order_by(desc(SensorReading.timestamp))
        .first()
    )

    # Devices without an hour meter send no run_hours
    run_hours = (latest.run_hours if latest else 0) or 0
    result = predict_fault(latest.to_dict() if latest else {"device_id": device_id})
    rul_days = result.get("rul_days", 365)
    urgency = result.get("maintenance_urgency", "SCHEDULED")

    # Standard maintenance schedule for induction motor + pump
    schedule = []

    # Bearing lubrication every 2000 hours
    bearing_due_hours = 2000 - (run_hours % 2000)
    schedule.append({
        "task": "Bearing Lubrication",
        "due_in_hours": bearing_due_hours,
        "due_in_days": round(bearing_due_hours / 24, 0),
        "priority": "HIGH" if bearing_due_hours < 200 else "LOW",
    })

    # Insulation resistance test every 6 months
    schedule.append({
        "task": "Insulation Resistance Test (Megger)",
        "due_in_days": 180,
        "priority": "MEDIUM",
    })

    # Coupling alignment check every 3 months
    schedule.append({
        "task": "Shaft Coupling Alignment Check",
        "due_in_days": 90,
        "priority": "MEDIUM",
    })

    # Air filter cleaning every 30 days
    schedule.append({
        "task": "Motor Air Filter Cleaning",
        "due_in_days": 30,
        "priority": "LOW",
    })

    # ML-based predictive action
    if result.get("fault_type") != "Normal Operation":
        urgent_days = 1 if urgency == "IMMEDIATE" else 2 if urgency == "WITHIN_48H" else 7
        schedule.insert(0, {
            "task": f"[ML ALERT] Inspect: {result.get('fault_type')}",
            "due_in_days": urgent_days,
            "priority": "CRITICAL" if urgency == "IMMEDIATE" else "HIGH",
            "recommendation": result.get("recommendation"),
            "ml_confidence": result.get("confidence"),
        })

    return jsonify({
        "device_id": device_id,
        "run_hours": round(run_hours, 1),
        "predicted_rul_days": rul_days,
        "maintenance_urgency": urgency,
        "schedule": schedule,
    }), 200


def _save_fault_event(device_id: str, prediction: dict):
    """Save ML-predicted fault to database."""
    try:
        existing = FaultEvent.query.filter_by(
            device_id=device_id,
            fault_type=prediction.get("fault_type"),
            is_active=True
        ).first()

        if not existing:
            fault = FaultEvent(
                device_id=device_id,
                fault_type=prediction.get("fault_type"),
                fault_code=prediction.get("fault_class", 0),
                severity=prediction.get("severity", "MEDIUM"),
                severity_score=prediction.get("severity_score", 0),
                root_cause=prediction.get("root_cause", ""),
                recommendation=prediction.get("recommendation", ""),
                predicted_by_ml=prediction.get("ml_predicted", False),
                ml_confidence=prediction.get("confidence", 0),
                failure_prob=prediction.get("failure_prob", 0),
                rul_days=prediction.get("rul_days"),
            )
            db.session.add(fault)
            db.session.commit()
    except Exception as e:
        print(f"[PRED] Error saving fault event: {e}")
        db.session.rollback()
