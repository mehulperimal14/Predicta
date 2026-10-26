"""
PREDICTA – Segment B Live Device Simulator
Streams realistic ESP32-style readings to /api/live/ingest so the live monitoring
page can be demonstrated without hardware.

Each scenario runs: healthy baseline → slow degradation (the trend forecast should
show a finite "time to critical limit") → critical → maintenance reset → repeat.

Usage:
  python simulator.py                                   # local dev server (127.0.0.1 avoids a 2 s IPv6
                                                        # fallback per request on Windows), demo admin login
  python simulator.py --url https://your-app.onrender.com --username admin --password '...'
  python simulator.py --device-key pdk_xxx              # use a key issued in the Live Monitor page

Without --device-key the simulator logs in (admin / engineer) and registers the
device itself, rotating its key if the device already exists.
"""

import argparse
import math
import os
import random
import time

import requests

INTERVAL_SEC = 2

# (phase length in cycles, phase name) – one cycle every INTERVAL_SEC seconds
SCENARIOS = [
    ("bearing_lubrication", [(120, "healthy"), (300, "degrading"), (45, "critical"), (15, "maintenance")]),
    ("cooling_fan_blockage", [(120, "healthy"), (300, "degrading"), (45, "critical"), (15, "maintenance")]),
    ("overload_binding", [(120, "healthy"), (240, "degrading"), (45, "critical"), (15, "maintenance")]),
]


def scenario_state(cycle: int):
    """Returns (scenario name, phase name, progress 0..1 through the phase)."""
    total = sum(sum(n for n, _ in phases) for _, phases in SCENARIOS)
    c = cycle % total
    for name, phases in SCENARIOS:
        for length, phase in phases:
            if c < length:
                return name, phase, c / length
            c -= length
    return SCENARIOS[0][0], "healthy", 0.0


def simulate(cycle: int, device_id: str) -> dict:
    """Generate one realistic sensor reading."""
    t = cycle * INTERVAL_SEC
    scenario, phase, p = scenario_state(cycle)

    load = 0.75 + 0.15 * math.sin(t * 0.01)
    voltage = 413 + 6 * math.sin(t * 0.007) + random.gauss(0, 0.6)
    current = 3.1 * load + random.gauss(0, 0.04)
    ambient = 31 + 2 * math.sin(t * 0.001)
    motor_temp = ambient + 22 * load + random.gauss(0, 0.25)
    bearing_temp = ambient + 15 * load + random.gauss(0, 0.2)
    vibration = 0.11 + 0.05 * load + abs(random.gauss(0, 0.012))
    rpm = 1440 * (0.975 + 0.015 * load) + random.gauss(0, 2)
    pressure = 290 + 50 * load + random.gauss(0, 4)

    # Severity ramps 0 → 1 through "degrading" and stays high through "critical"
    severity = {"healthy": 0.0, "degrading": p, "critical": 1.0 + 0.3 * p, "maintenance": 0.0}[phase]

    if scenario == "bearing_lubrication":
        bearing_temp += 24 * severity                     # friction heat first…
        vibration += 0.75 * max(0.0, severity - 0.3)      # …vibration follows
        current += 0.3 * severity
    elif scenario == "cooling_fan_blockage":
        motor_temp += 30 * severity                        # heat with steady current
        bearing_temp += 6 * severity
    elif scenario == "overload_binding":
        current += 1.9 * severity
        motor_temp += 14 * severity
        rpm -= 25 * severity
        vibration += 0.2 * severity

    power_kw = voltage * current * 0.85 * 1.732 / 1000
    return {
        "device_id": device_id,
        "voltage": round(voltage, 1),
        "current": round(current, 2),
        "motor_temp": round(motor_temp, 1),
        "bearing_temp": round(bearing_temp, 1),
        "ambient_temp": round(ambient, 1),
        "humidity": round(62 + 5 * math.sin(t * 0.003), 1),
        "vibration_rms": round(vibration, 3),
        "rpm": int(rpm),
        "pressure": round(pressure, 1),
        "power_kw": round(power_kw, 3),
        "run_hours": round(t / 3600, 3),
        "motor_running": True,
        "_phase": f"{scenario}/{phase}",
    }


def obtain_key(base_url: str, device_id: str, username: str, password: str) -> str:
    login = requests.post(f"{base_url}/api/auth/login", json={"username": username, "password": password}, timeout=10)
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    res = requests.post(f"{base_url}/api/live/devices", headers=headers, timeout=10, json={
        "device_id": device_id, "name": "Simulated Pump Motor", "location": "Simulator",
        "machine_type": "induction_motor",
    })
    if res.status_code == 409:
        res = requests.post(f"{base_url}/api/live/devices/{device_id}/rotate-key", headers=headers, timeout=10)
    res.raise_for_status()
    return res.json()["device_key"]


def main():
    parser = argparse.ArgumentParser(description="Predicta live device simulator (Segment B)")
    parser.add_argument("--url", default=os.getenv("PREDICTA_URL", "http://127.0.0.1:5000"))
    parser.add_argument("--device-id", default=os.getenv("PREDICTA_DEVICE_ID", "SIM_MOTOR_01"))
    parser.add_argument("--device-key", default=os.getenv("PREDICTA_DEVICE_KEY"))
    parser.add_argument("--username", default=os.getenv("PREDICTA_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("PREDICTA_PASSWORD", "Predicta@2024"))
    args = parser.parse_args()
    base_url = args.url.rstrip("/")

    print("=" * 60)
    print("  PREDICTA - Live Device Simulator (Segment B)")
    print(f"  Backend: {base_url}")
    print(f"  Device:  {args.device_id}   Interval: {INTERVAL_SEC}s")
    print("=" * 60)

    key = args.device_key
    while not key:
        try:
            key = obtain_key(base_url, args.device_id, args.username, args.password)
            print(f"  Registered device; key {key[:10]}... (use --device-key to reuse it)")
        except requests.RequestException as e:
            print(f"  Waiting for backend / login ({e}) - retrying in 3s")
            time.sleep(3)

    headers = {"X-Device-Key": key}
    cycle = 0
    while True:
        reading = simulate(cycle, args.device_id)
        phase = reading.pop("_phase")
        try:
            resp = requests.post(f"{base_url}/api/live/ingest", json=reading, headers=headers, timeout=10)
            if resp.status_code == 201:
                body = resp.json()
                status = (body.get("assessment") or {}).get("status", "")
                print(f"  [{cycle:04d}] {phase:<32} T={reading['motor_temp']:>5}C "
                      f"Tb={reading['bearing_temp']:>5}C I={reading['current']:>4}A "
                      f"Vib={reading['vibration_rms']:.3f}g Health={body.get('health_score')} {status}")
            else:
                print(f"  [{cycle:04d}] Error {resp.status_code}: {resp.text[:100]}")
        except requests.RequestException as e:
            print(f"  [{cycle:04d}] Backend not reachable ({e}) - retrying")
        cycle += 1
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
