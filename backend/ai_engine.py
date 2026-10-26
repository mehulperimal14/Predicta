"""
PREDICTA 2.0 – Layered AI & Predictive Maintenance Engine
Implements:
- Layer 1: Engineering Rules & Statistical Thresholds
- Layer 2: Unsupervised Anomaly Detection (Isolation Forest)
- Layer 3: Supervised Failure Prediction (Time-based validation, leak-free)
- Layer 4: Honest Remaining Useful Life (RUL) Estimator
- Layer 5: Combined Machine-Health Risk Engine
"""

import os
import math
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    precision_score, recall_score, f1_score, roc_auc_score, average_precision_score, confusion_matrix
)

from analytics_engine import running_rows, TREND_VARIABLES

DEFAULT_ENGINEERING_LIMITS = {
    "motor_temp": {"warn": 75.0, "crit": 85.0, "unit": "°C"},
    "bearing_temp": {"warn": 70.0, "crit": 80.0, "unit": "°C"},
    "discharge_temp": {"warn": 95.0, "crit": 105.0, "unit": "°C"},
    "current": {"warn": 4.2, "crit": 5.0, "unit": "A"},
    "voltage": {"min_crit": 360.0, "min_warn": 380.0, "max_warn": 440.0, "max_crit": 460.0, "unit": "V"},
    "vibration_rms": {"warn": 0.45, "crit": 0.90, "unit": "g"},
    "pressure": {"min_warn": 80.0, "max_warn": 550.0, "unit": "kPa"},
    "rpm": {"min_warn": 1250, "max_warn": 1580, "unit": "RPM"}
}

DEFAULT_CONTAMINATION = 0.03

# Mapped columns that must never be model inputs: identifiers, the run flag, monotonic
# counters, the timestamp (which leaks "late in the file = failure"), and the label itself.
NON_FEATURE_COLUMNS = {
    "_std_timestamp", "_std_asset_id", "_std_motor_running", "_std_run_hours",
    "_std_fault_code", "_std_failure_label",
}


def merged_limits(custom_limits: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    return {**DEFAULT_ENGINEERING_LIMITS, **(custom_limits or {})}


# ─── Layer 1: Engineering Rules & Statistical Limits ──────────────────────────

def evaluate_layer1_rules(
    df: pd.DataFrame,
    custom_limits: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluates engineering limit violations (upper and lower bands) on running rows only,
    so planned stops do not trigger low-RPM / low-pressure alarms. Robust Z-score
    deviations from the baseline are reported as context (not scored).
    """
    limits = merged_limits(custom_limits)
    violations = []

    evaluated = running_rows(df)
    total_samples = len(evaluated)
    if total_samples == 0:
        return {"violations": [], "critical_violations": 0, "warning_violations": 0,
                "layer1_score": 0.0, "statistical_deviations": [], "samples_evaluated": 0}

    def _violation(var, level, mask, series, threshold_text, unit):
        count = int(mask.sum())
        if count == 0:
            return None
        return {
            "variable": var,
            "level": level,
            "threshold": threshold_text,
            "unit": unit,
            "max_observed": round(float(series.max()), 2),
            "min_observed": round(float(series.min()), 2),
            "violation_count": count,
            "percentage": round(count / total_samples * 100, 1),
            "rule": f"{var} outside {threshold_text} {unit}".strip()
        }

    for var, cfg in limits.items():
        std_col = f"_std_{var}"
        if std_col not in evaluated.columns:
            continue

        series = pd.to_numeric(evaluated[std_col], errors="coerce").dropna()
        if len(series) == 0:
            continue

        unit = cfg.get("unit", "")
        upper_crit = cfg.get("crit", cfg.get("max_crit"))
        lower_crit = cfg.get("min_crit")
        upper_warn = cfg.get("warn", cfg.get("max_warn"))
        lower_warn = cfg.get("min_warn")

        crit_mask = pd.Series(False, index=series.index)
        if upper_crit is not None:
            crit_mask |= series > upper_crit
        if lower_crit is not None:
            crit_mask |= series < lower_crit

        warn_mask = pd.Series(False, index=series.index)
        if upper_warn is not None:
            warn_mask |= series > upper_warn
        if lower_warn is not None:
            warn_mask |= series < lower_warn
        warn_mask &= ~crit_mask

        crit_text = " / ".join(t for t in [
            f"< {lower_crit}" if lower_crit is not None else "",
            f"> {upper_crit}" if upper_crit is not None else ""] if t)
        warn_text = " / ".join(t for t in [
            f"< {lower_warn}" if lower_warn is not None else "",
            f"> {upper_warn}" if upper_warn is not None else ""] if t)

        for level, mask, text in [("CRITICAL", crit_mask, crit_text), ("WARNING", warn_mask, warn_text)]:
            if text:
                v = _violation(var, level, mask, series, text, unit)
                if v:
                    v["rule"] = f"{var} {text} {unit}".strip()
                    violations.append(v)

    # Statistical context: sustained robust Z-score deviation from the baseline period
    statistical_deviations = []
    for var in TREND_VARIABLES:
        z_col = f"{var}_robust_zscore"
        if z_col not in evaluated.columns:
            continue
        z = pd.to_numeric(evaluated[z_col], errors="coerce").dropna()
        if len(z) == 0:
            continue
        beyond = float((z.abs() > 4.0).mean() * 100)
        if beyond >= 5.0:
            statistical_deviations.append({
                "variable": var,
                "pct_samples_beyond_4_sigma": round(beyond, 1),
                "max_abs_robust_z": round(float(z.abs().max()), 1),
            })

    # Layer 1 Penalty calculation
    crit_count = sum(v["violation_count"] for v in violations if v["level"] == "CRITICAL")
    warn_count = sum(v["violation_count"] for v in violations if v["level"] == "WARNING")

    crit_score = min(100.0, (crit_count / max(1, total_samples)) * 300.0)
    warn_score = min(50.0, (warn_count / max(1, total_samples)) * 100.0)
    period_severity = min(100.0, crit_score + warn_score)

    # Current state: the same formula on the most recent 10% of running samples, so a
    # record that ends in a fault is not diluted by hours of healthy history.
    recent = evaluated.tail(max(10, int(total_samples * 0.10)))
    recent_crit = recent_warn = 0
    for var, cfg in limits.items():
        std_col = f"_std_{var}"
        if std_col not in recent.columns:
            continue
        s = pd.to_numeric(recent[std_col], errors="coerce")
        crit = pd.Series(False, index=s.index)
        warn = pd.Series(False, index=s.index)
        if cfg.get("crit", cfg.get("max_crit")) is not None:
            crit |= s > cfg.get("crit", cfg.get("max_crit"))
        if cfg.get("min_crit") is not None:
            crit |= s < cfg["min_crit"]
        if cfg.get("warn", cfg.get("max_warn")) is not None:
            warn |= s > cfg.get("warn", cfg.get("max_warn"))
        if cfg.get("min_warn") is not None:
            warn |= s < cfg["min_warn"]
        recent_crit += int(crit.sum())
        recent_warn += int((warn & ~crit).sum())
    recent_severity = min(100.0, min(100.0, recent_crit / len(recent) * 300.0)
                          + min(50.0, recent_warn / len(recent) * 100.0))
    layer1_severity = max(period_severity, recent_severity)

    return {
        "violations": violations,
        "critical_violations": len([v for v in violations if v["level"] == "CRITICAL"]),
        "warning_violations": len([v for v in violations if v["level"] == "WARNING"]),
        "layer1_score": round(layer1_severity, 1),
        "period_score": round(period_severity, 1),
        "current_state_score": round(recent_severity, 1),
        "samples_evaluated": int(total_samples),
        "statistical_deviations": statistical_deviations,
    }


# ─── Layer 2: Unsupervised Anomaly Detection (Isolation Forest) ───────────────

def run_layer2_unsupervised_detection(
    df: pd.DataFrame,
    contamination: float = DEFAULT_CONTAMINATION
) -> Dict[str, Any]:
    """
    Fits Isolation Forest on engineered features of running rows to detect structural
    anomalies (stops are excluded so they are not flagged as anomalies).
    Works without failure labels. anomaly_indices are labels of the input DataFrame.
    """
    df = running_rows(df)
    # Select numeric feature columns (rolling means, std, z-scores); the run flag is constant here
    feature_cols = [c for c in df.columns if (
        c.startswith("_std_") or c.endswith("_roll_mean") or c.endswith("_roll_std") or c.endswith("_robust_zscore") or c.endswith("_slope") or c in ["temp_to_current_ratio", "pressure_to_flow_ratio"]
    ) and c not in NON_FEATURE_COLUMNS and pd.api.types.is_numeric_dtype(df[c])]


    if len(feature_cols) < 2 or len(df) < 15:
        return {
            "model": "IsolationForest",
            "status": "SKIPPED",
            "reason": "Insufficient features or sample size for unsupervised anomaly detection",
            "anomaly_count": 0,
            "anomaly_rate": 0.0,
            "layer2_score": 0.0,
            "anomaly_indices": []
        }
        
    X = df[feature_cols].fillna(df[feature_cols].median()).fillna(0.0)
    
    # Train Isolation Forest
    iso = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        random_state=42,
        n_jobs=-1
    )
    
    preds = iso.fit_predict(X)
    scores = iso.decision_function(X)
    
    # Convert scores: negative is anomalous. Map to 0-100 anomaly scale
    anomaly_indices = [int(label) if isinstance(label, (int, np.integer)) else str(label)
                       for label, p in zip(df.index, preds) if p == -1]
    anomaly_count = len(anomaly_indices)
    anomaly_rate = round(anomaly_count / len(df) * 100, 2)
    
    # Normalize decision scores: lower score means more anomalous
    normalized_scores = np.clip(1.0 - (scores - scores.min()) / max(1e-5, (scores.max() - scores.min())), 0.0, 1.0)
    mean_anomaly_severity = float(np.mean(normalized_scores[preds == -1])) * 100 if anomaly_count > 0 else 0.0
    
    layer2_score = min(100.0, anomaly_rate * 4.0 + mean_anomaly_severity * 0.4)
    
    return {
        "model": "IsolationForest",
        "status": "COMPLETED",
        "contamination": contamination,
        "samples_evaluated": int(len(df)),
        "features_used": feature_cols,
        "anomaly_count": anomaly_count,
        "anomaly_rate_pct": anomaly_rate,
        "layer2_score": round(layer2_score, 1),
        "anomaly_indices": anomaly_indices[:200],  # cap to top 200 indices for JSON payload
        "mean_anomaly_severity": round(mean_anomaly_severity, 1)
    }


# ─── Layer 3: Supervised Failure Prediction (When Labels Available) ───────────

def run_layer3_supervised_prediction(
    df: pd.DataFrame,
    label_col: Optional[str] = None
) -> Dict[str, Any]:
    """
    Trains a leak-free Random Forest or gradient-boosting model if ground-truth failure labels exist.
    Uses strict time-based validation (train on past, test on future).
    """
    # Check if target column exists
    target = None
    if label_col and label_col in df.columns:
        target = label_col
    elif "_std_failure_label" in df.columns:
        target = "_std_failure_label"
    elif "failure" in df.columns:
        target = "failure"
    elif "is_failure" in df.columns:
        target = "is_failure"

    if not target or df[target].isnull().all():
        return {
            "available": False,
            "reason": "Supervised failure prediction unavailable: dataset contains no validated failure labels. Operating in unsupervised anomaly detection & trend monitoring mode."
        }
        
    y = pd.to_numeric(df[target], errors="coerce").fillna(0).astype(int)
    unique_classes = np.unique(y)
    failure_instances = int((y == 1).sum())
    
    if len(unique_classes) < 2 or failure_instances < 5:
        return {
            "available": False,
            "failure_instances": failure_instances,
            "reason": f"Supervised failure prediction cannot be trained reliably: insufficient failure events ({failure_instances} observed). Minimum 5 confirmed failure instances required."
        }
        
    # Select feature columns (exclude target)
    feature_cols = [c for c in df.columns if (
        c.startswith("_std_") or c.endswith("_roll_mean") or c.endswith("_roll_std") or c.endswith("_robust_zscore")
    ) and c != target and c not in NON_FEATURE_COLUMNS and pd.api.types.is_numeric_dtype(df[c])]

    
    X = df[feature_cols].fillna(df[feature_cols].median()).fillna(0.0)
    
    # Strict temporal train-test split (75% train, 25% test) to prevent future data leakage
    split_idx = int(len(X) * 0.75)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    if len(np.unique(y_train)) < 2:
        return {
            "available": False,
            "reason": "Training partition does not contain positive failure instances. Time-based split cannot train classifier."
        }
        
    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, class_weight="balanced")
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1] if len(model.classes_) > 1 else np.zeros(len(X_test))
    
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    cm = confusion_matrix(y_test, y_pred, labels=[0, 1]).tolist()

    # Ranking metrics need both classes in the (future) test partition
    if len(np.unique(y_test)) > 1:
        pr_auc = round(float(average_precision_score(y_test, y_proba)), 3)
        roc_auc = round(float(roc_auc_score(y_test, y_proba)), 3)
        ranking_note = None
    else:
        pr_auc = roc_auc = None
        ranking_note = "PR-AUC / ROC-AUC undefined: test period contains only one class."
    
    # Feature importances
    importances = dict(zip(feature_cols, [round(float(v), 4) for v in model.feature_importances_]))
    sorted_importances = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "available": True,
        "model": "RandomForest_TimeSplit",
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "test_failure_count": int(y_test.sum()),
        "metrics": {
            "precision": round(float(prec), 3),
            "recall": round(float(rec), 3),
            "f1_score": round(float(f1), 3),
            "pr_auc": pr_auc,
            "roc_auc": roc_auc,
            "ranking_metrics_note": ranking_note,
            "confusion_matrix": cm
        },
        "top_predictive_features": sorted_importances,
        "calibrated_failure_prob_latest": round(float(y_proba[-1]) * 100, 1) if len(y_proba) > 0 else 0.0
    }


# ─── Layer 4: Remaining Useful Life (RUL) ─────────────────────────────────────

def has_run_to_failure_history(df: pd.DataFrame, label_col: Optional[str] = None) -> bool:
    """True when the labels contain at least one healthy → failed transition."""
    for col in [label_col, "_std_failure_label", "failure", "is_failure"]:
        if col and col in df.columns:
            y = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int).to_numpy()
            return bool(len(y) > 1 and np.any((y[:-1] == 0) & (y[1:] == 1)))
    return False


def failure_levels_from_history(df: pd.DataFrame, label_col: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Learns, per variable, the level at which labelled failures began (median of the first
    failed samples), when it clearly differs from the healthy baseline. These observed
    failure levels replace vendor limits as the Layer 4 target.
    """
    col = next((c for c in [label_col, "_std_failure_label", "failure", "is_failure"] if c and c in df.columns), None)
    if not col:
        return {}
    y = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    healthy, failed = df[y == 0], df[y == 1]
    if len(failed) == 0 or len(healthy) < 10:
        return {}

    onset = failed.head(max(3, int(len(failed) * 0.05)))
    levels = {}
    for var in TREND_VARIABLES:
        std_col = f"_std_{var}"
        if std_col not in df.columns:
            continue
        base = pd.to_numeric(healthy[std_col], errors="coerce").dropna()
        at_failure = pd.to_numeric(onset[std_col], errors="coerce").dropna()
        if len(base) < 10 or len(at_failure) == 0:
            continue
        base_med, base_std = float(base.median()), float(base.std() or 0.0)
        level = float(at_failure.median())
        if abs(level - base_med) <= 3 * max(base_std, 1e-6):
            continue
        unit = DEFAULT_ENGINEERING_LIMITS.get(var, {}).get("unit", "")
        levels[var] = {"crit": level, "unit": unit} if level > base_med else {"min_crit": level, "unit": unit}
    return levels


def evaluate_layer4_rul(
    df: pd.DataFrame,
    has_run_to_failure: bool = False,
    trend_forecast: Optional[Dict[str, Any]] = None,
    failure_levels: Optional[Dict[str, Dict[str, Any]]] = None,
    timestamp_col: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Remaining useful life is ONLY reported when the data contains run-to-failure history:
    the current trend is then extrapolated to the levels at which past failures began.
    Without that history, the honest "unavailable" message is returned, together with the
    trend forecast to engineering limits (clearly labelled as not being a validated RUL).
    """
    base = {"trend_forecast": trend_forecast}

    if not has_run_to_failure:
        return {
            **base,
            "available": False,
            "message": "Remaining useful life unavailable: insufficient validated degradation or failure-history data.",
            "rul_hours": None,
            "confidence_interval": None
        }

    from trend_forecast import forecast_time_to_limits
    levels = failure_levels if failure_levels is not None else failure_levels_from_history(df)
    if not levels:
        return {
            **base,
            "available": False,
            "message": "Failure events are labelled, but no variable shows a clear shift at failure onset "
                       "to use as a degradation threshold.",
            "rul_hours": None,
            "confidence_interval": None
        }

    rul_forecast = forecast_time_to_limits(df, levels, timestamp_col=timestamp_col)
    earliest = rul_forecast.get("earliest_critical")
    if not earliest:
        return {
            **base,
            "available": False,
            "message": "No variable is currently trending toward the levels at which past failures began.",
            "failure_levels": levels,
            "rul_hours": None,
            "confidence_interval": None
        }

    return {
        **base,
        "available": True,
        "method": "Linear trend of recent running data extrapolated to the level observed at past failure onsets",
        "driving_variable": earliest["variable"],
        "rul_hours": earliest["hours"],
        "confidence_interval": earliest.get("ci_hours"),
        "failure_levels": levels,
        "assumptions": "Assumes the current load profile and degradation rate continue, and that future "
                       "failures begin at the same level as the labelled ones in this file.",
        "message": ("Machine has already reached the level at which previous failures began."
                    if earliest["hours"] == 0 else None),
    }


# ─── Layer 5: Combined Machine-Health Risk Engine ─────────────────────────────

INACTIVE_FAULT_CODES = {"", "0", "0.0", "nan", "none", "ok", "normal", "no fault", "-"}


def alarm_rate_pct(df: pd.DataFrame, fault_col: Optional[str] = None) -> Optional[float]:
    """
    Share of running samples with an active PLC / drive fault code. Uses the raw mapped
    column so text codes such as "F012" count (the _std_ copy is numeric-only).
    """
    col = fault_col if fault_col and fault_col in df.columns else None
    if col is None:
        return None
    running = running_rows(df)
    if len(running) == 0:
        return None
    codes = running[col].astype(str).str.strip().str.lower()
    active = running[col].notna() & ~codes.isin(INACTIVE_FAULT_CODES)
    return round(float(active.mean() * 100), 2)


def compute_layer5_risk_score(
    layer1_res: Dict[str, Any],
    layer2_res: Dict[str, Any],
    layer3_res: Dict[str, Any],
    data_quality_score: float = 100.0,
    trend_score: Optional[float] = None,
    alarm_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Combines rule violations, unsupervised anomaly scores, supervised failure estimates,
    trend deterioration, alarm frequency and data quality into a documented composite
    Machine Health Risk Score (0–100).

    Trend and alarm inputs are optional; they raise the score toward 100 in proportion
    to the remaining headroom (score += w * input * (1 - score/100)), so they can never
    dilute direct evidence from Layers 1–3.
    """
    l1_score = layer1_res.get("layer1_score", 0.0)
    l2_score = layer2_res.get("layer2_score", 0.0)

    # Supervised contribution (if available)
    if layer3_res.get("available") and "calibrated_failure_prob_latest" in layer3_res:
        l3_prob = layer3_res["calibrated_failure_prob_latest"]
        # Blend: L1 (35%), L2 (25%), L3 (30%), Data Quality discount (10%)
        composite = (l1_score * 0.35) + (l2_score * 0.25) + (l3_prob * 0.30)
    else:
        # Without supervised labels: L1 (55%), L2 (45%)
        composite = (l1_score * 0.55) + (l2_score * 0.45)

    # Trend deterioration (time-to-limit forecast): up to +30% of remaining headroom
    if trend_score is not None:
        composite += 0.30 * trend_score * (1.0 - composite / 100.0)

    # Alarm frequency: 20% of running samples in alarm counts as maximum; up to +15% of headroom
    alarm_score = min(100.0, alarm_rate * 5.0) if alarm_rate is not None else None
    if alarm_score is not None:
        composite += 0.15 * alarm_score * (1.0 - composite / 100.0)

    # Apply data quality penalty (if quality is very poor, inflate uncertainty / risk)
    if data_quality_score < 60.0:
        composite = min(100.0, composite + (60.0 - data_quality_score) * 0.2)
        
    final_score = round(max(0.0, min(100.0, composite)), 1)
    
    # Categorization
    if final_score >= 75.0:
        category = "CRITICAL"
        action = "Immediate inspection required. Machine is at severe risk of unplanned stoppage."
    elif final_score >= 50.0:
        category = "WARNING"
        action = "Abnormal degradation trend detected. Schedule physical maintenance inspection within 48 hours."
    elif final_score >= 25.0:
        category = "WATCH"
        action = "Minor deviations or anomalous patterns observed. Monitor operating trends during next shift."
    else:
        category = "NORMAL"
        action = "Machine operating within established engineering parameters and statistical baseline."

    return {
        "risk_score": final_score,
        "risk_category": category,
        "recommended_action": action,
        "contributing_weights": {
            "engineering_rule_severity": round(l1_score, 1),
            "unsupervised_anomaly_severity": round(l2_score, 1),
            "supervised_failure_probability": round(layer3_res.get("calibrated_failure_prob_latest", 0.0), 1) if layer3_res.get("available") else None,
            "trend_deterioration_score": trend_score,
            "alarm_frequency_pct": alarm_rate,
            "data_quality_confidence_factor": round(data_quality_score, 1)
        }
    }
