"""
PREDICTA 2.0 – Universal PLC/SCADA Data Ingestion Engine
Handles CSV, XLSX, and XLS file formats exported from industrial historians,
SCADA systems, and PLCs (Siemens, Rockwell/Allen-Bradley, Delta, Schneider, ABB, Yokogawa).
"""

import os
import re
import io
import csv
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone

# ── Standard Schema Variables for Predicta 2.0 ────────────────────────────────
STANDARD_VARIABLES = {
    "timestamp": {
        "label": "Timestamp / Datetime",
        "category": "Time",
        "required": True,
        "aliases": ["time", "timestamp", "date", "datetime", "dt", "ts", "record_time", "log_time", "tag_time", "plc_time"]
    },
    "asset_id": {
        "label": "Asset / Machine Identifier",
        "category": "Metadata",
        "required": False,
        "aliases": ["asset", "asset_id", "device", "device_id", "machine", "machine_id", "equipment_id", "unit_id", "tag_prefix"]
    },
    "motor_running": {
        "label": "Operating State (Run/Stop/Idle)",
        "category": "State",
        "required": False,
        "aliases": ["motor_running", "running", "state", "status", "run_status", "machine_state", "operating_mode", "mode", "run_cmd"]
    },
    "motor_temp": {
        "label": "Motor Temperature (°C)",
        "category": "Temperature",
        "required": False,
        "aliases": ["motor_temp", "m_temp", "motortemp", "t_motor", "motor_temperature", "stator_temp", "winding_temp", "te_101", "temp_m"]
    },
    "bearing_temp": {
        "label": "Bearing Temperature (°C)",
        "category": "Temperature",
        "required": False,
        "aliases": ["bearing_temp", "b_temp", "bearingtemp", "t_bearing", "nde_temp", "de_temp", "bearing_temperature", "te_102"]
    },
    "ambient_temp": {
        "label": "Ambient Temperature (°C)",
        "category": "Temperature",
        "required": False,
        "aliases": ["ambient_temp", "amb_temp", "t_ambient", "room_temp", "environment_temp", "air_temp"]
    },
    "current": {
        "label": "Motor Current (A)",
        "category": "Electrical",
        "required": False,
        "aliases": ["current", "amps", "i_motor", "motor_current", "drive_current", "current_flc", "i_rms", "phase_current", "ct_101"]
    },
    "voltage": {
        "label": "Supply Voltage (V)",
        "category": "Electrical",
        "required": False,
        "aliases": ["voltage", "volts", "v_motor", "v_bus", "grid_voltage", "line_voltage", "vt_101", "v_rms"]
    },
    "power_kw": {
        "label": "Active Power (kW)",
        "category": "Electrical",
        "required": False,
        "aliases": ["power", "power_kw", "kw", "active_power", "motor_power", "consumed_kw", "p_kw"]
    },
    "power_factor": {
        "label": "Power Factor (cos φ)",
        "category": "Electrical",
        "required": False,
        "aliases": ["power_factor", "pf", "cos_phi", "cosphi", "p_factor"]
    },
    "vibration_rms": {
        "label": "Vibration RMS (g or mm/s)",
        "category": "Mechanical",
        "required": False,
        "aliases": ["vibration", "vibration_rms", "vib_rms", "vib", "accel_rms", "velocity_rms", "overall_vib", "vib_de", "vib_nde"]
    },
    "rpm": {
        "label": "Rotational Speed (RPM)",
        "category": "Mechanical",
        "required": False,
        "aliases": ["rpm", "speed", "motor_speed", "rotational_speed", "encoder_rpm", "tachometer", "frequency_hz"]
    },
    "pressure": {
        "label": "Pressure (kPa / bar / PSI)",
        "category": "Process",
        "required": False,
        "aliases": ["pressure", "discharge_pressure", "pump_pressure", "hyd_pressure", "head_pressure", "p_discharge", "pt_101", "bar"]
    },
    "flow_rate": {
        "label": "Flow Rate (m³/h or L/min)",
        "category": "Process",
        "required": False,
        "aliases": ["flow", "flow_rate", "discharge_flow", "lpm", "m3h", "ft_101", "volumetric_flow"]
    },
    # Listed after the generic tags so a plain "Temp" / "Pressure" column is not claimed here first.
    "discharge_temp": {
        "label": "Discharge / Outlet Temperature (°C)",
        "category": "Temperature",
        "required": False,
        "aliases": ["discharge_temp", "discharge_temperature", "t_discharge", "outlet_temp", "stage_temp", "air_discharge_temp", "te_201"]
    },
    "torque": {
        "label": "Drive Torque (N·m or %)",
        "category": "Mechanical",
        "required": False,
        "aliases": ["torque", "drive_torque", "shaft_torque", "motor_torque", "load_torque", "torque_nm", "torque_pct"]
    },
    "differential_pressure": {
        "label": "Differential Pressure across Filter / Exchanger (kPa)",
        "category": "Process",
        "required": False,
        "aliases": ["differential_pressure", "diff_pressure", "delta_p", "filter_dp", "dp_filter", "pressure_drop", "pdt_101"]
    },
    "fault_code": {
        "label": "PLC / Drive Fault Code",
        "category": "Alarms",
        "required": False,
        "aliases": ["fault_code", "alarm_code", "trip_code", "error_code", "vfd_fault", "plc_fault", "alarm_id"]
    },
    "run_hours": {
        "label": "Cumulative Run Hours (h)",
        "category": "Operational",
        "required": False,
        "aliases": ["run_hours", "runtime", "operating_hours", "total_hours", "hour_meter", "service_hours"]
    },
    "failure_label": {
        "label": "Historical Failure Label (Ground Truth)",
        "category": "AI Training",
        "required": False,
        "aliases": ["failure", "fault", "is_failure", "failure_type", "breakdown", "machine_failure", "target"]
    }
}


def detect_csv_delimiter(file_path_or_bytes, sample_size=16384) -> str:
    """Detect CSV delimiter (comma, semicolon, tab, pipe)."""
    if isinstance(file_path_or_bytes, bytes):
        sample = file_path_or_bytes[:sample_size].decode("utf-8", errors="ignore")
    else:
        with open(file_path_or_bytes, "rb") as f:
            sample = f.read(sample_size).decode("utf-8", errors="ignore")
            
    # Try Python's Sniffer
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        pass
        
    # Heuristic count
    counts = {
        ",": sample.count(","),
        ";": sample.count(";"),
        "\t": sample.count("\t"),
        "|": sample.count("|")
    }
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def detect_file_encoding(file_path_or_bytes) -> str:
    """Detect file encoding safely."""
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"]
    if isinstance(file_path_or_bytes, bytes):
        raw = file_path_or_bytes[:10000]
        for enc in encodings:
            try:
                raw.decode(enc)
                return enc
            except UnicodeDecodeError:
                continue
    else:
        with open(file_path_or_bytes, "rb") as f:
            raw = f.read(10000)
            for enc in encodings:
                try:
                    raw.decode(enc)
                    return enc
                except UnicodeDecodeError:
                    continue
    return "utf-8"


def get_excel_sheets(file_path) -> list:
    """Get sheet names from Excel file."""
    try:
        excel_file = pd.ExcelFile(file_path)
        return excel_file.sheet_names
    except Exception as e:
        return []


def read_industrial_file(file_path: str, sheet_name=None) -> pd.DataFrame:
    """Read CSV or Excel into a clean pandas DataFrame."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        encoding = detect_file_encoding(file_path)
        delimiter = detect_csv_delimiter(file_path)
        df = pd.read_csv(file_path, delimiter=delimiter, encoding=encoding, low_memory=False)
    elif ext in [".xlsx", ".xls"]:
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Only CSV, XLSX, and XLS are supported.")
        
    # Clean column names (strip whitespace and null chars)
    df.columns = [str(col).strip().replace("\x00", "") for col in df.columns]
    return df


def detect_timestamp_column(df: pd.DataFrame) -> tuple:
    """
    Find best candidate timestamp column and attempt parsing.
    Returns: (column_name, parsed_series, sampling_rate_sec)
    """
    date_patterns = [
        r"time", r"date", r"timestamp", r"^ts$", r"datetime", r"log_time", r"plc_time", r"record_time"
    ]
    
    # Check column names first
    candidate_cols = []
    for col in df.columns:
        col_lower = str(col).lower().strip()
        for pat in date_patterns:
            if re.search(pat, col_lower):
                candidate_cols.append(col)
                break
                
    # Also check object/string columns if no name matched
    if not candidate_cols:
        candidate_cols = [c for c in df.columns if pd.api.types.is_string_dtype(df[c]) or pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_datetime64_any_dtype(df[c])]

    for col in candidate_cols:
        try:
            # Check if already datetime
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                parsed = pd.to_datetime(df[col])
            else:
                # Sample 100 non-null values
                sample = df[col].dropna().head(100)
                if len(sample) == 0:
                    continue
                # Try parsing sample
                parsed_sample = pd.to_datetime(sample, errors="coerce")
                if parsed_sample.isna().mean() > 0.3:
                    continue
                parsed = pd.to_datetime(df[col], errors="coerce")
                
            # If successfully parsed > 70% of rows
            valid_dt = parsed.dropna()
            if len(valid_dt) >= max(1, len(df) * 0.7):
                # Estimate sampling rate
                diffs = valid_dt.sort_values().diff().dt.total_seconds().dropna()
                positive_diffs = diffs[diffs > 0]
                median_sr = float(positive_diffs.median()) if len(positive_diffs) > 0 else 1.0
                return col, parsed, round(median_sr, 2)
        except Exception:
            continue
            
    return None, None, None



def suggest_tag_mappings(df: pd.DataFrame) -> dict:
    """
    Intelligently suggest mappings from plant tags to standard variables.
    Returns: {standard_var: suggested_col_name}
    """
    suggestions = {}
    used_cols = set()
    
    # 1. First detect timestamp
    ts_col, _, _ = detect_timestamp_column(df)
    if ts_col:
        suggestions["timestamp"] = ts_col
        used_cols.add(ts_col)
        
    # 2. Iterate standard variables
    for var, meta in STANDARD_VARIABLES.items():
        if var == "timestamp":
            continue
            
        best_col = None
        best_score = 0
        
        for col in df.columns:
            if col in used_cols:
                continue
                
            col_norm = re.sub(r"[^a-zA-Z0-9]", "_", str(col).lower()).strip("_")
            
            # Exact alias match
            for alias in meta["aliases"]:
                alias_norm = re.sub(r"[^a-zA-Z0-9]", "_", alias.lower()).strip("_")
                if col_norm == alias_norm:
                    best_col = col
                    best_score = 100
                    break
                elif alias_norm in col_norm or col_norm in alias_norm:
                    score = 70
                    if score > best_score:
                        best_col = col
                        best_score = score
            if best_score == 100:
                break
                
        if best_col and best_score >= 70:
            suggestions[var] = best_col
            used_cols.add(best_col)
            
    return suggestions


def analyze_data_quality(df: pd.DataFrame, timestamp_col=None) -> dict:
    """
    Documented Data Quality Scoring (0 to 100%).
    
    Deduction Weights:
    1. Missing Data Penalty: up to 30 pts (based on null percentage across entire dataset)
    2. Duplicate Rows Penalty: up to 20 pts (based on % of duplicate timestamps or identical rows)
    3. Timestamp Gaps & Irregularity: up to 20 pts (based on ratio of gaps > 3x median interval)
    4. Constant / Dead Columns: up to 15 pts (columns with zero variance)
    5. Invalid Engineering Values: up to 15 pts (unphysical negative values, extreme spikes)
    """
    total_rows = len(df)
    total_cols = len(df.columns)
    
    if total_rows == 0:
        return {
            "score": 0.0,
            "status": "FAIL",
            "metrics": {"error": "Empty dataset"}
        }

    deductions = []
    quality_details = {}
    
    # 1. Missing Values Analysis
    null_counts = df.isnull().sum()
    total_cells = total_rows * total_cols
    total_nulls = int(null_counts.sum())
    null_pct = (total_nulls / total_cells) * 100 if total_cells > 0 else 0
    missing_penalty = min(30.0, (null_pct / 20.0) * 30.0)
    deductions.append(missing_penalty)
    quality_details["missing_data"] = {
        "total_nulls": total_nulls,
        "null_percentage": round(null_pct, 2),
        "penalty": round(missing_penalty, 2),
        "cols_with_nulls": {col: int(cnt) for col, cnt in null_counts.items() if cnt > 0}
    }
    
    # 2. Duplicate Row Analysis
    if timestamp_col and timestamp_col in df.columns:
        dup_count = int(df.duplicated(subset=[timestamp_col]).sum())
    else:
        dup_count = int(df.duplicated().sum())
    dup_pct = (dup_count / total_rows) * 100
    dup_penalty = min(20.0, (dup_pct / 5.0) * 20.0)
    deductions.append(dup_penalty)
    quality_details["duplicates"] = {
        "duplicate_rows": dup_count,
        "duplicate_percentage": round(dup_pct, 2),
        "penalty": round(dup_penalty, 2)
    }
    
    # 3. Timestamp Continuity & Sampling Gaps
    gap_penalty = 0.0
    sampling_info = {"has_timestamp": False}
    if timestamp_col and timestamp_col in df.columns:
        try:
            ts_series = pd.to_datetime(df[timestamp_col], errors="coerce").dropna().sort_values()
            if len(ts_series) > 1:
                diffs = ts_series.diff().dt.total_seconds().dropna()
                pos_diffs = diffs[diffs > 0]
                median_step = float(pos_diffs.median()) if len(pos_diffs) > 0 else 1.0
                gaps = int((diffs > (median_step * 3.0)).sum())
                gap_ratio = (gaps / len(diffs)) * 100 if len(diffs) > 0 else 0
                gap_penalty = min(20.0, gap_ratio * 2.0)
                sampling_info = {
                    "has_timestamp": True,
                    "median_interval_seconds": round(median_step, 2),
                    "total_gaps_detected": gaps,
                    "gap_ratio_pct": round(gap_ratio, 2),
                    "time_start": ts_series.iloc[0].isoformat(),
                    "time_end": ts_series.iloc[-1].isoformat(),
                    "total_duration_hours": round((ts_series.iloc[-1] - ts_series.iloc[0]).total_seconds() / 3600, 2)
                }
        except Exception as e:
            sampling_info["error"] = str(e)
    deductions.append(gap_penalty)
    quality_details["sampling_continuity"] = {
        **sampling_info,
        "penalty": round(gap_penalty, 2)
    }
    
    # 4. Constant / Dead Columns (Zero Variance)
    num_cols = df.select_dtypes(include=[np.number]).columns
    constant_cols = [c for c in num_cols if df[c].std() == 0 or df[c].nunique() <= 1]
    const_pct = (len(constant_cols) / max(1, len(num_cols))) * 100 if len(num_cols) > 0 else 0
    const_penalty = min(15.0, (const_pct / 30.0) * 15.0)
    deductions.append(const_penalty)
    quality_details["constant_columns"] = {
        "constant_cols": constant_cols,
        "count": len(constant_cols),
        "penalty": round(const_penalty, 2)
    }
    
    # 5. Invalid / Unphysical Engineering Values
    invalid_count = 0
    invalid_notes = []
    for c in num_cols:
        c_low = c.lower()
        vals = df[c].dropna()
        if len(vals) == 0:
            continue
        # Unphysical RPM (< 0 or > 15000 for standard machinery)
        if "rpm" in c_low and (vals < 0).any():
            invalid_count += int((vals < 0).sum())
            invalid_notes.append(f"Negative RPM detected in {c}")
        # Unphysical Kelvin temperature (< 0 K) or Celsius (< -50 °C for indoor plant)
        if "temp" in c_low and (vals < -50).any():
            invalid_count += int((vals < -50).sum())
            invalid_notes.append(f"Extreme negative temperature in {c}")
        # Negative current or negative power (if motoring)
        if ("current" in c_low or "power" in c_low) and (vals < -5).any():
            invalid_count += int((vals < -5).sum())
            invalid_notes.append(f"Significant negative electrical reading in {c}")

    invalid_pct = (invalid_count / total_cells) * 100 if total_cells > 0 else 0
    invalid_penalty = min(15.0, invalid_pct * 15.0)
    deductions.append(invalid_penalty)
    quality_details["invalid_values"] = {
        "anomalous_reading_count": invalid_count,
        "notes": invalid_notes,
        "penalty": round(invalid_penalty, 2)
    }

    # Final Score Calculation
    total_deduction = sum(deductions)
    quality_score = max(0.0, min(100.0, 100.0 - total_deduction))
    
    grade = "EXCELLENT" if quality_score >= 90 else "GOOD" if quality_score >= 75 else "FAIR" if quality_score >= 55 else "POOR"
    
    return {
        "score": round(quality_score, 1),
        "grade": grade,
        "total_rows": total_rows,
        "total_columns": total_cols,
        "deductions": {
            "missing_data": round(missing_penalty, 1),
            "duplicates": round(dup_penalty, 1),
            "sampling_gaps": round(gap_penalty, 1),
            "constant_columns": round(const_penalty, 1),
            "invalid_values": round(invalid_penalty, 1)
        },
        "details": quality_details
    }


def generate_dataset_preview(df: pd.DataFrame, max_rows=15) -> dict:
    """Generate preview schema, statistics, and sample rows for UI display."""
    preview_df = df.head(max_rows).copy()
    
    # Handle NaN and date serialization
    preview_df = preview_df.replace({np.nan: None})
    sample_rows = preview_df.to_dict(orient="records")
    
    columns_meta = []
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        is_num = pd.api.types.is_numeric_dtype(df[col])
        col_info = {

            "name": col,
            "dtype": dtype_str,
            "is_numeric": bool(is_num),
            "null_count": int(df[col].isnull().sum()),
            "null_pct": round(float(df[col].isnull().mean()) * 100, 1),
            "unique_count": int(df[col].nunique())
        }
        if is_num and df[col].count() > 0:
            col_info.update({
                "min": round(float(df[col].min()), 3) if not math.isnan(df[col].min()) else None,
                "max": round(float(df[col].max()), 3) if not math.isnan(df[col].max()) else None,
                "mean": round(float(df[col].mean()), 3) if not math.isnan(df[col].mean()) else None,
                "std": round(float(df[col].std()), 3) if not math.isnan(df[col].std()) else None
            })
        columns_meta.append(col_info)
        
    return {
        "columns": columns_meta,
        "sample_rows": sample_rows,
        "total_rows": len(df),
        "total_columns": len(df.columns)
    }
