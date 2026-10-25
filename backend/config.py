"""
PREDICTA – Application Configuration
Loads from environment variables with sensible industrial defaults.
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ─── Flask ────────────────────────────────────────────────────────────────
    SECRET_KEY = os.getenv("SECRET_KEY", "predicta-super-secret-key-change-in-production")
    DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    # ─── Database ─────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///predicta.db"   # SQLite for local dev – no PostgreSQL needed
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ─── JWT ──────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "predicta-jwt-secret-key")
    JWT_ACCESS_TOKEN_EXPIRES  = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # ─── MQTT (Mosquitto Broker) ───────────────────────────────────────────────
    MQTT_BROKER_HOST    = os.getenv("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT    = int(os.getenv("MQTT_BROKER_PORT", 1883))
    MQTT_USERNAME       = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD       = os.getenv("MQTT_PASSWORD", "")
    MQTT_TOPIC_DATA     = "predicta/sensor/data"
    MQTT_TOPIC_ALERTS   = "predicta/alerts"
    MQTT_TOPIC_COMMANDS = "predicta/commands"
    MQTT_KEEPALIVE      = 60

    # ─── Alert Configuration ──────────────────────────────────────────────────
    # Email (Gmail SMTP or SendGrid)
    SMTP_SERVER   = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "your_email@gmail.com")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "your_app_password")
    ALERT_FROM    = os.getenv("ALERT_FROM", "predicta-alerts@gmail.com")
    ALERT_EMAILS  = os.getenv("ALERT_EMAILS", "engineer@company.com").split(",")

    # Telegram
    TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")

    # Twilio SMS
    TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER  = os.getenv("TWILIO_FROM_NUMBER", "")
    ALERT_SMS_RECIPIENTS = [s.strip() for s in os.getenv("ALERT_SMS_RECIPIENTS", "").split(",") if s.strip()]

    # Notification & Historical Replay Guard
    ALLOW_HISTORICAL_REPLAY = os.getenv("ALLOW_HISTORICAL_REPLAY", "False").lower() == "true"
    NOTIFICATION_MOCK_MODE  = os.getenv("NOTIFICATION_MOCK_MODE", "True").lower() == "true"
    NOTIFICATION_COOLDOWN_MINUTES = int(os.getenv("NOTIFICATION_COOLDOWN_MINUTES", 15))

    # ─── File Uploads (PLC/SCADA Ingestion) ───────────────────────────────────
    UPLOAD_FOLDER       = os.getenv("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "uploads"))
    MAX_CONTENT_LENGTH  = 100 * 1024 * 1024  # 100 MB max file size
    ALLOWED_EXTENSIONS  = {"csv", "xlsx", "xls"}

    # ─── Machine Thresholds (defaults, overridable per-device in DB) ──────────
    THRESHOLDS = {
        "voltage_min":      380.0,   # V (3-phase line voltage)
        "voltage_max":      440.0,
        "current_flc":       3.5,    # A (full load current)
        "current_overload":  4.5,    # A (130% FLC)
        "temp_warning":     75.0,    # °C
        "temp_critical":    85.0,    # °C
        "bearing_temp_warn": 70.0,
        "vibration_warn":    0.5,    # g RMS
        "vibration_crit":    1.0,
        "rpm_min":         1200,     # RPM
        "rpm_max":         1600,
        "pressure_min":      50.0,   # kPa
        "pressure_max":     600.0,
    }

    # ─── Machine Learning ─────────────────────────────────────────────────────
    ML_MODEL_PATH       = os.getenv("ML_MODEL_PATH", "ml_model/saved_models/")
    ML_SCALER_PATH      = os.getenv("ML_SCALER_PATH", "ml_model/saved_models/scaler.pkl")
    ML_CONFIDENCE_MIN   = 0.65      # Minimum confidence to trigger alert
    ML_PREDICTION_WINDOW = 10       # Number of readings to average before prediction

    # ─── Data Retention ───────────────────────────────────────────────────────
    DATA_RETENTION_DAYS = 365       # Keep 1 year of sensor data
    AGGREGATION_INTERVAL = 60       # Aggregate raw data every 60 seconds

    # ─── PDF Reports ──────────────────────────────────────────────────────────
    REPORT_OUTPUT_DIR = os.getenv("REPORT_OUTPUT_DIR", "reports/")

    # ─── Rate Limiting ────────────────────────────────────────────────────────
    RATELIMIT_DEFAULT = "200 per minute"


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False  # Set True to see SQL queries


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_POOL_SIZE = 20
    SQLALCHEMY_MAX_OVERFLOW = 40


config = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig
}
