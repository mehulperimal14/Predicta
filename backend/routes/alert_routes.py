"""
PREDICTA – Alert Management Routes
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from sqlalchemy import desc

from database import db
from models import AlertHistory, MaintenanceLog

alert_bp = Blueprint("alerts", __name__)


@alert_bp.route("/history/<device_id>", methods=["GET"])
@jwt_required()
def alert_history(device_id):
    days  = int(request.args.get("days", 7))
    since = datetime.utcnow() - timedelta(days=days)
    alerts = AlertHistory.query.filter(
        AlertHistory.device_id == device_id,
        AlertHistory.sent_at >= since
    ).order_by(desc(AlertHistory.sent_at)).limit(200).all()
    return jsonify([a.to_dict() for a in alerts]), 200


@alert_bp.route("/maintenance", methods=["GET"])
@jwt_required()
def list_maintenance():
    device_id = request.args.get("device_id")
    query = MaintenanceLog.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    logs = query.order_by(desc(MaintenanceLog.scheduled_date)).limit(100).all()
    return jsonify([m.to_dict() for m in logs]), 200


@alert_bp.route("/maintenance", methods=["POST"])
@jwt_required()
def create_maintenance():
    data = request.get_json()
    log = MaintenanceLog(
        device_id=data["device_id"],
        maintenance_type=data.get("maintenance_type", "Preventive"),
        description=data["description"],
        performed_by=data.get("performed_by", get_jwt_identity()),
        scheduled_date=datetime.strptime(data["scheduled_date"], "%Y-%m-%d").date(),
        status="SCHEDULED",
        cost_inr=data.get("cost_inr"),
        parts_replaced=data.get("parts_replaced"),
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify(log.to_dict()), 201


@alert_bp.route("/maintenance/<int:log_id>/complete", methods=["POST"])
@jwt_required()
def complete_maintenance(log_id):
    log = MaintenanceLog.query.get_or_404(log_id)
    log.status = "DONE"
    log.completed_date = datetime.utcnow().date()
    data = request.get_json() or {}
    log.downtime_hours = data.get("downtime_hours", 0)
    log.cost_inr = data.get("cost_inr", log.cost_inr)
    log.notes = data.get("notes", log.notes)
    db.session.commit()
    return jsonify(log.to_dict()), 200
