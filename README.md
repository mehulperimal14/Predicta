# PREDICTA
## AI-Based Industrial Machine Health Monitoring & Predictive Maintenance System

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-green)](https://flask.palletsprojects.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue)](https://postgresql.org)
[![ESP32](https://img.shields.io/badge/MCU-ESP32-red)](https://espressif.com)
[![ML](https://img.shields.io/badge/ML-RandomForest-orange)](https://scikit-learn.org)

---

## Overview

PREDICTA is a complete industrial-grade platform for monitoring a **3-Phase Induction Motor + Water Pump** system using:
- **ESP32** for real-time sensor acquisition (Current, Voltage, Temperature, Vibration, RPM, Pressure)
- **Delta PLC** for motor protection and control (Modbus RTU/TCP)
- **Node-RED SCADA** for live HMI visualization
- **Flask + PostgreSQL** for REST API and time-series storage
- **Random Forest ML** for fault prediction with root cause analysis
- **React-inspired HTML Dashboard** for web-based monitoring
- **Email + Telegram alerts** for fault notifications

---

## System Architecture

```
[Layer 1] 3φ Motor + Pump
[Layer 2] ESP32 (Sensors + MQTT + Modbus RTU Slave)
[Layer 3] Delta DVP-ES2 PLC (Protection + Control)
[Layer 4] Node-RED SCADA (Modbus TCP + MQTT)
[Layer 5] Flask Backend + REST API (Python)
[Layer 6] PostgreSQL Database (Time-series)
[Layer 7] ML Engine (RandomForest + XGBoost)
[Layer 8] Web Dashboard (HTML/CSS/JS + Chart.js)
[Layer 9] Alerts + Reports + Admin Panel
```

---

## Project Structure

```
FaultiX/
├── backend/              Flask REST API + ML Engine
│   ├── app.py            Application entry point
│   ├── config.py         Configuration management
│   ├── models.py         SQLAlchemy ORM models
│   ├── database.py       DB connection
│   ├── prediction.py     ML inference engine
│   ├── preprocess.py     Feature engineering + health score
│   ├── alerts.py         Email + Telegram alerting
│   ├── mqtt_client.py    MQTT → REST bridge
│   ├── routes/           API route blueprints
│   └── requirements.txt
├── frontend/             Web Dashboard
│   ├── index.html        Live monitoring dashboard
│   ├── login.html        Authentication page
│   ├── analytics.html    Trend + energy analytics
│   ├── maintenance.html  Maintenance schedule
│   ├── reports.html      PDF reports + logs
│   ├── admin.html        User + threshold management
│   ├── css/style.css     Industrial dark theme
│   └── js/               dashboard.js, api.js, charts.js
├── ml_model/             Machine Learning
│   ├── train_model.py    RF + XGBoost + SVM + IsolationForest
│   ├── saved_models/     Trained model artifacts
│   └── data/             Dataset storage
├── hardware_design/      ESP32 firmware + wiring docs
│   └── esp32_firmware/main.ino
├── plc_logic/            Ladder logic documentation
├── scada_files/          Node-RED flow JSON
├── database/             PostgreSQL schema + seed data
├── deployment/           Docker Compose + Dockerfiles
└── documentation/        README, viva Q&A, resume points
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 15
- Mosquitto MQTT Broker
- Node.js (for Node-RED, optional)
- Docker (for containerized deployment)

### 1. Database Setup
```bash
psql -U postgres -c "CREATE DATABASE predicta_db;"
psql -U postgres -c "CREATE USER predicta WITH PASSWORD 'predicta123';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE predicta_db TO predicta;"
psql -U postgres -d predicta_db -f database/schema.sql
```

### 2. Backend Setup
```bash
cd backend
pip install -r requirements.txt
cp ../deployment/.env.example .env
# Edit .env with your credentials
python app.py
```
Backend starts at: http://localhost:5000

### 3. Train ML Model
```bash
cd ml_model
pip install -r ../backend/requirements.txt
python train_model.py
# Downloads AI4I dataset automatically and trains models
# Saves to: ml_model/saved_models/
```

### 4. Frontend
Open `frontend/login.html` in browser.
Default credentials: `admin / Predicta@2024`

### 5. Docker Deployment (Recommended)
```bash
cd deployment
cp .env.example .env
# Fill .env with credentials
docker-compose up -d
```
Access:
- Dashboard: http://localhost
- Backend API: http://localhost:5000/api
- Node-RED SCADA: http://localhost:1880
- PostgreSQL: localhost:5432

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/auth/login | Login, get JWT |
| POST | /api/sensor/ingest | Ingest sensor reading (ESP32) |
| GET  | /api/sensor/latest/{id} | Latest reading |
| GET  | /api/sensor/history/{id} | History (last N hours) |
| GET  | /api/predict/run/{id} | Run ML prediction |
| GET  | /api/predict/faults/{id} | Active faults |
| GET  | /api/predict/maintenance-schedule/{id} | Maintenance schedule |
| GET  | /api/analytics/health-trend/{id} | Health trend |
| GET  | /api/analytics/energy/{id} | Energy analysis |
| GET  | /api/analytics/performance-index/{id} | OEE metrics |
| GET  | /api/reports/generate/{id} | Download PDF report |

---

## Sensors & Parameters

| Sensor | Parameter | Range | Threshold |
|--------|-----------|-------|-----------|
| ACS712-30A | Current | 0–30A | OL: >4.5A |
| ZMPT101B | Voltage | 0–500V | <380V or >440V |
| DS18B20 | Motor Temp | -55 to 125°C | Warn: 75°C, Crit: 85°C |
| DS18B20 | Bearing Temp | -55 to 125°C | Warn: 70°C |
| MPU6050 | Vibration | 0–16g | Warn: 0.5g, Crit: 1.0g |
| Hall Effect | RPM | 0–5000 | <1200 or >1600 |
| DHT22 | Humidity | 0–100% | Monitoring only |
| MPX5700 | Pressure | 0–700 kPa | 50–600 kPa |

---

## ML Models

| Model | Role | Accuracy |
|-------|------|---------|
| Random Forest (primary) | Multi-class fault prediction | ~92% |
| XGBoost | Secondary validation | ~91% |
| SVM | Tertiary check | ~88% |
| Isolation Forest | Novel anomaly detection | Unsupervised |

---

## Fault Types Detected

1. Normal Operation
2. Bearing Failure
3. Motor Overheating
4. Overcurrent / Overload
5. Rotor Imbalance / Vibration
6. Cooling System Failure
7. Power Supply Anomaly
8. Winding Fault

---

## Standards Referenced

- IEC 61131-3 (PLC Programming)
- IEC 60204-1 (Safety of Machinery – Emergency Stop)
- ISO 10816-3 (Vibration limits for industrial machines)
- IEC 60947-4-1 (Motor starters and contactors)
- ISO 13374 (Condition Monitoring and Diagnostics)
- MQTT v3.1.1 (ISO/IEC 20922)
- Modbus RTU/TCP (Modbus Organization Standard)

---
