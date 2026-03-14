import subprocess
import re
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QScrollArea, QGroupBox, QFormLayout, QLabel, QLineEdit, QHBoxLayout, QGridLayout
from PySide6.QtCore import QThread, Signal, Qt
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from datetime import datetime
from collections import Counter

def get_wifi_dump():
    try:
        # Ensure the adb command is executed without showing a window
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "wifi"],
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            startupinfo=si
        )
        return result.stdout
    except Exception as e:
        print("ADB error:", e)
        return ""


def signal_quality(dbm):
    if dbm >= -50:
        return "excellent"
    elif dbm >= -60:
        return "good"
    elif dbm >= -70:
        return "ok"
    else:
        return "weak"


def wifi_band(freq):
    if freq >= 5000:
        return "5GHz"
    return "2.4GHz"


def router_tech_name(val):
    tech = {
        1: "802.11a",
        2: "802.11b",
        3: "802.11g",
        4: "802.11n",
        5: "802.11ac",
        6: "802.11ax"
    }
    return tech.get(val, "unknown")


def parse_wifi_events(log):
    # This pattern is an example. You may need to adjust it based on the actual output of `dumpsys wifi`
    # on your target devices. It's designed to be robust but might not capture all formats.
    pattern = re.compile(
        r'startTime=(?P<time>\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*?'
        r'SSID=(?P<ssid>.*?),\s+'
        r'BSSID=(?P<bssid>[0-9a-fA-F:]+).*?'
        r'durationMillis=(?P<duration>\d+).*?'
        r'signalStrength=(?P<signal>-?\d+).*?'
        r'wifiState=(?P<wifi_state>\w+).*?'
        r'screenOn=(?P<screen>\w+).*?'
        r'mChannelInfo=(?P<channel>\d+).*?'
        r'mRouterTechnology=(?P<tech>\d+)',
        re.DOTALL
    )

    events = []
    # Using finditer to catch all occurrences
    for m in pattern.finditer(log):
        d = m.groupdict()
        try:
            signal = int(d["signal"])
            channel = int(d["channel"])
            tech = int(d["tech"])

            events.append({
                "time": d["time"],
                "ssid": d["ssid"].strip('"'),
                "bssid": d["bssid"],
                "duration_ms": int(d["duration"]),
                "signal_dbm": signal,
                "signal_quality": signal_quality(signal),
                "wifi_state": d["wifi_state"],
                "screen_on": d["screen"] == "true",
                "channel_mhz": channel,
                "band": wifi_band(channel),
                "router_tech": router_tech_name(tech)
            })
        except (ValueError, KeyError) as e:
            print(f"Skipping malformed event entry: {e} in {d}")
            continue

    return events

class WifiWorker(QThread):
    result = Signal(list)
    error = Signal(str)

    def run(self):
        try:
            wifi_log = get_wifi_dump()
            if not wifi_log:
                self.error.emit("No wifi data received from adb.")
                return
            events = parse_wifi_events(wifi_log)
            self.result.emit(events)
        except Exception as e:
            self.error.emit(f"Error fetching wifi data: {e}")

class WifiWidget(QWidget):
    status_update = Signal(str)

    def __init__(self):
        super().__init__()
        self.worker = None
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)

        self.refresh_button = QPushButton("🔃 Refresh Wifi Data")
        self.refresh_button.clicked.connect(self.load_wifi_data)
        layout.addWidget(self.refresh_button)

        # Summary Group Box
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(4)

        field_ss = ("QLineEdit { border: 1px solid #ddd; border-radius: 4px; padding: 2px 6px; background: #ffffff; color: #212121; font-size: 11px; min-height: 20px;} QLineEdit:read-only { background: #f7f9ff; }")
        label_ss = "color: #555; font-size: 11px; font-weight: bold;"

        def _field():
            le = QLineEdit()
            le.setReadOnly(True)
            le.setStyleSheet(field_ss)
            return le

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet(label_ss)
            return l

        self.ssid_label = _field()
        self.bssid_label = _field()
        self.router_tech_label = _field()
        self.band_label = _field()
        self.avg_duration_label = _field()
        self.avg_channel_label = _field()

        # Column 1
        grid_layout.addWidget(_lbl("SSID:"), 0, 0)
        grid_layout.addWidget(self.ssid_label, 0, 1)
        grid_layout.addWidget(_lbl("BSSID:"), 1, 0)
        grid_layout.addWidget(self.bssid_label, 1, 1)
        grid_layout.addWidget(_lbl("Router Tech:"), 2, 0)
        grid_layout.addWidget(self.router_tech_label, 2, 1)

        # Column 2
        grid_layout.addWidget(_lbl("Band:"), 0, 2)
        grid_layout.addWidget(self.band_label, 0, 3)
        grid_layout.addWidget(_lbl("Avg. Connection Duration (ms):"), 1, 2)
        grid_layout.addWidget(self.avg_duration_label, 1, 3)
        grid_layout.addWidget(_lbl("Avg. Channel (MHz):"), 2, 2)
        grid_layout.addWidget(self.avg_channel_label, 2, 3)

        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(3, 1)

        layout.addLayout(grid_layout)

        # Charts Area
        self.charts_container = QWidget()
        self.charts_layout = QVBoxLayout(self.charts_container)
        layout.addWidget(self.charts_container)

    def load_wifi_data(self):
        if self.worker and self.worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Loading...")
        self.status_update.emit("Loading wifi data...")
        self.worker = WifiWorker()
        self.worker.result.connect(self.on_wifi_data_loaded)
        self.worker.error.connect(self.on_wifi_data_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("🔃 Refresh Wifi Data")
        self.worker = None

    def on_wifi_data_error(self, message):
        self.status_update.emit(f"❌ {message}")

    def on_wifi_data_loaded(self, events):
        if not events:
            self.status_update.emit("⚠️ No parsable wifi events found.")
            self.clear_charts()
            return

        self.status_update.emit(f"✅ Loaded {len(events)} wifi events.")

        if events:
            # Update summary labels
            latest_event = events[-1]
            self.ssid_label.setText(latest_event.get("ssid", "N/A"))
            self.bssid_label.setText(latest_event.get("bssid", "N/A"))
            self.router_tech_label.setText(latest_event.get("router_tech", "N/A"))
            self.band_label.setText(latest_event.get("band", "N/A"))

            # Calculate and display averages
            durations = [e['duration_ms'] for e in events if 'duration_ms' in e]
            channels = [e['channel_mhz'] for e in events if 'channel_mhz' in e]

            avg_duration = sum(durations) / len(durations) if durations else 0
            avg_channel = sum(channels) / len(channels) if channels else 0

            self.avg_duration_label.setText(f"{avg_duration:.2f}")
            self.avg_channel_label.setText(f"{avg_channel:.2f}")

            # Display charts
            self.display_charts(events)
        else:
            # Clear labels and charts if no data
            self.ssid_label.setText("N/A")
            self.bssid_label.setText("N/A")
            self.router_tech_label.setText("N/A")
            self.band_label.setText("N/A")
            self.avg_duration_label.setText("N/A")
            self.avg_channel_label.setText("N/A")
            # Clear existing charts
            for i in reversed(range(self.charts_layout.count())):
                widget = self.charts_layout.itemAt(i).widget()
                if widget:
                    widget.deleteLater()

    def clear_charts(self):
        for i in reversed(range(self.charts_layout.count())):
            widgetToRemove = self.charts_layout.itemAt(i).widget()
            self.charts_layout.removeWidget(widgetToRemove)
            widgetToRemove.setParent(None)

    def display_charts(self, events):
        self.clear_charts()

        # Row 1: Signal Strength Over Time and WiFi Usage Frequency
        row1_layout = QHBoxLayout()
        row1_layout.addWidget(self.create_signal_chart(events))
        row1_layout.addWidget(self.create_ssid_chart(events))
        self.charts_layout.addLayout(row1_layout)

        # Row 2: Signal Strength by WiFi and Connection Duration
        row2_layout = QHBoxLayout()
        row2_layout.addWidget(self.create_signal_by_ssid_chart(events))
        row2_layout.addWidget(self.create_duration_chart(events))
        self.charts_layout.addLayout(row2_layout)

    def update_summary(self, events):
        self.clear_summary()

        # Summary statistics
        total_events = len(events)
        unique_ssids = len(set(e["ssid"] for e in events))
        average_signal = sum(e["signal_dbm"] for e in events) / total_events
        average_duration = sum(e["duration_ms"] for e in events) / total_events

        # Add summary fields
        self.add_summary_field("Total Events", total_events)
        self.add_summary_field("Unique SSIDs", unique_ssids)
        self.add_summary_field("Average Signal (dBm)", f"{average_signal:.2f}")
        self.add_summary_field("Average Duration (ms)", f"{average_duration:.2f}")

    def clear_summary(self):
        for i in reversed(range(self.summary_layout.count())):
            self.summary_layout.removeRow(i)

    def add_summary_field(self, label, value):
        self.summary_layout.addRow(QLabel(label), QLabel(str(value)))

    def create_chart_canvas(self, fig, title):
        group = QGroupBox(title)
        layout = QVBoxLayout()
        canvas = FigureCanvas(fig)
        canvas.setFixedHeight(230)
        layout.addWidget(canvas)
        group.setLayout(layout)
        plt.close(fig)
        return group

    def create_signal_chart(self, events):
        fig, ax = plt.subplots(figsize=(8, 4))  # Adjust figsize for landscape aspect ratio
        times = [datetime.strptime(e["time"], "%m-%d %H:%M:%S.%f") for e in events]
        signals = [e["signal_dbm"] for e in events]
        ax.plot(times, signals, marker="o")
        ax.set_xlabel("Time", fontsize=5)
        ax.set_ylabel("Signal (dBm)", fontsize=5)
        ax.grid(True)
        ax.tick_params(axis='x', labelsize=5)
        ax.tick_params(axis='y', labelsize=5)
        fig.autofmt_xdate()
        fig.tight_layout(pad=0.5)
        return self.create_chart_canvas(fig, "Signal Strength Over Time")

    def create_ssid_chart(self, events):
        fig, ax = plt.subplots(figsize=(8, 4))
        ssids = [e["ssid"] for e in events]
        count = Counter(ssids)
        ax.bar(count.keys(), count.values())
        ax.set_xlabel("SSID", fontsize=5)
        ax.set_ylabel("Connections", fontsize=5)
        ax.tick_params(axis='x', labelsize=5)
        ax.tick_params(axis='y', labelsize=5)
        plt.setp(ax.get_xticklabels(), rotation=30, ha='right')
        fig.tight_layout(pad=0.5)
        return self.create_chart_canvas(fig, "WiFi Usage Frequency")

    def create_signal_by_ssid_chart(self, events):
        fig, ax = plt.subplots(figsize=(8, 4))
        ssid = [e["ssid"] for e in events]
        signal = [e["signal_dbm"] for e in events]
        ax.scatter(ssid, signal)
        ax.set_ylabel("Signal (dBm)", fontsize=5)
        ax.tick_params(axis='x', labelsize=5)
        ax.tick_params(axis='y', labelsize=5)
        plt.setp(ax.get_xticklabels(), rotation=30, ha='right')
        fig.tight_layout(pad=0.5)
        return self.create_chart_canvas(fig, "Signal Strength by WiFi")

    def create_duration_chart(self, events):
        fig, ax = plt.subplots(figsize=(8, 4))
        durations = [e["duration_ms"] for e in events]
        ax.bar(range(len(durations)), durations)
        ax.set_xlabel("Connection Event", fontsize=5)
        ax.set_ylabel("Duration (ms)", fontsize=5)
        ax.tick_params(axis='x', labelsize=5)
        ax.tick_params(axis='y', labelsize=5)
        fig.tight_layout(pad=0.5)
        return self.create_chart_canvas(fig, "Connection Duration")
