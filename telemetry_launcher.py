"""Local Windows controller for the SHT40 telemetry test setup."""
import ast
import json
import os
import queue
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


ROOT = Path(__file__).resolve().parent
DEVICE_FILE = ROOT / "device" / "sht40_main.py"
SERVER_DIR = ROOT / "server"
PYTHON = SERVER_DIR / ".venv" / "Scripts" / "python.exe"
MPREMOTE = SERVER_DIR / ".venv" / "Scripts" / "mpremote.exe"
HEALTH_URL = "http://127.0.0.1:5000/api/health"
DASHBOARD_URL = "http://127.0.0.1:5000/sht40"
LATEST_URL = "http://127.0.0.1:5000/api/sht40/latest"
EXPORT_URL = "http://127.0.0.1:5000/api/sht40/export.txt"


def read_device_settings():
    tree = ast.parse(DEVICE_FILE.read_text(encoding="utf-8"))
    settings = {}
    wanted = {"MQTT_HOST", "MQTT_PORT", "MQTT_TOPIC"}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            settings[target.id] = ast.literal_eval(node.value)
    host = settings.get("MQTT_HOST", "")
    topic = settings.get("MQTT_TOPIC", b"sensors/sht40")
    if isinstance(topic, bytes):
        topic = topic.decode("ascii")
    return host, int(settings.get("MQTT_PORT", 1883)), topic


def get_health():
    with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as response:
        return json.loads(response.read().decode("utf-8"))


class TelemetryLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("SHT40 Telemetry")
        self.root.geometry("660x520")
        self.root.minsize(600, 480)
        self.root.configure(bg="#f2f5f4")

        self.events = queue.Queue()
        self.server_process = None
        self.publisher_process = None
        self.starting = False
        self.status_values = {}
        self.status_labels = {}

        self._build_ui()
        self._refresh_status()
        self.root.after(150, self._drain_events)
        self.root.after(2500, self._periodic_refresh)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background="#f2f5f4")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f2f5f4", foreground="#18332f",
                        font=("Segoe UI", 19, "bold"))
        style.configure("Subtitle.TLabel", background="#f2f5f4", foreground="#52625f",
                        font=("Segoe UI", 10))
        style.configure("PanelTitle.TLabel", background="#ffffff", foreground="#18332f",
                        font=("Segoe UI", 10, "bold"))
        style.configure("Body.TLabel", background="#ffffff", foreground="#263532",
                        font=("Segoe UI", 10))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))

        page = ttk.Frame(self.root, style="App.TFrame", padding=(22, 18))
        page.pack(fill="both", expand=True)

        ttk.Label(page, text="SHT40 Telemetry", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="Pico 2 W  |  Local MQTT, Flask and readings",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(2, 14))

        panel = ttk.Frame(page, style="Panel.TFrame", padding=(16, 12))
        panel.pack(fill="x")
        ttk.Label(panel, text="SYSTEM STATUS", style="PanelTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 7))
        for row, (key, title) in enumerate((
                ("broker", "Mosquitto broker"),
                ("flask", "Flask API"),
                ("publisher", "Pico publisher")), start=1):
            ttk.Label(panel, text=title, style="Body.TLabel").grid(
                row=row, column=0, sticky="w", pady=3)
            value = tk.StringVar(value="Checking")
            label = ttk.Label(panel, textvariable=value, style="Body.TLabel")
            label.grid(row=row, column=1, sticky="e", padx=(24, 0), pady=3)
            self.status_values[key] = value
            self.status_labels[key] = label
        panel.columnconfigure(0, weight=1)

        actions = ttk.Frame(page, style="App.TFrame")
        actions.pack(fill="x", pady=(14, 8))
        self.start_button = ttk.Button(actions, text="Start telemetry",
                                       style="Primary.TButton", command=self.start_all)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Stop", command=self.stop_all)
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Refresh", command=self._refresh_status).pack(
            side="right")

        links = ttk.Frame(page, style="App.TFrame")
        links.pack(fill="x", pady=(0, 10))
        ttk.Button(links, text="Open dashboard", command=lambda: self._open(DASHBOARD_URL)).pack(
            side="left")
        ttk.Button(links, text="Latest JSON reading", command=lambda: self._open(LATEST_URL)).pack(
            side="left", padx=(8, 0))
        ttk.Button(links, text="Export TXT", command=self._export_readings).pack(
            side="left", padx=(8, 0))

        ttk.Label(page, text="ACTIVITY", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 4))
        log_frame = ttk.Frame(page, style="Panel.TFrame", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=9, wrap="word", state="disabled",
                           bg="#ffffff", fg="#263532", relief="flat",
                           font=("Consolas", 9), padx=4, pady=4)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(page, text="Wi-Fi credentials stay in device/sht40_main.py and are not shown here.",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(9, 0))

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, key, text, good=None):
        self.status_values[key].set(text)
        color = "#28745c" if good else "#9b5b23" if good is False else "#52625f"
        self.status_labels[key].configure(foreground=color)

    def _broker_reachable(self):
        host, port, _ = read_device_settings()
        if not host or host == "192.168.1.10":
            return False
        try:
            with socket.create_connection((host, port), timeout=0.8):
                return True
        except OSError:
            return False

    def _refresh_status(self):
        try:
            service = subprocess.run(["sc.exe", "query", "mosquitto"],
                                     capture_output=True, text=True, timeout=2)
            broker_running = "RUNNING" in service.stdout
            broker_reachable = self._broker_reachable()
            if broker_reachable:
                self._set_status("broker", "Reachable", True)
            elif broker_running:
                self._set_status("broker", "Running, not reachable", False)
            else:
                self._set_status("broker", "Not running", False)
        except (OSError, subprocess.SubprocessError, SyntaxError, ValueError):
            self._set_status("broker", "Check configuration", False)

        try:
            health = get_health()
            configured = health.get("mqtt_configured", False)
            self._set_status("flask", "Online" if configured else "Online, MQTT off", configured)
        except (OSError, urllib.error.URLError, ValueError):
            self._set_status("flask", "Offline", False)

        publisher_running = self.publisher_process is not None and self.publisher_process.poll() is None
        self._set_status("publisher", "Running" if publisher_running else "Stopped",
                         publisher_running)

    def _periodic_refresh(self):
        self._refresh_status()
        self.root.after(2500, self._periodic_refresh)

    def _drain_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._append_log(value)
                elif kind == "error":
                    self._append_log("ERROR: " + value)
                    messagebox.showerror("Telemetry could not start", value, parent=self.root)
                elif kind == "started":
                    self._append_log(value)
                elif kind == "ready":
                    self.starting = False
                    self.start_button.state(["!disabled"])
                    self._refresh_status()
        except queue.Empty:
            pass
        self.root.after(150, self._drain_events)

    def start_all(self):
        if self.starting:
            return
        self.starting = True
        self.start_button.state(["disabled"])
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        try:
            if not PYTHON.is_file() or not MPREMOTE.is_file():
                raise RuntimeError("Project environment is missing. Follow the setup commands in README.md first.")
            host, port, topic = read_device_settings()
            if not host or host == "192.168.1.10":
                raise RuntimeError("Set MQTT_HOST in device/sht40_main.py to the broker's current LAN IP.")
            try:
                with socket.create_connection((host, port), timeout=2):
                    pass
            except OSError:
                raise RuntimeError("Cannot reach the MQTT broker. Check the hotspot, Mosquitto listener, and firewall.")

            try:
                health = get_health()
                if not health.get("mqtt_configured", False):
                    raise RuntimeError("Flask is already running with MQTT disabled. Stop it, then start from this window.")
                self.events.put(("log", "Using the running Flask API."))
            except (OSError, urllib.error.URLError, ValueError):
                env = os.environ.copy()
                env["MQTT_HOST"] = host
                env["MQTT_PORT"] = str(port)
                env["SHT40_MQTT_TOPIC"] = topic
                env["PORT"] = "5000"
                env.pop("DATABASE_URL", None)
                self.server_process = subprocess.Popen(
                    [str(PYTHON), "app.py"], cwd=str(SERVER_DIR), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                threading.Thread(target=self._read_server_output, daemon=True).start()
                self.events.put(("log", "Starting Flask API..."))
                for _ in range(30):
                    if self.server_process.poll() is not None:
                        raise RuntimeError("Flask exited during startup. Check the activity log.")
                    try:
                        health = get_health()
                        if health.get("mqtt_configured", False):
                            break
                    except (OSError, urllib.error.URLError, ValueError):
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError("Flask did not become ready within 15 seconds.")
                self.events.put(("log", "Flask API is ready."))

            if self.publisher_process is None or self.publisher_process.poll() is not None:
                flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                self.publisher_process = subprocess.Popen(
                    [str(MPREMOTE), "connect", "auto", "run", str(DEVICE_FILE)],
                    cwd=str(ROOT), creationflags=flags)
                self.events.put(("log", "Pico publisher started in its own console window."))
            self.events.put(("started", "Telemetry started. Open the dashboard to view readings."))
        except (OSError, SyntaxError, ValueError, RuntimeError) as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("ready", ""))

    def _read_server_output(self):
        process = self.server_process
        if process is not None and process.stdout is not None:
            for line in process.stdout:
                self.events.put(("log", "Flask: " + line.rstrip()))

    def stop_all(self):
        publisher = self.publisher_process
        if publisher is not None and publisher.poll() is None:
            try:
                publisher.send_signal(signal.CTRL_BREAK_EVENT)
                self._append_log("Stop requested for Pico publisher. Check its console for exit status.")
            except (OSError, ValueError, AttributeError):
                publisher.terminate()
                self._append_log("Pico publisher process stopped.")
        server = self.server_process
        if server is not None and server.poll() is None:
            server.terminate()
            self._append_log("Flask API stopped.")
        self._refresh_status()

    def _open(self, url):
        webbrowser.open(url)

    def _export_readings(self):
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export SHT40 readings",
            defaultextension=".txt",
            initialfile="sht40_readings.txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not destination:
            return
        try:
            with urllib.request.urlopen(EXPORT_URL, timeout=10) as response:
                content = response.read()
            Path(destination).write_bytes(content)
            self._append_log(f"Exported SHT40 readings to {destination}")
            messagebox.showinfo("Export complete", f"Saved {len(content)} bytes to:\n{destination}", parent=self.root)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            self._append_log("ERROR: Could not export readings: " + str(exc))
            messagebox.showerror("Export failed", "Start Flask and try again.\n" + str(exc), parent=self.root)

    def _close(self):
        self.stop_all()
        self.root.destroy()


def main():
    root = tk.Tk()
    TelemetryLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()