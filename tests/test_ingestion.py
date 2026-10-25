"""
Tests for PREDICTA 2.0 – Ingestion, Data Quality Scoring, and Tag Mapping
"""

import os
import io
import pytest
import pandas as pd
import numpy as np

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from ingestion import (
    detect_csv_delimiter, detect_timestamp_column, suggest_tag_mappings,
    analyze_data_quality, generate_dataset_preview, STANDARD_VARIABLES
)


def test_detect_csv_delimiter():
    csv_comma = b"time,current,voltage\n2026-01-01 00:00:00,3.5,415\n"
    assert detect_csv_delimiter(csv_comma) == ","

    csv_semi = b"time;current;voltage\n2026-01-01 00:00:00;3.5;415\n"
    assert detect_csv_delimiter(csv_semi) == ";"

    csv_tab = b"time\tcurrent\tvoltage\n2026-01-01 00:00:00\t3.5\t415\n"
    assert detect_csv_delimiter(csv_tab) == "\t"


def test_detect_timestamp_column():
    df = pd.DataFrame({
        "log_time": ["2026-01-01 10:00:00", "2026-01-01 10:01:00", "2026-01-01 10:02:00"],
        "motor_amps": [3.2, 3.4, 3.3]
    })
    col, parsed, sr = detect_timestamp_column(df)
    assert col == "log_time"
    assert sr == 60.0


def test_suggest_tag_mappings():
    df = pd.DataFrame({
        "timestamp": ["2026-01-01 00:00", "2026-01-01 00:01"],
        "Motor_Temp": [55.2, 56.1],
        "Vib_RMS": [0.12, 0.15],
        "Drive_Current": [3.4, 3.5],
        "Pump_Pressure": [280, 285]
    })
    mappings = suggest_tag_mappings(df)
    assert mappings.get("timestamp") == "timestamp"
    assert mappings.get("motor_temp") == "Motor_Temp"
    assert mappings.get("vibration_rms") == "Vib_RMS"
    assert mappings.get("current") == "Drive_Current"
    assert mappings.get("pressure") == "Pump_Pressure"


def test_data_quality_scoring():
    # 1. Clean perfect dataset
    clean_df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=100, freq="1min"),
        "current": np.random.uniform(3.0, 3.8, 100),
        "temp": np.random.uniform(45.0, 60.0, 100)
    })
    q_clean = analyze_data_quality(clean_df, timestamp_col="time")
    assert q_clean["score"] >= 95.0
    assert q_clean["grade"] == "EXCELLENT"

    # 2. Corrupt dataset with nulls, dead column, negative RPM
    corrupt_df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=100, freq="1min"),
        "current": [None if i % 4 == 0 else 3.5 for i in range(100)],
        "dead_constant": [42.0] * 100,
        "rpm": [-100 if i == 5 else 1440 for i in range(100)]
    })
    q_corrupt = analyze_data_quality(corrupt_df, timestamp_col="time")
    assert q_corrupt["score"] < q_clean["score"]
    assert q_corrupt["deductions"]["missing_data"] > 0
    assert q_corrupt["deductions"]["constant_columns"] > 0
    assert q_corrupt["deductions"]["invalid_values"] > 0


def test_generate_dataset_preview():
    df = pd.DataFrame({
        "speed_rpm": [1440, 1445, 1438, 1450],
        "status": ["RUN", "RUN", "RUN", "IDLE"]
    })
    preview = generate_dataset_preview(df, max_rows=2)
    assert len(preview["sample_rows"]) == 2
    assert preview["total_rows"] == 4
    assert len(preview["columns"]) == 2
    rpm_col = [c for c in preview["columns"] if c["name"] == "speed_rpm"][0]
    assert rpm_col["is_numeric"] is True
    assert rpm_col["min"] == 1438.0
