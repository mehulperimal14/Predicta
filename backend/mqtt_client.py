"""
PREDICTA – MQTT Subscriber Bridge
Subscribes to ESP32 MQTT topic and forwards data to Flask backend.
Compatible with paho-mqtt v1 and v2.
"""

import json
import threading
import requests as _requests


def start_mqtt_subscriber(app, socketio):
    """Start MQTT subscriber in background thread."""
    def _run():
        config = app.config
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("[MQTT] paho-mqtt not installed — MQTT bridge disabled")
            return

        # paho-mqtt v2 compatibility
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="predicta-backend")
        except AttributeError:
            client = mqtt.Client(client_id="predicta-backend")

        if config.get("MQTT_USERNAME"):
            client.username_pw_set(config["MQTT_USERNAME"], config["MQTT_PASSWORD"])

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                client.subscribe(config["MQTT_TOPIC_DATA"])
                print(f"[MQTT] Connected. Subscribed to {config['MQTT_TOPIC_DATA']}")
            else:
                print(f"[MQTT] Connection failed rc={rc}")

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                resp = _requests.post(
                    "http://localhost:5000/api/sensor/ingest",
                    json=payload, timeout=5
                )
                if resp.status_code == 201:
                    result = resp.json()
                    socketio.emit("sensor_update", {
                        "device_id":   payload.get("device_id"),
                        "data":        payload,
                        "health_score":result.get("health_score"),
                        "prediction":  result.get("prediction"),
                    })
            except Exception as e:
                print(f"[MQTT] Message error: {e}")

        client.on_connect = on_connect
        client.on_message = on_message

        try:
            client.connect(
                config["MQTT_BROKER_HOST"],
                config["MQTT_BROKER_PORT"],
                config.get("MQTT_KEEPALIVE", 60)
            )
            client.loop_forever()
        except Exception as e:
            print(f"[MQTT] Could not connect to broker ({config['MQTT_BROKER_HOST']}:{config['MQTT_BROKER_PORT']}): {e}")
            print("[MQTT] MQTT bridge disabled — using HTTP polling mode")

    thread = threading.Thread(target=_run, daemon=True, name="mqtt-subscriber")
    thread.start()
    print("[MQTT] Subscriber thread started")
