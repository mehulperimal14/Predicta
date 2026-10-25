"""
PREDICTA 2.0 – Notification Configuration & Testing Routes
Manage Telegram Bot API & Twilio SMS settings, trigger test notifications,
and review delivery audit trails.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from datetime import datetime

from database import db
from models import NotificationConfig, AlertHistory, AuditLog
from notifications import (
    send_telegram_message, send_sms_twilio,
    format_telegram_alert, format_sms_alert, get_active_notification_config
)

notification_bp = Blueprint("notifications", __name__)


@notification_bp.route("/config", methods=["GET"])
@jwt_required()
def get_config():
    """GET /api/notifications/config – Return active notification settings (masked secrets)."""
    cfg = NotificationConfig.query.first()
    if not cfg:
        # Create default config record
        cfg = NotificationConfig(
            telegram_enabled=False,
            telegram_min_severity="WARNING",
            sms_enabled=False,
            sms_min_severity="CRITICAL",
            cooldown_minutes=15,
            allow_historical_replay=False,
            mock_mode=True
        )
        db.session.add(cfg)
        db.session.commit()
        
    cfg_dict = cfg.to_dict()
    # Mask secrets
    if cfg.telegram_bot_token:
        cfg_dict["telegram_bot_token_masked"] = cfg.telegram_bot_token[:6] + "..." + cfg.telegram_bot_token[-4:]
    else:
        cfg_dict["telegram_bot_token_masked"] = ""
        
    if cfg.twilio_auth_token:
        cfg_dict["twilio_auth_token_masked"] = "••••••••••••"
    else:
        cfg_dict["twilio_auth_token_masked"] = ""

    return jsonify(cfg_dict), 200


@notification_bp.route("/config", methods=["POST"])
@jwt_required()
def update_config():
    """POST /api/notifications/config – Update notification settings and channel credentials."""
    claims = get_jwt()
    if claims.get("role") not in ["admin", "engineer"]:
        return jsonify({"error": "Admin or Engineer privileges required"}), 403
        
    data = request.get_json() or {}
    cfg = NotificationConfig.query.first()
    if not cfg:
        cfg = NotificationConfig()
        db.session.add(cfg)
        
    if "telegram_enabled" in data:
        cfg.telegram_enabled = bool(data["telegram_enabled"])
    if "telegram_bot_token" in data and data["telegram_bot_token"] and not data["telegram_bot_token"].startswith("•••"):
        cfg.telegram_bot_token = data["telegram_bot_token"].strip()
    if "telegram_chat_ids" in data:
        cfg.telegram_chat_ids = data["telegram_chat_ids"].strip()
    if "telegram_min_severity" in data:
        cfg.telegram_min_severity = data["telegram_min_severity"]
        
    if "sms_enabled" in data:
        cfg.sms_enabled = bool(data["sms_enabled"])
    if "twilio_account_sid" in data and data["twilio_account_sid"]:
        cfg.twilio_account_sid = data["twilio_account_sid"].strip()
    if "twilio_auth_token" in data and data["twilio_auth_token"] and not data["twilio_auth_token"].startswith("•••"):
        cfg.twilio_auth_token = data["twilio_auth_token"].strip()
    if "twilio_from_number" in data:
        cfg.twilio_from_number = data["twilio_from_number"].strip()
    if "sms_recipient_numbers" in data:
        cfg.sms_recipient_numbers = data["sms_recipient_numbers"].strip()
    if "sms_min_severity" in data:
        cfg.sms_min_severity = data["sms_min_severity"]
        
    if "cooldown_minutes" in data:
        cfg.cooldown_minutes = max(1, int(data["cooldown_minutes"]))
    if "allow_historical_replay" in data:
        cfg.allow_historical_replay = bool(data["allow_historical_replay"])
    if "mock_mode" in data:
        cfg.mock_mode = bool(data["mock_mode"])
        
    cfg.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({"status": "success", "config": cfg.to_dict()}), 200


@notification_bp.route("/test-telegram", methods=["POST"])
@jwt_required()
def test_telegram():
    """POST /api/notifications/test-telegram – Trigger test message to configured Telegram bot & chats."""
    cfg = get_active_notification_config()
    token = cfg.get("telegram_token")
    chats = cfg.get("telegram_chats")
    
    if not token or not chats:
        return jsonify({
            "status": "error",
            "message": "Telegram Bot Token and at least one Chat ID must be configured in settings."
        }), 400
        
    test_msg = format_telegram_alert(
        asset_id="TEST-ASSET-01",
        severity="WARNING",
        title="Predicta 2.0 Notification Verification Test",
        evidence=[
            "Test communication packet dispatched from Predicta 2.0 Web Platform",
            "Telegram Bot API connectivity verified",
            "Audit logging and alert dispatch operational"
        ],
        suggested_action="No action required. This is a system verification message."
    )
    
    outcomes = []
    for chat_id in chats:
        res = send_telegram_message(token, chat_id, test_msg)
        outcomes.append(res)
        
        # Log test event
        log = AlertHistory(
            device_id="TEST-ASSET-01",
            alert_type="TELEGRAM_TEST",
            message="Telegram verification message",
            severity="LOW",
            sent_at=datetime.utcnow(),
            delivered=res.get("delivered", False),
            recipient=chat_id
        )
        db.session.add(log)
    db.session.commit()

    all_delivered = all(o.get("delivered") for o in outcomes)
    return jsonify({
        "status": "success" if all_delivered else "partial_failure",
        "outcomes": outcomes
    }), 200 if all_delivered else 207


@notification_bp.route("/test-sms", methods=["POST"])
@jwt_required()
def test_sms():
    """POST /api/notifications/test-sms – Trigger test SMS via Twilio or Mock mode."""
    cfg = get_active_notification_config()
    recipients = cfg.get("sms_recipients")
    
    if not recipients:
        return jsonify({
            "status": "error",
            "message": "At least one recipient phone number (E.164 format, e.g. +1234567890) required."
        }), 400
        
    test_msg = format_sms_alert(
        asset_id="TEST-ASSET-01",
        severity="CRITICAL",
        title="Test Alert Verification"
    )
    
    outcomes = []
    for phone in recipients:
        res = send_sms_twilio(
            cfg.get("twilio_sid", ""),
            cfg.get("twilio_token", ""),
            cfg.get("twilio_from", ""),
            phone,
            test_msg,
            mock_mode=cfg.get("mock_mode", True)
        )
        outcomes.append(res)
        
        # Log to DB
        log = AlertHistory(
            device_id="TEST-ASSET-01",
            alert_type="SMS_TEST",
            message=test_msg,
            severity="LOW",
            sent_at=datetime.utcnow(),
            delivered=res.get("delivered", False),
            recipient=phone
        )
        db.session.add(log)
    db.session.commit()

    return jsonify({
        "status": "success",
        "mock_mode": cfg.get("mock_mode", True),
        "outcomes": outcomes
    }), 200


@notification_bp.route("/history", methods=["GET"])
@jwt_required()
def notification_history():
    """GET /api/notifications/history – Retrieve recent notification delivery audit logs."""
    limit = min(100, int(request.args.get("limit", 50)))
    logs = AlertHistory.query.order_by(AlertHistory.sent_at.desc()).limit(limit).all()
    return jsonify([l.to_dict() for l in logs]), 200
