# Predicta – Correction & Restructuring Prompt

> Use this prompt as the brief for an engineer or an AI coding agent working on
> this repository. It lists every known problem, how to fix it, and how to check
> the fix. Items marked **[DONE]** were implemented in the commit that added this file.

---

## 0. Context for whoever picks this up

Predicta is a Flask + vanilla-JS predictive-maintenance platform for industrial
machines (motors, pumps, gearboxes, compressors). It is **advisory only** – it never
writes to PLCs, actuators or safety interlocks.

The product must be organised as **two clearly separated segments that share one
analytics core**:

| | Segment A – SCADA / PLC File Analysis | Segment B – Live IoT Monitoring |
|---|---|---|
| Who supplies data | Plant engineers upload files themselves | ESP32 / microcontrollers stream continuously |
| Data shape | Historical CSV / XLSX / XLS exports from PLC, SCADA, DCS, historians | One JSON reading every few seconds per device |
| Transport | Browser upload → `POST /api/ingest/upload` | HTTPS `POST /api/live/ingest` (or MQTT bridge) with a per-device key |
| Main question answered | "What could have caused / is causing damage to this machine?" – full root-cause re-evaluation | "Is the machine healthy right now, which way is it trending, and when will it break down if nothing changes?" |
| Output | 5-layer risk report + fault hypotheses + checklist | Live health status, trend charts, time-to-limit forecast, likely causes |
| Alerts | Suppressed by default (historical replay guard) | Live Telegram / SMS alerts with per-asset cooldown |
| Backend entry | `backend/routes/ingestion_routes.py` | `backend/routes/live_routes.py`, `backend/live_engine.py` |
| UI | `upload.html`, `ai_analysis.html` | `live.html`, `analytics.html` |

Shared core (used by both segments – never duplicate this logic):
`analytics_engine.py` (features, CUSUM), `ai_engine.py` (Layers 1–5),
`trend_forecast.py` (time-to-limit extrapolation), `investigation.py`
(fault hypotheses), `notifications.py` (Telegram / SMS dispatcher).

---

## 1. Security problems (fix first)

### 1.1 Forgeable login tokens on the live site **[DONE]**
- **Problem:** `render.yaml` generated `SECRET_KEY` but never set `JWT_SECRET_KEY`,
  so `config.py` fell back to the public string `"predicta-jwt-secret-key"`.
  Anyone who read the repo could mint an admin JWT for the deployed app.
  `docker-compose.yml` and `.env.example` also shipped fixed fallback secrets.
- **Fix:**
  - `config.py`: no hard-coded secrets. Read `SECRET_KEY` / `JWT_SECRET_KEY` from
    the environment; if absent, generate a random key once and persist it in
    `backend/instance/` (git-ignored) so restarts and multiple gunicorn workers share it.
    `JWT_SECRET_KEY` falls back to `SECRET_KEY`, never to a literal.
  - `render.yaml`: `JWT_SECRET_KEY: generateValue: true`.
  - `docker-compose.yml`: require `SECRET_KEY` / `JWT_SECRET_KEY` (`${VAR:?…}`), no defaults.
  - `.env.example`: empty secret values with a command to generate them.
- **Check:** `grep -rn "predicta-jwt-secret-key\|change-in-production" backend deployment render.yaml` returns nothing; app still starts locally with no `.env`.

### 1.2 Admin password published next to the live URL **[DONE]**
- **Problem:** README listed `admin / Predicta@2024` beside the public Render URL;
  admin can edit Telegram / Twilio credentials and users.
- **Fix:**
  - Seed passwords come from `PREDICTA_ADMIN_PASSWORD`, `PREDICTA_ENGINEER_PASSWORD`,
    `PREDICTA_OPERATOR_PASSWORD`.
  - Development (`FLASK_ENV` ≠ `production`): falls back to the documented demo passwords.
  - Production: if a variable is unset, a random password is generated and printed
    once to the server log. If an existing seeded account still has its demo
    password and the env variable is set, it is rotated on startup.
  - README no longer prints credentials next to the live URL.
- **Check:** with `FLASK_ENV=production` and no password env vars, logging in with
  `Predicta@2024` fails on a fresh database.

### 1.3 Anyone could push fake sensor data **[DONE]**
- **Problem:** `POST /api/sensor/ingest` had no authentication and auto-registered
  any `device_id`.
- **Fix:** per-device API keys (`DeviceCredential` table, only the SHA-256 hash is
  stored). Devices are registered by an admin / engineer (`POST /api/live/devices`)
  and must send `X-Device-Key`. Unknown devices are rejected. The MQTT bridge calls
  the ingest function in-process (trusted broker), not over HTTP to `localhost:5000`.
- **Check:** ingest without a key → 401; with the key returned at registration → 201.

---

## 2. README-vs-code gaps

| # | README claim | Reality before | Fix |
|---|---|---|---|
| 2.1 | 9 failure signatures | 5 implemented | **[DONE]** Added compressor valve, gearbox wear, lubrication breakdown, filter clogging / process inefficiency. New standard tags: `discharge_temp`, `torque`, `differential_pressure`. |
| 2.2 | CUSUM change-points in the pipeline | `detect_cusum_changepoints` never called | **[DONE]** Run per variable in both segments; results returned as `changepoints` and used as evidence (gearbox step-change, lubrication onset order). |
| 2.3 | Layer 4 RUL needs validated run-to-failure data | Always called with `False`; `True` returned hard-coded 120 h | **[DONE]** Real trend extrapolation (`trend_forecast.py`): linear fit on recent running data, hours to warning / critical limit with 95 % interval. Reported as *validated RUL* only when the file has labelled failure events; otherwise as a *trend forecast* with the honest "unavailable" message kept. |
| 2.4 | Supervised model "PR-AUC evaluated" | PR-AUC never computed | **[DONE]** `average_precision_score` and ROC-AUC added to Layer 3 metrics; summary prints the value. |
| 2.5 | Isolation Forest contamination = 0.03 | Code used 0.05 | **[DONE]** Default 0.03, configurable via `ISOLATION_FOREST_CONTAMINATION`. |
| 2.6 | Layer 1 checks limits per operating state | Stopped rows were included; `min_warn`/`max_warn` limits (pressure, RPM, voltage warn band) were never checked | **[DONE]** Layer 1 evaluates running rows only and checks both upper and lower bands. Robust Z-score deviations are reported as context. |
| 2.7 | Layer 5 includes trend deterioration and alarm frequency | Only L1 / L2 / L3 / data quality | **[DONE]** Optional trend and alarm-frequency inputs blended in; old weights kept when they are absent. |
| 2.8 | ESP32 → MQTT → backend live path | `start_mqtt_subscriber` never called | **[DONE]** Started when `MQTT_ENABLED=true`. HTTPS is the default cloud transport. |
| 2.9 | Saved ML model 100 % accuracy (metadata) | Trained on generated `sensor_training_data.csv`, not AI4I | **[DONE]** Metadata and prediction output state `training_data: synthetic`; README says the score is not real-world performance. Retrain on real labelled plant data before trusting it. |
| 2.10 | Compressor sample has 2 sheets | 1 sheet; discharge temp was written into `motor_temp` | **[DONE]** Two sheets (`Telemetry`, `Asset_Info`), real `discharge_temp` column. Selected sheet is now remembered for analysis. |
| 2.11 | `render.yaml` cooldown env var | Set `ALERT_COOLDOWN_MINUTES`, code reads `NOTIFICATION_COOLDOWN_MINUTES` | **[DONE]** Renamed. |
| 2.12 | Local quick start opens the Render URL | Wrong URL for a local run | **[DONE]** `http://localhost:5000/login.html`. |
| 2.13 | Live dashboard shows real data | Silently showed browser-generated fake readings when the backend had none; Socket.IO hard-coded to `localhost:5000` | **[DONE]** Shows an explicit "no data / offline" state; Socket.IO uses the page origin. |
| 2.14 | Reports in PDF and CSV | PDF only | **[DONE]** CSV export for device telemetry and for an analysis run. |
| 2.15 | Docker compose works from `deployment/` | Volume paths pointed at `deployment/database`, `deployment/ml_model` | **[DONE]** Paths fixed to `../…`; SQL init removed (SQLAlchemy creates tables). |
| 2.16 | Test list in README | Names / count did not match `tests/` | **[DONE]** README shows the real `pytest` output. |
| 2.17 | Compiled files | `backend/routes/__pycache__/*.pyc` committed | **[DONE]** Removed and git-ignored. |

### 2b. Found and fixed while implementing the above **[DONE]**

| # | Problem | Fix |
|---|---|---|
| 2.18 | Login page showed `admin / Predicta@2024` on the public site | Removed; replaced with a "ask your administrator" note |
| 2.19 | Time-split Layer 3 also used the mapped timestamp and a copy of the label as features (leakage) | `NON_FEATURE_COLUMNS` excluded from Layers 2 and 3 |
| 2.20 | Layer 1 averaged violations over the whole file, so a record ending in failure scored only WATCH | Score = max(whole period, most recent 10 % of running samples) |
| 2.21 | CUSUM fires hundreds of times on daily load / ambient cycles; "first change-point" was meaningless | Reports the onset of the **ongoing** shift (the dense run of detections reaching the end of the data) |
| 2.22 | Hypotheses rated STRONG on proxy evidence (e.g. current instead of torque) | Proxy-only evidence capped at MODERATE |
| 2.23 | Sample compressor / pump currents sat above the default 1.5 kW motor limits; no sample let Layer 3 train | Currents fixed; motor and gearbox samples include an earlier, repaired failure |
| 2.24 | PDF download put the JWT in the URL (`?token=`), which the API ignores → 401 | Downloads use `fetch` with the Authorization header (`API.download`) |
| 2.25 | ESP32 sent `millis()` (time since boot) as `timestamp` → readings dated 1970 | NTP epoch seconds when synced, otherwise omitted (server stamps arrival) |
| 2.26 | `/api/predict/maintenance-schedule` crashed for devices without `run_hours`; `predict_fault` crashed on `None` sensor values | Treat missing values as absent |
| 2.27 | Tests wrote into the developer's `backend/instance/predicta.db` and `backend/uploads/` | `tests/conftest.py` sets an in-memory DB, temp upload folder and test secret before import |
| 2.28 | "Run ML Prediction" showed a fabricated healthy result when the API failed | Shows the error instead |
| 2.29 | `.btn-action` style only existed in `upload.html`; buttons on other pages were unstyled links | Moved to `css/style.css` |

---

## 3. Segment B – what "live monitoring" must do

1. **Register a device** (admin / engineer): `POST /api/live/devices` → returns the
   device key **once**. `POST /api/live/devices/<id>/rotate-key` issues a new one.
2. **Stream readings**: `POST /api/live/ingest` with header `X-Device-Key`. Body is
   one reading or `{"device_id": "...", "readings": [...]}` (lets the ESP32 flush a
   buffer after a Wi-Fi drop). Optional `timestamp` per reading (ISO-8601 or epoch).
3. **Assess continuously**: every N readings (and on demand) run the shared core on
   a rolling window of recent readings: Layer 1 rules, Layer 2 anomalies, CUSUM,
   trend forecast, Layer 5 risk, fault hypotheses.
4. **Answer the three questions** in `GET /api/live/devices/<id>/assessment`:
   - *Is it healthy?* → `status`: `HEALTHY` / `WATCH` / `DEGRADING` / `CRITICAL` / `OFFLINE` / `NO_DATA`
   - *Which way is it trending?* → per-variable slope per hour, R², direction
   - *When will it break down?* → hours until each warning / critical limit, the
     earliest one, and a 95 % interval. Always labelled as an extrapolation of the
     current trend, never as a guarantee.
5. **Alert live**: WARNING / CRITICAL dispatches Telegram / SMS through
   `notifications.dispatch_machine_alert(..., is_historical=False)` with cooldown.
6. **Fleet view**: `GET /api/live/fleet` – every device with online state, last seen,
   latest health status (cached assessment).

Acceptance: run `python backend/simulator.py` → device registers itself, streams,
`live.html` shows the status moving from HEALTHY to DEGRADING/CRITICAL during the
injected faults, with a finite "time to critical limit" while a trend is rising.

---

## 4. Segment A – what "file analysis" must do

1. Upload CSV / XLSX / XLS, choose sheet, auto-detect delimiter / encoding / timestamp,
   quality score, tag-mapping suggestions (exists).
2. Analysis re-evaluates **all nine** failure signatures, each with evidence strength,
   alternative explanations, data limitations and an inspection checklist.
3. Report CUSUM change-points ("when did behaviour change?") and the trend forecast
   ("where was it heading at the end of the file?").
4. Historical uploads never page plant staff unless `ALLOW_HISTORICAL_REPLAY=true`
   or the user explicitly asks.

---

## 4b. Owner decision: open access

The owner chose to make the hosted demo open to everyone. With `PUBLIC_ACCESS=true` (default)
`POST /api/auth/visitor` issues a password-less admin session ("Visitor"); the login page uses it
automatically and returns the visitor to the page they opened. `PUBLIC_ACCESS=false` restores
login-only access and immediately invalidates visitor sessions. Device ingest still requires
per-device keys. Trade-off accepted knowingly: visitors can change users, notification
credentials and device keys.

---

## 5. Still open (not done here)

- Database migrations (Alembic). New **tables** are created automatically; new
  **columns** on existing tables would need a migration, so this change avoids them.
- Real-world model validation: collect labelled failures from a plant and retrain
  `ml_model/train_model.py --dataset <file>`.
- Socket.IO push across multiple gunicorn workers needs a message queue (Redis);
  the live page polls every few seconds so it works without one.
- Rate limiting on login and ingest endpoints.
