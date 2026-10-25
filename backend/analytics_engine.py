"""
PREDICTA 2.0 – Industrial Time-Series Feature & Analytics Engine
Calculates rolling metrics, EWMA, CUSUM change points, operating states,
and cross-variable relationships without future data leakage.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


def compute_time_series_features(
    df: pd.DataFrame,
    mapping: Dict[str, str],
    rolling_window: int = 15
) -> pd.DataFrame:
    """
    Computes time-series engineering features for mapped variables.
    Respects temporal ordering to prevent data leakage.
    """
    features_df = df.copy()
    
    # Sort chronologically if timestamp exists
    ts_col = mapping.get("timestamp")
    if ts_col and ts_col in features_df.columns:
        features_df[ts_col] = pd.to_datetime(features_df[ts_col], errors="coerce")
        features_df = features_df.sort_values(by=ts_col).reset_index(drop=True)
        
    # Standardize mapped columns into unified workspace columns
    mapped_series = {}
    for std_key, raw_col in mapping.items():
        if raw_col and raw_col in features_df.columns:
            mapped_series[std_key] = pd.to_numeric(features_df[raw_col], errors="coerce")
            features_df[f"_std_{std_key}"] = mapped_series[std_key]

    # ── 1. Operating State Classification (Running vs Idle vs Stopped) ──────────
    # If motor_running not explicitly provided, estimate from electrical / rpm
    if "_std_motor_running" not in features_df.columns:
        is_running = pd.Series(True, index=features_df.index)
        if "_std_rpm" in features_df.columns:
            is_running = is_running & (features_df["_std_rpm"] > 200)
        elif "_std_current" in features_df.columns:
            is_running = is_running & (features_df["_std_current"] > 0.5)
        elif "_std_power_kw" in features_df.columns:
            is_running = is_running & (features_df["_std_power_kw"] > 0.1)
        features_df["_std_motor_running"] = is_running.astype(int)

    # ── 2. Rolling Statistics (Mean, Std, Min, Max, EWMA, Rate of Change) ──────
    active_vars = [k for k in ["motor_temp", "bearing_temp", "current", "voltage", "vibration_rms", "pressure", "flow_rate", "rpm"] if f"_std_{k}" in features_df.columns]
    
    for var in active_vars:
        s = features_df[f"_std_{var}"]
        # Rolling Mean & Std
        roll = s.rolling(window=rolling_window, min_periods=1)
        features_df[f"{var}_roll_mean"] = roll.mean()
        features_df[f"{var}_roll_std"] = roll.std().fillna(0.0)
        features_df[f"{var}_roll_min"] = roll.min()
        features_df[f"{var}_roll_max"] = roll.max()
        
        # Exponentially Weighted Moving Average (EWMA)
        features_df[f"{var}_ewma"] = s.ewm(span=rolling_window, adjust=False).mean()
        
        # First Difference / Rate of Change
        features_df[f"{var}_diff"] = s.diff().fillna(0.0)
        
        # Trend Slope (approximate sliding difference over window)
        features_df[f"{var}_trend_slope"] = (s - s.shift(rolling_window)).fillna(0.0) / max(1, rolling_window)

        # Robust Z-Score against baseline (first 20% or overall median/IQR)
        median_base = s.head(max(20, int(len(s) * 0.2))).median()
        q75 = s.head(max(20, int(len(s) * 0.2))).quantile(0.75)
        q25 = s.head(max(20, int(len(s) * 0.2))).quantile(0.25)
        iqr = max(1e-5, q75 - q25)
        features_df[f"{var}_robust_zscore"] = (s - median_base) / (iqr * 0.7413)

    # ── 3. Cross-Variable Engineering Relationships ────────────────────────────
    # Thermal-Current relationship (rising heat without rising current indicates cooling failure or bearing friction)
    if "_std_motor_temp" in features_df.columns and "_std_current" in features_df.columns:
        # Ratio of temperature to current
        curr_safe = features_df["_std_current"].clip(lower=0.5)
        features_df["temp_to_current_ratio"] = features_df["_std_motor_temp"] / curr_safe
        
    # Pressure-Flow relationship (centrifugal pump degradation indicator)
    if "_std_pressure" in features_df.columns and "_std_flow_rate" in features_df.columns:
        flow_safe = features_df["_std_flow_rate"].clip(lower=0.1)
        features_df["pressure_to_flow_ratio"] = features_df["_std_pressure"] / flow_safe

    # Temperature gradient (Bearing Temp minus Motor Temp or Ambient)
    if "_std_bearing_temp" in features_df.columns and "_std_motor_temp" in features_df.columns:
        features_df["bearing_motor_delta"] = features_df["_std_bearing_temp"] - features_df["_std_motor_temp"]

    if "_std_motor_temp" in features_df.columns and "_std_ambient_temp" in features_df.columns:
        features_df["motor_ambient_delta"] = features_df["_std_motor_temp"] - features_df["_std_ambient_temp"]

    return features_df


def detect_cusum_changepoints(
    series: pd.Series,
    threshold: float = 4.0,
    drift: float = 0.5
) -> List[int]:
    """
    Two-sided Cumulative Sum (CUSUM) test for abrupt industrial change detection.
    Returns list of indices where statistically significant shifts occurred.
    """
    s = series.dropna().to_numpy()
    if len(s) < 10:
        return []
        
    mean = np.mean(s[:max(5, int(len(s) * 0.15))])
    std = np.std(s[:max(5, int(len(s) * 0.15))])
    if std < 1e-6:
        std = 1.0
        
    z = (s - mean) / std
    
    gp = np.zeros(len(z))
    gn = np.zeros(len(z))
    changepoints = []
    
    for i in range(1, len(z)):
        gp[i] = max(0, gp[i - 1] + z[i] - drift)
        gn[i] = min(0, gn[i - 1] + z[i] + drift)
        
        if gp[i] > threshold or gn[i] < -threshold:
            changepoints.append(i)
            gp[i] = 0
            gn[i] = 0
            
    return changepoints
