"""
PREDICTA – SQLAlchemy Database Models
Defines all ORM models for PostgreSQL tables.
"""

from datetime import datetime
from database import db


# ─── Users & Authentication ───────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"

    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(50), unique=True, nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    password_hash= db.Column(db.String(256), nullable=False)
    role         = db.Column(db.String(20), default="operator")  # admin|engineer|operator
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    last_login   = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }


# ─── Machine / Device Registry ────────────────────────────────────────────────

class Machine(db.Model):
    __tablename__ = "machines"

    id           = db.Column(db.Integer, primary_key=True)
    device_id    = db.Column(db.String(50), unique=True, nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    location     = db.Column(db.String(100))
    machine_type = db.Column(db.String(50))          # motor, pump, compressor
    rated_power  = db.Column(db.Float)               # kW
    rated_current= db.Column(db.Float)               # A (FLC)
    rated_voltage= db.Column(db.Float)               # V
    rated_rpm    = db.Column(db.Integer)
    install_date = db.Column(db.Date)
    is_active    = db.Column(db.Boolean, default=True)
    notes        = db.Column(db.Text)

    readings = db.relationship("SensorReading", backref="machine", lazy="dynamic")
    faults   = db.relationship("FaultEvent", backref="machine", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "name": self.name,
            "location": self.location,
            "machine_type": self.machine_type,
            "rated_power": self.rated_power,
            "rated_current": self.rated_current,
            "rated_voltage": self.rated_voltage,
            "rated_rpm": self.rated_rpm,
            "is_active": self.is_active,
        }


# ─── Real-Time Sensor Readings ────────────────────────────────────────────────

class SensorReading(db.Model):
    __tablename__ = "sensor_readings"

    id             = db.Column(db.Integer, primary_key=True)
    device_id      = db.Column(db.String(50), db.ForeignKey("machines.device_id"), nullable=False)
    timestamp      = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Electrical
    voltage        = db.Column(db.Float)   # V
    current        = db.Column(db.Float)   # A
    power_kw       = db.Column(db.Float)   # kW
    energy_kwh     = db.Column(db.Float)   # kWh cumulative
    power_factor   = db.Column(db.Float, default=0.85)

    # Thermal
    motor_temp     = db.Column(db.Float)   # °C
    bearing_temp   = db.Column(db.Float)   # °C
    ambient_temp   = db.Column(db.Float)   # °C
    humidity       = db.Column(db.Float)   # %RH

    # Mechanical
    vibration_rms  = db.Column(db.Float)   # g
    vibration_x    = db.Column(db.Float)
    vibration_y    = db.Column(db.Float)
    vibration_z    = db.Column(db.Float)
    rpm            = db.Column(db.Integer)
    pressure       = db.Column(db.Float)   # kPa

    # Operational
    run_hours      = db.Column(db.Float)
    start_cycles   = db.Column(db.Integer)
    motor_running  = db.Column(db.Boolean, default=True)

    # Fault flags
    overload       = db.Column(db.Boolean, default=False)
    overheat       = db.Column(db.Boolean, default=False)
    high_vibration = db.Column(db.Boolean, default=False)
    low_rpm        = db.Column(db.Boolean, default=False)

    # Computed by backend
    health_score   = db.Column(db.Float)   # 0–100%
    efficiency     = db.Column(db.Float)   # 0–100%

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "timestamp": self.timestamp.isoformat(),
            "voltage": self.voltage,
            "current": self.current,
            "power_kw": self.power_kw,
            "energy_kwh": self.energy_kwh,
            "motor_temp": self.motor_temp,
            "bearing_temp": self.bearing_temp,
            "ambient_temp": self.ambient_temp,
            "humidity": self.humidity,
            "vibration_rms": self.vibration_rms,
            "rpm": self.rpm,
            "pressure": self.pressure,
            "run_hours": self.run_hours,
            "start_cycles": self.start_cycles,
            "motor_running": self.motor_running,
            "overload": self.overload,
            "overheat": self.overheat,
            "high_vibration": self.high_vibration,
            "low_rpm": self.low_rpm,
            "health_score": self.health_score,
            "efficiency": self.efficiency,
        }


# ─── Fault Events ─────────────────────────────────────────────────────────────

class FaultEvent(db.Model):
    __tablename__ = "fault_events"

    id               = db.Column(db.Integer, primary_key=True)
    device_id        = db.Column(db.String(50), db.ForeignKey("machines.device_id"), nullable=False)
    fault_type       = db.Column(db.String(100))    # Overload, Overheat, Vibration, etc.
    fault_code       = db.Column(db.Integer)
    severity         = db.Column(db.String(20))     # LOW | MEDIUM | HIGH | CRITICAL
    severity_score   = db.Column(db.Float)          # 0–100
    root_cause       = db.Column(db.Text)
    recommendation   = db.Column(db.Text)
    predicted_by_ml  = db.Column(db.Boolean, default=False)
    ml_confidence    = db.Column(db.Float)
    failure_prob     = db.Column(db.Float)          # 0.0–1.0
    rul_days         = db.Column(db.Float)          # Remaining Useful Life
    occurred_at      = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    resolved_at      = db.Column(db.DateTime, nullable=True)
    is_active        = db.Column(db.Boolean, default=True)
    acknowledged_by  = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "fault_type": self.fault_type,
            "fault_code": self.fault_code,
            "severity": self.severity,
            "severity_score": self.severity_score,
            "root_cause": self.root_cause,
            "recommendation": self.recommendation,
            "predicted_by_ml": self.predicted_by_ml,
            "ml_confidence": self.ml_confidence,
            "failure_prob": self.failure_prob,
            "rul_days": self.rul_days,
            "occurred_at": self.occurred_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "is_active": self.is_active,
        }


# ─── Maintenance Logs ─────────────────────────────────────────────────────────

class MaintenanceLog(db.Model):
    __tablename__ = "maintenance_logs"

    id              = db.Column(db.Integer, primary_key=True)
    device_id       = db.Column(db.String(50), db.ForeignKey("machines.device_id"), nullable=False)
    maintenance_type= db.Column(db.String(50))   # Preventive | Corrective | Predictive
    description     = db.Column(db.Text)
    performed_by    = db.Column(db.String(100))
    scheduled_date  = db.Column(db.Date)
    completed_date  = db.Column(db.Date, nullable=True)
    status          = db.Column(db.String(20), default="SCHEDULED")  # SCHEDULED|DONE|OVERDUE
    cost_inr        = db.Column(db.Float, nullable=True)
    downtime_hours  = db.Column(db.Float, default=0.0)
    parts_replaced  = db.Column(db.Text, nullable=True)
    notes           = db.Column(db.Text, nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "maintenance_type": self.maintenance_type,
            "description": self.description,
            "performed_by": self.performed_by,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "completed_date": self.completed_date.isoformat() if self.completed_date else None,
            "status": self.status,
            "cost_inr": self.cost_inr,
            "downtime_hours": self.downtime_hours,
            "parts_replaced": self.parts_replaced,
        }


# ─── Alert History ────────────────────────────────────────────────────────────

class AlertHistory(db.Model):
    __tablename__ = "alert_history"

    id           = db.Column(db.Integer, primary_key=True)
    device_id    = db.Column(db.String(50), nullable=False)
    alert_type   = db.Column(db.String(50))    # EMAIL | TELEGRAM | SMS | DASHBOARD
    message      = db.Column(db.Text)
    severity     = db.Column(db.String(20))
    sent_at      = db.Column(db.DateTime, default=datetime.utcnow)
    delivered    = db.Column(db.Boolean, default=False)
    recipient    = db.Column(db.String(200))

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "alert_type": self.alert_type,
            "message": self.message,
            "severity": self.severity,
            "sent_at": self.sent_at.isoformat(),
            "delivered": self.delivered,
        }


# ─── Energy Daily Summary ─────────────────────────────────────────────────────

class EnergyDaily(db.Model):
    __tablename__ = "energy_daily"

    id           = db.Column(db.Integer, primary_key=True)
    device_id    = db.Column(db.String(50), nullable=False)
    date         = db.Column(db.Date, nullable=False, index=True)
    total_kwh    = db.Column(db.Float, default=0.0)
    peak_kw      = db.Column(db.Float, default=0.0)
    avg_kw       = db.Column(db.Float, default=0.0)
    run_hours    = db.Column(db.Float, default=0.0)
    fault_count  = db.Column(db.Integer, default=0)
    avg_health   = db.Column(db.Float, default=100.0)

    __table_args__ = (db.UniqueConstraint("device_id", "date"),)

    def to_dict(self):
        return {
            "device_id": self.device_id,
            "date": self.date.isoformat(),
            "total_kwh": self.total_kwh,
            "peak_kw": self.peak_kw,
            "avg_kw": self.avg_kw,
            "run_hours": self.run_hours,
            "fault_count": self.fault_count,
            "avg_health": self.avg_health,
        }


# ─── Device Thresholds (per-machine configurable) ─────────────────────────────

class DeviceThreshold(db.Model):
    __tablename__ = "device_thresholds"

    id               = db.Column(db.Integer, primary_key=True)
    device_id        = db.Column(db.String(50), unique=True, nullable=False)
    voltage_min      = db.Column(db.Float, default=380.0)
    voltage_max      = db.Column(db.Float, default=440.0)
    current_flc      = db.Column(db.Float, default=3.5)
    current_overload = db.Column(db.Float, default=4.5)
    temp_warning     = db.Column(db.Float, default=75.0)
    temp_critical    = db.Column(db.Float, default=85.0)
    vibration_warn   = db.Column(db.Float, default=0.5)
    vibration_crit   = db.Column(db.Float, default=1.0)
    rpm_min          = db.Column(db.Integer, default=1200)
    rpm_max          = db.Column(db.Integer, default=1600)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "device_id": self.device_id,
            "voltage_min": self.voltage_min,
            "voltage_max": self.voltage_max,
            "current_flc": self.current_flc,
            "current_overload": self.current_overload,
            "temp_warning": self.temp_warning,
            "temp_critical": self.temp_critical,
            "vibration_warn": self.vibration_warn,
            "vibration_crit": self.vibration_crit,
            "rpm_min": self.rpm_min,
            "rpm_max": self.rpm_max,
        }
