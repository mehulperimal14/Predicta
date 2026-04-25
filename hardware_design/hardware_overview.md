# PREDICTA – Hardware Design Overview

## Target Machine: 3-Phase Induction Motor + Water Pump
- Rating: 1.5 kW / 2 HP, 415V, 3-Phase, 50 Hz, 4-Pole, 1440 RPM
- Protection: IP55 | Insulation Class F

---

## System Block Diagram

```
[3φ Power 415V] → [MCB 10A] → [Contactor LC1-D09] → [Overload Relay LRD-10] → [Motor + Pump]

Sensors on motor/panel:
├── ACS712-30A      → Phase Current (Analog)
├── ZMPT101B        → Line Voltage (Analog)
├── DS18B20 (×2)   → Motor + Bearing Temperature (OneWire)
├── MPU6050         → Vibration 3-axis (I2C)
├── Hall Effect     → RPM (Digital interrupt)
├── DHT22           → Ambient Temp + Humidity
└── MPX5700         → Pump Pressure (Analog)

ESP32 DevKit → MQTT (WiFi) → Node-RED SCADA → Flask Backend → ML Engine → Dashboard
           ↕ RS485/Modbus RTU
Delta DVP-ES2 PLC → Digital I/O → Contactor, Emergency Stop, Alarm Lamp
```

---

## ESP32 Pin Mapping

| GPIO | Sensor | Interface |
|------|--------|-----------|
| 34 | ACS712 Current | ADC Analog |
| 35 | ZMPT101B Voltage | ADC Analog |
| 32 | MPX5700 Pressure | ADC Analog |
| 4  | DS18B20 Motor Temp | OneWire |
| 5  | DS18B20 Bearing Temp | OneWire |
| 21 | MPU6050 SDA | I2C |
| 22 | MPU6050 SCL | I2C |
| 2  | Hall Effect RPM | Digital IRQ |
| 15 | DHT22 | Single-wire |
| 16 | MAX485 RO (RS485) | UART2 |
| 17 | MAX485 DI (RS485) | UART2 |
| 18 | MAX485 DE/RE | GPIO |
| 19 | Relay Alarm Out | GPIO |

---

## Component List & Cost (INR)

| Component | Model | Cost |
|-----------|-------|------|
| ESP32 DevKit V1 | 38-pin | ₹450 |
| Delta PLC | DVP-ES2 (16DI/16DO) | ₹8,500 |
| Current Sensor | ACS712-30A | ₹120 |
| Voltage Sensor | ZMPT101B | ₹150 |
| Temp Sensors | DS18B20 ×2 | ₹160 |
| Vibration | MPU6050 | ₹200 |
| Speed | Hall Effect SS49E | ₹80 |
| Ambient | DHT22 | ₹250 |
| Pressure | MPX5700GP | ₹350 |
| RS485 | MAX485 module | ₹80 |
| Contactor | Schneider LC1-D09 | ₹750 |
| Overload Relay | Schneider LRD-10 | ₹450 |
| MCB | 10A 3-pole Type C | ₹350 |
| Relay Module | 4-channel opto-isolated | ₹150 |
| OLED | SSD1306 0.96" I2C | ₹200 |
| Indicators + Buttons | 3 lamps, 3 buttons | ₹500 |
| Emergency Stop | 40mm mushroom NC | ₹250 |
| Panel + Wiring | DIN rails, terminals | ₹900 |
| **TOTAL** | | **≈₹13,890** |

---

## Why Delta DVP-ES2 PLC?

- Cost-effective (~₹8,500 vs Siemens S7-1200 at ₹25,000+)
- Free programming software (WPLSoft / ISPSoft)
- Built-in RS485 port for Modbus RTU
- Relay outputs suitable for 240V AC contactor control
- Widely used in Indian manufacturing SMEs
- Same IEC 61131-3 ladder logic standard as Siemens/Mitsubishi

---

## Sensor Calibration Formulas

```
Current (ACS712-30A): I = (ADC_V - 1.65) / 0.066     [A]
Voltage (ZMPT101B):   V = ADC_peak / sqrt(2) × 170.5  [V_rms]
Temperature (DS18B20): Direct °C from OneWire protocol
RPM (Hall Effect):    RPM = (pulse_count × 60) / interval_sec
Vibration (MPU6050):  RMS_g = sqrt((ax²+ay²+az²)/3) - 1.0
Power:                P = V × I × pf × sqrt(3)          [kW, 3-phase]
```

---

## Safety Wiring Rules

1. Ground all metal enclosures to Protective Earth (PE)
2. Use shielded cable for analog signals (ACS712, ZMPT101B)
3. Separate power cables from signal cables by ≥30 cm
4. Add ferrite cores on ESP32 supply lines to reduce EMI
5. Place MOV surge arrestors across contactor coil terminals
6. Use 500 mA fast-blow fuse on ESP32 24V supply
7. Label all terminal blocks with wire numbers (IEC 60445)
