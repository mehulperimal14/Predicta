"""
Tests for PREDICTA 2.0 – Notification Engine, Formatting, Cooldowns & Replay Guard
"""

import os
import pytest
from datetime import datetime

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from notifications import (
    format_telegram_alert, format_sms_alert, is_in_cooldown,
    send_telegram_message, send_sms_twilio
)


def test_telegram_message_formatting():
    msg = format_telegram_alert(
        asset_id="MOTOR-PUMP-01",
        severity="WARNING",
        title="Motor Temperature Elevated",
        evidence=[
            "Motor temp 82.5°C exceeds 75.0°C limit",
            "Current normal at 3.4A (cooling degradation pattern)"
        ],
        suggested_action="Inspect cooling cowl and air filter."
    )
    assert "PREDICTA 2.0" in msg
    assert "MOTOR-PUMP-01" in msg
    assert "WARNING" in msg
    assert "Inspect cooling cowl" in msg


def test_sms_message_formatting():
    msg = format_sms_alert(
        asset_id="MOTOR-02",
        severity="CRITICAL",
        title="Overload Detected"
    )
    assert "PREDICTA CRITICAL" in msg
    assert "MOTOR-02" in msg
    assert len(msg) < 160  # fits standard single-segment SMS


def test_alert_cooldown_deduplication():
    # First time should not be in cooldown
    res1 = is_in_cooldown("ASSET-TEST-COOL", "BEARING_OVERHEAT", cooldown_minutes=5)
    assert res1 is False

    # Immediate second call for same asset & fault should be suppressed by cooldown
    res2 = is_in_cooldown("ASSET-TEST-COOL", "BEARING_OVERHEAT", cooldown_minutes=5)
    assert res2 is True

    # Different fault type for same asset should not be suppressed
    res3 = is_in_cooldown("ASSET-TEST-COOL", "VOLTAGE_SAG", cooldown_minutes=5)
    assert res3 is False


def test_sms_mock_mode_safe_execution():
    res = send_sms_twilio(
        account_sid="",
        auth_token="",
        from_number="",
        to_number="+15551234567",
        message="Test alert",
        mock_mode=True
    )
    assert res["delivered"] is True
    assert res["mock"] is True
    assert res["provider"] == "SMS_MOCK"
