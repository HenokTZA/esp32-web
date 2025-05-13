"""from flask import Flask, request, jsonify, render_template
import paho.mqtt.client as mqtt
import os, json

BROKER   = "147.93.127.215"
PORT     = 1883
USER     = os.getenv("MQTT_USER", "iotuser")
PASSWORD = os.getenv("MQTT_PASS", "secretpass")

mqttc = mqtt.Client(callback_api_version=1)
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
    app.run(host="0.0.0.0", port=5000, debug=True)     # debug=auto-reload"""

# app.py
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
import paho.mqtt.client as mqtt
import os, json, threading, time

BROKER   = "147.93.127.215"
PORT     = 1883
USER     = os.getenv("MQTT_USER", "iotuser")
PASSWORD = os.getenv("MQTT_PASS", "secretpass")

# In-memory user store: { email: {first, last, pw_hash} }
users = {}

# In‐memory store of devices → status
devices = {}          # e.g. { "esp32-123": "online", ... }
devices_lock = threading.Lock()

telemetry = {}      # { device_id: {volt, curr, temp, ts} }
tele_lock = threading.Lock()

def on_mqtt_connect(client, userdata, flags, rc):
    client.subscribe([
        ("devices/+/status", 0),
        ("devices/+/tele",   0),        # NEW
        ("devices/+/ip",     0),
    ])

def on_mqtt_message(client, userdata, msg):
    topic = msg.topic              # e.g. "devices/esp32-123/status" or ".../tele"
    parts = topic.split("/")
    # only handle topics of form devices/<device_id>/<kind>
    if len(parts) != 3 or parts[0] != "devices":
        return

    dev, kind = parts[1], parts[2]

    if kind == "status":
        status = msg.payload.decode()   # "online" or "offline"
        with devices_lock:
            if status == "offline":
                devices.pop(dev, None)
            else:
                devices[dev] = status

    elif kind == "tele":
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return  # invalid JSON, ignore

        # store the latest telemetry + a timestamp
        with tele_lock:
            existing = telemetry.get(dev, {})
            existing.update({
                "voltage":     data.get("voltage"),
                "current":     data.get("current"),
                "temperature": data.get("temperature"),
                "ts":          time.time()
            })
            telemetry[dev] = existing


    elif kind == "ip":
        # decode the IP string
        ip_str = msg.payload.decode()
        # store it alongside tele data
        with tele_lock:
            telemetry.setdefault(dev, {})["ip"] = ip_str


mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
mqttc.username_pw_set(USER, PASSWORD)
mqttc.on_connect = on_mqtt_connect
mqttc.on_message = on_mqtt_message
mqttc.connect(BROKER, PORT)
mqttc.loop_start()                       # background thread

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'replace-with-a-secure-random-string')  # for session

@app.route("/")
def select_device():
    # Show page listing all online devices
    with devices_lock:
        dev_list = dict(devices)
    return render_template("devices.html", devices=dev_list)

@app.route("/device/<device_id>")
def control_device(device_id):
    # If device isn't known/online, redirect back
    with devices_lock:
        if device_id not in devices:
            return redirect(url_for("select_device"))
    return render_template("device.html", device_id=device_id)

@app.route("/api/telemetry/<device_id>")
def get_telemetry(device_id):
    with tele_lock:
        data = telemetry.get(device_id)
    return (jsonify(data) if data else ("{}", 404))


@app.route("/api/gpio", methods=["POST"])
def queue_cmd():
    data = request.get_json(force=True)
    dev, pin, state = data.get("device"), data.get("pin"), data.get("state")
    if None in (dev, pin, state):
        return {"error": "device, pin, state required"}, 400
    topic   = f"devices/{dev}/cmd"
    payload = json.dumps({"pin": int(pin), "state": int(state)})
    mqttc.publish(topic, payload, qos=1)
    return {"queued": True}, 200

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        fn = request.form.get('first_name','').strip()
        ln = request.form.get('last_name','').strip()
        email = request.form.get('email','').strip().lower()
        pw = request.form.get('password','')
        cpw = request.form.get('confirm_password','')
        sec = request.form.get('security_number','')
        
        # Validation
        if not all([fn,ln,email,pw,cpw,sec]):
            flash('All fields are required','error')
        elif sec != '1234':
            flash('Invalid signup security number','error')
        elif pw != cpw:
            flash('Passwords do not match','error')
        elif email in users:
            flash('Email already registered','error')
        else:
            # In real life, hash pw! Here store plain for demo
            users[email] = {'first':fn,'last':ln,'pw':pw}
            flash('Registration successful. Please log in.','success')
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        pw = request.form.get('password','')
        user = users.get(email)
        if not user or user['pw'] != pw:
            flash('Invalid email/password','error')
        else:
            session['user_email'] = email
            return redirect(url_for('select_device'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))



# Protect your existing dashboard routes:
@app.before_request
def require_login():
    auth_paths = ['/login','/signup','/static/','/api/telemetry']
    if any(request.path.startswith(p) for p in auth_paths):
        return
    if 'user_email' not in session:
        return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

