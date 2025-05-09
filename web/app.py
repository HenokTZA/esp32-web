from flask import Flask, request, jsonify, render_template
import paho.mqtt.client as mqtt
import os, json

BROKER   = "192.168.137.101"
PORT     = 1883
USER     = os.getenv("MQTT_USER", "iotuser")
PASSWORD = os.getenv("MQTT_PASS", "secretpass")

mqttc = mqtt.Client()
mqttc.username_pw_set(USER, PASSWORD)
mqttc.connect(BROKER, PORT)
mqttc.loop_start()           # background thread

app = Flask(__name__)

@app.route("/")
def index():
    # pass the device id down to the template
    return render_template("index.html", device_id="esp32-123")

@app.route("/api/gpio", methods=["POST"])
def queue_cmd():
    data = request.get_json(force=True)       # ← JSON or 400
    dev, pin, state = data.get("device"), data.get("pin"), data.get("state")
    if None in (dev, pin, state):
        return {"error": "device, pin, state required"}, 400

    topic   = f"devices/{dev}/cmd"
    payload = json.dumps({"pin": int(pin), "state": int(state)})
    mqttc.publish(topic, payload, qos=1)
    return {"queued": True}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)     # debug=auto-reload
