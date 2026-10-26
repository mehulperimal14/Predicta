"""
Tests for PREDICTA – Segment B: Live IoT Monitoring
Device keys, authenticated ingest, and live health / trend / time-to-breakdown assessment.
"""

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app import create_app
from database import db


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            from app import _seed_default_data
            _seed_default_data(app)
        yield client


def _auth(client, username="admin", password="Predicta@2024"):
    token = client.post("/api/auth/login", json={"username": username, "password": password}).get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _register(client, device_id):
    res = client.post("/api/live/devices", json={"device_id": device_id}, headers=_auth(client))
    assert res.status_code == 201, res.get_json()
    return res.get_json()["device_key"]


def _readings(device_id, n=200, degrade_from=None, step_s=10, seed=0):
    """Steady readings every step_s seconds ending ~now; bearing temp ramps after degrade_from."""
    rng = np.random.default_rng(seed)
    start = datetime.utcnow() - timedelta(seconds=n * step_s)
    rows = []
    for i in range(n):
        bearing = 50.0 + rng.normal(0, 0.2)
        if degrade_from is not None and i >= degrade_from:
            bearing += 0.25 * (i - degrade_from)          # 90 °C/h friction heating
        rows.append({
            "timestamp": (start + timedelta(seconds=i * step_s)).isoformat(),
            "device_id": device_id,
            "voltage": round(415 + rng.normal(0, 1.0), 1),
            "current": round(3.2 + rng.normal(0, 0.03), 2),
            "motor_temp": round(58 + rng.normal(0, 0.3), 1),
            "bearing_temp": round(bearing, 1),
            "vibration_rms": round(0.15 + abs(rng.normal(0, 0.01)), 3),
            "rpm": 1440,
            "motor_running": True,
        })
    return rows


def test_ingest_rejects_missing_or_wrong_key(client):
    reading = {"device_id": "MOTOR_01", "motor_temp": 55.0}
    assert client.post("/api/live/ingest", json=reading).status_code == 401
    assert client.post("/api/sensor/ingest", json=reading).status_code == 401
    assert client.post("/api/live/ingest", json=reading, headers={"X-Device-Key": "pdk_wrong"}).status_code == 401
    # Unknown devices are no longer auto-registered
    unknown = {"device_id": "ROGUE_01", "motor_temp": 55.0}
    assert client.post("/api/live/ingest", json=unknown, headers={"X-Device-Key": "pdk_x"}).status_code == 401


def test_operator_cannot_register_devices(client):
    res = client.post("/api/live/devices", json={"device_id": "PUMP_9"},
                      headers=_auth(client, "operator", "Operator@2024"))
    assert res.status_code == 403


def test_degrading_device_gets_time_to_breakdown(client):
    key = _register(client, "TEST_DEV_01")
    res = client.post("/api/live/ingest", headers={"X-Device-Key": key}, json={
        "device_id": "TEST_DEV_01", "readings": _readings("TEST_DEV_01", degrade_from=100)})
    assert res.status_code == 201
    body = res.get_json()
    assert body["accepted"] == 200
    assert body["assessment"] is not None

    a = client.get("/api/live/devices/TEST_DEV_01/assessment?refresh=1", headers=_auth(client)).get_json()
    assert a["online"] is True
    assert a["status"] == "DEGRADING"
    ttb = a["time_to_breakdown"]
    assert ttb["variable"] == "bearing_temp"
    assert 0 < ttb["hours"] < 1.0
    bearing = [v for v in a["trend_forecast"]["variables"] if v["variable"] == "bearing_temp"][0]
    assert bearing["direction"] == "RISING"
    assert len(a["hypotheses"]) == 9
    assert "bearing_temp" in a["charts"]["variables"]


def test_steady_device_is_healthy(client):
    key = _register(client, "TEST_DEV_02")
    client.post("/api/live/ingest", headers={"X-Device-Key": key},
                json={"device_id": "TEST_DEV_02", "readings": _readings("TEST_DEV_02", seed=1)})
    a = client.get("/api/live/devices/TEST_DEV_02/assessment?refresh=1", headers=_auth(client)).get_json()
    assert a["status"] == "HEALTHY", a["headline"]
    assert a["time_to_breakdown"] is None


def test_rotate_key_invalidates_old_key(client):
    old_key = _register(client, "TEST_DEV_03")
    reading = {"device_id": "TEST_DEV_03", "motor_temp": 55.0, "current": 3.1}
    assert client.post("/api/live/ingest", json=reading, headers={"X-Device-Key": old_key}).status_code == 201

    rotated = client.post("/api/live/devices/TEST_DEV_03/rotate-key", headers=_auth(client)).get_json()
    assert client.post("/api/live/ingest", json=reading, headers={"X-Device-Key": old_key}).status_code == 401
    assert client.post("/api/live/ingest", json=reading,
                       headers={"X-Device-Key": rotated["device_key"]}).status_code == 201

    fleet = client.get("/api/live/fleet", headers=_auth(client)).get_json()
    entry = [d for d in fleet if d["device_id"] == "TEST_DEV_03"][0]
    assert entry["streaming_enabled"] is True
    assert "device_key" not in entry


def test_fleet_lists_only_live_devices(client):
    from models import Machine
    with client.application.app_context():
        db.session.add(Machine(device_id="FILE-ASSET-9", name="Asset from an uploaded file"))  # as Segment A does
        db.session.commit()
    _register(client, "TEST_DEV_05")
    ids = [d["device_id"] for d in client.get("/api/live/fleet", headers=_auth(client)).get_json()]
    assert "TEST_DEV_05" in ids
    assert "FILE-ASSET-9" not in ids


def test_device_without_readings_reports_no_data(client):
    _register(client, "TEST_DEV_04")
    a = client.get("/api/live/devices/TEST_DEV_04/assessment", headers=_auth(client)).get_json()
    assert a["status"] == "NO_DATA"
