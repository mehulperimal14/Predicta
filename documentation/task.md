# PREDICTA – Build Task Tracker

## Shared analytics core
- [x] Time-series features, CUSUM change-points with ongoing-shift onset (`analytics_engine.py`)
- [x] Layer 1–5 risk engine with two-sided limits, state filtering, PR-AUC, RUL from failure history (`ai_engine.py`)
- [x] Trend forecast: time to warning / critical limit with 95 % interval (`trend_forecast.py`)
- [x] Nine failure signatures with proxy disclosure (`investigation.py`)
- [x] Telegram / SMS dispatcher with cooldown and replay guard (`notifications.py`)

## Segment A – SCADA / PLC file analysis
- [x] Upload CSV / XLSX / XLS, sheet selection remembered for analysis
- [x] Tag mapping incl. `discharge_temp`, `torque`, `differential_pressure`
- [x] Analysis returns forecast + change-points; CSV export of each run
- [x] Investigation page shows forecast table and sorted hypotheses

## Segment B – live IoT monitoring
- [x] Per-device API keys (`DeviceCredential`), register / rotate / revoke
- [x] Authenticated HTTPS ingest, single reading or batch (`/api/live/ingest`)
- [x] Rolling-window assessment: status, trends, time to breakdown, likely causes
- [x] Live alerts through the shared dispatcher
- [x] MQTT bridge ingests in-process when `MQTT_ENABLED=true`
- [x] Live Monitor page, Overview page, device selector shared across pages
- [x] ESP32 firmware: HTTPS + device key, NTP timestamps, offline buffer
- [x] Simulator registers itself and streams degradation cycles

## Security
- [x] No published JWT / Flask secrets; random persisted fallback
- [x] Seed passwords from env; random in production; demo passwords rotated
- [x] Demo credentials removed from README and login page

## Open
- [ ] Alembic migrations (new columns on existing tables need them)
- [ ] Redis message queue for Socket.IO across gunicorn workers
- [ ] Rate limiting on login and ingest
- [ ] Retrain the fault-type classifier on real labelled plant data
- [ ] Per-device engineering limits for every variable (only a subset is configurable today)
