/*
 * PREDICTA – ESP32 Industrial Sensor Acquisition Firmware
 * Target: ESP32 DevKit V1
 * System: 3-Phase Induction Motor + Water Pump Monitoring
 *
 * Libraries Required:
 *   - PubSubClient (MQTT)
 *   - ArduinoJson
 *   - OneWire + DallasTemperature (DS18B20)
 *   - MPU6050 by Electronic Cats
 *   - DHT sensor library by Adafruit
 *   - ModbusMaster (for Modbus RTU slave)
 *
 * Install via Arduino Library Manager
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <MPU6050.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>

// ─── WiFi + MQTT Configuration ────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_SERVER   = "192.168.1.100";    // Node-RED / Mosquitto broker IP
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC    = "predicta/sensor/data";
const char* MQTT_ALERT    = "predicta/alerts";
const char* DEVICE_ID     = "MOTOR_01";

// ─── Pin Definitions ──────────────────────────────────────────────────────────
#define PIN_CURRENT       34   // ACS712-30A analog out
#define PIN_VOLTAGE       35   // ZMPT101B analog out
#define PIN_PRESSURE      32   // MPX5700 pressure sensor
#define PIN_DS18B20_MOTOR  4   // DS18B20 motor body temperature
#define PIN_DS18B20_BEAR   5   // DS18B20 bearing temperature
#define PIN_DHT           15   // DHT22 ambient
#define PIN_HALL           2   // Hall effect RPM (interrupt)
#define PIN_RS485_RX      16   // MAX485 RO
#define PIN_RS485_TX      17   // MAX485 DI
#define PIN_RS485_DE      18   // MAX485 DE+RE
#define PIN_RELAY_ALARM   19   // Relay module output
#define PIN_STATUS_LED    26   // Onboard status LED
#define DHT_TYPE          DHT22

// ─── Calibration Constants ────────────────────────────────────────────────────
#define ACS712_SENSITIVITY  0.066    // 66 mV/A for ACS712-30A
#define ACS712_ZERO         1.65     // Zero-current voltage (at 3.3V supply)
#define VOLTAGE_CAL_FACTOR  170.5    // Calibrate with multimeter
#define ADC_REF             3.3
#define ADC_RESOLUTION      4095.0
#define CURRENT_SAMPLES     1000     // Samples for RMS calculation
#define MOTOR_POLES         4
#define POWER_FACTOR        0.85     // Assumed pf for induction motor

// ─── Threshold Definitions (configurable via MQTT) ───────────────────────────
#define TEMP_WARNING        75.0    // °C
#define TEMP_CRITICAL       85.0    // °C
#define CURRENT_OVERLOAD    4.5     // A (130% of FLC 3.5A)
#define VIBRATION_WARNING   0.5     // g RMS
#define VIBRATION_CRITICAL  1.0     // g RMS
#define RPM_LOW_LIMIT       1200    // RPM (below = possible stall)
#define RPM_HIGH_LIMIT      1600    // RPM (above = possible overspeed)

// ─── Objects ──────────────────────────────────────────────────────────────────
WiFiClient espClient;
PubSubClient mqttClient(espClient);
OneWire oneWireMotor(PIN_DS18B20_MOTOR);
OneWire oneWireBear(PIN_DS18B20_BEAR);
DallasTemperature motorTempSensor(&oneWireMotor);
DallasTemperature bearingTempSensor(&oneWireBear);
MPU6050 mpu;
DHT dht(PIN_DHT, DHT_TYPE);
Adafruit_SSD1306 oled(128, 64, &Wire, -1);

// ─── Global Variables ─────────────────────────────────────────────────────────
volatile unsigned long rpmPulseCount = 0;
unsigned long lastRpmCalc = 0;
unsigned long lastPublish = 0;
unsigned long motorStartTime = 0;
bool motorRunning = false;
float totalEnergyKWh = 0.0;
unsigned long startStopCycles = 0;
unsigned long lastCurrentTime = 0;

// ─── Interrupt Handler for RPM ────────────────────────────────────────────────
void IRAM_ATTR hallISR() {
  rpmPulseCount++;
}

// ─── Setup ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);  // Modbus RTU

  // GPIO Setup
  pinMode(PIN_HALL, INPUT_PULLUP);
  pinMode(PIN_RELAY_ALARM, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);
  pinMode(PIN_RS485_DE, OUTPUT);
  digitalWrite(PIN_RELAY_ALARM, HIGH);  // Relay NC, deactivate
  digitalWrite(PIN_RS485_DE, LOW);      // Receive mode

  attachInterrupt(digitalPinToInterrupt(PIN_HALL), hallISR, RISING);

  // Sensor Init
  motorTempSensor.begin();
  bearingTempSensor.begin();
  mpu.initialize();
  dht.begin();
  Wire.begin(21, 22);

  // OLED Init
  if (!oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED init failed");
  }
  oledSplash();

  // WiFi + MQTT
  connectWiFi();
  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  connectMQTT();

  motorStartTime = millis();
  motorRunning = true;
  startStopCycles++;

  Serial.println("PREDICTA ESP32 Node Online");
}

// ─── Main Loop ────────────────────────────────────────────────────────────────
void loop() {
  if (!mqttClient.connected()) connectMQTT();
  mqttClient.loop();

  unsigned long now = millis();

  // Publish sensor data every 2 seconds
  if (now - lastPublish >= 2000) {
    lastPublish = now;

    // Read all sensors
    float current     = readCurrentRMS();
    float voltage     = readVoltageRMS();
    float motorTemp   = readTemperature(motorTempSensor);
    float bearingTemp = readTemperature(bearingTempSensor);
    float ambientTemp = dht.readTemperature();
    float humidity    = dht.readHumidity();
    float vibration   = readVibrationRMS();
    float rpm         = calculateRPM();
    float pressure    = readPressure();
    float power       = calculatePower(voltage, current, POWER_FACTOR);
    float runHours    = (millis() - motorStartTime) / 3600000.0;

    // Accumulate energy
    totalEnergyKWh += power * (2.0 / 3600000.0);  // kWh = kW × hours

    // Build JSON payload
    StaticJsonDocument<512> doc;
    doc["device_id"]     = DEVICE_ID;
    doc["timestamp"]     = now;
    doc["voltage"]       = round(voltage * 10) / 10.0;
    doc["current"]       = round(current * 100) / 100.0;
    doc["motor_temp"]    = round(motorTemp * 10) / 10.0;
    doc["bearing_temp"]  = round(bearingTemp * 10) / 10.0;
    doc["ambient_temp"]  = round(ambientTemp * 10) / 10.0;
    doc["humidity"]      = round(humidity * 10) / 10.0;
    doc["vibration_rms"] = round(vibration * 1000) / 1000.0;
    doc["rpm"]           = (int)rpm;
    doc["pressure"]      = round(pressure * 10) / 10.0;
    doc["power_kw"]      = round(power * 100) / 100.0;
    doc["energy_kwh"]    = round(totalEnergyKWh * 1000) / 1000.0;
    doc["run_hours"]     = round(runHours * 100) / 100.0;
    doc["start_cycles"]  = startStopCycles;
    doc["motor_running"] = motorRunning;

    // Fault flags
    doc["overload"]      = (current > CURRENT_OVERLOAD);
    doc["overheat"]      = (motorTemp > TEMP_WARNING);
    doc["high_vibration"]= (vibration > VIBRATION_WARNING);
    doc["low_rpm"]       = (rpm < RPM_LOW_LIMIT && motorRunning);

    char payload[512];
    serializeJson(doc, payload);
    mqttClient.publish(MQTT_TOPIC, payload);

    // Local alarm relay
    if (current > CURRENT_OVERLOAD || motorTemp > TEMP_CRITICAL || vibration > VIBRATION_CRITICAL) {
      digitalWrite(PIN_RELAY_ALARM, LOW);  // Energize alarm
    } else {
      digitalWrite(PIN_RELAY_ALARM, HIGH);
    }

    // Update OLED
    updateOLED(voltage, current, motorTemp, vibration, rpm);

    // Debug output
    Serial.printf("[SENSOR] V=%.1fV I=%.2fA T=%.1f°C Vib=%.3fg RPM=%.0f P=%.2fkW\n",
                  voltage, current, motorTemp, vibration, rpm, power);
  }
}

// ─── Sensor Reading Functions ─────────────────────────────────────────────────

float readCurrentRMS() {
  long sum = 0;
  for (int i = 0; i < CURRENT_SAMPLES; i++) {
    int raw = analogRead(PIN_CURRENT);
    float voltage = (raw / ADC_RESOLUTION) * ADC_REF;
    float current = (voltage - ACS712_ZERO) / ACS712_SENSITIVITY;
    sum += (long)(current * current * 100);
    delayMicroseconds(100);
  }
  float rms = sqrt((float)sum / (CURRENT_SAMPLES * 100));
  return max(0.0f, rms);
}

float readVoltageRMS() {
  int maxRaw = 0;
  for (int i = 0; i < 500; i++) {
    int raw = analogRead(PIN_VOLTAGE);
    if (raw > maxRaw) maxRaw = raw;
    delayMicroseconds(100);
  }
  float peakVoltage = (maxRaw / ADC_RESOLUTION) * ADC_REF;
  return peakVoltage * VOLTAGE_CAL_FACTOR;
}

float readTemperature(DallasTemperature& sensor) {
  sensor.requestTemperatures();
  float t = sensor.getTempCByIndex(0);
  return (t == DEVICE_DISCONNECTED_C) ? 0.0f : t;
}

float readVibrationRMS() {
  int16_t ax, ay, az, gx, gy, gz;
  float sumSq = 0;
  int samples = 100;
  for (int i = 0; i < samples; i++) {
    mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
    float ax_g = ax / 4096.0;
    float ay_g = ay / 4096.0;
    float az_g = az / 4096.0;
    sumSq += ax_g * ax_g + ay_g * ay_g + az_g * az_g;
    delay(1);
  }
  float total_rms = sqrt(sumSq / samples);
  return max(0.0f, total_rms - 1.0f);  // Remove gravity component
}

float calculateRPM() {
  unsigned long now = millis();
  unsigned long elapsed = now - lastRpmCalc;
  if (elapsed < 500) return -1;  // Not ready yet

  noInterrupts();
  unsigned long pulses = rpmPulseCount;
  rpmPulseCount = 0;
  interrupts();

  lastRpmCalc = now;
  float rpm = (pulses * 60000.0f) / elapsed;
  return rpm;
}

float readPressure() {
  int raw = analogRead(PIN_PRESSURE);
  float voltage = (raw / ADC_RESOLUTION) * ADC_REF;
  // MPX5700GP: Vout = VS × (0.006788 × P + 0.04)
  // P (kPa) = (Vout / VS - 0.04) / 0.006788
  float pressure_kpa = (voltage / 5.0 - 0.04) / 0.006788;
  return max(0.0f, pressure_kpa);
}

float calculatePower(float v, float i, float pf) {
  return (v * i * pf * 1.732) / 1000.0;  // kW (3-phase)
}

// ─── WiFi + MQTT ──────────────────────────────────────────────────────────────

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    digitalWrite(PIN_STATUS_LED, !digitalRead(PIN_STATUS_LED));
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWiFi connected: %s\n", WiFi.localIP().toString().c_str());
    digitalWrite(PIN_STATUS_LED, HIGH);
  } else {
    Serial.println("\nWiFi connection failed! Running in offline mode.");
  }
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("Connecting to MQTT...");
    String clientId = "ESP32_" + String(DEVICE_ID);
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println("connected");
      mqttClient.subscribe("predicta/commands");
      mqttClient.subscribe("predicta/thresholds");
    } else {
      Serial.printf("Failed rc=%d, retry in 5s\n", mqttClient.state());
      delay(5000);
    }
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  StaticJsonDocument<256> doc;
  if (!deserializeJson(doc, msg)) {
    // Handle remote commands
    if (doc.containsKey("motor_stop") && doc["motor_stop"].as<bool>()) {
      motorRunning = false;
      Serial.println("Remote STOP command received");
    }
    // Update thresholds dynamically
    if (doc.containsKey("temp_warning")) {
      // In production: update global threshold variables
      Serial.printf("Threshold update: temp_warning=%.1f\n", doc["temp_warning"].as<float>());
    }
  }
}

// ─── OLED Display ─────────────────────────────────────────────────────────────

void oledSplash() {
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(10, 10);
  oled.println("PREDICTA v1.0");
  oled.setCursor(5, 25);
  oled.println("Motor Monitor Node");
  oled.setCursor(20, 40);
  oled.println("Initializing...");
  oled.display();
  delay(2000);
}

void updateOLED(float v, float i, float t, float vib, float rpm) {
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);

  oled.setCursor(0, 0);  oled.printf("V: %.1fV  I: %.2fA", v, i);
  oled.setCursor(0, 16); oled.printf("T: %.1fC  RPM:%d", t, (int)rpm);
  oled.setCursor(0, 32); oled.printf("Vib: %.3fg", vib);

  // Status bar
  oled.setCursor(0, 48);
  if (i > CURRENT_OVERLOAD) {
    oled.println("!! OVERLOAD !!");
  } else if (t > TEMP_WARNING) {
    oled.println("!! OVERHEAT !!");
  } else if (vib > VIBRATION_WARNING) {
    oled.println("!! VIBRATION !!");
  } else {
    oled.println("STATUS: NORMAL");
  }

  oled.display();
}
