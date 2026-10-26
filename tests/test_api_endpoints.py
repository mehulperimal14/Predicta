"""
Integration tests for PREDICTA 2.0 Flask REST API Endpoints
"""

import os
import io
import json
import pytest

import sys
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


def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "PREDICTA 2.0 Online"
    assert data["version"] == "2.0.0"


def test_auth_login_and_token(client):
    res = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "Predicta@2024"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert "access_token" in data
    assert data["user"]["username"] == "admin"


def test_sample_datasets_list(client):
    res = client.get("/api/ingest/samples")
    assert res.status_code == 200
    samples = res.get_json()
    assert isinstance(samples, list)
    assert len(samples) >= 4
    filenames = [s["filename"] for s in samples]
    assert "motor_cooling_failure.csv" in filenames
    assert "pump_cavitation_anomaly.csv" in filenames


def test_file_upload_and_analysis_workflow(client):
    # 1. Login
    login_res = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "Predicta@2024"
    })
    token = login_res.get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Upload CSV
    csv_content = (
        "time,motor_temp,current,voltage,vibration_rms\n"
        "2026-01-01 10:00:00,55.0,3.2,415.0,0.12\n"
        "2026-01-01 10:01:00,56.0,3.3,415.2,0.13\n"
        "2026-01-01 10:02:00,82.0,4.8,414.0,0.48\n"
        "2026-01-01 10:03:00,89.5,5.4,413.5,0.95\n"
    )
    data = {
        "file": (io.BytesIO(csv_content.encode("utf-8")), "plant_test_data.csv")
    }
    upload_res = client.post("/api/ingest/upload", data=data, content_type="multipart/form-data", headers=headers)
    assert upload_res.status_code == 201
    upload_data = upload_res.get_json()
    assert upload_data["status"] == "success"
    assert upload_data["quality"]["score"] > 80.0
    dataset_id = upload_data["dataset_id"]

    # 3. Trigger 5-layer Analysis
    analyze_res = client.post(f"/api/ingest/analyze/{dataset_id}", json={
        "asset_id": "TEST-PUMP-01",
        "mapping": upload_data["suggested_mappings"],
        "trigger_notifications": False
    }, headers=headers)
    assert analyze_res.status_code == 200, f"Analysis failed: {analyze_res.get_json()}"
    analysis = analyze_res.get_json()

    assert analysis["status"] == "success"
    assert analysis["risk"]["risk_category"] in ["WARNING", "CRITICAL"]
    assert len(analysis["hypotheses"]) > 0
    assert "layer1_rules" in analysis
    assert "layer2_unsupervised" in analysis


def test_notification_config_and_mock_test(client):
    login_res = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "Predicta@2024"
    })
    token = login_res.get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Update config
    update_res = client.post("/api/notifications/config", json={
        "telegram_enabled": True,
        "telegram_chat_ids": "12345678",
        "sms_enabled": True,
        "sms_recipient_numbers": "+15551234567",
        "mock_mode": True
    }, headers=headers)
    assert update_res.status_code == 200

    # Trigger Test SMS in Mock mode
    sms_test_res = client.post("/api/notifications/test-sms", headers=headers)
    assert sms_test_res.status_code == 200
    sms_data = sms_test_res.get_json()
    assert sms_data["status"] == "success"
    assert sms_data["mock_mode"] is True

    # Check notification history
    hist_res = client.get("/api/notifications/history", headers=headers)
    assert hist_res.status_code == 200
    logs = hist_res.get_json()
    assert len(logs) > 0


@pytest.mark.parametrize("sample", [
    "motor_cooling_failure.csv", "pump_cavitation_anomaly.csv",
    "gearbox_vibration_wear.csv", "compressor_valve_degradation.xlsx",
])
def test_every_sample_dataset_analyses(client, sample):
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "Predicta@2024"})
    headers = {"Authorization": f"Bearer {login_res.get_json()['access_token']}"}
    path = os.path.join(os.path.dirname(__file__), "..", "backend", "sample_data", sample)
    with open(path, "rb") as f:
        up = client.post("/api/ingest/upload", data={"file": (io.BytesIO(f.read()), sample)},
                         content_type="multipart/form-data", headers=headers)
    assert up.status_code == 201, up.get_json()
    if sample.endswith(".xlsx"):
        assert up.get_json()["excel_sheets"] == ["Telemetry", "Asset_Info"]

    res = client.post(f"/api/ingest/analyze/{up.get_json()['dataset_id']}",
                      json={"mapping": up.get_json()["suggested_mappings"]}, headers=headers)
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert len(body["hypotheses"]) == 9
    assert body["risk"]["risk_category"] in ("WATCH", "WARNING", "CRITICAL")
    assert body["trend_forecast"]["available"] is True
    assert "changepoints" in body
    assert "Remaining Useful Life" in body["summary_markdown"]


def test_jwt_secret_is_not_a_published_literal():
    from config import Config
    assert Config.JWT_SECRET_KEY not in ("predicta-jwt-secret-key", "")
    assert len(Config.SECRET_KEY) >= 32
