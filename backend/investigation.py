"""
PREDICTA 2.0 – Explainable Industrial Fault Investigation Engine
Evaluates evidence across available tags to produce multi-variable hypotheses,
proxy disclosures, alternative explanations, and inspection recommendations.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional

from analytics_engine import running_rows, compute_changepoints


def _baseline_vs_recent(df: pd.DataFrame, col: str, fraction: float = 0.2) -> Optional[Dict[str, float]]:
    """Median of the first and last `fraction` of running samples, and the change between them."""
    s = pd.to_numeric(running_rows(df)[col], errors="coerce").dropna() if col in df.columns else pd.Series(dtype=float)
    if len(s) < 10:
        return None
    n = max(5, int(len(s) * fraction))
    base, recent = float(s.head(n).median()), float(s.tail(n).median())
    pct = (recent - base) / abs(base) * 100 if abs(base) > 1e-9 else 0.0
    return {"baseline": base, "recent": recent, "delta": recent - base, "pct": pct}


def _insufficient(name: str, category: str, limitation: str, action: str) -> Dict[str, Any]:
    return {
        "hypothesis": name,
        "category": category,
        "confidence": "INSUFFICIENT",
        "applicable": False,
        "supporting_evidence": [],
        "alternative_explanations": [],
        "data_limitations": limitation,
        "recommended_actions": [action],
    }


def generate_fault_hypotheses(
    df: pd.DataFrame,
    mapping: Dict[str, str],
    layer1_res: Dict[str, Any],
    layer2_res: Dict[str, Any],
    risk_res: Dict[str, Any],
    changepoints: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Evaluates 9 industrial failure signatures based STRICTLY on available data tags.
    Assigns documented evidence strength: STRONG, MODERATE, WEAK, INSUFFICIENT.
    Discloses when a proxy variable is used rather than a physical sensor.
    CUSUM change-points (computed here if not supplied) date the onset of each shift.
    """
    hypotheses = []
    if changepoints is None:
        changepoints = compute_changepoints(df, timestamp_col=mapping.get("timestamp"))

    # Check which standard variables are available in the dataset
    has_motor_temp = "_std_motor_temp" in df.columns
    has_bearing_temp = "_std_bearing_temp" in df.columns
    has_current = "_std_current" in df.columns
    has_voltage = "_std_voltage" in df.columns
    has_vibration = "_std_vibration_rms" in df.columns
    has_pressure = "_std_pressure" in df.columns
    has_flow = "_std_flow_rate" in df.columns
    has_rpm = "_std_rpm" in df.columns
    has_discharge_temp = "_std_discharge_temp" in df.columns
    has_torque = "_std_torque" in df.columns
    has_diff_pressure = "_std_differential_pressure" in df.columns

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
    else:
        hypotheses.append(_insufficient(
            "Motor Electrical Overload / Driven Load Binding", "Electrical",
            "No motor current tag in the uploaded data.",
            "Include motor current (or drive output current) in the export."))

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
    else:
        hypotheses.append(_insufficient(
            "Cooling System Degradation / Ventilation Blockage", "Thermal",
            "No motor temperature tag in the uploaded data.",
            "Include motor winding or casing temperature in the export."))

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
    else:
        hypotheses.append(_insufficient(
            "Pump Hydraulic Cavitation / Suction Starvation", "Hydraulic",
            "No pressure or flow tag in the uploaded data.",
            "Include discharge pressure and flow rate in the export."))

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
    else:
        hypotheses.append(_insufficient(
            "Electrical Supply Grid / Busbar Voltage Instability", "Electrical",
            "No supply voltage tag in the uploaded data.",
            "Include line voltage from the MCC or drive in the export."))

    # ── 6. Compressor Valve Degradation ───────────────────────────────────────
    temp_col = "_std_discharge_temp" if has_discharge_temp else ("_std_motor_temp" if has_motor_temp else None)
    if has_pressure and temp_col:
        p = _baseline_vs_recent(df, "_std_pressure")
        t = _baseline_vs_recent(df, temp_col)
        f = _baseline_vs_recent(df, "_std_flow_rate") if has_flow else None
        c = _baseline_vs_recent(df, "_std_current") if has_current else None
        temp_name = "Discharge temperature" if has_discharge_temp else "Motor temperature (proxy for discharge temperature)"

        evidence_points = []
        p_drop = p is not None and p["pct"] <= -10.0
        t_rise = t is not None and t["delta"] >= 10.0
        t_mild = t is not None and t["delta"] >= 5.0
        if p is not None and p["pct"] <= -5.0:
            evidence_points.append(f"Delivery pressure deficit: {p['baseline']:.1f} → {p['recent']:.1f} kPa ({p['pct']:.0f}%)")
        if t_mild:
            evidence_points.append(f"{temp_name} rise: {t['baseline']:.1f} → {t['recent']:.1f} °C (+{t['delta']:.1f} °C)")
        if f is not None and f["pct"] <= -10.0:
            evidence_points.append(f"Delivered flow falling ({f['pct']:.0f}%) – valves re-compressing leaked air")
        if c is not None and c["pct"] >= 5.0:
            evidence_points.append(f"Drive current up {c['pct']:.0f}% while delivering less – work wasted on leakage")
        support = (f is not None and f["pct"] <= -10.0) or (c is not None and c["pct"] >= 5.0)

        # STRONG needs a real discharge temperature, not the motor-temperature proxy
        if p_drop and t_rise and support and has_discharge_temp:
            strength = "STRONG"
        elif p_drop and t_mild:
            strength = "MODERATE"
        elif p is not None and p["pct"] <= -5.0 and t_mild:
            strength = "WEAK"
        else:
            strength = "INSUFFICIENT"

        hypotheses.append({
            "hypothesis": "Compressor Valve Degradation / Internal Leakage",
            "category": "Pneumatic",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Delivery pressure and discharge temperature stable"],
            "alternative_explanations": [
                "Increased plant air demand or a downstream leak pulling line pressure down",
                "Clogged intake filter starving the compression stage",
                "Intercooler / aftercooler fouling raising discharge temperature"
            ],
            "data_limitations": ("Per-stage pressures and valve temperatures not recorded; analysis uses delivery pressure "
                                 "and a single discharge temperature." if has_discharge_temp else
                                 "No discharge temperature tag: motor temperature used as a weak proxy for stage heating."),
            "recommended_actions": [
                "Measure per-stage suction / discharge temperatures; a hot valve cover pinpoints the leaking valve",
                "Inspect suction and discharge valve plates, springs and seats for wear or carbon build-up",
                "Run a load / unload timing test to quantify capacity loss"
            ]
        })
    else:
        hypotheses.append(_insufficient(
            "Compressor Valve Degradation / Internal Leakage", "Pneumatic",
            "Needs delivery pressure plus discharge (or motor) temperature tags.",
            "Include discharge pressure and discharge temperature in the export."))

    # ── 7. Gearbox Tooth Wear & Mechanical Imbalance ──────────────────────────
    if has_vibration:
        v = _baseline_vs_recent(df, "_std_vibration_rms")
        load_col = "_std_torque" if has_torque else ("_std_current" if has_current else None)
        load = _baseline_vs_recent(df, load_col) if load_col else None
        vib_cp = changepoints.get("vibration_rms", {})

        evidence_points = []
        if v is not None and v["pct"] >= 30.0:
            evidence_points.append(f"Vibration RMS up {v['pct']:.0f}% ({v['baseline']:.3f} → {v['recent']:.3f} g)")
        if vib_cp.get("ongoing_shift"):
            when = f" since {vib_cp['ongoing_shift_timestamp']}" if vib_cp.get("ongoing_shift_timestamp") else ""
            evidence_points.append(f"CUSUM: sustained step-change in vibration{when}")
        if load is not None and load["pct"] >= 10.0:
            load_name = "Drive torque" if has_torque else "Motor current (torque proxy)"
            evidence_points.append(f"{load_name} up {load['pct']:.0f}% – higher drive effort")

        vib_up = v["pct"] if v is not None else 0.0
        load_up = load is not None and load["pct"] >= 10.0
        # STRONG needs a real torque measurement: current alone also rises with plain overload
        if vib_up >= 100.0 and vib_cp.get("ongoing_shift") and load_up and has_torque:
            strength = "STRONG"
        elif vib_up >= 50.0 and vib_cp.get("ongoing_shift"):
            strength = "MODERATE"
        elif vib_up >= 30.0:
            strength = "WEAK"
        else:
            strength = "INSUFFICIENT"

        hypotheses.append({
            "hypothesis": "Gearbox Tooth Wear / Mechanical Imbalance",
            "category": "Mechanical",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Vibration level steady with no step-change"],
            "alternative_explanations": [
                "Rotor imbalance, loose coupling or soft foot producing 1× running-speed vibration",
                "Bearing defect (see bearing hypothesis) – both raise overall RMS",
                "Process load change rather than mechanical damage"
            ],
            "data_limitations": ("Overall RMS only – gear-mesh frequency and sidebands need a spectrum (FFT) to confirm tooth damage."
                                 + ("" if has_torque else " No torque tag: motor current used as a torque proxy.")),
            "recommended_actions": [
                "Collect a vibration spectrum at the gearbox input and output bearings; look for gear-mesh frequency sidebands",
                "Drain a gear oil sample for wear-metal (ferrography) and particle-count analysis",
                "Inspect tooth contact pattern and backlash at the next planned stop"
            ]
        })
    else:
        hypotheses.append(_insufficient(
            "Gearbox Tooth Wear / Mechanical Imbalance", "Mechanical",
            "No vibration tag in the uploaded data.",
            "Include vibration RMS (and torque if available) to enable gearbox monitoring."))

    # ── 8. Lubrication Breakdown ──────────────────────────────────────────────
    lube_temp = "bearing_temp" if has_bearing_temp else ("motor_temp" if has_motor_temp else None)
    if lube_temp and has_vibration:
        t = _baseline_vs_recent(df, f"_std_{lube_temp}")
        v = _baseline_vs_recent(df, "_std_vibration_rms")
        t_cp = changepoints.get(lube_temp, {})
        v_cp = changepoints.get("vibration_rms", {})
        lead = max(3, int(len(df) * 0.01))
        t_start = t_cp.get("ongoing_shift_row") if t_cp.get("ongoing_shift") else None
        v_start = v_cp.get("ongoing_shift_row") if v_cp.get("ongoing_shift") else None
        temp_leads = (isinstance(t_start, int) and
                      (not isinstance(v_start, int) or t_start + lead <= v_start))

        evidence_points = []
        if t is not None and t["delta"] >= 5.0:
            evidence_points.append(f"{lube_temp.replace('_', ' ').capitalize()} up {t['delta']:.1f} °C ({t['baseline']:.1f} → {t['recent']:.1f} °C)")
        if temp_leads and t is not None and t["delta"] >= 5.0:
            when = f" ({t_cp.get('ongoing_shift_timestamp')})" if t_cp.get("ongoing_shift_timestamp") else ""
            evidence_points.append(f"Temperature shift began before the vibration shift{when} – friction heat first, wear later")
        if v is not None and v["pct"] >= 30.0:
            evidence_points.append(f"Vibration followed with a {v['pct']:.0f}% rise")

        t_rise = t["delta"] if t is not None else 0.0
        v_rise = v["pct"] if v is not None else 0.0
        # STRONG needs bearing temperature: motor temperature also rises with load or cooling faults
        if temp_leads and t_rise >= 8.0 and has_bearing_temp:
            strength = "STRONG"
        elif t_rise >= 8.0 and v_rise >= 30.0:
            strength = "MODERATE"
        elif t_rise >= 5.0:
            strength = "WEAK"
        else:
            strength = "INSUFFICIENT"

        hypotheses.append({
            "hypothesis": "Lubrication Breakdown / Friction Heating",
            "category": "Tribological",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["No friction-heating pattern found"],
            "alternative_explanations": [
                "Over-greasing causing churning heat (temperature rises without later vibration)",
                "Higher ambient temperature or reduced cooling air",
                "Load increase raising both temperature and vibration together"
            ],
            "data_limitations": ("Oil condition, viscosity and level are not measured; inferred from the order of "
                                 "temperature and vibration changes." +
                                 ("" if has_bearing_temp else " No bearing temperature: motor temperature used as proxy.")),
            "recommended_actions": [
                "Check lubricant level, colour and viscosity; replace if darkened, thinned or contaminated",
                "Verify re-greasing interval and quantity against the bearing / gearbox manufacturer's schedule",
                "Inspect breathers and seals for water or dust ingress"
            ]
        })
    else:
        hypotheses.append(_insufficient(
            "Lubrication Breakdown / Friction Heating", "Tribological",
            "Needs a temperature tag (bearing or motor) and vibration to compare onset order.",
            "Include bearing temperature and vibration RMS in the export."))

    # ── 9. Process Inefficiency & Filter Clogging ─────────────────────────────
    if has_diff_pressure or (has_flow and (has_current or "_std_power_kw" in df.columns)):
        evidence_points = []
        f = _baseline_vs_recent(df, "_std_flow_rate") if has_flow else None
        if has_diff_pressure:
            dp = _baseline_vs_recent(df, "_std_differential_pressure")
            dp_up = dp["pct"] if dp is not None else 0.0
            if dp is not None and dp_up >= 10.0:
                evidence_points.append(f"Differential pressure up {dp_up:.0f}% ({dp['baseline']:.1f} → {dp['recent']:.1f} kPa)")
            if f is not None and f["pct"] <= -10.0:
                evidence_points.append(f"Flow down {abs(f['pct']):.0f}% as resistance builds")
            if dp_up >= 25.0 and f is not None and f["pct"] <= -10.0:
                strength = "STRONG"
            elif dp_up >= 25.0:
                strength = "MODERATE"
            elif dp_up >= 10.0:
                strength = "WEAK"
            else:
                strength = "INSUFFICIENT"
            limitation = "Filter / exchanger differential pressure measured directly."
        else:
            energy_col = "_std_power_kw" if "_std_power_kw" in df.columns else "_std_current"
            ratio_df = running_rows(df)
            flow = pd.to_numeric(ratio_df["_std_flow_rate"], errors="coerce").clip(lower=0.1)
            ratio_df = ratio_df.assign(_specific_energy=pd.to_numeric(ratio_df[energy_col], errors="coerce") / flow)
            se = _baseline_vs_recent(ratio_df, "_specific_energy")
            se_up = se["pct"] if se is not None else 0.0
            if se_up >= 8.0:
                evidence_points.append(f"Energy per unit flow up {se_up:.0f}% – more effort for less throughput")
            if f is not None and f["pct"] <= -10.0:
                evidence_points.append(f"Flow down {abs(f['pct']):.0f}%")
            strength = "MODERATE" if se_up >= 15.0 else ("WEAK" if se_up >= 8.0 else "INSUFFICIENT")
            limitation = ("No differential-pressure tag: clogging inferred from energy per unit flow "
                          f"({'power' if energy_col == '_std_power_kw' else 'current'} ÷ flow), which also rises with cavitation or valve wear.")

        hypotheses.append({
            "hypothesis": "Process Inefficiency / Filter Clogging",
            "category": "Process",
            "confidence": strength,
            "applicable": strength in ["STRONG", "MODERATE", "WEAK"],
            "supporting_evidence": evidence_points if evidence_points else ["Throughput efficiency steady"],
            "alternative_explanations": [
                "Pump cavitation or compressor valve leakage also lower delivered flow per kW",
                "Intentional throttling / set-point change by operations",
                "Heat-exchanger fouling rather than a strainer or filter"
            ],
            "data_limitations": limitation,
            "recommended_actions": [
                "Inspect and clean suction strainers, inline filters or exchanger tube bundles",
                "Compare differential-pressure gauge readings against the clean-filter baseline",
                "Review recent set-point or valve-position changes with operations"
            ]
        })
    else:
        hypotheses.append(_insufficient(
            "Process Inefficiency / Filter Clogging", "Process",
            "Needs a differential-pressure tag, or flow together with current / power.",
            "Include filter differential pressure, or flow rate and motor current, in the export."))

    return hypotheses
