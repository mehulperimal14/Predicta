"""
PREDICTA – Machine Health Score & Feature Engineering
Computes health score, efficiency, and ML features from raw sensor readings.
"""

import numpy as np
from datetime import datetime, timedelta
from config import Config


THRESHOLDS = Config.THRESHOLDS


def compute_health_score(reading: dict) -> float:
    """
    Compute machine health score (0–100%) from sensor reading.
    Weighted deduction model — each parameter contributes to health deduction.
    """
    score = 100.0
    deductions = []

    v   = reading.get("voltage", 415)
    i   = reading.get("current", 3.5)
    mt  = reading.get("motor_temp", 40)
    bt  = reading.get("bearing_temp", 40)
    vib = reading.get("vibration_rms", 0.1)
    rpm = reading.get("rpm", 1440)

    # ─── Voltage Deduction (weight: 15 points)
    if v < THRESHOLDS["voltage_min"] or v > THRESHOLDS["voltage_max"]:
        deviation = abs(v - 415) / 415 * 100
        deductions.append(min(15, deviation * 0.5))

    # ─── Current Deduction (weight: 20 points)
    flc = THRESHOLDS["current_flc"]
    if i > flc:
        overload_pct = (i - flc) / flc * 100
        deductions.append(min(20, overload_pct * 0.4))

    # ─── Temperature Deduction (weight: 25 points)
    tw = THRESHOLDS["temp_warning"]
    tc = THRESHOLDS["temp_critical"]
    if mt > tc:
        deductions.append(25)
    elif mt > tw:
        deductions.append(10 + (mt - tw) / (tc - tw) * 15)
    elif mt > 60:
        deductions.append((mt - 60) / (tw - 60) * 10)

    # ─── Bearing Temperature Deduction (weight: 15 points)
    btw = THRESHOLDS["bearing_temp_warn"]
    if bt > btw + 10:
        deductions.append(15)
    elif bt > btw:
        deductions.append((bt - btw) / 10 * 15)

    # ─── Vibration Deduction (weight: 25 points)
    vw = THRESHOLDS["vibration_warn"]
    vc = THRESHOLDS["vibration_crit"]
    if vib > vc:
        deductions.append(25)
    elif vib > vw:
        deductions.append(10 + (vib - vw) / (vc - vw) * 15)

    # ─── RPM Deduction (weight: 10 points)
    rmin = THRESHOLDS["rpm_min"]
    rmax = THRESHOLDS["rpm_max"]
    if rpm > 0 and (rpm < rmin or rpm > rmax):
        deviation = min(abs(rpm - 1440) / 1440 * 100, 10)
        deductions.append(deviation)

    total_deduction = sum(deductions)
    score = max(0.0, min(100.0, score - total_deduction))
    return round(score, 1)


def compute_efficiency(reading: dict, rated_power_kw: float = 1.5) -> float:
    """
    Estimate motor efficiency: actual useful power / consumed power.
    Uses motor characteristic curves for induction motors.
    """
    v   = reading.get("voltage", 415)
    i   = reading.get("current", 3.5)
    pf  = reading.get("power_factor", 0.85)
    rpm = reading.get("rpm", 1440)

    consumed_kw = (v * i * pf * 1.732) / 1000  # 3-phase
    if consumed_kw <= 0:
        return 0.0

    # Load factor estimation
    load_factor = min(1.0, consumed_kw / rated_power_kw)

    # Efficiency curve for induction motor (typical values)
    # At 100% load: ~87%, At 75% load: ~88%, At 50% load: ~84%
    if load_factor >= 0.90:
        base_eff = 0.87
    elif load_factor >= 0.70:
        base_eff = 0.88
    elif load_factor >= 0.50:
        base_eff = 0.84
    elif load_factor >= 0.25:
        base_eff = 0.75
    else:
        base_eff = 0.60

    # Degrade efficiency based on temperature rise
    motor_temp = reading.get("motor_temp", 40)
    temp_derate = max(0, (motor_temp - 40) * 0.001)

    # Degrade efficiency based on vibration
    vib = reading.get("vibration_rms", 0.0)
    vib_derate = min(0.05, vib * 0.05)

    efficiency = (base_eff - temp_derate - vib_derate) * 100
    return round(max(0, min(100, efficiency)), 1)


def build_ml_features(reading: dict) -> list:
    """
    Build feature vector for ML model prediction.
    Feature order must match training data exactly.
    Features: [voltage, current, motor_temp, bearing_temp, vibration_rms,
               rpm, pressure, power_factor, humidity, ambient_temp,
               current_to_flc_ratio, temp_rise, vibration_category, rpm_slip]
    """
    flc = THRESHOLDS["current_flc"]
    rated_rpm = 1440

    voltage      = reading.get("voltage", 415)
    current      = reading.get("current", 3.5)
    motor_temp   = reading.get("motor_temp", 40)
    bearing_temp = reading.get("bearing_temp", 40)
    vibration    = reading.get("vibration_rms", 0.1)
    rpm          = reading.get("rpm", 1440) or rated_rpm
    pressure     = reading.get("pressure", 200)
    power_factor = reading.get("power_factor", 0.85)
    humidity     = reading.get("humidity", 50)
    ambient_temp = reading.get("ambient_temp", 30)

    # Derived features
    current_ratio   = current / flc if flc > 0 else 1.0
    temp_rise       = motor_temp - ambient_temp
    bearing_rise    = bearing_temp - ambient_temp
    rpm_slip        = abs(1500 - rpm) / 1500 * 100  # Slip %
    power_kw        = (voltage * current * power_factor * 1.732) / 1000

    # Vibration category: 0=normal, 1=warning, 2=critical
    if vibration < 0.3:
        vib_cat = 0
    elif vibration < 0.7:
        vib_cat = 1
    else:
        vib_cat = 2

    features = [
        voltage, current, motor_temp, bearing_temp,
        vibration, rpm, pressure, power_factor,
        humidity, ambient_temp,
        current_ratio, temp_rise, bearing_rise,
        rpm_slip, power_kw, vib_cat
    ]
    return features


def detect_anomalies(reading: dict) -> list:
    """
    Rule-based anomaly detection — runs alongside ML predictions.
    Returns list of detected anomaly dicts.
    """
    anomalies = []
    t = THRESHOLDS

    v   = reading.get("voltage", 415)
    i   = reading.get("current", 3.5)
    mt  = reading.get("motor_temp", 40)
    bt  = reading.get("bearing_temp", 40)
    vib = reading.get("vibration_rms", 0.1)
    rpm = reading.get("rpm", 1440) or 1440

    if i > t["current_overload"]:
        anomalies.append({
            "type": "OVERCURRENT",
            "severity": "HIGH" if i > t["current_flc"] * 1.5 else "MEDIUM",
            "value": i,
            "threshold": t["current_overload"],
            "message": f"Current {i:.2f}A exceeds overload threshold {t['current_overload']}A"
        })

    if mt > t["temp_critical"]:
        anomalies.append({
            "type": "OVERTEMPERATURE",
            "severity": "CRITICAL",
            "value": mt,
            "threshold": t["temp_critical"],
            "message": f"Motor temperature {mt:.1f}°C is CRITICAL (>{t['temp_critical']}°C)"
        })
    elif mt > t["temp_warning"]:
        anomalies.append({
            "type": "HIGH_TEMPERATURE",
            "severity": "MEDIUM",
            "value": mt,
            "threshold": t["temp_warning"],
            "message": f"Motor temperature {mt:.1f}°C above warning threshold {t['temp_warning']}°C"
        })

    if vib > t["vibration_crit"]:
        anomalies.append({
            "type": "EXCESSIVE_VIBRATION",
            "severity": "CRITICAL",
            "value": vib,
            "threshold": t["vibration_crit"],
            "message": f"Vibration {vib:.3f}g exceeds critical limit {t['vibration_crit']}g"
        })
    elif vib > t["vibration_warn"]:
        anomalies.append({
            "type": "HIGH_VIBRATION",
            "severity": "MEDIUM",
            "value": vib,
            "threshold": t["vibration_warn"],
            "message": f"Vibration {vib:.3f}g above warning threshold {t['vibration_warn']}g"
        })

    if v < t["voltage_min"]:
        anomalies.append({
            "type": "UNDERVOLTAGE",
            "severity": "MEDIUM",
            "value": v,
            "threshold": t["voltage_min"],
            "message": f"Voltage {v:.1f}V below minimum {t['voltage_min']}V"
        })
    elif v > t["voltage_max"]:
        anomalies.append({
            "type": "OVERVOLTAGE",
            "severity": "MEDIUM",
            "value": v,
            "threshold": t["voltage_max"],
            "message": f"Voltage {v:.1f}V above maximum {t['voltage_max']}V"
        })

    if bt > t["bearing_temp_warn"]:
        anomalies.append({
            "type": "BEARING_OVERHEAT",
            "severity": "HIGH",
            "value": bt,
            "threshold": t["bearing_temp_warn"],
            "message": f"Bearing temperature {bt:.1f}°C indicates possible bearing failure"
        })

    if rpm < t["rpm_min"] and rpm > 100:
        anomalies.append({
            "type": "LOW_RPM",
            "severity": "MEDIUM",
            "value": rpm,
            "threshold": t["rpm_min"],
            "message": f"Motor RPM {rpm} below normal operating range — possible overload or stall"
        })

    return anomalies


def compute_severity_score(anomalies: list) -> tuple:
    """
    Compute overall severity score (0–100) and label from anomalies.
    Returns: (score, label)
    """
    if not anomalies:
        return 0, "NORMAL"

    severity_weights = {"CRITICAL": 100, "HIGH": 70, "MEDIUM": 40, "LOW": 15}
    max_score = max(severity_weights.get(a["severity"], 0) for a in anomalies)

    if max_score >= 100:
        return max_score, "CRITICAL"
    elif max_score >= 70:
        return max_score, "HIGH"
    elif max_score >= 40:
        return max_score, "MEDIUM"
    else:
        return max_score, "LOW"
