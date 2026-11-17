"""BME280 MQTT publisher for a Raspberry Pi Pico W (MicroPython).

Wiring: BME280 VIN->3V3, GND->GND, SDA->GP4, SCL->GP5.
Install ``umqtt.simple`` and a MicroPython ``bme280`` driver on the board.
"""
import network
import time
import machine
import ubinascii
import ujson
from umqtt.simple import MQTTClient
import bme280

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
MQTT_HOST = "192.168.1.10"  # broker reachable on the same Wi-Fi network
MQTT_PORT = 1883
MQTT_TOPIC = b"sensors/bme280"
PUBLISH_INTERVAL_S = 10

# On Pico W, GP4/GP5 are I2C0 SDA/SCL respectively.
i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=100_000)
sensor = bme280.BME280(i2c=i2c)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), 20_000)
        while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(250)
    if not wlan.isconnected():
        raise RuntimeError("Wi-Fi connection timed out")
    print("Wi-Fi connected:", wlan.ifconfig()[0])
    return wlan


def read_payload():
    # Common drivers format pressure as either "100653Pa" or "1006.53hPa".
    temperature, pressure, humidity = sensor.values
    if pressure.endswith("hPa"):
        pressure_hpa = float(pressure[:-3])
    elif pressure.endswith("Pa"):
        pressure_hpa = float(pressure[:-2]) / 100.0
    else:
        pressure_hpa = float(pressure)
    return {
        "device_id": ubinascii.hexlify(machine.unique_id()).decode(),
        "sensor_type": "bme280",
        "temperature_c": float(temperature[:-1]),
        "pressure_hpa": pressure_hpa,
        "humidity_pct": float(humidity[:-1]),
    }


def main():
    wlan = None
    client = None
    try:
        wlan = connect_wifi()
        client_id = b"bme280-" + ubinascii.hexlify(machine.unique_id())
        client = MQTTClient(client_id, MQTT_HOST, port=MQTT_PORT, keepalive=60)
        while True:
            try:
                if not wlan.isconnected():
                    wlan = connect_wifi()
                client.connect()
                break
            except OSError as exc:
                print("MQTT connection failed; retrying:", exc)
                time.sleep(5)

        while True:
            try:
                payload = ujson.dumps(read_payload())
                client.publish(MQTT_TOPIC, payload)
                print("Published", payload)
                time.sleep(PUBLISH_INTERVAL_S)
            except OSError as exc:
                print("MQTT/publish error; reconnecting:", exc)
                time.sleep(2)
                try:
                    if not wlan.isconnected():
                        wlan = connect_wifi()
                    client.connect()
                except OSError as reconnect_error:
                    print("Reconnect failed:", reconnect_error)
                    time.sleep(5)
    except KeyboardInterrupt:
        print("BME280 publisher stopped")
    finally:
        if client is not None:
            try:
                client.disconnect()
            except OSError as exc:
                print("MQTT disconnect failed:", exc)
        if wlan is not None:
            wlan.active(False)


if __name__ == "__main__":
    main()

