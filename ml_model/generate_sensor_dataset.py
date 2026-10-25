"""
PREDICTA – Sensor Dataset Generator
Generates a realistic synthetic sensor dataset representing all 8 machine health states.
This is used to train high-fidelity ML models for predictive maintenance.
"""

import os
import random
import numpy as np
import pandas as pd

# Define output path
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "sensor_training_data.csv")

def generate_dataset(num_samples=1000):
    print(f"Generating synthetic sensor dataset with {num_samples} samples per class...")
    
    data = []
    
    # Define classes (matches FAULT_LABELS in prediction.py)
    # 0: Normal Operation
    # 1: Bearing Failure
    # 2: Motor Overheating
    # 3: Overcurrent / Overload
    # 4: Rotor Imbalance / Vibration
    # 5: Cooling System Failure
    # 6: Power Supply Anomaly
    # 7: Winding Fault
    
    classes = [0, 1, 2, 3, 4, 5, 6, 7]
    
    for cls in classes:
        for _ in range(num_samples):
            # Base ambient & environmental conditions
            ambient_temp = random.uniform(22.0, 38.0)
            humidity = random.uniform(35.0, 75.0)
            pressure = random.uniform(180.0, 320.0)
            power_factor = random.uniform(0.81, 0.88)
            
            # Nominal base values
            voltage = random.uniform(410.0, 420.0)
            current = random.uniform(2.8, 3.4)
            motor_temp = ambient_temp + random.uniform(10.0, 20.0)
            bearing_temp = ambient_temp + random.uniform(8.0, 15.0)
            vibration_rms = random.uniform(0.06, 0.18)
            rpm = random.uniform(1430.0, 1460.0)
            
            # Apply class-specific perturbations
            if cls == 0:
                # Normal Operation
                pass
            elif cls == 1:
                # Bearing Failure: High vibration, high bearing temp
                vibration_rms = random.uniform(0.65, 1.25)
                bearing_temp = ambient_temp + random.uniform(32.0, 48.0)
                motor_temp += random.uniform(3.0, 8.0)
            elif cls == 2:
                # Motor Overheating: Very high motor temp, normal load
                motor_temp = ambient_temp + random.uniform(48.0, 62.0)
                bearing_temp += random.uniform(8.0, 15.0)
            elif cls == 3:
                # Overcurrent / Overload: High current, lower RPM, slight temperature rise
                current = random.uniform(4.6, 5.8)
                rpm = random.uniform(1150.0, 1320.0)
                motor_temp += random.uniform(12.0, 25.0)
                power_factor = random.uniform(0.86, 0.94)
            elif cls == 4:
                # Rotor Imbalance / Vibration: High vibration RMS only
                vibration_rms = random.uniform(0.95, 1.85)
            elif cls == 5:
                # Cooling System Failure: Moderately high motor temp, normal current
                motor_temp = ambient_temp + random.uniform(40.0, 52.0)
            elif cls == 6:
                # Power Supply Anomaly: Undervoltage (<380) or Overvoltage (>440)
                if random.choice([True, False]):
                    voltage = random.uniform(340.0, 375.0)
                    current += random.uniform(0.4, 1.0)  # voltage drop causes current rise for same load
                else:
                    voltage = random.uniform(445.0, 475.0)
            elif cls == 7:
                # Winding Fault: Moderate current rise, unbalanced/low RPM, low power factor
                current = random.uniform(4.2, 5.2)
                rpm = random.uniform(1200.0, 1350.0)
                power_factor = random.uniform(0.65, 0.76)
                motor_temp += random.uniform(15.0, 30.0)
            
            # Calculate derived features matching preprocess.py
            current_ratio = current / 3.5
            temp_rise = motor_temp - ambient_temp
            bearing_rise = bearing_temp - ambient_temp
            rpm_slip = abs(1500 - rpm) / 1500 * 100
            power_kw = (voltage * current * power_factor * 1.732) / 1000
            
            if vibration_rms < 0.3:
                vib_cat = 0
            elif vibration_rms < 0.7:
                vib_cat = 1
            else:
                vib_cat = 2
                
            data.append({
                "voltage": round(voltage, 2),
                "current": round(current, 2),
                "motor_temp": round(motor_temp, 2),
                "bearing_temp": round(bearing_temp, 2),
                "vibration_rms": round(vibration_rms, 3),
                "rpm": round(rpm, 1),
                "pressure": round(pressure, 2),
                "power_factor": round(power_factor, 3),
                "humidity": round(humidity, 2),
                "ambient_temp": round(ambient_temp, 2),
                "current_ratio": round(current_ratio, 3),
                "temp_rise": round(temp_rise, 2),
                "bearing_rise": round(bearing_rise, 2),
                "rpm_slip": round(rpm_slip, 3),
                "power_kw": round(power_kw, 4),
                "vib_cat": vib_cat,
                "label": cls
            })
            
    df = pd.DataFrame(data)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Successfully saved {len(df)} generated samples to {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_dataset(1000)
