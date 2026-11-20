# Personal SHT40 Test Reference

This is the local end-to-end test procedure for the Raspberry Pi Pico 2 W, SHT40, Windows PC, phone hotspot, Mosquitto, and Flask service. It contains no Wi-Fi credentials. Do not commit or publish local credential changes in `device/main.py`.

For the quick path, double-click [Run Telemetry.pyw](Run%20Telemetry.pyw) and click **Start telemetry**. The GUI starts or opens the Flask subscriber, shows service status, and provides dashboard/API/export buttons. The Pico runs independently from its boot-time `main.py`. Detailed setup and manual Command Prompt steps are in [README.md](README.md).

## Verified hardware and path

- Board: Raspberry Pi Pico 2 W running MicroPython 1.29.
- Sensor: SHT40 on I2C0, SDA GP4 and SCL GP5, address `0x44`.
- Tested path: SHT40 measurement and CRC check, Pico JSON payload, MQTT publish, Flask subscriber, SQLAlchemy record, and `GET /api/sht40/latest`.
- Pico filesystem needs `lib/umqtt/simple.py` and `main.py`. `main.py` must contain the SHT40 firmware so it publishes whenever the board is powered.

## Before each test

1. Turn on the phone hotspot and connect both the PC and Pico to it. Keep the hotspot active while testing; its local IP addresses can change after reconnecting.
2. Connect the SHT40 to 3V3, GND, GP4 (SDA), and GP5 (SCL).
3. Confirm Mosquitto is running and listening:

   ```powershell
   Get-Service mosquitto
   Get-NetTCPConnection -LocalPort 1883 -State Listen
   ```

4. Find the PC's current Wi-Fi IPv4 address:

   ```powershell
   (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi" | Where-Object AddressState -eq Preferred).IPAddress
   ```

5. In `device/main.py`, set `MQTT_HOST` to that current PC address. The `WIFI_SSID` and `WIFI_PASSWORD` values should match the phone hotspot. Do not put credential values in this document or commit them to GitHub.
6. If Windows Firewall blocks the Pico, use a Private profile and an inbound TCP 1883 rule limited to the local subnet. Do not expose MQTT through router port forwarding or use an open broker on an untrusted network.

## Start the Flask subscriber

Open PowerShell at the project root and run these commands, replacing the IP with the current PC Wi-Fi address:

```powershell
$env:MQTT_HOST = "172.20.10.2"
$env:MQTT_PORT = "1883"
$env:MQTT_TOPIC = "sensors/sht40"
Set-Location server
.\.venv\Scripts\python.exe app.py
```

Leave this terminal running. It uses the normal SQLite database at `server/instance/readings.db`.

## Install and verify the Pico publisher

Connect the Pico by USB once, close Thonny or any other program using `COM3`, and install the boot firmware:

```powershell
server\.venv\Scripts\mpremote.exe connect COM3 mip install umqtt.simple
server\.venv\Scripts\mpremote.exe connect COM3 fs cp device/main.py :main.py
server\.venv\Scripts\mpremote.exe connect COM3 reset
```

Expected serial messages include `Wi-Fi connected` and `Published` with an SHT40 JSON payload. The Pico will continue publishing when the USB cable is unplugged and a 5 V USB adapter supplies power.

## Read the data

In a third PowerShell, check service health, latest reading, and recent history:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod http://127.0.0.1:5000/api/sht40/latest | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://127.0.0.1:5000/api/sht40/readings?limit=20" | ConvertTo-Json -Depth 6
```

Open the dashboard at [http://127.0.0.1:5000/sht40](http://127.0.0.1:5000/sht40). From another device on the same hotspot, replace `127.0.0.1` with the PC's current Wi-Fi IP.

The latest endpoint returns `reading: null` if no message has reached Flask. A populated reading includes `device_id`, `temperature_c`, `humidity_pct`, and the server's UTC `recorded_at` timestamp. SHT40 does not report pressure.

## Quick diagnostics

Check that the Pico can reach the MQTT listener without publishing a message:

```powershell
server\.venv\Scripts\mpremote.exe connect COM3 exec "import socket, sht40_main; s=socket.socket(); s.settimeout(5); s.connect((sht40_main.MQTT_HOST,sht40_main.MQTT_PORT)); print('PICO_TO_BROKER: PASS'); s.close()"
```

- `PICO_TO_BROKER` fails: check that both devices are still on the same hotspot, `MQTT_HOST` is the PC's current Wi-Fi IP, Mosquitto listens on `0.0.0.0:1883`, and the Windows Firewall rule allows the local subnet.
- Pico reports `STAT_NO_AP_FOUND`: check the hotspot SSID, enable 2.4 GHz compatibility if available, and reconnect the Pico.
- Broker works but API is empty: confirm Flask started with the same `MQTT_HOST`, the Flask terminal has no MQTT exception, and the Pico prints `Published`.
- `COM3` is busy: close the serial monitor/Thonny, then retry.

## Stop the test

Press Ctrl+C in the Pico publisher terminal and the Flask terminal. Mosquitto can remain running as a Windows service. Do not copy the edited credential-bearing local file to GitHub.