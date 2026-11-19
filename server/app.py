import json
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, render_template, request, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect

db = SQLAlchemy()


class Reading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), nullable=False, index=True)
    sensor_type = db.Column(db.String(16), nullable=False, default="bme280", server_default="bme280", index=True)
    temperature_c = db.Column(db.Float, nullable=False)
    pressure_hpa = db.Column(db.Float, nullable=True)
    humidity_pct = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    def as_dict(self):
        stamp = self.recorded_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return {
            "id": self.id,
            "device_id": self.device_id,
            "sensor_type": self.sensor_type,
            "temperature_c": self.temperature_c,
            "pressure_hpa": self.pressure_hpa,
            "humidity_pct": self.humidity_pct,
            "recorded_at": stamp.isoformat(),
        }


def _save_payload(payload, topic_sensor_type, application):
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")
    sensor_type = topic_sensor_type
    if payload.get("sensor_type", sensor_type) != sensor_type:
        raise ValueError("Payload sensor_type does not match its MQTT topic")
    if sensor_type not in ("bme280", "sht40"):
        raise ValueError("sensor_type must be bme280 or sht40")
    required = ("device_id", "temperature_c", "humidity_pct")
    if sensor_type == "bme280":
        required += ("pressure_hpa",)
    if any(key not in payload for key in required):
        raise ValueError("Payload is missing required fields for " + sensor_type)
    reading = Reading(
        device_id=str(payload["device_id"])[:64],
        sensor_type=sensor_type,
        temperature_c=float(payload["temperature_c"]),
        pressure_hpa=(float(payload["pressure_hpa"])
                      if sensor_type == "bme280" and payload["pressure_hpa"] is not None else None),
        humidity_pct=float(payload["humidity_pct"]),
        recorded_at=datetime.now(timezone.utc),
    )
    with application.app_context():
        db.session.add(reading)
        db.session.commit()


def _start_mqtt(app):
    host = app.config["MQTT_HOST"]
    if not host:
        app.logger.info("MQTT_HOST is unset; MQTT subscriber is disabled")
        return

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            topics = (app.config["MQTT_TOPIC"], app.config["SHT40_MQTT_TOPIC"])
            client.subscribe([(topic, 0) for topic in topics])
            app.logger.info("Subscribed to %s and %s", *topics)
        else:
            app.logger.error("MQTT connection refused: %s", reason_code)

    def on_message(client, userdata, message):
        try:
            topic_sensor_type = "sht40" if message.topic.endswith("/sht40") else "bme280"
            _save_payload(json.loads(message.payload.decode("utf-8")), topic_sensor_type, app)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            app.logger.warning("Ignoring invalid MQTT message: %s", exc)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="telemetry-flask")
    username, password = app.config["MQTT_USERNAME"], app.config["MQTT_PASSWORD"]
    if username:
        client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(host, app.config["MQTT_PORT"], 60)
    client.loop_start()
    app.extensions["mqtt_client"] = client


def create_app(test_config=None):
    application = Flask(__name__)
    application.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///readings.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MQTT_HOST=os.getenv("MQTT_HOST", ""),
        MQTT_PORT=int(os.getenv("MQTT_PORT", "1883")),
        MQTT_TOPIC=os.getenv("MQTT_TOPIC", "sensors/bme280"),
        SHT40_MQTT_TOPIC=os.getenv("SHT40_MQTT_TOPIC", "sensors/sht40"),
        MQTT_USERNAME=os.getenv("MQTT_USERNAME", ""),
        MQTT_PASSWORD=os.getenv("MQTT_PASSWORD", ""),
    )
    if test_config:
        application.config.update(test_config)
    db.init_app(application)
    with application.app_context():
        db.create_all()
        # Upgrade existing databases from the version without sensor_type;
        # their existing rows are BME280 readings.
        columns = {column["name"] for column in inspect(db.engine).get_columns("reading")}
        if "sensor_type" not in columns:
            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE reading ADD COLUMN sensor_type VARCHAR(16) NOT NULL DEFAULT 'bme280'"
                )

    @application.get("/")
    def dashboard():
        return render_template("index.html")

    @application.get("/sht40")
    def sht40_dashboard():
        return render_template("sht40.html")

    @application.get("/api/readings")
    def readings():
        limit = min(max(request.args.get("limit", default=100, type=int), 1), 1000)
        query = Reading.query.filter_by(sensor_type="bme280")
        device_id = request.args.get("device_id")
        if device_id:
            query = query.filter_by(device_id=device_id)
        since = request.args.get("since")
        if since:
            try:
                parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                query = query.filter(Reading.recorded_at >= parsed)
            except ValueError:
                return jsonify(error="since must be an ISO 8601 timestamp"), 400
        rows = query.order_by(Reading.recorded_at.desc()).limit(limit).all()
        return jsonify(readings=[row.as_dict() for row in rows])

    @application.get("/api/latest")
    def latest():
        row = Reading.query.filter_by(sensor_type="bme280").order_by(Reading.recorded_at.desc()).first()
        return (jsonify(reading=row.as_dict()), 200) if row else (jsonify(reading=None), 200)

    @application.get("/api/sht40/readings")
    def sht40_readings():
        limit = min(max(request.args.get("limit", default=100, type=int), 1), 1000)
        query = Reading.query.filter_by(sensor_type="sht40")
        device_id = request.args.get("device_id")
        if device_id:
            query = query.filter_by(device_id=device_id)
        since = request.args.get("since")
        if since:
            try:
                parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                query = query.filter(Reading.recorded_at >= parsed)
            except ValueError:
                return jsonify(error="since must be an ISO 8601 timestamp"), 400
        rows = query.order_by(Reading.recorded_at.desc()).limit(limit).all()
        return jsonify(readings=[row.as_dict() for row in rows])

    @application.get("/api/sht40/latest")
    def sht40_latest():
        row = Reading.query.filter_by(sensor_type="sht40").order_by(Reading.recorded_at.desc()).first()
        return (jsonify(reading=row.as_dict()), 200) if row else (jsonify(reading=None), 200)

    @application.get("/api/sht40/export.txt")
    def sht40_export_txt():
        query = Reading.query.filter_by(sensor_type="sht40")
        device_id = request.args.get("device_id")
        if device_id:
            query = query.filter_by(device_id=device_id)
        since = request.args.get("since")
        if since:
            try:
                parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                query = query.filter(Reading.recorded_at >= parsed)
            except ValueError:
                return jsonify(error="since must be an ISO 8601 timestamp"), 400

        rows = query.order_by(Reading.recorded_at.asc()).all()
        lines = [
            "SHT40 telemetry export",
            "recorded_at_utc\tdevice_id\ttemperature_c\thumidity_pct",
        ]
        for row in rows:
            stamp = row.recorded_at
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            lines.append(
                f"{stamp.isoformat()}\t{row.device_id}\t"
                f"{row.temperature_c:.2f}\t{row.humidity_pct:.2f}"
            )
        filename = datetime.now(timezone.utc).strftime("sht40_readings_%Y%m%d_%H%M%S.txt")
        return Response(
            "\n".join(lines) + "\n",
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @application.get("/api/health")
    def health():
        return jsonify(status="ok", mqtt_configured=bool(application.config["MQTT_HOST"]))

    if application.config.get("START_MQTT", True):
        _start_mqtt(application)
    return application


app = create_app()

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
    finally:
        client = app.extensions.get("mqtt_client")
        if client is not None:
            try:
                client.loop_stop()
            finally:
                client.disconnect()
