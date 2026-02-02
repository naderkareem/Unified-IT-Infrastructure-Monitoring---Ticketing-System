import random
import threading
import time
import redis
from flask_cors import CORS



from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

# -------------------------------------------------
# App & Database Setup
# -------------------------------------------------
app = Flask(__name__)
CORS(app)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///monitoring.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

redis_client = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
)

# -------------------------------------------------
# Database Models
# -------------------------------------------------
class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default="UP")


class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(200))
    severity = db.Column(db.String(20))


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, nullable=False)
    alert_id = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(200))
    status = db.Column(db.String(20), default="OPEN")
    created_at = db.Column(db.DateTime, default=db.func.now())

# -------------------------------------------------
# Monitoring Thread (Producer)
# -------------------------------------------------
def monitor_devices():
    with app.app_context():
        while True:
            time.sleep(10)

            devices = Device.query.all()
            for device in devices:
                old_status = device.status
                device.status = random.choice(["UP", "DOWN"])

                if old_status == "UP" and device.status == "DOWN":
                    alert_data = {
                        "device_id": device.id,
                        "message": f"{device.name} is DOWN",
                        "severity": "CRITICAL"
                    }
                    redis_client.xadd("alert_stream", alert_data)

            db.session.commit()
            print("Monitoring cycle completed")

# -------------------------------------------------
# Alert Worker (Consumer)
# -------------------------------------------------
def alert_worker():
    with app.app_context():
        last_id = "0"

        while True:
            messages = redis_client.xread(
                {"alert_stream": last_id},
                block=5000
            )

            for stream, msgs in messages:
                for msg_id, data in msgs:
                    alert = Alert(
                        device_id=data["device_id"],
                        message=data["message"],
                        severity=data["severity"]
                    )
                    db.session.add(alert)
                    db.session.commit()

                    ticket = Ticket(
                        device_id=alert.device_id,
                        alert_id=alert.id,
                        description=alert.message
                    )
                    db.session.add(ticket)
                    db.session.commit()

                    print("Ticket created for alert:", alert.id)
                    last_id = msg_id

# -------------------------------------------------
# API Routes
# -------------------------------------------------
@app.route("/devices", methods=["GET"])
def get_devices():
    devices = Device.query.all()
    return jsonify([
        {
            "id": d.id,
            "name": d.name,
            "type": d.type,
            "status": d.status
        } for d in devices
    ])


@app.route("/devices", methods=["POST"])
def add_device():
    data = request.get_json()

    if not data or "name" not in data or "type" not in data:
        return jsonify({"error": "Invalid input"}), 400

    device = Device(
        name=data["name"],
        type=data["type"]
    )

    db.session.add(device)
    db.session.commit()

    return jsonify({
        "id": device.id,
        "name": device.name,
        "type": device.type,
        "status": device.status
    }), 201


@app.route("/tickets", methods=["GET"])
def get_tickets():
    tickets = Ticket.query.all()
    return jsonify([
        {
            "id": t.id,
            "device_id": t.device_id,
            "alert_id": t.alert_id,
            "description": t.description,
            "status": t.status,
            "created_at": t.created_at
        } for t in tickets
    ])


@app.route("/tickets/<int:ticket_id>", methods=["PUT"])
def update_ticket(ticket_id):
    data = request.get_json()
    ticket = Ticket.query.get(ticket_id)

    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    if "status" in data:
        ticket.status = data["status"]

    db.session.commit()

    return jsonify({
        "message": "Ticket updated",
        "status": ticket.status
    })

# -------------------------------------------------
# App Start
# -------------------------------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    threading.Thread(target=monitor_devices, daemon=True).start()
    threading.Thread(target=alert_worker, daemon=True).start()

    app.run(debug=True)
