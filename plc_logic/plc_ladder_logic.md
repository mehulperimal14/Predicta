# PREDICTA – PLC Ladder Logic Documentation
## Delta DVP-ES2 / Siemens S7-1200 Implementation

---

## I/O MAPPING

### Digital Inputs (DI)
| PLC Input | Terminal | Signal | Description |
|-----------|----------|--------|-------------|
| X0 | DI0 | Start Button (NO) | Green pushbutton – start motor |
| X1 | DI1 | Stop Button (NC) | Red pushbutton – stop motor |
| X2 | DI2 | Emergency Stop (NC) | Mushroom head E-Stop |
| X3 | DI3 | Overload Relay (NC) | Thermal overload trip contact |
| X4 | DI4 | Remote Start (from SCADA) | Digital output from Node-RED |
| X5 | DI5 | Remote Stop (from SCADA) | Digital output from Node-RED |
| X6 | DI6 | Fault Reset Button | Manual fault reset |
| X7 | DI7 | Local/Remote Selector | Position = Local; 1 = Remote |

### Digital Outputs (DO)
| PLC Output | Terminal | Load | Description |
|------------|----------|------|-------------|
| Y0 | DO0 | Contactor Coil (KM1) | Main motor contactor |
| Y1 | DO1 | Green Lamp (H1) | Motor Running indicator |
| Y2 | DO2 | Red Lamp (H2) | Fault indicator |
| Y3 | DO3 | Yellow Lamp (H3) | Ready/Standby indicator |
| Y4 | DO4 | Alarm Buzzer | Audible alarm |
| Y5 | DO5 | SCADA Fault Signal | To Node-RED digital input |
| Y6 | DO6 | ESP32 Alarm Relay | Triggers ESP32 relay for logging |

### Modbus Registers (read from ESP32 via RS485)
| Register | Parameter | Scaling |
|----------|-----------|---------|
| 40001 | Voltage (V) | × 0.1 |
| 40002 | Current (A) | × 0.01 |
| 40003 | Motor Temperature (°C) | × 0.1 |
| 40004 | Bearing Temperature (°C) | × 0.1 |
| 40005 | Vibration RMS (g) | × 0.001 |
| 40006 | RPM | × 1 |
| 40007 | Power (kW) | × 0.01 |
| 40008 | Pressure (kPa) | × 0.1 |

---

## LADDER LOGIC RUNGS (Pseudocode + Description)

---

### RUNG 1 – Emergency Stop Master Latch
```
[X2]─────────────────────────────────────────────────[SET M_ESTOP]
 |NC                                                         |
[X6]─────────────────────────────────────────────────[RST M_ESTOP]
```
**Logic:** E-Stop button (NC) opens → sets internal coil M_ESTOP.
Fault Reset button (X6) held 3 seconds → resets M_ESTOP.

---

### RUNG 2 – Overload Relay Fault Latch
```
[X3_NC]──────────────────────────────────────────────[SET M_OL_FAULT]
 │
[X6]─────────────────────────────────────────────────[RST M_OL_FAULT]
```
**Logic:** Overload relay trips (NC contact opens) → latches M_OL_FAULT.
Resets only after manual reset.

---

### RUNG 3 – Temperature Fault (from Modbus register)
```
[D_MOTOR_TEMP > 850]──────────────────────────────────[SET M_TEMP_FAULT]
     (40003 × 0.1 > 85°C)
[D_MOTOR_TEMP < 700 AND X6]───────────────────────────[RST M_TEMP_FAULT]
```
**Logic:** If motor temperature exceeds 85°C, set temperature fault.
Auto-reset when temp drops below 70°C and operator presses reset.

---

### RUNG 4 – Overcurrent Fault (from Modbus register)
```
[D_CURRENT > 450]─────────────────────────────────────[SET M_OC_FAULT]
    (40002 × 0.01 > 4.5A)
[D_CURRENT < 400 AND X6]──────────────────────────────[RST M_OC_FAULT]
```
**Logic:** Current > 4.5A (130% FLC) for 3 seconds → overcurrent fault.
Use Timer T1 (3-second delay) to avoid nuisance tripping on startup inrush.

---

### RUNG 5 – Vibration Fault (from Modbus register)
```
[D_VIBRATION > 500]───────────────────────────────────[SET M_VIB_FAULT]
    (40005 × 0.001 > 0.5g)
[D_VIBRATION < 400 AND X6]────────────────────────────[RST M_VIB_FAULT]
```
**Logic:** Vibration RMS > 0.5g for 5 seconds → vibration fault.

---

### RUNG 6 – Fault Summary Coil
```
[M_ESTOP + M_OL_FAULT + M_TEMP_FAULT + M_OC_FAULT + M_VIB_FAULT]──[M_FAULT]
```
**Logic:** OR of all fault conditions → master fault coil M_FAULT.

---

### RUNG 7 – Start/Stop Motor (Self-Holding Circuit)
```
LOCAL MODE (X7 = 0):
[X0 OR X4_REMOTE] AND [NOT M_FAULT] AND [NOT M_ESTOP]
    ──┬──────────────────────────────────────────[Y0 = SET (Contactor ON)]
      │
[Y0_feedback]────────────────────────────────────[HOLD latch]
      │
[X1_NC AND X5_REMOTE_STOP]───────────────────────[Y0 = RESET (Contactor OFF)]

REMOTE MODE (X7 = 1):
X4 = Remote Start, X5 = Remote Stop from SCADA
```
**Logic:** Standard industrial 3-wire start/stop with self-holding contact.
E-Stop and any fault break the holding circuit immediately.

---

### RUNG 8 – Startup Timer (Anti-Inrush Current Delay)
```
[Y0 Rising Edge]──[T1 Timer 5s]──[M_STARTUP]
```
**Logic:** During first 5 seconds after motor start, M_STARTUP = TRUE.
Overcurrent protection threshold raised to 8A during startup (motor inrush ~6× FLC).

---

### RUNG 9 – Motor Running Indicator
```
[Y0 AND NOT M_FAULT]──────────────────────────────────[Y1 Green Lamp]
```

---

### RUNG 10 – Fault Indicator + Buzzer
```
[M_FAULT OR M_ESTOP]──────────────────────────────────[Y2 Red Lamp]
                   └─────────────[T_BUZZER Flashing 1Hz]──[Y4 Buzzer]
```

---

### RUNG 11 – Ready Indicator (No fault, Motor stopped)
```
[NOT Y0 AND NOT M_FAULT]──────────────────────────────[Y3 Yellow Lamp]
```

---

### RUNG 12 – SCADA Fault Output
```
[M_FAULT]─────────────────────────────────────────────[Y5 SCADA Signal]
```

---

### RUNG 13 – Fault Code Register
```
M_OL_FAULT     → D_FAULT_CODE = 1 (Overload)
M_TEMP_FAULT   → D_FAULT_CODE = 2 (Overtemperature)
M_OC_FAULT     → D_FAULT_CODE = 3 (Overcurrent)
M_VIB_FAULT    → D_FAULT_CODE = 4 (Vibration)
M_ESTOP        → D_FAULT_CODE = 5 (Emergency Stop)
NO FAULT       → D_FAULT_CODE = 0
```
Stored in D_FAULT_CODE register, readable via Modbus TCP by SCADA.

---

### RUNG 14 – Runtime Hour Counter
```
[Y0]──[T_RUN_MS 1000ms]──[C_RUN_SEC counter]
C_RUN_SEC / 3600 → D_RUN_HOURS (stored in data register)
```

---

### RUNG 15 – Start/Stop Cycle Counter
```
[Y0 Rising Edge]──[C_STARTS + 1]
[Y0 Falling Edge]──[C_STOPS + 1]
```
Cycle count stored in D_CYCLES register.

---

## INTERLOCKING LOGIC

1. **Motor cannot start** if any fault is active
2. **Motor cannot start** if E-Stop is activated
3. **Overload relay** must be reset manually before restart
4. **Temperature fault** requires temperature to drop AND manual reset
5. **Remote/Local** selection prevents double actuation
6. **Fault reset** only works when motor is stopped (Y0 = OFF)

---

## MODBUS TCP REGISTER MAP (for SCADA via DVP-EN01 module)

| Address | Register | R/W | Description |
|---------|----------|-----|-------------|
| 40001 | Y_STATUS | R | Digital output word (Y0-Y7) |
| 40002 | X_STATUS | R | Digital input word (X0-X7) |
| 40003 | D_FAULT_CODE | R | Current fault code (0-5) |
| 40004 | D_RUN_HOURS | R | Runtime hours (low word) |
| 40005 | D_CYCLES | R | Start/Stop cycle count |
| 40010 | D_REMOTE_CMD | R/W | 1=Remote Start, 2=Remote Stop, 3=Fault Reset |
| 40020 | D_TEMP_SP | R/W | Temperature setpoint (default 850 = 85°C) |
| 40021 | D_CURR_SP | R/W | Overcurrent setpoint (default 450 = 4.5A) |

---

## SAFETY COMPLIANCE NOTES

- E-Stop follows IEC 60204-1 Safety of Machinery standard
- Motor protection follows IEC 60947-4-1 (Contactors and motor-starters)
- Ladder logic follows IEC 61131-3 (Programmable controllers standard)
- Thermal overload relay provides Class 10 protection curve
- All interlocks are hardware-backed (not software only)
- Dual-channel E-Stop recommended for PLe/SIL2 applications
