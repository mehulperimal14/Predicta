-- PREDICTA – PostgreSQL Database Schema
-- Run: psql -U postgres -c "CREATE DATABASE predicta_db;"
-- Then: psql -U postgres -d predicta_db -f schema.sql

-- Enable TimescaleDB extension (optional – for hypertables)
-- CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Users ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50) UNIQUE NOT NULL,
    email         VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    role          VARCHAR(20) DEFAULT 'operator',  -- admin|engineer|operator
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_login    TIMESTAMPTZ
);

-- ── Machines ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS machines (
    id            SERIAL PRIMARY KEY,
    device_id     VARCHAR(50) UNIQUE NOT NULL,
    name          VARCHAR(100) NOT NULL,
    location      VARCHAR(100),
    machine_type  VARCHAR(50),
    rated_power   FLOAT,
    rated_current FLOAT,
    rated_voltage FLOAT,
    rated_rpm     INTEGER,
    install_date  DATE,
    is_active     BOOLEAN DEFAULT TRUE,
    notes         TEXT
);

-- ── Sensor Readings (main time-series table) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS sensor_readings (
    id             BIGSERIAL PRIMARY KEY,
    device_id      VARCHAR(50) REFERENCES machines(device_id),
    timestamp      TIMESTAMPTZ DEFAULT NOW(),
    voltage        FLOAT,
    current        FLOAT,
    power_kw       FLOAT,
    energy_kwh     FLOAT,
    power_factor   FLOAT DEFAULT 0.85,
    motor_temp     FLOAT,
    bearing_temp   FLOAT,
    ambient_temp   FLOAT,
    humidity       FLOAT,
    vibration_rms  FLOAT,
    vibration_x    FLOAT,
    vibration_y    FLOAT,
    vibration_z    FLOAT,
    rpm            INTEGER,
    pressure       FLOAT,
    run_hours      FLOAT,
    start_cycles   INTEGER,
    motor_running  BOOLEAN DEFAULT TRUE,
    overload       BOOLEAN DEFAULT FALSE,
    overheat       BOOLEAN DEFAULT FALSE,
    high_vibration BOOLEAN DEFAULT FALSE,
    low_rpm        BOOLEAN DEFAULT FALSE,
    health_score   FLOAT,
    efficiency     FLOAT
);

CREATE INDEX IF NOT EXISTS idx_readings_device_time ON sensor_readings(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_readings_time ON sensor_readings(timestamp DESC);

-- ── Fault Events ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fault_events (
    id              SERIAL PRIMARY KEY,
    device_id       VARCHAR(50) REFERENCES machines(device_id),
    fault_type      VARCHAR(100),
    fault_code      INTEGER,
    severity        VARCHAR(20),
    severity_score  FLOAT,
    root_cause      TEXT,
    recommendation  TEXT,
    predicted_by_ml BOOLEAN DEFAULT FALSE,
    ml_confidence   FLOAT,
    failure_prob    FLOAT,
    rul_days        FLOAT,
    occurred_at     TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    acknowledged_by VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_faults_device ON fault_events(device_id, occurred_at DESC);

-- ── Maintenance Logs ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS maintenance_logs (
    id               SERIAL PRIMARY KEY,
    device_id        VARCHAR(50) REFERENCES machines(device_id),
    maintenance_type VARCHAR(50),
    description      TEXT,
    performed_by     VARCHAR(100),
    scheduled_date   DATE,
    completed_date   DATE,
    status           VARCHAR(20) DEFAULT 'SCHEDULED',
    cost_inr         FLOAT,
    downtime_hours   FLOAT DEFAULT 0,
    parts_replaced   TEXT,
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ── Alert History ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_history (
    id          SERIAL PRIMARY KEY,
    device_id   VARCHAR(50) NOT NULL,
    alert_type  VARCHAR(50),
    message     TEXT,
    severity    VARCHAR(20),
    sent_at     TIMESTAMPTZ DEFAULT NOW(),
    delivered   BOOLEAN DEFAULT FALSE,
    recipient   VARCHAR(200)
);

-- ── Energy Daily Summary ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS energy_daily (
    id          SERIAL PRIMARY KEY,
    device_id   VARCHAR(50) NOT NULL,
    date        DATE NOT NULL,
    total_kwh   FLOAT DEFAULT 0,
    peak_kw     FLOAT DEFAULT 0,
    avg_kw      FLOAT DEFAULT 0,
    run_hours   FLOAT DEFAULT 0,
    fault_count INTEGER DEFAULT 0,
    avg_health  FLOAT DEFAULT 100,
    UNIQUE(device_id, date)
);

-- ── Device Thresholds ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS device_thresholds (
    id               SERIAL PRIMARY KEY,
    device_id        VARCHAR(50) UNIQUE NOT NULL,
    voltage_min      FLOAT DEFAULT 380,
    voltage_max      FLOAT DEFAULT 440,
    current_flc      FLOAT DEFAULT 3.5,
    current_overload FLOAT DEFAULT 4.5,
    temp_warning     FLOAT DEFAULT 75,
    temp_critical    FLOAT DEFAULT 85,
    vibration_warn   FLOAT DEFAULT 0.5,
    vibration_crit   FLOAT DEFAULT 1.0,
    rpm_min          INTEGER DEFAULT 1200,
    rpm_max          INTEGER DEFAULT 1600,
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ── Views ────────────────────────────────────────────────────────────────────

-- Latest reading per machine
CREATE OR REPLACE VIEW v_machine_latest AS
SELECT DISTINCT ON (device_id)
    device_id, timestamp, voltage, current, motor_temp,
    vibration_rms, rpm, health_score, efficiency, motor_running
FROM sensor_readings
ORDER BY device_id, timestamp DESC;

-- Daily fault summary
CREATE OR REPLACE VIEW v_daily_faults AS
SELECT
    device_id,
    DATE(occurred_at) AS fault_date,
    COUNT(*) AS fault_count,
    COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_count,
    COUNT(*) FILTER (WHERE severity = 'HIGH') AS high_count
FROM fault_events
GROUP BY device_id, DATE(occurred_at)
ORDER BY fault_date DESC;

-- ── Initial Data ─────────────────────────────────────────────────────────────

-- Default machine
INSERT INTO machines (device_id, name, location, machine_type, rated_power, rated_current, rated_voltage, rated_rpm, install_date)
VALUES ('MOTOR_01', 'Cooling Tower Pump Motor #1', 'Production Hall A', 'induction_motor', 1.5, 3.5, 415, 1440, '2023-01-15')
ON CONFLICT (device_id) DO NOTHING;

-- Default thresholds
INSERT INTO device_thresholds (device_id) VALUES ('MOTOR_01')
ON CONFLICT (device_id) DO NOTHING;
