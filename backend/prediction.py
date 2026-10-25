"""
PREDICTA – ML Prediction Engine
Loads trained Random Forest model and runs inference on sensor data.
"""

import os
import joblib
import numpy as np
from datetime import datetime
from typing import Optional

from preprocess import build_ml_features, detect_anomalies, compute_severity_score

# Fault type mapping (matches training labels)
FAULT_LABELS = {
    0: "Normal Operation",
    1: "Bearing Failure",
    2: "Motor Overheating",
    3: "Overcurrent / Overload",
    4: "Rotor Imbalance / Vibration",
    5: "Cooling System Failure",
    6: "Power Supply Anomaly",
    7: "Winding Fault",
}

ROOT_CAUSES = {
    "Normal Operation":             "All parameters within normal operating range.",
    "Bearing Failure":              "Abnormal vibration pattern combined with rising bearing temperature indicates progressive bearing wear or lubrication failure.",
    "Motor Overheating":            "Motor core temperature significantly above ambient — caused by overloading, blocked ventilation, or cooling fan failure.",
    "Overcurrent / Overload":       "Current exceeds Full Load Current by more than 30% — caused by mechanical jam, pump blockage, or worn impeller.",
    "Rotor Imbalance / Vibration":  "High vibration RMS with normal temperature suggests rotor imbalance, shaft misalignment, or loose foundation bolts.",
    "Cooling System Failure":       "Temperature rising progressively while load remains constant — cooling fan may have failed or air filter blocked.",
    "Power Supply Anomaly":         "Voltage fluctuations outside ±5% nominal — caused by supply grid instability or loose power connections.",
    "Winding Fault":                "Disproportionate current draw with low RPM suggests stator winding insulation degradation or turn-to-turn fault.",
}

RECOMMENDATIONS = {
    "Normal Operation":             "Continue monitoring. Schedule preventive maintenance as per schedule.",
    "Bearing Failure":              "Inspect and replace bearings within 5 working days. Check lubrication intervals. Measure bearing clearance.",
    "Motor Overheating":            "Check cooling fan operation immediately. Clean air filter. Verify ambient temperature. Reduce load if above 100% FLA.",
    "Overcurrent / Overload":       "Check pump for blockage or cavitation. Verify overload relay setting. Inspect impeller for wear.",
    "Rotor Imbalance / Vibration":  "Check shaft alignment with dial indicator. Inspect foundation bolts. Balance rotor if vibration persists.",
    "Cooling System Failure":       "Inspect cooling fan blades and motor for debris. Check thermistor. Consider forced cooling.",
    "Power Supply Anomaly":         "Measure supply voltage at MCC. Check terminal connections. Install voltage stabilizer if grid fluctuations persist.",
    "Winding Fault":                "Perform insulation resistance test (Megger). Measure winding resistance. Send motor for rewind if IR < 1 MΩ.",
}

_model = None
_scaler = None
_model_loaded = False


def _load_model():
    """Lazy-load model from disk (thread-safe)."""
    global _model, _scaler, _model_loaded
    if _model_loaded:
        return

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    model_path  = os.path.join(base_dir, "ml_model", "saved_models", "random_forest_model.pkl")
    scaler_path = os.path.join(base_dir, "ml_model", "saved_models", "scaler.pkl")

    if os.path.exists(model_path) and os.path.exists(scaler_path):
        _model  = joblib.load(model_path)
        _scaler = joblib.load(scaler_path)
        _model_loaded = True
        print(f"[ML] Model loaded from {model_path}")
    else:
        print(f"[ML] WARNING: Model not found at {model_path}. Using rule-based prediction only.")
        _model_loaded = True  # Mark as attempted


def predict_fault(reading: dict) -> dict:
    """
    Run ML fault prediction on a sensor reading.
    Falls back to rule-based detection if model is unavailable.

    Args:
        reading: dict of sensor values

    Returns:
        dict with prediction results
    """
    _load_model()

    # Rule-based detection (always runs)
    anomalies = detect_anomalies(reading)
    severity_score, severity_label = compute_severity_score(anomalies)

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "device_id": reading.get("device_id", "UNKNOWN"),
        "anomalies": anomalies,
        "severity_score": severity_score,
        "severity": severity_label,
        "ml_available": _model is not None,
    }

    # ML-based prediction
    if _model is not None and _scaler is not None:
        try:
            features = build_ml_features(reading)
            features_arr = np.array(features).reshape(1, -1)
            features_scaled = _scaler.transform(features_arr)

            fault_class = int(_model.predict(features_scaled)[0])
            probabilities = _model.predict_proba(features_scaled)[0]
            confidence = float(probabilities[fault_class])
            failure_prob = 1.0 - float(probabilities[0])  # Prob of any fault

            fault_type = FAULT_LABELS.get(fault_class, "Unknown Fault")
            root_cause = ROOT_CAUSES.get(fault_type, "Investigate sensor readings.")
            recommendation = RECOMMENDATIONS.get(fault_type, "Consult maintenance engineer.")

            # Estimate Remaining Useful Life (simple model)
            rul_days = _estimate_rul(reading, failure_prob)

            result.update({
                "fault_class":   fault_class,
                "fault_type":    fault_type,
                "confidence":    round(confidence * 100, 1),
                "failure_prob":  round(failure_prob * 100, 1),
                "root_cause":    root_cause,
                "recommendation":recommendation,
                "rul_days":      rul_days,
                "all_probabilities": {
                    FAULT_LABELS[i]: round(float(p) * 100, 1)
                    for i, p in enumerate(probabilities)
                    if i in FAULT_LABELS
                },
                "ml_predicted":  True,
            })

            # Determine urgency
            if failure_prob > 0.8:
                result["maintenance_urgency"] = "IMMEDIATE"
            elif failure_prob > 0.5:
                result["maintenance_urgency"] = "WITHIN_48H"
            elif failure_prob > 0.3:
                result["maintenance_urgency"] = "THIS_WEEK"
            else:
                result["maintenance_urgency"] = "SCHEDULED"

        except Exception as e:
            print(f"[ML] Prediction error: {e}")
            result["ml_error"] = str(e)
            result["ml_predicted"] = False
            _rule_based_fallback(result, reading, anomalies)
    else:
        _rule_based_fallback(result, reading, anomalies)

    return result


def _rule_based_fallback(result: dict, reading: dict, anomalies: list):
    """Populate prediction result using rule-based logic when ML unavailable."""
    if not anomalies:
        result.update({
            "fault_type":    "Normal Operation",
            "confidence":    99.0,
            "failure_prob":  0.0,
            "root_cause":    ROOT_CAUSES["Normal Operation"],
            "recommendation":RECOMMENDATIONS["Normal Operation"],
            "rul_days":      365,
            "ml_predicted":  False,
            "maintenance_urgency": "SCHEDULED",
        })
        return

    # Use highest severity anomaly
    sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    top = sorted(anomalies, key=lambda a: sev_order.get(a["severity"], 0), reverse=True)[0]

    type_map = {
        "OVERCURRENT":        "Overcurrent / Overload",
        "OVERTEMPERATURE":    "Motor Overheating",
        "HIGH_TEMPERATURE":   "Motor Overheating",
        "EXCESSIVE_VIBRATION":"Rotor Imbalance / Vibration",
        "HIGH_VIBRATION":     "Rotor Imbalance / Vibration",
        "BEARING_OVERHEAT":   "Bearing Failure",
        "UNDERVOLTAGE":       "Power Supply Anomaly",
        "OVERVOLTAGE":        "Power Supply Anomaly",
        "LOW_RPM":            "Overcurrent / Overload",
    }
    fault_type = type_map.get(top["type"], "Normal Operation")
    failure_prob = min(95, result["severity_score"])

    result.update({
        "fault_type":    fault_type,
        "confidence":    85.0,
        "failure_prob":  failure_prob,
        "root_cause":    ROOT_CAUSES.get(fault_type, ""),
        "recommendation":RECOMMENDATIONS.get(fault_type, ""),
        "rul_days":      _estimate_rul(reading, failure_prob / 100),
        "ml_predicted":  False,
        "maintenance_urgency": "WITHIN_48H" if failure_prob > 60 else "THIS_WEEK",
    })


def _estimate_rul(reading: dict, failure_prob: float) -> Optional[float]:
    """
    RUL estimation is optional and strictly guarded:
    Returns None when validated degradation trajectory or run-to-failure cycles are not provided.
    """
    # If run_hours and validated degradation rate exist in reading:
    if reading.get("has_validated_degradation") and reading.get("degradation_rate_per_hour"):
        # Extrapolate linear / exponential bounds
        remaining = (1.0 - failure_prob) / max(0.0001, reading["degradation_rate_per_hour"])
        return round(remaining / 24.0, 1)
    # Default honest industrial standard: RUL is unavailable without historical run-to-failure profiles
    return None

