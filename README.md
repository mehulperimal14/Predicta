---
title: Predicta 2.0 Industrial Predictive Maintenance
emoji: 🏭
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 5000
pinned: false
---

# PREDICTA 2.0
## Industrial Predictive Maintenance – from SCADA / PLC files and from live IoT sensors

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-blue)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-green)](https://flask.palletsprojects.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)](https://docker.com)
[![Tests](https://img.shields.io/badge/Tests-39%20Passed-brightgreen)](#9-automated-tests)
[![License](https://img.shields.io/badge/License-Proprietary%20%2F%20Industrial-lightgrey)](#)

---

## 1. What Predicta does

Predicta tells maintenance engineers what is happening to a machine (motor, pump, gearbox, compressor) **before it breaks down**. It is split into two segments that share one analytics core:

| | **Segment A – SCADA / PLC File Analysis** | **Segment B – Live IoT Monitoring** |
|---|---|---|
| Data source | Engineers upload what their PLC, SCADA, DCS or historian already recorded (CSV, XLSX, XLS) | ESP32 / microcontrollers stream sensor readings continuously to the cloud |
| Question answered | *What could have caused – or is causing – damage to this machine?* | *Is it healthy now, which way is it trending, and when will it break down if nothing changes?* |
| Output | Risk report, all 9 failure signatures with evidence, change-points, trend forecast, inspection checklist | Live status (HEALTHY / WATCH / DEGRADING / CRITICAL), trend per variable, time-to-breakdown estimate, likely causes |
| Alerts | Suppressed by default (historical replay guard) | Live Telegram / SMS with per-asset cooldown |
| New hardware | None | ESP32 + sensors (see `hardware_design/`) |
| Pages | `upload.html`, `ai_analysis.html` | `live.html`, `analytics.html` |
| API | `/api/ingest/*` | `/api/live/*` |

Predicta is **read-only and advisory**: it never writes to PLCs, actuators or safety interlocks (see [§11](#11-industrial-safety-advisory-notice)).

---

## 2. How each segment works

```
SEGMENT A – file analysis                         SEGMENT B – live monitoring
──────────────────────────                        ───────────────────────────
Upload CSV / XLSX / XLS                           ESP32 reads sensors every 2 s
  │  delimiter, encoding, timestamp, sheet          │  HTTPS POST /api/live/ingest every 10 s
  ▼  0–100 % data-quality score                     ▼  header X-Device-Key (per-device key)
Tag Mapping Studio (plant tag → standard var)     Rolling window of recent readings per device
  │                                                 │
  └──────────────► SHARED ANALYTICS CORE ◄──────────┘
                   • time-series features (rolling stats, EWMA, robust Z, slopes)
                   • CUSUM change-points  → "when did behaviour change?"
                   • Layer 1–5 risk engine
                   • trend forecast       → "time to warning / critical limit"
                   • 9 failure signatures → evidence, alternatives, data limits, checklist
  ┌──────────────────────────┘          └──────────────────────────┐
  ▼                                                                ▼
Investigation report, PDF / CSV export            Live status + forecast, Telegram / SMS alerts
```

Shared core modules: `analytics_engine.py`, `ai_engine.py`, `trend_forecast.py`, `investigation.py`, `notifications.py`.
Segment-specific: `routes/ingestion_routes.py` (A), `live_engine.py` + `routes/live_routes.py` (B).

---

## 3. Layered risk engine

| Layer | Method | Details |
|---|---|---|
| **1** | Engineering limits | Upper **and** lower warning / critical bands (temperature, current, voltage, vibration, pressure, RPM, discharge temperature), evaluated on **running** samples only, so planned stops do not raise low-RPM alarms. Score = max(whole period, most recent 10 %). Robust Z-score deviations are reported as context. |
| **2** | Isolation Forest | Unsupervised anomaly detection on engineered features of running samples, `contamination = 0.03` (env `ISOLATION_FOREST_CONTAMINATION`). Identifiers, timestamps, counters and labels are never used as features. |
| **3** | Random Forest | Only when the data has failure labels: trained on the earlier 75 %, tested on the later 25 % (no future leakage). Reports precision, recall, F1, **PR-AUC**, ROC-AUC. Falls back honestly when labels are missing or the training period has no failures. |
| **4** | Remaining useful life | With labelled run-to-failure history: the current trend is extrapolated to the level at which past failures began. Without it: *"Remaining useful life unavailable: insufficient validated degradation or failure-history data"* – plus the trend forecast to engineering limits, clearly labelled as not a validated RUL. |
| **5** | Composite risk | L1 + L2 (+ L3 when available), raised by trend deterioration (time-to-limit forecast) and PLC alarm frequency, adjusted for poor data quality → **NORMAL / WATCH / WARNING / CRITICAL**. |

**Trend forecast** (`trend_forecast.py`): a linear fit over the most recent running data for each limited variable gives the slope per hour, R², and the hours until the warning and critical limits, with a 95 % interval. It is only reported when the trend is statistically significant, and only up to 5× the fitted window (max 30 days). Beyond that, extrapolation is not credible.

---

## 4. The nine failure signatures

Every analysis (file or live) evaluates all nine and grades each **STRONG / MODERATE / WEAK / INSUFFICIENT**. Evidence that relies on a proxy tag (e.g. motor current instead of torque) is capped at MODERATE.

| # | Signature | Main evidence |
|---|---|---|
| 1 | Bearing wear / mechanical degradation | Vibration RMS and bearing temperature above limits |
| 2 | Motor overload / driven-load binding | Current above 120 % FLC with winding temperature rise |
| 3 | Cooling system degradation | Temperature rising while current stays normal |
| 4 | Pump cavitation / suction starvation | Discharge-pressure drop and volatility, falling flow |
| 5 | Supply voltage instability | Under / over-voltage beyond ±5 % |
| 6 | Compressor valve degradation | Delivery-pressure deficit + discharge-temperature rise + falling flow or rising current |
| 7 | Gearbox tooth wear / imbalance | Vibration step-change (CUSUM) with rising drive torque |
| 8 | Lubrication breakdown | Friction heating **before** the vibration shift (CUSUM onset order) |
| 9 | Process inefficiency / filter clogging | Rising differential pressure, or energy per unit flow |

Each card lists supporting evidence, alternative explanations, data limitations and recommended inspections.

---

## 5. Web interface

| Page | Segment | Purpose |
|---|---|---|
| `index.html` – Overview | both | Recent file analyses and live device fleet side by side |
| `upload.html` – Upload & Map Tags | A | Drag-and-drop upload, sheet selector, quality score, tag mapping, sample datasets |
| `ai_analysis.html` – Root-Cause Investigation | A | Risk gauge, layer results, trend forecast + change-points, 9 hypothesis cards, CSV export |
| `live.html` – Live Monitor | B | Device selector, health verdict, time-to-breakdown, trend table, likely causes, live telemetry, device registration / key rotation |
| `analytics.html` – Health Trends | B | Historical telemetry of the selected device |
| `maintenance.html`, `notifications.html`, `reports.html`, `admin.html` | shared | Work orders, Telegram / SMS settings, PDF + CSV reports, users and thresholds |

---

## 6. Telegram & Twilio SMS alerts

- Telegram Bot API and Twilio SMS; tokens are stored server-side and masked in the UI.
- **Mock mode** (`NOTIFICATION_MOCK_MODE=True`, default) logs alerts without sending them.
- **Per-asset cooldown** (`NOTIFICATION_COOLDOWN_MINUTES`, default 15).
- **Historical replay guard**: uploaded files never page staff unless `ALLOW_HISTORICAL_REPLAY=true` or the analysis is explicitly run with notifications. Live devices (Segment B) alert in real time when they become DEGRADING or CRITICAL.

---

## 7. Synthetic demonstration data

All sample data is **simulated** and labelled as such.

**Segment A** (`backend/sample_data/`, regenerated by `python backend/synthetic_generator.py`):

| File | Machine & injected fault |
|---|---|
| `motor_cooling_failure.csv` | Induction motor: an earlier repaired failure, then thermal runaway with overload in the last 25 % |
| `pump_cavitation_anomaly.csv` | Centrifugal pump: suction cavitation, pressure collapse and flow loss |
| `gearbox_vibration_wear.csv` | Conveyor gearbox with torque tag: an earlier lubrication failure, then friction heating followed by gear-mesh vibration |
| `compressor_valve_degradation.xlsx` | Two sheets (`Telemetry`, `Asset_Info`): valve leakage – pressure deficit, discharge-temperature rise, flow loss |

**Segment B**: `python backend/simulator.py` registers a simulated device and streams readings through repeating healthy → degrading → critical → maintenance cycles.

The bundled fault-type classifier in `ml_model/saved_models/` was trained on generated data; its ~100 % accuracy says nothing about real plants. Retrain with labelled plant data: `python ml_model/train_model.py --dataset your.csv`.

---

## 8. Installation & quick start

Hosted demo: **https://predicta-i6vf.onrender.com** – open to everyone, no login needed.

### Open access

By default (`PUBLIC_ACCESS=true`) Predicta needs no password: every visitor is signed in automatically as **"Visitor" with full admin rights**. Use the logout button to sign in with a named account instead.

> [!WARNING]
> With open access anyone can manage users, change the Telegram / Twilio settings (and send SMS that your Twilio account pays for), and register devices or rotate and revoke device keys. Keep `NOTIFICATION_MOCK_MODE=True` on public demos. Set `PUBLIC_ACCESS=false` to require login again; existing visitor sessions stop working immediately.
>
> ESP32 devices still authenticate with their own device keys, so they are not affected by this setting.

```bash
git clone https://github.com/mehulperimal14/Predicta.git
cd Predicta
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
python backend/app.py
```

Open **http://localhost:5000/login.html**.

In development (`FLASK_ENV` not `production`) three demo accounts are created: `admin` / `Predicta@2024`, `engineer` / `Engineer@2024`, `operator` / `Operator@2024`. Secrets you do not set are generated randomly into `backend/instance/` (git-ignored).

**Try Segment A:** Upload & Map Tags → download a sample → upload it → Analyse.

**Try Segment B:** in a second terminal run `python backend/simulator.py`, then open Live Monitor.

### Connecting a real ESP32 (Segment B)

1. Live Monitor → **Register device** (admin / engineer). Use the same `DEVICE_ID` as in the firmware. Copy the key – it is shown once.
2. In `hardware_design/esp32_firmware/main.ino` set `WIFI_SSID`, `WIFI_PASSWORD`, `DEVICE_ID`, `DEVICE_KEY`, `PREDICTA_INGEST_URL`, and paste your host's root certificate into `ROOT_CA`.
3. The device posts one reading every 10 s, stamps readings with NTP time, and buffers up to 30 readings while offline.

Test without hardware:

```bash
curl -X POST http://localhost:5000/api/live/ingest -H "Content-Type: application/json" -H "X-Device-Key: pdk_..." -d "{\"device_id\":\"PUMP_02\",\"motor_temp\":55.2,\"current\":3.3,\"vibration_rms\":0.14}"
```

Ingest also accepts a batch: `{"device_id": "...", "readings": [{... "timestamp": 1730000000}, ...]}`. On-premise sites with a Mosquitto broker can set `MQTT_ENABLED=true` instead.

---

## 9. Automated tests

```bash
pytest tests/ -v
```

`tests/conftest.py` runs everything against an in-memory database and a temporary upload folder, so your local data is never touched.

```text
tests/test_ai_engine.py ............ 14 passed  (layers 1–5, CUSUM, trend forecast, 9 signatures, PR-AUC, RUL)
tests/test_api_endpoints.py ........ 10 passed  (health, login, upload → analysis for every sample, notifications, secrets)
tests/test_ingestion.py ............  5 passed  (delimiter, timestamp, tag mapping, quality score, preview)
tests/test_live_monitoring.py ......  6 passed  (device keys, key rotation, degrading → time to breakdown, healthy, no data)
tests/test_notifications.py ........  4 passed  (Telegram / SMS formatting, cooldown, mock mode)
============================== 39 passed ==============================
```

---

## 10. Production deployment

### Required environment

| Variable | Why |
|---|---|
| `FLASK_ENV=production` | Disables demo passwords |
| `PUBLIC_ACCESS` | `true` (default): no login, visitors are admins. `false`: login required |
| `SECRET_KEY`, `JWT_SECRET_KEY` | Random 64-hex strings: `python -c "import secrets; print(secrets.token_hex(32))"`. Never reuse values published anywhere. |
| `PREDICTA_ADMIN_PASSWORD` (+ `_ENGINEER_`, `_OPERATOR_`) | Initial passwords. If unset in production, random ones are printed once to the server log. An existing account still on its old demo password is rotated to this value on start-up. |
| `DATABASE_URL` | PostgreSQL in production |

### Render
`render.yaml` generates `SECRET_KEY` and `JWT_SECRET_KEY` and asks for the three `PREDICTA_*_PASSWORD` values in the dashboard. Health check: `GET /api/health`.

> **If you deployed before this change:** your login tokens were signed with a key published in this repository. Set `JWT_SECRET_KEY` and `PREDICTA_ADMIN_PASSWORD` (and the engineer / operator passwords) in the Render dashboard and redeploy.

### Docker Compose
```bash
cp deployment/.env.example deployment/.env    # fill SECRET_KEY, JWT_SECRET_KEY, passwords
docker compose -f deployment/docker-compose.yml --env-file deployment/.env up --build -d
```

The container (`Dockerfile`, single-stage, non-root) runs gunicorn and regenerates the sample datasets at build time.

---

## 11. Industrial safety advisory notice

> [!CAUTION]
> Predicta is an **operational intelligence and predictive-maintenance advisory tool**.
>
> - It **never writes back to PLCs, DCS controllers or safety interlocks**.
> - It **does not control actuators, valves or motor starters**, and does not reset fault codes.
> - Time-to-breakdown figures extrapolate the current trend and are **not guarantees**.
>
> All maintenance interventions, shutdowns and component replacements must be verified and executed by qualified plant personnel in line with IEC, ISO, OSHA and site-specific safety standards.

---

## 12. Further documentation

- `documentation/CORRECTION_PROMPT.md` – the full list of problems fixed in Predicta 2.0's restructuring, and what is still open
- `hardware_design/` – sensor wiring and ESP32 firmware
- `plc_logic/` – reference ladder logic for the motor starter panel

## License & credits

Developed by **Mehul Perimal** and the Predicta Engineering Team.
Proprietary industrial software. For enquiries, support or custom SCADA integrations, contact the project maintainers.
