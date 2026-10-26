"""
PREDICTA – Segment B: Live IoT Monitoring API
Device registration with per-device keys, authenticated telemetry ingest from
ESP32 / microcontrollers, and live health / trend / time-to-breakdown assessments.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from database import db
from models import Machine, DeviceCredential
from live_engine import (
    ingest_readings, issue_device_key, verify_device_key, assess_device, fleet_summary
)

live_bp = Blueprint("live", __name__)

DEVICE_KEY_HEADER = "X-Device-Key"


def _require_role(*roles):
    """Returns an error response tuple when the JWT role is not allowed, else None."""
    if get_jwt().get("role") not in roles:
        return jsonify({"error": f"Requires role: {' or '.join(roles)}"}), 403
    return None


# ─── Telemetry ingest (device-authenticated, no user login) ───────────────────

@live_bp.route("/ingest", methods=["POST"])
def ingest():
    """
    POST /api/live/ingest
    Header: X-Device-Key: <key issued at registration>
    Body:   one reading  {"device_id": "MOTOR_01", "motor_temp": 61.2, "current": 3.4, ...}
       or   a batch      {"device_id": "MOTOR_01", "readings": [{...,"timestamp": 1730000000}, ...]}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data.get("device_id"):
        return jsonify({"error": "JSON body with device_id required"}), 400

    device_id = str(data["device_id"])
    if not verify_device_key(device_id, request.headers.get(DEVICE_KEY_HEADER)):
        # Same response for unknown device and wrong key: do not reveal which devices exist.
        return jsonify({"error": f"Invalid device_id or {DEVICE_KEY_HEADER}"}), 401

    readings = data.get("readings")
    if readings is None:
        readings = [data]
    if not isinstance(readings, list) or not readings:
        return jsonify({"error": "'readings' must be a non-empty list"}), 400

    result = ingest_readings(device_id, [r for r in readings if isinstance(r, dict)])
    return jsonify({"status": "ok", "device_id": device_id, **result}), 201


# ─── Device registry & keys ───────────────────────────────────────────────────

@live_bp.route("/devices", methods=["GET"])
@jwt_required()
def list_devices():
    """GET /api/live/devices – registered devices with streaming-key status (never the key)."""
    return jsonify(fleet_summary()), 200


@live_bp.route("/devices", methods=["POST"])
@jwt_required()
def register_device():
    """
    POST /api/live/devices  (admin / engineer)
    Body: {"device_id": "PUMP_02", "name": "...", "location": "...", "machine_type": "pump",
           "rated_power": 1.5, "rated_current": 3.5, "rated_voltage": 415, "rated_rpm": 1440}
    Registers the device (or enables streaming for an existing machine) and returns its
    key ONCE. Use /devices/<id>/rotate-key if the key is lost.
    """
    denied = _require_role("admin", "engineer")
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    device_id = str(data.get("device_id", "")).strip()
    if not device_id or len(device_id) > 50:
        return jsonify({"error": "device_id required (max 50 characters)"}), 400

    if DeviceCredential.query.filter_by(device_id=device_id, is_active=True).first():
        return jsonify({"error": f"{device_id} already has a streaming key. Rotate it instead."}), 409

    machine = Machine.query.filter_by(device_id=device_id).first()
    if not machine:
        machine = Machine(
            device_id=device_id,
            name=data.get("name") or f"Machine {device_id}",
            location=data.get("location"),
            machine_type=data.get("machine_type") or "induction_motor",
            rated_power=data.get("rated_power", 1.5),
            rated_current=data.get("rated_current", 3.5),
            rated_voltage=data.get("rated_voltage", 415),
            rated_rpm=data.get("rated_rpm", 1440),
            is_active=True,
        )
        db.session.add(machine)
        db.session.commit()

    key = issue_device_key(device_id, created_by=str(get_jwt_identity()))
    return jsonify({
        "device": machine.to_dict(),
        "device_key": key,
        "ingest_url": request.host_url.rstrip("/") + "/api/live/ingest",
        "header": DEVICE_KEY_HEADER,
        "note": "Store this key in the device firmware now. It is not shown again.",
    }), 201


@live_bp.route("/devices/<device_id>/rotate-key", methods=["POST"])
@jwt_required()
def rotate_key(device_id):
    """POST /api/live/devices/<id>/rotate-key (admin / engineer) – old key stops working immediately."""
    denied = _require_role("admin", "engineer")
    if denied:
        return denied
    Machine.query.filter_by(device_id=device_id).first_or_404()
    key = issue_device_key(device_id, created_by=str(get_jwt_identity()))
    return jsonify({"device_id": device_id, "device_key": key, "header": DEVICE_KEY_HEADER}), 200


@live_bp.route("/devices/<device_id>/key", methods=["DELETE"])
@jwt_required()
def revoke_key(device_id):
    """DELETE /api/live/devices/<id>/key (admin) – stop accepting telemetry from this device."""
    denied = _require_role("admin")
    if denied:
        return denied
    cred = DeviceCredential.query.filter_by(device_id=device_id).first_or_404()
    cred.is_active = False
    db.session.commit()
    return jsonify({"device_id": device_id, "streaming_enabled": False}), 200


# ─── Live assessment ──────────────────────────────────────────────────────────

@live_bp.route("/fleet", methods=["GET"])
@jwt_required()
def fleet():
    """GET /api/live/fleet – every device with online state and latest health status."""
    return jsonify(fleet_summary()), 200


@live_bp.route("/devices/<device_id>/assessment", methods=["GET"])
@jwt_required()
def device_assessment(device_id):
    """
    GET /api/live/devices/<id>/assessment?window=720&refresh=1
    Health status, trend per variable, time to warning / critical limit, likely causes.
    """
    Machine.query.filter_by(device_id=device_id).first_or_404()
    window = request.args.get("window", type=int)
    if window is not None:
        window = max(30, min(window, 5000))
    refresh = request.args.get("refresh", "0") in ("1", "true", "yes")
    return jsonify(assess_device(device_id, window=window, force=refresh)), 200
