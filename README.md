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
## Intelligent Industrial Predictive Maintenance & PLC/SCADA Analytics Platform

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-blue)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-green)](https://flask.palletsprojects.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)](https://docker.com)
[![Tests](https://img.shields.io/badge/Tests-21%20Passed-brightgreen)](https://pytest.org)
[![License](https://img.shields.io/badge/License-Proprietary%20%2F%20Industrial-lightgrey)](#)

---

## 1. Executive Summary & Vision

**Predicta 2.0** is an enterprise-ready, AI-powered industrial predictive maintenance system engineered to analyze historical machine operational data directly from existing **PLC, SCADA, DCS, and Historian exports** (CSV, XLSX, XLS).

### Zero Additional Physical Sensors Required
Unlike traditional IoT solutions that require purchasing and bolting new sensors onto operating machinery, Predicta 2.0 leverages the rich telemetry and fault records **already collected by your existing industrial automation infrastructure**:
- Variable Frequency Drives (VFDs) & Motor Control Centers (MCCs)
- SCADA historical trend logs & industrial historian exports
- PLC fault logs & run/stop state records
- Production downtime & maintenance logs

Predicta 2.0 operates strictly in a **read-only, advisory capacity** to safeguard human life and plant integrity. It provides engineering teams with transparent, explainable health assessments and automated notifications via **Telegram** and **Twilio SMS** before costly breakdowns occur.

---

## 2. Core Workflow

```
[ Upload Data File ] ──► ( CSV / XLSX / XLS from PLC / SCADA / Historian )
         │
         ▼
[ Ingestion & Quality ] ──► ( Delimiter/Encoding, Timestamps, 0–100% Quality Score )
         │
         ▼
[ Tag Mapping Studio ] ──► ( Reusable mapping of plant tags to standard variables )
         │
         ▼
[ Time-Series Analytics ] ──► ( Rolling Stats, EWMA, CUSUM Changepoints, State Filtering )
         │
         ▼
[ 5-Layer AI Risk Engine ] ──► ( Limits ➔ Isolation Forest ➔ Supervised RF ➔ RUL ➔ Composite Risk )
         │
         ▼
[ Explainable Investigation ] ──► ( 9 Failure Signatures, Confidence Grades, Inspection Checklists )
         │
         ▼
[ Notification Dispatcher ] ──► ( Telegram & Twilio SMS with 15-min Cooldown & Replay Protection )
         │
         ▼
[ Maintenance & Reports ] ──► ( Work Order Assignment, PDF/CSV Executive Reports )
```

---

## 3. Layered AI & Diagnostic Architecture

Predicta 2.0 employs a strict 5-layer diagnostic methodology that guarantees transparency and prevents misleading predictions:

| Layer | Method | Purpose & Capabilities |
|---|---|---|
| **Layer 1** | **Engineering Limits & Statistical Thresholds** | Evaluates vendor operational ceilings, Z-scores, and EWMA deviation bands per operating state. |
| **Layer 2** | **Unsupervised Anomaly Detection** | Uses **Isolation Forests** (contamination=0.03) to detect multivariate shifts when failure labels are unavailable. |
| **Layer 3** | **Supervised Failure Prediction** | Evaluates **Random Forest** classification with strict temporal train/test split. Gracefully falls back to unsupervised analysis if labels are absent. |
| **Layer 4** | **Remaining Useful Life (RUL)** | Requires validated run-to-failure degradation trajectories. If absent, explicitly reports: *"Remaining useful life unavailable: insufficient validated degradation or failure-history data"*. |
| **Layer 5** | **Composite Machine-Health Risk** | Synthesizes limit breaches, anomaly density, trend deterioration, alarm frequency, and state context into standardized risk categories: **NORMAL**, **WATCH**, **WARNING**, **CRITICAL**. |

---

## 4. Explainable Fault Investigation & Failure Signatures

Predicta 2.0 does not treat AI as a black box. For every detected anomaly, it evaluates 9 distinct industrial failure hypotheses with rigorous evidence confidence grading (**Strong**, **Moderate**, **Weak**, **Insufficient**):

1. **Motor Overload & Thermal Runaway**: Sustained current above nominal baseline paired with exponential stator temperature rise.
2. **Bearing Degradation / Mechanical Rub**: High-frequency vibration RMS rise correlated with localized bearing temperature rise.
3. **Cooling System Breakdown**: Temperature gradient excursion despite stable or declining motor current/power.
4. **Pump Cavitation & Flow Instability**: Rapid discharge pressure fluctuations and declining flow rate at constant pump speed.
5. **Compressor Valve Degradation**: Pressure delivery deficit and elevated discharge temperatures.
6. **Gearbox Tooth Wear & Mechanical Imbalance**: Step-changes in mechanical vibration with elevated drive torque.
7. **Electrical Supply & Voltage Imbalance**: Phase current asymmetry or voltage instability triggering repeated VFD trip codes.
8. **Lubrication Breakdown**: Linear friction-induced temperature rise prior to vibration onset.
9. **Process Inefficiency & Filter Clogging**: Progressive pressure drop across filters or heat exchangers.

Every hypothesis card provides:
- Primary evidence and observed sensor shifts
- Alternative operational explanations (e.g., ambient heatwave, legitimate heavy product batch)
- Data limitation disclosures (e.g., whether vibration is directly measured or inferred via current proxies)
- Actionable, prioritized maintenance inspection checklists

---

## 5. Web Interface (Browser-Accessible)

The platform is served via an integrated single-port web interface with 8 purpose-built industrial views:

1. **Overview Dashboard (`/` or `index.html`)**: Fleet-wide machine health, active risk distributions, recent alerts, and quick telemetry gauges.
2. **Upload & Tag Mapping Studio (`upload.html`)**: Drag-and-drop file ingestion, CSV delimiter & encoding auto-detection, Excel multi-sheet selector, 0–100% automated data quality scorecard, intelligent tag mapper, and 1-click sample dataset downloads.
3. **AI Analysis & Fault Investigation (`ai_analysis.html`)**: Composite risk gauge, 5-layer diagnostic breakdown, multi-variable interactive Chart.js trends, and 9-signature hypothesis cards with confidence pills.
4. **Asset Health & Telemetry (`analytics.html`)**: Historical telemetry time-series, baseline comparison bands, and energy efficiency analytics.
5. **Maintenance Management (`maintenance.html`)**: Work order tracking, alert assignment to maintenance engineers, acknowledgement audit trails, and outcome logs.
6. **Telegram & SMS Notification Center (`notifications.html`)**: Token management with security masking, test dispatch triggers, cooldown controls, historical replay guard toggle, and delivery audit log.
7. **Executive Reports (`reports.html`)**: Instant PDF and CSV engineering reports containing analysis parameters, telemetry trends, and inspection checklists.
8. **System Administration (`admin.html`)**: Role-based access control, asset threshold configurations, and system health status.

---

## 6. Telegram & Twilio SMS Alert Integration

Predicta 2.0 features an industrial-grade notification dispatcher engineered to prevent alert fatigue:

### Telegram Bot Integration
- Direct integration via official Telegram Bot API.
- Markdown-formatted alerts detailing asset ID, risk level, observed sensor shifts, recommended inspections, and one-click hosted dashboard links.
- Server-side token storage (never exposed in frontend code or client responses).

### Twilio SMS Integration
- High-priority SMS alerts for `CRITICAL` machine states formatted for international E.164 phone numbers.
- Automated fallback to a documented testable mock mode when credentials are not configured.

### Protection Against Alert Flooding
- **Per-Asset Cooldown:** Configurable 15-minute suppression window prevents duplicate alerts during ongoing anomalous conditions.
- **Historical Replay Guard:** By default, uploading historical files analyzes data chronologically without blasting real-time notifications to plant personnel (`ALLOW_HISTORICAL_REPLAY=False`).

---

## 7. Synthetic Industrial Demonstration Datasets

Predicta 2.0 includes 4 physics-grounded synthetic industrial datasets in `backend/sample_data/` for immediate offline demonstration and training:

1. **`motor_cooling_failure.csv`**: Electric motor undergoing sudden cooling fan blockage with thermal runaway while current remains steady.
2. **`pump_cavitation_anomaly.csv`**: Centrifugal pump experiencing suction pressure drop, severe flow turbulence, and discharge pressure fluctuations.
3. **`gearbox_vibration_wear.csv`**: Industrial conveyor gearbox exhibiting progressive bearing/gear wear with rising vibration RMS and temperature.
4. **`compressor_valve_degradation.xlsx`**: Reciprocating compressor exhibiting valve leakage with declining pressure delivery and rising stage temperature across 2 workbook sheets.

*Note: All synthetic datasets are explicitly labelled as simulations and are never conflated with real plant telemetry.*

---

## 8. Installation & Quick Start

### Prerequisites
- Python 3.11, 3.12, or 3.14
- Modern web browser (Chrome, Edge, Firefox, Safari)

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/mehulperimal14/Predicta.git
cd Predicta

# Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

### 2. Configure Environment Variables
Copy the deployment template and configure as needed:
```bash
cp deployment/.env.example backend/.env
```
Key configuration parameters:
- `SECRET_KEY`: Random 32-character string for JWT session security.
- `DATABASE_URL`: Defaults to `sqlite:///predicta.db` for local dev; use `postgresql://user:pass@host:5432/predicta` for production.
- `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`: Bot credentials for Telegram notifications.
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`: Twilio credentials for SMS alerts.
- `NOTIFICATION_MOCK_MODE`: Set to `True` to safely simulate and audit notifications without sending real messages.

### 3. Run the Application
```bash
python backend/app.py
```
Open your browser to:
**`http://localhost:5000`**

Default credentials:
- **Username:** `admin`
- **Password:** `Predicta@2024`

---

## 9. Automated Testing Suite

Predicta 2.0 includes a comprehensive test suite covering ingestion, data quality scoring, AI analytics, notification dispatchers, and REST endpoints:

```bash
pytest tests/ -v
```

**Verification Results:**
```text
tests/test_ingestion.py::test_csv_detection_and_parsing PASSED
tests/test_ingestion.py::test_excel_parsing PASSED
tests/test_ingestion.py::test_timestamp_detection PASSED
tests/test_ingestion.py::test_tag_mapping_suggestions PASSED
tests/test_ingestion.py::test_data_quality_scoring PASSED
tests/test_ingestion.py::test_invalid_engineering_values PASSED
tests/test_ai_engine.py::test_engineering_limits_layer1 PASSED
tests/test_ai_engine.py::test_isolation_forest_layer2 PASSED
tests/test_ai_engine.py::test_supervised_prediction_layer3 PASSED
tests/test_ai_engine.py::test_rul_estimation_honesty_layer4 PASSED
tests/test_ai_engine.py::test_composite_risk_engine_layer5 PASSED
tests/test_ai_engine.py::test_fault_investigation_hypotheses PASSED
tests/test_notifications.py::test_telegram_message_formatting PASSED
tests/test_notifications.py::test_sms_message_formatting PASSED
tests/test_notifications.py::test_mock_mode_delivery PASSED
tests/test_notifications.py::test_deduplication_cooldown PASSED
tests/test_notifications.py::test_historical_replay_protection PASSED
tests/test_api_endpoints.py::test_health_endpoint PASSED
tests/test_api_endpoints.py::test_login_workflow PASSED
tests/test_api_endpoints.py::test_sample_datasets_endpoint PASSED
tests/test_api_endpoints.py::test_file_upload_and_analysis_workflow PASSED

============================= 21 passed in 2.64s =============================
```

---

## 10. Production Deployment

### Option A: Docker & Docker Compose
```bash
# Build and run multi-container stack (Flask + PostgreSQL)
docker-compose -f deployment/docker-compose.yml up --build -d
```

### Option B: Cloud Application Hosting (Render, Railway, Fly.io, Heroku)
Predicta 2.0 is fully pre-configured for one-click cloud deployment:
- `Procfile`: Configured with Gunicorn production WSGI server:
  ```text
  web: gunicorn --bind 0.0.0.0:$PORT backend.app:app --workers 2 --threads 4 --timeout 120
  ```
- `Dockerfile`: Multi-stage production container with synthetic dataset generation on initialization.
- Healthcheck endpoint: `GET /api/health`

---

## 11. Industrial Safety Advisory Notice

> [!CAUTION]
> **Advisory & Read-Only System Constraint**
>
> Predicta 2.0 is designed exclusively as an **operational intelligence and predictive maintenance advisory tool**.
>
> - Predicta 2.0 **never writes back to active PLCs, DCS controllers, or safety interlocks**.
> - It **does not directly control actuators, valves, or motor starters**.
> - It **does not reset industrial fault codes or bypass hardware safety systems**.
>
> All machine maintenance interventions, shutdowns, and component replacements **must be verified and executed by qualified plant engineering personnel** in compliance with applicable IEC, ISO, OSHA, and site-specific industrial safety standards.

---

## 12. License & Credits

Developed by **Mehul Perimal** and the Predicta Engineering Team.  
Proprietary industrial software. For inquiries, support, or custom SCADA integrations, contact the project maintainers.
