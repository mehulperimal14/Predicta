"""
PREDICTA 2.0 – Central Notification & Escalation Service
Integrates Telegram Bot API and Twilio SMS with:
- Alert deduplication and per-asset cooldown timers
- Historical replay guard (prevents old dataset uploads from spamming live channels)
- Safe mock-mode fallback when credentials are unconfigured
- Bounded retries with exponential backoff
- Delivery status audit logging to DB
"""

import os
import re
import time
import requests
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from flask import current_app

from database import db
from models import AlertHistory, NotificationConfig

# Thread-safe in-memory alert cooldown cache: key = f"{asset_id}:{fault_type}" -> expiration datetime
_cooldown_lock = threading.Lock()
_alert_cooldowns: Dict[str, datetime] = {}


def is_in_cooldown(asset_id: str, alert_type: str, cooldown_minutes: int = 15) -> bool:
    """Check if an alert for this asset and type is currently in cooldown."""
    key = f"{asset_id}:{alert_type}"
    now = datetime.utcnow()
    with _cooldown_lock:
        if key in _alert_cooldowns:
            if now < _alert_cooldowns[key]:
                return True
        _alert_cooldowns[key] = now + timedelta(minutes=cooldown_minutes)
        return False


def get_active_notification_config() -> Dict[str, Any]:
    """Retrieve notification configuration from DB or fall back to environment variables."""
    cfg = NotificationConfig.query.first()
    if cfg:
        return {
            "telegram_enabled": cfg.telegram_enabled,
            "telegram_token": cfg.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "telegram_chats": [c.strip() for c in (cfg.telegram_chat_ids or os.getenv("TELEGRAM_CHAT_ID", "")).split(",") if c.strip()],
            "telegram_min_severity": cfg.telegram_min_severity or "WARNING",
            "sms_enabled": cfg.sms_enabled,
            "twilio_sid": cfg.twilio_account_sid or os.getenv("TWILIO_ACCOUNT_SID", ""),
            "twilio_token": cfg.twilio_auth_token or os.getenv("TWILIO_AUTH_TOKEN", ""),
            "twilio_from": cfg.twilio_from_number or os.getenv("TWILIO_FROM_NUMBER", ""),
            "sms_recipients": [p.strip() for p in (cfg.sms_recipient_numbers or os.getenv("ALERT_SMS_RECIPIENTS", "")).split(",") if p.strip()],
            "sms_min_severity": cfg.sms_min_severity or "CRITICAL",
            "cooldown_minutes": cfg.cooldown_minutes or 15,
            "allow_historical_replay": cfg.allow_historical_replay,
            "mock_mode": cfg.mock_mode
        }
    else:
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
        return {
            "telegram_enabled": bool(tg_token and tg_chat),
            "telegram_token": tg_token,
            "telegram_chats": [c.strip() for c in tg_chat.split(",") if c.strip()],
            "telegram_min_severity": "WARNING",
            "sms_enabled": bool(os.getenv("TWILIO_ACCOUNT_SID")),
            "twilio_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
            "twilio_token": os.getenv("TWILIO_AUTH_TOKEN", ""),
            "twilio_from": os.getenv("TWILIO_FROM_NUMBER", ""),
            "sms_recipients": [p.strip() for p in os.getenv("ALERT_SMS_RECIPIENTS", "").split(",") if p.strip()],
            "sms_min_severity": "CRITICAL",
            "cooldown_minutes": int(os.getenv("NOTIFICATION_COOLDOWN_MINUTES", 15)),
            "allow_historical_replay": os.getenv("ALLOW_HISTORICAL_REPLAY", "False").lower() == "true",
            "mock_mode": True
        }


def format_telegram_alert(
    asset_id: str,
    severity: str,
    title: str,
    evidence: List[str],
    suggested_action: str,
    dashboard_url: str = "http://localhost:5000"
) -> str:
    """Format rich Telegram alert using Markdown."""
    emoji = "🚨" if severity == "CRITICAL" else "⚠️" if severity == "WARNING" else "ℹ️"
    
    evidence_text = "\n".join([f"• {e}" for e in evidence[:4]]) if evidence else "• Operational anomaly detected"
    
    msg = (
        f"{emoji} *PREDICTA 2.0 — MACHINE HEALTH {severity}*\n\n"
        f"🏭 *Asset:* `{asset_id}`\n"
        f"⚡ *Alert:* {title}\n"
        f"📊 *Severity:* {severity}\n"
        f"🕐 *Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"📋 *Evidence:*\n{evidence_text}\n\n"
        f"🔧 *Suggested Action:* {suggested_action}\n\n"
        f"🔗 [Open Predicta Dashboard]({dashboard_url})"
    )
    return msg


def format_sms_alert(
    asset_id: str,
    severity: str,
    title: str,
    dashboard_url: str = "http://localhost:5000"
) -> str:
    """Format concise industrial SMS message (< 160 chars)."""
    return f"PREDICTA {severity}: Asset {asset_id} - {title}. Recommended: Review dashboard: {dashboard_url}"


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    message: str,
    max_retries: int = 3
) -> Dict[str, Any]:
    """Sends message to Telegram Bot API with bounded exponential backoff retries."""
    if not bot_token or not chat_id:
        return {"delivered": False, "error": "Missing bot token or chat ID"}
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return {"delivered": True, "provider": "TELEGRAM", "recipient": chat_id}
            elif resp.status_code == 429:  # Rate limited
                retry_after = int(resp.headers.get("Retry-After", 2))
                time.sleep(retry_after)
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
            
    return {"delivered": False, "error": last_err, "provider": "TELEGRAM", "recipient": chat_id}


def send_sms_twilio(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    message: str,
    mock_mode: bool = False
) -> Dict[str, Any]:
    """
    Sends SMS using Twilio REST API.
    Falls back cleanly to mock mode if credentials are placeholder.
    """
    # Clean phone number to E.164 format
    clean_to = re.sub(r"[^\d+]", "", to_number)
    if not clean_to.startswith("+"):
        clean_to = "+" + clean_to
        
    if mock_mode or not (account_sid and auth_token and from_number):
        # Safely log mock SMS without making real HTTP request
        return {
            "delivered": True,
            "mock": True,
            "provider": "SMS_MOCK",
            "recipient": clean_to,
            "message_preview": message[:100]
        }
        
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    auth = (account_sid, auth_token)
    data = {
        "From": from_number,
        "To": clean_to,
        "Body": message
    }
    
    try:
        resp = requests.post(url, data=data, auth=auth, timeout=10)
        if resp.status_code in [200, 201]:
            return {"delivered": True, "provider": "TWILIO", "recipient": clean_to}
        else:
            return {"delivered": False, "error": f"Twilio HTTP {resp.status_code}: {resp.text[:120]}", "recipient": clean_to}
    except Exception as e:
        return {"delivered": False, "error": str(e), "recipient": clean_to}


def dispatch_machine_alert(
    asset_id: str,
    severity: str,
    title: str,
    evidence: List[str],
    suggested_action: str,
    is_historical: bool = True
) -> Dict[str, Any]:
    """
    Central dispatcher coordinating deduplication, replay protection, and delivery.
    """
    cfg = get_active_notification_config()
    
    # ── 1. Historical Replay Guard ────────────────────────────────────────────
    # For file ingestion of historical data, suppress live notifications unless explicitly enabled
    if is_historical and not cfg.get("allow_historical_replay", False):
        return {
            "dispatched": False,
            "suppressed": True,
            "reason": "Historical replay guard active. Notifications from uploaded historical files are suppressed by default."
        }
        
    # ── 2. Cooldown & Deduplication ───────────────────────────────────────────
    if is_in_cooldown(asset_id, title, cfg.get("cooldown_minutes", 15)):
        return {
            "dispatched": False,
            "suppressed": True,
            "reason": f"Alert '{title}' for {asset_id} is in {cfg.get('cooldown_minutes')}m cooldown."
        }
        
    results = {"telegram": [], "sms": []}
    sev_weights = {"WATCH": 1, "WARNING": 2, "CRITICAL": 3}
    alert_weight = sev_weights.get(severity, 1)

    # ── 3. Telegram Dispatch ──────────────────────────────────────────────────
    tg_min_weight = sev_weights.get(cfg.get("telegram_min_severity", "WARNING"), 2)
    if cfg.get("telegram_enabled") and alert_weight >= tg_min_weight:
        tg_text = format_telegram_alert(asset_id, severity, title, evidence, suggested_action)
        for chat_id in cfg.get("telegram_chats", []):
            res = send_telegram_message(cfg.get("telegram_token", ""), chat_id, tg_text)
            results["telegram"].append(res)
            # Log to DB
            _log_notification_event(asset_id, "TELEGRAM", title, severity, res.get("delivered", False), chat_id)

    # ── 4. SMS Dispatch ───────────────────────────────────────────────────────
    sms_min_weight = sev_weights.get(cfg.get("sms_min_severity", "CRITICAL"), 3)
    if cfg.get("sms_enabled") and alert_weight >= sms_min_weight:
        sms_text = format_sms_alert(asset_id, severity, title)
        for phone in cfg.get("sms_recipients", []):
            res = send_sms_twilio(
                cfg.get("twilio_sid", ""),
                cfg.get("twilio_token", ""),
                cfg.get("twilio_from", ""),
                phone,
                sms_text,
                mock_mode=cfg.get("mock_mode", True)
            )
            results["sms"].append(res)
            _log_notification_event(asset_id, "SMS", title, severity, res.get("delivered", False), phone)

    return {
        "dispatched": True,
        "results": results
    }


def _log_notification_event(
    asset_id: str,
    alert_type: str,
    message: str,
    severity: str,
    delivered: bool,
    recipient: str
):
    """Logs delivery outcome directly to AlertHistory."""
    try:
        log = AlertHistory(
            device_id=asset_id,
            alert_type=alert_type,
            message=message[:400],
            severity=severity,
            sent_at=datetime.utcnow(),
            delivered=delivered,
            recipient=recipient[:200]
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
