"""
PREDICTA – Segment B MQTT Subscriber Bridge
Subscribes to the ESP32 MQTT topic and ingests readings in-process through the same
code path as POST /api/live/ingest. Started from app.py when MQTT_ENABLED=true.

Trust model: the broker authenticates devices (MQTT_USERNAME / ACLs). The bridge only
accepts readings for devices that were registered in Predicta; a device_key in the
payload, if present, must also match.
Compatible with paho-mqtt v1 and v2.
"""

import json
import threading


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
            from models import Machine
            from live_engine import ingest_readings, verify_device_key
            try:
                payload = json.loads(msg.payload.decode())
                device_id = str(payload.get("device_id", ""))
                with app.app_context():
                    if not Machine.query.filter_by(device_id=device_id).first():
                        print(f"[MQTT] Ignored reading from unregistered device '{device_id}'")
                        return
                    if payload.get("device_key") and not verify_device_key(device_id, payload["device_key"]):
                        print(f"[MQTT] Ignored reading with invalid device_key for '{device_id}'")
                        return
                    readings = payload.get("readings") or [payload]
                    ingest_readings(device_id, readings)  # also emits "sensor_update"
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
