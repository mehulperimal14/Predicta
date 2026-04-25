# PREDICTA – Viva / Interview Q&A (50+ Questions)

## Section 1: Project Overview

**Q1. What is PREDICTA?**
PREDICTA is an AI-based industrial machine health monitoring and predictive maintenance system. It monitors a 3-phase induction motor and water pump using IoT sensors (ESP32), communicates with a PLC via Modbus RTU/TCP, sends data to a SCADA system (Node-RED), stores readings in PostgreSQL, applies Random Forest ML for fault prediction, and displays everything on a real-time web dashboard with Email/Telegram alerts.

**Q2. What real industrial problem does this solve?**
Unplanned machine failures cause 40–70% of production downtime in manufacturing. PREDICTA predicts failures before they occur, reducing downtime by detecting early warning signs in vibration, temperature, and current trends — converting costly reactive maintenance to proactive predictive maintenance.

**Q3. Why did you choose a 3-phase induction motor + pump as the target?**
Induction motors drive 65–70% of industrial electrical loads globally. They are used in pumps, compressors, fans, and conveyors. Failure modes (bearing wear, overheating, overload) are well-understood and measurable with affordable sensors. This makes it ideal for demonstrating predictive maintenance in a student project with real industrial relevance.

---

## Section 2: Hardware

**Q4. Why ESP32 instead of Arduino?**
ESP32 has built-in WiFi and Bluetooth, dual-core processor (240 MHz), more ADC pins, RTOS support, and Modbus library support. Arduino lacks WiFi natively, has limited RAM (2KB vs 520KB), and is not suitable for industrial IoT. ESP32 is widely used in industrial IoT gateways.

**Q5. How does ACS712 measure current?**
ACS712 uses the Hall Effect principle. Current through the conductor creates a magnetic field proportional to the current. The Hall sensor converts this to a voltage output. For ACS712-30A: sensitivity = 66 mV/A, zero-current output = VCC/2 = 2.5V. Formula: `I = (Vout - 2.5V) / 0.066`. We sample 1000 readings and calculate RMS for AC current.

**Q6. How do you measure RPM with Hall Effect sensor?**
A neodymium magnet is attached to the motor shaft. The Hall Effect sensor outputs one digital pulse per revolution. Using interrupts (IRAM_ATTR): `RPM = (pulse_count × 60,000) / elapsed_milliseconds`. We reset the counter every 500ms for smooth readings.

**Q7. What is MPU6050 and how is vibration measured?**
MPU6050 is a 6-DOF IMU (3-axis accelerometer + 3-axis gyroscope) with I2C interface. Vibration RMS = `sqrt((ax² + ay² + az²) / 3) - 1.0g`. The -1.0g removes gravity component. Normal vibration for a healthy motor is <0.3g. Warning >0.5g. Critical >1.0g (ISO 10816 standard).

**Q8. Why Delta DVP-ES2 instead of Siemens S7-1200?**
Delta costs ₹8,500 vs ₹25,000+ for Siemens. Both follow IEC 61131-3 ladder logic. Delta has free WPLSoft programming software vs expensive TIA Portal license. Delta has built-in RS485 port for Modbus RTU. For a student project demonstrating industrial PLC concepts, Delta provides the same learning value at 1/3 the cost. In industry, Delta is widely used in Indian and Southeast Asian manufacturing SMEs.

---

## Section 3: Communication Protocols

**Q9. Explain Modbus RTU.**
Modbus RTU is a serial communication protocol over RS485. It uses a master-slave topology. Each slave has an address (1–247). Data is transmitted in binary frames with CRC16 error checking. The ESP32 acts as Modbus RTU slave (address 1). The PLC is master and polls ESP32 registers every 100ms to read sensor values. Registers 40001–40008 contain sensor data scaled by factors (e.g., temperature × 10 for one decimal place).

**Q10. How does MQTT work in your system?**
MQTT (Message Queuing Telemetry Transport) is a publish-subscribe protocol designed for IoT. ESP32 publishes sensor data JSON to topic `predicta/sensor/data` every 2 seconds. Node-RED and Flask backend subscribe to this topic via Mosquitto broker (MQTT server). Advantages: lightweight, async, works over WiFi, supports QoS levels. We use QoS 1 (at-least-once delivery) for sensor data.

**Q11. What is Modbus TCP vs Modbus RTU?**
Modbus RTU uses RS485 serial (9600 baud, 8N1 frame, CRC16). Modbus TCP encapsulates Modbus in TCP/IP packets over Ethernet (port 502). PLC communicates to SCADA via Modbus TCP using the DVP-EN01 Ethernet module. This allows SCADA on any networked PC to read PLC registers remotely.

**Q12. What is the full data flow?**
```
Sensors → ESP32 (ADC/I2C/OneWire) → MQTT Publish + Modbus RTU Slave
      ↓ MQTT over WiFi                    ↓ RS485
Mosquitto Broker                      Delta PLC (Modbus Master)
      ↓                                    ↓ Modbus TCP
Flask Backend (MQTT Subscriber)      Node-RED SCADA
      ↓                                    ↓ HTTP POST
PostgreSQL DB + ML Engine → Prediction → Dashboard + Alerts
```

---

## Section 4: PLC & SCADA

**Q13. What PLC logic did you implement?**
1. Start/Stop motor with self-holding contact (3-wire control)
2. Emergency Stop (NC contact, IEC 60204-1 compliant)
3. Overload relay fault latch
4. Temperature shutdown (from Modbus register > 85°C)
5. Overcurrent protection (current > 4.5A for 3 seconds using timer)
6. Vibration fault (vibration > 0.5g for 5 seconds)
7. Fault summary coil (OR of all faults) → breaks motor circuit
8. Runtime hour counter
9. Start/stop cycle counter
10. Remote/local control via selector switch

**Q14. What is Node-RED and why did you use it for SCADA?**
Node-RED is a flow-based programming tool from IBM (now open-source). It's ideal for student-level SCADA because: free, runs on Raspberry Pi or PC, excellent MQTT and Modbus nodes, built-in dashboard with gauges/charts/alarms, easy HTTP integration with Flask backend. Industrial alternatives: Ignition SCADA, WinCC, InTouch — used in real plants but require expensive licenses.

---

## Section 5: Machine Learning

**Q15. Why Random Forest as the primary model?**
1. **Handles non-linear relationships** between sensor parameters
2. **No feature scaling required** (unlike SVM/neural networks)
3. **Built-in feature importance** for interpretability
4. **Robust to outliers** and missing values
5. **Ensemble method** reduces overfitting vs single decision tree
6. **Fast inference** (milliseconds) suitable for real-time prediction
7. **Industry standard** — used in GE Predix, IBM Maximo, SAP PM

**Q16. What dataset did you use and why?**
AI4I 2020 Predictive Maintenance Dataset (UCI ML Repository). It has 10,000 industrial machine records with 5 failure types: Tool Wear, Heat Dissipation, Power Failure, Overstrain, Random Failures. We map these to our motor failure types. It's from a real simulation of industrial machine failure patterns. After training, the model can be replaced with actual sensor data collected over weeks/months.

**Q17. How do you replace the dataset with real sensor data?**
1. Collect sensor readings in CSV format with PREDICTA running for 2–4 weeks
2. Manually label fault periods (during which faults occurred)
3. Export from PostgreSQL: `COPY sensor_readings TO 'my_data.csv' CSV HEADER`
4. Add `failure_type` column with labels
5. Run: `python train_model.py --dataset my_data.csv`
6. New model auto-saved to `saved_models/` and loaded by Flask

**Q18. What is the ML prediction pipeline?**
```
Raw sensor reading → build_ml_features() → 16 features
→ StandardScaler transform → RandomForestClassifier.predict_proba()
→ fault_class + confidence + all_probabilities
→ ROOT_CAUSES[fault_type] + RECOMMENDATIONS[fault_type]
→ _estimate_rul() → JSON response to dashboard
```

**Q19. What is Remaining Useful Life (RUL)?**
RUL is an estimate of how many days remain before a failure requires maintenance. We use a simple model based on failure probability: if P(failure) > 80% → RUL = 2 days, P > 60% → 7 days, P > 40% → 14 days, etc. More accurate RUL uses degradation curves (LSTM/Weibull distribution) for advanced implementations.

**Q20. What is the Isolation Forest for?**
Isolation Forest is an unsupervised anomaly detection algorithm. It isolates anomalies by randomly partitioning data — anomalies require fewer splits to isolate. We use it as a secondary check: if Isolation Forest flags a reading as anomalous but Random Forest predicts "Normal", we raise a low-severity alert. This catches novel/unseen failure modes that weren't in training data.

---

## Section 6: Backend & Database

**Q21. Why Flask instead of Django?**
Flask is lightweight, microframework — ideal for REST APIs. Django is full-stack (ORM, admin, templates) — overkill for an API backend. Flask gives full control with minimal overhead. Production-grade with Gunicorn + Eventlet for WebSocket support.

**Q22. Why PostgreSQL instead of MySQL?**
PostgreSQL handles time-series data better (window functions, partitioning). It supports JSONB for flexible sensor metadata. Better concurrent write performance for high-frequency IoT data. TimescaleDB extension (built on PG) is the industry standard for IoT time-series. Also: PG has better support for complex analytics queries (CTEs, window functions) used in trend analysis.

**Q23. How do you handle high-frequency sensor data at 2 readings/second?**
1. Use PostgreSQL bulk inserts (not individual INSERTs)
2. ML prediction runs every 10th reading (not every 2 seconds)
3. Data is indexed on (device_id, timestamp DESC) for fast latest-reading queries
4. Aggregation job runs every 60 seconds to compute hourly averages
5. Data retention policy: raw data for 30 days, aggregated data for 1 year

**Q24. How does JWT authentication work?**
1. User logs in → Flask checks username/password hash (bcrypt)
2. Flask returns access_token (8-hour expiry) + refresh_token (30-day expiry)
3. Frontend stores tokens in localStorage
4. Every API request includes `Authorization: Bearer <access_token>`
5. On 401 (expired), frontend auto-refreshes using refresh_token
6. Role-based: admin can manage users, engineer can acknowledge faults, operator can only view

---

## Section 7: Advanced Features

**Q25. How do email alerts work?**
Flask alerts.py uses Python `smtplib` with Gmail SMTP (TLS port 587). We send HTML-formatted emails with color-coded severity, sensor values, ML confidence, and recommendation. A cooldown mechanism (15 minutes per device+fault_type) prevents alert flooding. Emails are sent in a background thread to not block API response.

**Q26. How do Telegram alerts work?**
We use Telegram Bot API: `POST https://api.telegram.org/bot{TOKEN}/sendMessage`. Bot created via @BotFather. Chat ID obtained from `getUpdates` API. Message formatted with Markdown for bold text and emoji. No library needed — just `requests.post()`.

**Q27. What is the Machine Health Score?**
A composite 0–100% score computed as: `100 - sum(deductions)`. Each parameter contributes weighted deductions: Temperature (25 pts), Vibration (25 pts), Current (20 pts), Voltage (15 pts), Bearing Temp (15 pts), RPM (10 pts). Score ≥80% = Normal, 60–80% = Warning, <60% = Critical. Inspired by OEE (Overall Equipment Effectiveness) industrial metric.

**Q28. What is OEE?**
OEE = Availability × Performance × Quality. In PREDICTA: Availability = % time sensor readings show healthy state, Performance = estimated motor efficiency, Quality = 100 - vibration deduction. OEE of 85%+ is world-class. We display this in the analytics page as a KPI.

**Q29. How would you scale this to 50 machines?**
1. PostgreSQL partitioning by device_id
2. TimescaleDB hypertable for sensor_readings
3. Multiple MQTT topics: `predicta/sensor/{device_id}`
4. ML model per machine type (group similar machines)
5. Redis cache for latest readings (sub-millisecond response)
6. Message queue (Celery + Redis) for async ML predictions
7. Load balancer (Nginx) in front of multiple Flask workers
8. Cloud deployment: AWS IoT Core + RDS + ECS containers

**Q30. How would you deploy this in a real plant?**
1. ESP32 nodes installed on each machine, connected to plant WiFi
2. Industrial PC (Advantech, Siemens IPC) running Docker stack
3. Delta PLC in MCC (Motor Control Center) panel
4. Node-RED on industrial PC or cloud VM
5. Flask backend on cloud VM (AWS EC2 t2.medium ~₹1500/month)
6. Frontend served via Nginx, accessible from any plant browser
7. VPN for remote access by maintenance engineers

---

## Section 8: Resume-Ready Points

**PREDICTA – Key Resume Bullet Points:**

- Designed 9-layer Industrial IoT architecture integrating ESP32 sensors, Delta PLC (Modbus RTU/TCP), Node-RED SCADA, Flask REST API, PostgreSQL, and Random Forest ML achieving >90% fault prediction accuracy

- Implemented real-time machine health scoring system processing 2 readings/second from 8 sensors (current, voltage, temperature, vibration, RPM, pressure, humidity) with WebSocket live dashboard updates

- Built multi-channel predictive alert system delivering fault notifications via Email (HTML SMTP) and Telegram Bot API with 15-minute cooldown and severity-based filtering

- Engineered Random Forest + XGBoost + SVM + Isolation Forest ML pipeline on AI4I 2020 dataset with cross-validation, feature importance analysis, and human-readable root cause analysis

- Developed JWT-based role-based access control (Admin/Engineer/Operator) with auto token refresh and PDF report generation using ReportLab

- Containerized full-stack deployment using Docker Compose (PostgreSQL + Mosquitto MQTT + Flask + Nginx + Node-RED) with environment-based configuration

---

## Section 9: System Architecture Questions

**Q31. What is the difference between predictive and preventive maintenance?**
Preventive = scheduled at fixed intervals (e.g., oil change every 2000 hours) regardless of actual condition. Predictive = data-driven, done when sensors/ML indicates degradation. PREDICTA implements both: fixed maintenance schedule + ML-triggered alerts when failure probability exceeds threshold.

**Q32. What is bearing failure and how do you detect it?**
Bearings support rotating shafts. They fail due to: worn balls/races, lubricant failure, contamination, misalignment. Early signs: increased vibration (>0.5g), rising bearing temperature (>70°C). PREDICTA correlates vibration RMS rise + bearing temperature rise → flags "Bearing Failure" prediction. Physical symptoms appear weeks before catastrophic failure.

**Q33. What is slip in an induction motor?**
Slip = (Synchronous speed - Actual speed) / Synchronous speed × 100%. At no load: slip ≈ 1–2%. At full load: 3–5%. In PREDICTA: rated RPM 1440 (4-pole, 50Hz, synchronous 1500 RPM, slip = 4%). If RPM drops below 1200 → possible overload or stall → LOW_RPM alert triggered.
