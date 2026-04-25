"""
PREDICTA – Data Simulator
Auto-generates realistic sensor readings to demo the dashboard
without real hardware connected.

Run alongside the backend:  python simulator.py
"""

import time
import math
import random
import requests
from datetime import datetime

BASE_URL = "http://localhost:5000/api/sensor/ingest"
DEVICE_ID = "MOTOR_01"
INTERVAL_SEC = 2   # Publish every 2 seconds

# ── Fault injection schedule (for demo purposes) ──────────────────────────────
# Format: (start_cycle, end_cycle, fault_type)
FAULT_SCHEDULE = [
    (50,  70,  "bearing_heat"),   # bearing temp rises
    (120, 135, "overload"),        # current spike
    (200, 215, "vibration"),       # high vibration
]

def simulate(cycle: int) -> dict:
    """Generate one realistic sensor reading."""
    t = cycle * INTERVAL_SEC

    # Base values with sinusoidal variation (simulates load changes)
    load_factor = 0.75 + 0.2 * math.sin(t * 0.02)

    voltage = 411 + 8 * math.sin(t * 0.007) + random.gauss(0, 0.5)
    current = 3.2 * load_factor + random.gauss(0, 0.05)
    motor_temp   = 45 + 15 * load_factor + 0.01 * t + random.gauss(0, 0.3)
    bearing_temp = 42 + 10 * load_factor + random.gauss(0, 0.2)
    vibration    = 0.12 + 0.06 * load_factor + abs(random.gauss(0, 0.02))
    rpm          = int(1440 * (0.97 + 0.02 * load_factor) + random.gauss(0, 3))
    pressure     = 280 + 60 * load_factor + random.gauss(0, 5)
    humidity     = 62 + 5 * math.sin(t * 0.003)
    ambient_temp = 32 + 2 * math.sin(t * 0.001)
    power_kw     = (voltage * current * 0.85 * 1.732) / 1000
    energy_kwh   = cycle * power_kw * INTERVAL_SEC / 3600

    # ── Fault Injection ──────────────────────────────────────────────────────
    for (start, end, fault) in FAULT_SCHEDULE:
        if start <= cycle <= end:
            progress = (cycle - start) / (end - start)
            if fault == "bearing_heat":
                bearing_temp += 30 * progress   # Bearing temp rises to ~72°C
                motor_temp   += 10 * progress
            elif fault == "overload":
                current  += 2.0 * progress       # Current rises to ~5.2A
                vibration += 0.2 * progress
            elif fault == "vibration":
                vibration += 0.7 * progress      # Vibration rises to ~0.82g
                bearing_temp += 15 * progress

    overload       = current > 4.5
    overheat       = motor_temp > 75
    high_vibration = vibration > 0.5

    return {
        "device_id":    DEVICE_ID,
        "voltage":      round(voltage, 1),
        "current":      round(current, 2),
        "motor_temp":   round(motor_temp, 1),
        "bearing_temp": round(bearing_temp, 1),
        "ambient_temp": round(ambient_temp, 1),
        "humidity":     round(humidity, 1),
        "vibration_rms":round(vibration, 3),
        "rpm":          rpm,
        "pressure":     round(pressure, 1),
        "power_kw":     round(power_kw, 3),
        "energy_kwh":   round(energy_kwh, 4),
        "run_hours":    round(cycle * INTERVAL_SEC / 3600, 3),
        "start_cycles": 1,
        "motor_running":True,
        "overload":     overload,
        "overheat":     overheat,
        "high_vibration": high_vibration,
        "low_rpm":      rpm < 1200,
    }


def main():
    print("=" * 55)
    print("  PREDICTA – Data Simulator")
    print(f"  Sending to: {BASE_URL}")
    print(f"  Device:     {DEVICE_ID}")
    print(f"  Interval:   {INTERVAL_SEC}s")
    print("=" * 55)
    print("  Waiting for backend to start…")
    time.sleep(3)

    cycle = 0
    while True:
        data = simulate(cycle)
        try:
            resp = requests.post(BASE_URL, json=data, timeout=5)
            if resp.status_code == 201:
                result = resp.json()
                health = result.get("health_score", "?")
                pred   = result.get("prediction")
                fault  = pred.get("fault_type", "—") if pred else "—"
                status = "⚠" if data["overload"] or data["overheat"] or data["high_vibration"] else "✓"
                print(f"  [{cycle:04d}] {status} V={data['voltage']}V I={data['current']}A "
                      f"T={data['motor_temp']}°C Vib={data['vibration_rms']}g "
                      f"RPM={data['rpm']} Health={health}% | {fault}")
            else:
                print(f"  [{cycle:04d}] Error: {resp.status_code} {resp.text[:80]}")
        except requests.ConnectionError:
            print(f"  [{cycle:04d}] Backend not reachable — retrying…")
        except Exception as e:
            print(f"  [{cycle:04d}] {e}")

        cycle += 1
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
