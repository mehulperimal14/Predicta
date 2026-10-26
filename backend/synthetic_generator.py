"""
PREDICTA 2.0 – Industrial Synthetic Data Generator
Generates realistic multi-asset PLC/SCADA time-series datasets representing:
1. Electric Induction Motor (Thermal & Electrical Overload)
2. Centrifugal Water Pump (Cavitation & Pressure Instability)
3. Conveyor Helical Gearbox (Mechanical Wear & Vibration Elevation)
4. Industrial Air Compressor (Discharge Overheating & Valve Leakage)

Includes:
- Realistic operating state transitions (Running, Idle, Startup, Shutdown)
- Sensor noise, periodic load shifts, and ambient fluctuations
- Documented injected degradation periods with ground-truth failure labels
- Clearly marked synthetic disclaimer metadata
"""

import os
import math
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), "sample_data")


def generate_motor_dataset(
    asset_id: str = "MOTOR-IND-101",
    num_hours: int = 48,
    interval_seconds: int = 60,
    inject_fault: bool = True
) -> pd.DataFrame:
    """Simulates a 3-Phase Induction Motor with thermal breakdown and overcurrent."""
    num_samples = int((num_hours * 3600) / interval_seconds)
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=num_hours)
    
    rows = []
    cum_energy = 0.0
    run_hours = 1240.0
    
    for i in range(num_samples):
        ts = base_time + timedelta(seconds=i * interval_seconds)
        t_sec = i * interval_seconds
        
        # Diurnal ambient temperature variation (22°C to 34°C)
        ambient = 28.0 + 6.0 * math.sin(2 * math.pi * (t_sec % 86400) / 86400) + random.gauss(0, 0.4)
        
        # Periodic production shift load cycle (6-hour cycles)
        load_cycle = 0.75 + 0.20 * math.sin(2 * math.pi * t_sec / 21600)
        
        # Planned shutdown every 24 hours for 30 minutes
        is_planned_stop = (t_sec % 86400) < 1800
        
        if is_planned_stop:
            running = 0
            voltage = 415.0 + random.gauss(0, 1.0)
            current = 0.0
            rpm = 0
            motor_temp = max(ambient, 45.0 - (t_sec % 1800) * 0.01)
            bearing_temp = max(ambient, 40.0 - (t_sec % 1800) * 0.01)
            vibration = 0.02 + abs(random.gauss(0, 0.01))
            power_kw = 0.0
            is_failure = 0
        else:
            running = 1
            run_hours += (interval_seconds / 3600.0)
            voltage = 415.0 + 8.0 * math.sin(0.005 * t_sec) + random.gauss(0, 1.2)
            current = 3.2 * load_cycle + random.gauss(0, 0.08)
            rpm = int(1445 - 25 * load_cycle + random.gauss(0, 3))
            
            # Base temperatures
            motor_temp = ambient + 25.0 * load_cycle + random.gauss(0, 0.3)
            bearing_temp = ambient + 18.0 * load_cycle + random.gauss(0, 0.2)
            vibration = 0.12 + 0.08 * load_cycle + abs(random.gauss(0, 0.02))
            power_kw = (voltage * current * 0.85 * 1.732) / 1000.0
            cum_energy += power_kw * (interval_seconds / 3600.0)
            is_failure = 0

            # ── Fault Injection: Thermal Runaway in final 12 hours ─────────────
            if inject_fault and i >= int(num_samples * 0.75):
                progress = (i - int(num_samples * 0.75)) / (num_samples * 0.25)
                # Degrading cooling fan + winding breakdown
                motor_temp += 32.0 * progress
                bearing_temp += 18.0 * progress
                current += 1.8 * progress  # Current rises to ~5.2A (overload)
                vibration += 0.4 * progress
                if progress > 0.6:
                    is_failure = 1

        # Occasional random sensor jitter
        if random.random() < 0.002:
            current = None  # Missing packet
            
        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "asset_id": asset_id,
            "motor_running": running,
            "voltage": round(voltage, 1) if voltage is not None else None,
            "current": round(current, 2) if current is not None else None,
            "motor_temp": round(motor_temp, 1),
            "bearing_temp": round(bearing_temp, 1),
            "ambient_temp": round(ambient, 1),
            "vibration_rms": round(vibration, 3),
            "rpm": rpm,
            "power_kw": round(power_kw, 2),
            "run_hours": round(run_hours, 1),
            "failure_label": is_failure
        })
        
    return pd.DataFrame(rows)


def generate_pump_dataset(
    asset_id: str = "PUMP-CENT-201",
    num_hours: int = 48,
    interval_seconds: int = 60,
    inject_fault: bool = True
) -> pd.DataFrame:
    """Simulates a Centrifugal Water Pump with suction cavitation and pressure collapse."""
    num_samples = int((num_hours * 3600) / interval_seconds)
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=num_hours)
    
    rows = []
    for i in range(num_samples):
        ts = base_time + timedelta(seconds=i * interval_seconds)
        t_sec = i * interval_seconds
        
        running = 1
        current = 4.1 + 0.3 * math.sin(0.002 * t_sec) + random.gauss(0, 0.05)
        rpm = 1450 + int(random.gauss(0, 4))
        pressure = 280.0 + 15.0 * math.sin(0.004 * t_sec) + random.gauss(0, 3.0)
        flow_rate = 45.0 + 4.0 * math.sin(0.004 * t_sec) + random.gauss(0, 0.8)
        motor_temp = 52.0 + random.gauss(0, 0.4)
        vibration = 0.18 + abs(random.gauss(0, 0.02))
        is_failure = 0
        
        # ── Fault Injection: Cavitation & Pressure Drop in last 10 hours ───────
        if inject_fault and i >= int(num_samples * 0.80):
            progress = (i - int(num_samples * 0.80)) / (num_samples * 0.20)
            # Pressure drops, volatility skyrockets, vibration increases
            pressure = max(40.0, pressure - 160.0 * progress + random.gauss(0, 25.0 * progress))
            flow_rate = max(5.0, flow_rate - 28.0 * progress + random.gauss(0, 4.0 * progress))
            vibration += 0.75 * progress  # Cavitation induced mechanical shock
            if progress > 0.5:
                is_failure = 1

        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "asset_id": asset_id,
            "motor_running": running,
            "current": round(current, 2),
            "motor_temp": round(motor_temp, 1),
            "pressure": round(pressure, 1),
            "flow_rate": round(flow_rate, 1),
            "vibration_rms": round(vibration, 3),
            "rpm": rpm,
            "failure_label": is_failure
        })
        
    return pd.DataFrame(rows)


def generate_gearbox_dataset(
    asset_id: str = "GBOX-CONV-301",
    num_hours: int = 48,
    interval_seconds: int = 60,
    inject_fault: bool = True
) -> pd.DataFrame:
    """Simulates a Conveyor Helical Gearbox with lubrication degradation & bearing wear."""
    num_samples = int((num_hours * 3600) / interval_seconds)
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=num_hours)
    
    rows = []
    for i in range(num_samples):
        ts = base_time + timedelta(seconds=i * interval_seconds)
        t_sec = i * interval_seconds
        
        vibration = 0.15 + 0.04 * math.sin(0.001 * t_sec) + abs(random.gauss(0, 0.015))
        bearing_temp = 48.0 + random.gauss(0, 0.3)
        motor_temp = 54.0 + random.gauss(0, 0.4)
        current = 3.6 + random.gauss(0, 0.06)
        is_failure = 0
        
        # ── Fault: Lubrication breakdown in last 14 hours ─────────────────────
        if inject_fault and i >= int(num_samples * 0.70):
            progress = (i - int(num_samples * 0.70)) / (num_samples * 0.30)
            vibration += 0.85 * progress  # High gear mesh vibration
            bearing_temp += 28.0 * progress  # Sump and bearing friction heat
            current += 0.8 * progress  # Drag increases current
            if progress > 0.55:
                is_failure = 1

        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "asset_id": asset_id,
            "motor_running": 1,
            "current": round(current, 2),
            "motor_temp": round(motor_temp, 1),
            "bearing_temp": round(bearing_temp, 1),
            "vibration_rms": round(vibration, 3),
            "rpm": 1440,
            "failure_label": is_failure
        })
        
    return pd.DataFrame(rows)


def generate_compressor_dataset(
    asset_id: str = "COMP-AIR-401",
    num_hours: int = 48,
    interval_seconds: int = 60,
    inject_fault: bool = True
) -> pd.DataFrame:
    """Simulates an Industrial Air Compressor with discharge overheating & valve leakage."""
    num_samples = int((num_hours * 3600) / interval_seconds)
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=num_hours)
    
    rows = []
    for i in range(num_samples):
        ts = base_time + timedelta(seconds=i * interval_seconds)
        t_sec = i * interval_seconds
        
        pressure = 480.0 + 20.0 * math.sin(0.003 * t_sec) + random.gauss(0, 4.0)
        discharge_temp = 68.0 + random.gauss(0, 0.5)
        current = 5.2 + random.gauss(0, 0.08)
        flow_rate = 85.0 + random.gauss(0, 1.2)
        is_failure = 0
        
        # ── Fault: Valve Leakage & Overheating in last 12 hours ────────────────
        if inject_fault and i >= int(num_samples * 0.75):
            progress = (i - int(num_samples * 0.75)) / (num_samples * 0.25)
            discharge_temp += 34.0 * progress  # Temp reaches > 100°C
            pressure -= 90.0 * progress  # Cannot maintain line pressure
            flow_rate -= 30.0 * progress
            current += 1.2 * progress  # High load trying to pressurize
            if progress > 0.5:
                is_failure = 1

        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "asset_id": asset_id,
            "motor_running": 1,
            "current": round(current, 2),
            "motor_temp": round(discharge_temp, 1),  # Discharge air temp mapped to motor_temp
            "pressure": round(pressure, 1),
            "flow_rate": round(flow_rate, 1),
            "vibration_rms": round(0.20 + 0.15 * (i >= int(num_samples * 0.75)), 3),
            "failure_label": is_failure
        })
        
    return pd.DataFrame(rows)


def pregenerate_all_sample_files():
    """Generates and writes CSV and Excel demo files to backend/sample_data/."""
    os.makedirs(SAMPLE_DATA_DIR, exist_ok=True)
    
    files = {
        "motor_cooling_failure.csv": generate_motor_dataset(num_hours=24),
        "pump_cavitation_anomaly.csv": generate_pump_dataset(num_hours=24),
        "gearbox_vibration_wear.csv": generate_gearbox_dataset(num_hours=24),
        "compressor_valve_degradation.xlsx": generate_compressor_dataset(num_hours=24)
    }
    
    for filename, df in files.items():
        filepath = os.path.join(SAMPLE_DATA_DIR, filename)
        if filename.endswith(".csv"):
            df.to_csv(filepath, index=False)
        elif filename.endswith(".xlsx"):
            df.to_excel(filepath, index=False)
            
    print(f"[SYNTHETIC] 4 demonstration industrial datasets created in {SAMPLE_DATA_DIR}")


if __name__ == "__main__":
    pregenerate_all_sample_files()
