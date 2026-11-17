"""SHT40 MQTT publisher for Raspberry Pi Pico W / Pico 2 W (MicroPython).

Wiring: SHT40 VIN->3V3, GND->GND, SDA->GP4, SCL->GP5.
Uses the SHT40's standard I2C commands directly; no sensor driver needed.
Publishes SHT40-specific temperature/humidity data to the Flask service.
"""
import machine
import network
import time
import ubinascii
import ujson
from umqtt.simple import MQTTClient

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
MQTT_HOST = "192.168.1.10"
MQTT_PORT = 1883
MQTT_TOPIC = b"sensors/sht40"
PUBLISH_INTERVAL_S = 10

SHT40_ADDRESS = 0x44
SHT40_MEASURE_HIGH_PRECISION = 0xFD

i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=100_000)


def crc8(data):
    """Sensirion CRC-8: polynomial 0x31, initial value 0xFF."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def read_measurement():
    i2c.writeto(SHT40_ADDRESS, bytes((SHT40_MEASURE_HIGH_PRECISION,)))
    time.sleep_ms(10)  # high-precision measurement conversion time
    data = i2c.readfrom(SHT40_ADDRESS, 6)
    if crc8(data[0:2]) != data[2] or crc8(data[3:5]) != data[5]:
        raise OSError("SHT40 CRC check failed")

    raw_temperature = (data[0] << 8) | data[1]
    raw_humidity = (data[3] << 8) | data[4]
    temperature_c = -45.0 + 175.0 * raw_temperature / 65535.0
    humidity_pct = -6.0 + 125.0 * raw_humidity / 65535.0
    humidity_pct = min(100.0, max(0.0, humidity_pct))
    return temperature_c, humidity_pct


def read_payload():
    temperature_c, humidity_pct = read_measurement()
    return {
        "device_id": ubinascii.hexlify(machine.unique_id()).decode(),
        "sensor_type": "sht40",
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
    }


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


def main():
    wlan = None
    client = None
    try:
        wlan = connect_wifi()
        client_id = b"sht40-" + ubinascii.hexlify(machine.unique_id())
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
                print("Sensor/MQTT error; reconnecting:", exc)
                time.sleep(2)
                try:
                    if not wlan.isconnected():
                        wlan = connect_wifi()
                    client.connect()
                except OSError as reconnect_error:
                    print("Reconnect failed:", reconnect_error)
                    time.sleep(5)
    except KeyboardInterrupt:
        print("SHT40 publisher stopped")
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
