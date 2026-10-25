"""
PREDICTA 2.0 – Explainable Industrial Fault Investigation Engine
Evaluates evidence across available tags to produce multi-variable hypotheses,
proxy disclosures, alternative explanations, and inspection recommendations.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional


def generate_fault_hypotheses(
    df: pd.DataFrame,
    mapping: Dict[str, str],
    layer1_res: Dict[str, Any],
    layer2_res: Dict[str, Any],
    risk_res: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Evaluates 9 industrial failure signatures based STRICTLY on available data tags.
    Assigns documented evidence strength: STRONG, MODERATE, WEAK, INSUFFICIENT.
    Discloses when a proxy variable is used rather than a physical sensor.
    """
    hypotheses = []
    
    # Check which standard variables are available in the dataset
    has_motor_temp = "_std_motor_temp" in df.columns
    has_bearing_temp = "_std_bearing_temp" in df.columns
    has_current = "_std_current" in df.columns
    has_voltage = "_std_voltage" in df.columns
    has_vibration = "_std_vibration_rms" in df.columns
    has_pressure = "_std_pressure" in df.columns
    has_flow = "_std_flow_rate" in df.columns
    has_rpm = "_std_rpm" in df.columns
    
    # ── 1. Bearing Degradation ────────────────────────────────────────────────
    if has_vibration or has_bearing_temp:
        vib_high = (df["_std_vibration_rms"] > 0.45).any() if has_vibration else False
        vib_crit = (df["_std_vibration_rms"] > 0.90).any() if has_vibration else False
        bt_high = (df["_std_bearing_temp"] > 70.0).any() if has_bearing_temp else False
        bt_crit = (df["_std_bearing_temp"] > 80.0).any() if has_bearing_temp else False
        
        evidence_points = []
        if vib_high:
            max_v = float(df["_std_vibration_rms"].max())
            evidence_points.append(f"Vibration RMS elevated (max {max_v:.3f}g vs 0.45g limit)")
        if bt_high:
            max_bt = float(df["_std_bearing_temp"].max())
            evidence_points.append(f"Bearing temperature elevated (max {max_bt:.1f}°C vs 70.0°C limit)")

        if vib_crit and bt_crit:
            strength = "STRONG"
        elif vib_high or bt_high:
            strength = "MODERATE" if (has_vibration and has_bearing_temp) else "WEAK"
        else:
            strength = "INSUFFICIENT"
            
        hypotheses.append({
            "hypothesis": "Bearing Wear / Mechanical Degradation",
            "category": "Mechanical",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Parameters within normal baseline limits"],
            "alternative_explanations": [
                "Shaft misalignment or loose base bolts causing high structural vibration",
                "High ambient temperature elevating bearing housing temperature without mechanical wear",
                "Excess grease packing causing temporary churning friction"
            ],
            "data_limitations": "High-frequency vibration FFT spectrum not available. Analysis based on aggregate 1Hz RMS / housing temperature. Defect frequency (BPFO/BPFI) unverified." if has_vibration else "Vibration sensor not present in uploaded dataset. Bearing health estimated solely from housing temperature proxy.",
            "recommended_actions": [
                "Perform manual stethoscopic / ultrasound acoustic inspection on drive-end and non-drive-end bearings",
                "Verify lubrication grease condition and replenish according to manufacturer schedule",
                "Check shaft alignment and foundation bolt tightness using dial gauge"
            ]
        })
    else:
        hypotheses.append({
            "hypothesis": "Bearing Wear / Mechanical Degradation",
            "category": "Mechanical",
            "confidence": "INSUFFICIENT",
            "applicable": False,
            "supporting_evidence": [],
            "alternative_explanations": [],
            "data_limitations": "Neither vibration RMS nor bearing temperature was present in uploaded data tags.",
            "recommended_actions": ["Include vibration or bearing temperature tags in export to enable mechanical monitoring."]
        })

    # ── 2. Motor Overload & Electrical Overstress ──────────────────────────────
    if has_current:
        curr = df["_std_current"].dropna()
        curr_high = (curr > 4.2).any()
        curr_crit = (curr > 5.0).any()
        mt_high = (df["_std_motor_temp"] > 75.0).any() if has_motor_temp else False
        
        evidence_points = []
        if curr_high:
            evidence_points.append(f"Motor current exceeds 120% Full Load Current (peak {curr.max():.2f}A vs 3.5A rated)")
        if mt_high:
            evidence_points.append(f"Motor winding / casing temperature elevated ({df['_std_motor_temp'].max():.1f}°C)")
            
        if curr_crit and mt_high:
            strength = "STRONG"
        elif curr_high:
            strength = "MODERATE"
        else:
            strength = "INSUFFICIENT"
            
        hypotheses.append({
            "hypothesis": "Motor Electrical Overload / Driven Load Binding",
            "category": "Electrical",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Current profile normal"],
            "alternative_explanations": [
                "Mechanical jam, impeller obstruction, or driven equipment drag",
                "Supply undervoltage forcing motor to draw higher current for constant power output",
                "Process throughput surge exceeding nominal design capacity"
            ],
            "data_limitations": "Phase-level balance (L1, L2, L3) not individually tracked. Single aggregate current reading analysed.",
            "recommended_actions": [
                "Check driven pump / machine coupling for free mechanical rotation by hand (lockout/tagout)",
                "Verify thermal overload relay trip settings and MCC contactor integrity",
                "Inspect process flow line for downstream valve throttling or physical blockages"
            ]
        })

    # ── 3. Cooling System Deterioration ───────────────────────────────────────
    if has_motor_temp:
        mt = df["_std_motor_temp"].dropna()
        mt_slope = df.get("motor_temp_trend_slope", pd.Series(0)).max()
        curr_normal = (df["_std_current"] < 3.8).all() if has_current else True
        
        thermal_runaway = (mt.max() > 75.0) and curr_normal
        evidence_points = []
        if mt.max() > 75.0:
            evidence_points.append(f"Motor temperature sustained above 75.0°C (peak {mt.max():.1f}°C)")
        if mt_slope > 0.1:
            evidence_points.append(f"Continuous upward thermal drift ({mt_slope:.2f}°C/sample)")
        if curr_normal and has_current:
            evidence_points.append("Motor current remains within nominal limits during temperature rise")

        if thermal_runaway and mt_slope > 0.05:
            strength = "STRONG"
        elif mt.max() > 75.0:
            strength = "MODERATE"
        else:
            strength = "INSUFFICIENT"
            
        hypotheses.append({
            "hypothesis": "Cooling System Degradation / Ventilation Blockage",
            "category": "Thermal",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Thermal levels within normal limits"],
            "alternative_explanations": [
                "High ambient plant temperature or seasonal summer heat excursion",
                "Adjacent thermal radiation from nearby furnaces or steam lines"
            ],
            "data_limitations": "Cooling air velocity and coolant flow sensors are not installed; condition inferred from temperature vs electrical load proxy.",
            "recommended_actions": [
                "Inspect motor cowl and external fan blades for physical damage or accumulated dust/debris",
                "Clean motor cooling fins and ensure air intake clearance of at least 150mm",
                "Verify ambient ventilation in the production hall"
            ]
        })

    # ── 4. Pump / Hydraulic Cavitation or Performance Loss ─────────────────────
    if has_pressure or has_flow:
        p = df["_std_pressure"].dropna() if has_pressure else pd.Series()
        f = df["_std_flow_rate"].dropna() if has_flow else pd.Series()
        p_std = df.get("pressure_roll_std", pd.Series(0)).max()
        
        evidence_points = []
        if len(p) > 0 and p.min() < 100.0:
            evidence_points.append(f"Discharge pressure drop observed (min {p.min():.1f} kPa vs 250 kPa nominal)")
        if p_std > 20.0:
            evidence_points.append(f"High pressure volatility / erratic fluctuations (std {p_std:.1f} kPa)")
        if len(f) > 0 and f.min() < 10.0:
            evidence_points.append(f"Flow rate decline detected (min {f.min():.1f} m³/h)")
            
        if (len(p) > 0 and p.min() < 100.0) and p_std > 20.0:
            strength = "STRONG"
        elif len(evidence_points) > 0:
            strength = "MODERATE"
        else:
            strength = "INSUFFICIENT"
            
        hypotheses.append({
            "hypothesis": "Pump Hydraulic Cavitation / Suction Starvation",
            "category": "Hydraulic",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Pressure and flow stable"],
            "alternative_explanations": [
                "Upstream suction tank low liquid level causing air entrainment",
                "Suction strainer partially blinded by particulate matter",
                "Discharge control valve hunting or modulation cycle"
            ],
            "data_limitations": "Suction pressure transmitter not present. Analysis derived from discharge pressure variance and flow proxy.",
            "recommended_actions": [
                "Inspect suction basket strainer and differential pressure indicator",
                "Check suction vessel level and verify Net Positive Suction Head (NPSH) margin",
                "Listen for gravel-like rattling sound indicating active cavitation"
            ]
        })

    # ── 5. Power Quality / Voltage Supply Anomaly ──────────────────────────────
    if has_voltage:
        v = df["_std_voltage"].dropna()
        v_low = (v < 380.0).any()
        v_high = (v > 440.0).any()
        
        evidence_points = []
        if v_low:
            evidence_points.append(f"Supply undervoltage detected (min {v.min():.1f}V vs 380V limit)")
        if v_high:
            evidence_points.append(f"Supply overvoltage detected (max {v.max():.1f}V vs 440V limit)")
            
        if v_low or v_high:
            strength = "STRONG" if (v.min() < 360.0 or v.max() > 460.0) else "MODERATE"
        else:
            strength = "INSUFFICIENT"
            
        hypotheses.append({
            "hypothesis": "Electrical Supply Grid / Busbar Voltage Instability",
            "category": "Electrical",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Supply voltage steady within ±5% tolerance"],
            "alternative_explanations": [
                "Plant-wide utility grid voltage sag from large motor starting nearby",
                "Loose terminal connection or corroded MCC busbar splice"
            ],
            "data_limitations": "Harmonics (THD) and individual phase angles not recorded in uploaded file.",
            "recommended_actions": [
                "Inspect MCC incoming feeder voltage with calibrated true-RMS multimeter",
                "Perform infrared thermography scan on breaker contacts and cable lugs"
            ]
        })

    return hypotheses
