"""
Tests for PREDICTA 2.0 – Layered AI Engine & Explainable Fault Investigation
"""

import os
import pytest
import pandas as pd
import numpy as np

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from analytics_engine import compute_time_series_features, detect_cusum_changepoints
from ai_engine import (
    evaluate_layer1_rules, run_layer2_unsupervised_detection,
    run_layer3_supervised_prediction, evaluate_layer4_rul, compute_layer5_risk_score
)
from investigation import generate_fault_hypotheses


def test_time_series_features():
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=30, freq="1min"),
        "m_temp": [40.0 + i * 0.5 for i in range(30)],
        "amps": [3.2 + (0.5 if i > 20 else 0) for i in range(30)]
    })
    mapping = {"timestamp": "time", "motor_temp": "m_temp", "current": "amps"}
    feat = compute_time_series_features(df, mapping=mapping, rolling_window=5)
    
    assert "motor_temp_roll_mean" in feat.columns
    assert "motor_temp_ewma" in feat.columns
    assert "motor_temp_trend_slope" in feat.columns
    assert "temp_to_current_ratio" in feat.columns
    assert feat["motor_temp_trend_slope"].iloc[-1] > 0


def test_cusum_changepoints():
    # Constant baseline then jump
    series = pd.Series([10.0] * 20 + [50.0] * 20)
    changepoints = detect_cusum_changepoints(series, threshold=4.0)
    assert len(changepoints) > 0
    assert 19 <= changepoints[0] <= 22


def test_layer1_engineering_rules():
    df = pd.DataFrame({
        "_std_motor_temp": [60.0, 76.0, 88.0, 72.0],  # 88.0 exceeds 85.0 critical, 76.0 exceeds 75.0 warning
        "_std_current": [3.2, 3.4, 5.2, 3.3]           # 5.2 exceeds 5.0 critical
    })
    res = evaluate_layer1_rules(df)
    assert res["critical_violations"] >= 2
    assert res["layer1_score"] > 50.0


def test_layer2_isolation_forest():
    # 90 normal points and 10 extreme outliers
    normal_data = np.random.normal(50, 2, 90)
    outliers = np.array([120, 130, 140, 150, 160, 170, 180, 190, 200, 210])
    combined = np.concatenate([normal_data, outliers])
    
    df = pd.DataFrame({
        "_std_motor_temp": combined,
        "_std_current": combined * 0.08,
        "motor_temp_roll_mean": combined,
        "motor_temp_roll_std": [1.0] * 100
    })
    res = run_layer2_unsupervised_detection(df)
    assert res["status"] == "COMPLETED"
    assert res["anomaly_count"] > 0
    assert res["anomaly_rate_pct"] > 0.0


def test_layer3_supervised_graceful_fallback():
    # Dataset without labels
    df_unlabelled = pd.DataFrame({
        "_std_motor_temp": [50.0, 52.0, 51.0],
        "_std_current": [3.2, 3.3, 3.2]
    })
    res = run_layer3_supervised_prediction(df_unlabelled)
    assert res["available"] is False
    assert "unsupervised anomaly detection" in res["reason"]


def test_layer4_honest_rul_declaration():
    df = pd.DataFrame({"_std_current": [3.5, 3.6]})
    res = evaluate_layer4_rul(df, has_run_to_failure=False)
    assert res["available"] is False
    assert "Remaining useful life unavailable: insufficient validated degradation or failure-history data." in res["message"]


def test_layer5_risk_and_hypotheses():
    df = pd.DataFrame({
        "_std_motor_temp": [88.0, 89.0, 91.0],
        "_std_bearing_temp": [82.0, 84.0, 85.0],
        "_std_vibration_rms": [0.95, 1.10, 1.25],
        "_std_current": [5.1, 5.2, 5.4],
        "_std_voltage": [415.0, 414.0, 412.0]
    })
    l1 = evaluate_layer1_rules(df)
    l2 = {"layer2_score": 80.0, "anomaly_count": 3}
    l3 = {"available": False}
    
    risk = compute_layer5_risk_score(l1, l2, l3, data_quality_score=95.0)
    assert risk["risk_category"] in ["WARNING", "CRITICAL"]
    assert risk["risk_score"] >= 50.0

    mapping = {
        "motor_temp": "t_motor",
        "bearing_temp": "t_bearing",
        "vibration_rms": "vib_rms",
        "current": "amps",
        "voltage": "volts"
    }
    hypotheses = generate_fault_hypotheses(df, mapping, l1, l2, risk)
    assert len(hypotheses) > 0
    
    # Bearing hypothesis should show STRONG confidence
    bearing_hypo = [h for h in hypotheses if "Bearing" in h["hypothesis"]][0]
    assert bearing_hypo["confidence"] == "STRONG"
    assert len(bearing_hypo["supporting_evidence"]) > 0
    assert len(bearing_hypo["alternative_explanations"]) > 0
    assert len(bearing_hypo["recommended_actions"]) > 0
