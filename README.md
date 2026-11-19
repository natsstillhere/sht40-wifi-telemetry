# SHT40 Wi-Fi Telemetry

MicroPython firmware on a Raspberry Pi Pico W or Pico 2 W reads an SHT40 over I2C and publishes JSON over Wi-Fi using MQTT. A Flask service subscribes to MQTT, stores timestamped readings with SQLAlchemy, and serves a web dashboard plus REST endpoints. BME280 firmware and dashboard support are also included, but SHT40 is the default sensor and MQTT topic.

For the step-by-step Windows, Pico 2 W, and phone-hotspot test procedure, see [TESTING.md](TESTING.md).

For personal Windows use, double-click [Run Telemetry.pyw](Run%20Telemetry.pyw) to open the local startup GUI without a console window. It starts Flask and the Pico publisher using the broker settings in `device/sht40_main.py`; it does not display Wi-Fi credentials. [Run Telemetry.vbs](Run%20Telemetry.vbs) and [Run Telemetry.cmd](Run%20Telemetry.cmd) remain available as fallbacks. The command-line setup and manual fallback are in [Windows Command Reference](#windows-command-reference).

## Data flow

```text
SHT40 --I2C GP4/GP5--> Pico W --Wi-Fi/MQTT--> Broker --MQTT--> Flask/SQLAlchemy
                                                               |--> /sht40 dashboard
                                                               `--> /api/sht40/*
```

The SHT40 reports temperature and relative humidity; it does not measure pressure. Each SHT40 message contains `device_id`, `sensor_type`, `temperature_c`, and `humidity_pct`. The server adds a UTC `recorded_at` timestamp when it receives the message.

## 1. Wire the sensor

Use a 3.3 V-compatible SHT40 breakout and connect it while the Pico is unpowered:

| SHT40 | Pico W / Pico 2 W |
| --- | --- |
| VIN / VCC | 3V3(OUT) |
| GND | GND |
| SDA | GP4 (I2C0 SDA) |
| SCL | GP5 (I2C0 SCL) |

The firmware uses the SHT40's standard I2C address `0x44` and performs CRC checks on both measurement values. No SHT40 driver is needed on the board.

## 2. Install and configure MicroPython

1. Install the MicroPython UF2 matching the exact board (Pico W or Pico 2 W) using the Raspberry Pi Pico installation instructions.
2. Install `mpremote` on the computer:

   ```powershell
   py -m pip install mpremote
   ```

3. Edit `device/sht40_main.py`: set `WIFI_SSID`, `WIFI_PASSWORD`, `MQTT_HOST` to the broker computer's LAN IP, and `MQTT_PORT` if the broker does not use 1883. The default topic is `sensors/sht40`.
4. Connect the Pico by USB, install the MQTT client library, copy the SHT40 firmware to the board as `main.py`, and reboot it:

   ```powershell
   mpremote connect auto mip install umqtt.simple
   mpremote connect auto fs cp device/sht40_main.py :main.py
   mpremote connect auto reset
   ```

The board runs `main.py` on boot. To see connection and publish messages, open a serial connection with `mpremote connect auto`. Stop the publisher with Ctrl+C; it attempts to disconnect MQTT and turn off the Wi-Fi interface cleanly.

## 3. Start an MQTT broker

Install an MQTT broker such as Mosquitto on a computer reachable by both the Pico and Flask server. Start the broker with a listener on the LAN interface and port 1883, and allow that port through the computer's firewall. For a local Mosquitto installation, `mosquitto -v` starts it in the foreground with verbose logs.

The broker host in the device firmware and `MQTT_HOST` in the Flask process must both point to the broker's LAN IP address, not `localhost` (unless broker and client are on the same machine). The default configuration uses unencrypted MQTT on port 1883 and is intended only for a trusted network. Configure broker authentication and TLS for networks you do not control; do not commit credentials.

## 4. Set up and run the Flask service

Install Python 3.10 or later. In PowerShell, from the project root:

```powershell
cd server
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:MQTT_HOST = "192.168.1.10"
$env:MQTT_PORT = "1883"
$env:MQTT_TOPIC = "sensors/sht40"
python app.py
```

Replace `192.168.1.10` with the broker's actual LAN IP. If the broker requires credentials, set `$env:MQTT_USERNAME` and `$env:MQTT_PASSWORD` in the same PowerShell session before running the server. `DATABASE_URL` can be set to change the database; by default, SQLite is created at `server/instance/readings.db`. The Flask service creates its table on startup and upgrades an older database lacking `sensor_type` by treating existing rows as BME280 readings.

Open the SHT40 dashboard at `http://127.0.0.1:5000/sht40`. To view it from another device on the LAN, use the computer's LAN IP instead of `127.0.0.1`. The BME280 dashboard is at `/`.

The same settings can be provided through environment variables on other operating systems. `.env.example` lists the server-side variable names and defaults; the application does not automatically load a `.env` file.

## Windows Command Reference

These commands are for Windows Command Prompt (`cmd.exe`) from the project root. They set up the local environment, install the Pico MQTT module, and offer a manual alternative to the GUI. No command below commits or pushes files.

### One-time computer setup

```cmd
py -m venv server\.venv
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
server\.venv\Scripts\python.exe -m pip install mpremote
```

### One-time Pico setup

Connect the Pico by USB, make sure no serial monitor is using its COM port, and run:

```cmd
server\.venv\Scripts\mpremote.exe connect auto mip install umqtt.simple
server\.venv\Scripts\mpremote.exe connect auto fs cp device\sht40_main.py :sht40_main.py
```

Keep the firmware named `sht40_main.py` on the Pico for GUI/manual testing; do not copy it to `main.py` unless you explicitly want it to start automatically at boot.

### Normal startup

1. Connect the PC and Pico to the same phone hotspot.
2. Ensure Mosquitto is running with a LAN listener on port 1883 and that the firewall allows the Pico on the trusted local network.
3. Keep the local `MQTT_HOST` in `device/sht40_main.py` set to the PC's current Wi-Fi IP. Keep the hotspot Wi-Fi values in that file local; do not commit or publish them.
4. Double-click `Run Telemetry.pyw` to use the GUI with no console pop-up. Use `Run Telemetry.vbs` or `Run Telemetry.cmd` as fallbacks. Click **Start telemetry**; the GUI checks Mosquitto, starts Flask, and opens the Pico publisher in a separate console. Use the GUI buttons to open the dashboard/latest JSON or stop the processes.

### Manual Command Prompt fallback

In the first Command Prompt, replace `PC_WIFI_IP` with the current address shown by `ipconfig` under the Wi-Fi adapter:

```cmd
set "MQTT_HOST=PC_WIFI_IP"
set "MQTT_PORT=1883"
set "SHT40_MQTT_TOPIC=sensors/sht40"
cd /d "C:\Users\horuas\Documents\Mechatronics Project\server"
.venv\Scripts\python.exe app.py
```

In a second Command Prompt opened at the project root, run:

```cmd
server\.venv\Scripts\mpremote.exe connect auto run device\sht40_main.py
```

Use a third Command Prompt to inspect readings:

```cmd
curl.exe http://127.0.0.1:5000/api/health
curl.exe http://127.0.0.1:5000/api/sht40/latest
curl.exe "http://127.0.0.1:5000/api/sht40/readings?limit=20"
```

The dashboard is at `http://127.0.0.1:5000/sht40`. Stop a manual Pico run with Ctrl+C in its console and stop Flask with Ctrl+C in its console.

## 5. Verify the end-to-end flow

Check service health and confirm that MQTT is configured:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
```

After the Pico publishes, request the newest reading and recent history:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/sht40/latest
Invoke-RestMethod "http://127.0.0.1:5000/api/sht40/readings?limit=20"
```

`/api/sht40/latest` returns `{"reading": null}` until a reading arrives. The history endpoint returns `{"readings": [...]}`. Both history routes accept `limit` (1-1000), optional `device_id`, and optional ISO 8601 `since` query parameters.

## REST API

| Method and path | Description |
| --- | --- |
| `GET /api/health` | Flask status and whether an MQTT host is configured |
| `GET /api/sht40/latest` | Most recent SHT40 reading, or a null reading |
| `GET /api/sht40/readings` | SHT40 history; supports `limit`, `device_id`, and `since` |
| `GET /api/latest` | Most recent BME280 reading |
| `GET /api/readings` | BME280 history; supports `limit`, `device_id`, and `since` |

The SHT40 web dashboard is `GET /sht40`; the BME280 dashboard is `GET /`.

## Optional BME280

`device/main.py` publishes to `sensors/bme280` and requires a MicroPython `bme280` driver in addition to `umqtt.simple`. Set its Wi-Fi and broker values, copy it to the board as `main.py` instead of `sht40_main.py`, and use the BME280 wiring (VIN, GND, SDA to GP4, SCL to GP5). Its dashboard and API endpoints are listed above. Do not copy both firmware scripts to the board as `main.py`.

## Troubleshooting

- **Wi-Fi timeout:** check the SSID/password and ensure the network is 2.4 GHz; Pico W does not connect to 5 GHz-only Wi-Fi.
- **MQTT connection retries:** verify the broker is running, both clients use its LAN IP and port, and firewall rules allow the connection.
- **No SHT40 data:** check 3.3 V/GND and GP4/GP5, confirm the sensor is at address `0x44`, and inspect the Pico serial output for CRC or I2C errors.
- **Health reports MQTT unconfigured:** set `MQTT_HOST` in the same shell that starts `python app.py`.
- **Dashboard has no readings:** inspect Flask and broker logs, then check `/api/sht40/latest` to distinguish missing messages from a dashboard issue.

## Project files

- `device/sht40_main.py` - primary SHT40 MicroPython publisher.
- `device/main.py` - optional BME280 MicroPython publisher.
- `server/app.py` - Flask dashboard routes, REST API, MQTT subscriber, and SQLAlchemy model.
- `server/templates/` - sensor dashboards.
- `server/requirements.txt` - Flask, Flask-SQLAlchemy, and Paho MQTT dependencies.
- `CHANGELOG.txt` - human-readable project change record.