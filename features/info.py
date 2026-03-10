from __future__ import annotations

import subprocess, os, re, time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QCheckBox, QComboBox, QScrollArea, QFrame, QSizePolicy,
    QFileDialog, QSpinBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor

# ── ADB bootstrap ────────────────────────────────────────────────────────
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

def _run(serial: str, *args: str, timeout: int = 10) -> str:
    """Run an adb command and return stripped stdout (never raises)."""
    try:
        r = subprocess.run(
            ["adb", "-s", serial, *args],
            startupinfo=_si,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""

def _shell(serial: str, cmd: str, timeout: int = 10) -> str:
    return _run(serial, "shell", cmd, timeout=timeout)

def _prop(serial: str, key: str) -> str:
    return _shell(serial, f"getprop {key}")

def _first(*values: str) -> str:
    """Return the first non-empty, non-placeholder value."""
    _bad = {"", "null", "n/a", "unknown", "0", "(null)", "unavailable"}
    for v in values:
        v = (v or "").strip()
        if v and v.lower() not in _bad:
            return v
    return ""

def _re_first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""

# ── Background fetch worker ──────────────────────────────────────────────
class _FetchWorker(QThread):
    result = Signal(dict)
    error  = Signal(str)

    def __init__(self, serial: str, manual_wifi: str = ""):
        super().__init__()
        self.serial = serial
        self.manual_wifi = manual_wifi

    def run(self):
        try:
            s = self.serial
            # ── Grab the entire prop table once (single fast call) ────────
            all_props_raw = _shell(s, "getprop", timeout=12)
            props: dict[str, str] = {}
            for line in all_props_raw.splitlines():
                m = re.match(r"\[([^\]]+)\]\s*:\s*\[([^\]]*)\]", line)
                if m:
                    props[m.group(1)] = m.group(2).strip()

            def p(*keys: str) -> str:
                _bad = {"", "null", "unknown", "0"}
                for k in keys:
                    v = props.get(k, "").strip()
                    if v and v.lower() not in _bad:
                        return v
                return ""

            # ── Basic device ──────────────────────────────────────────────
            brand        = _first(p("ro.product.brand", "ro.product.vendor.brand"))
            model        = _first(p("ro.product.model", "ro.product.vendor.model"))
            manufacturer = _first(p("ro.product.manufacturer", "ro.product.vendor.manufacturer"))
            android_os   = _first(p("ro.build.version.release", "ro.system.build.version.release"))
            sdk          = _first(p("ro.build.version.sdk", "ro.system.build.version.sdk"))
            serial_no    = _first(p("ro.serialno", "ro.boot.serialno"), _shell(s, "getprop ro.serialno"))
            cpu_abi      = _first(p("ro.product.cpu.abi", "ro.product.cpu.abilist"))
            fingerprint  = _first(p("ro.build.fingerprint", "ro.system.build.fingerprint"))

            # ── Screen resolution ─────────────────────────────────────────
            wm_size = _shell(s, "wm size")
            rm = re.search(r"(\d+)\s*[xX]\s*(\d+)", wm_size)
            resolution = f"{rm.group(1)}x{rm.group(2)}" if rm else ""
            if not resolution:
                disp = _shell(s, "dumpsys display | grep -E 'mBaseDisplayInfo|DisplayInfo' | head -3")
                rm2 = re.search(r"(\d{3,4})\s*,\s*(\d{3,4})", disp)
                resolution = f"{rm2.group(1)}x{rm2.group(2)}" if rm2 else ""

            # ── RAM ───────────────────────────────────────────────────────
            meminfo = _shell(s, "cat /proc/meminfo | head -3")
            ram_total = ""
            mt = re.search(r"MemTotal\s*:\s*(\d+)", meminfo)
            if mt:
                kb = int(mt.group(1))
                gb = kb / 1024 / 1024
                mb = kb // 1024
                ram_total = f"{gb:.1f} GB ({mb} MB)" if gb >= 1 else f"{mb} MB"

            # ── IMEI ──────────────────────────────────────────────────────
            imei = ""
            # Method 1: dumpsys iphonesubinfo (most reliable, works without root)
            isub = _shell(s, "dumpsys iphonesubinfo", timeout=6)
            for pattern in [
                r"Device ID\s*=\s*(\d{14,})",
                r"IMEI\s*=\s*(\d{14,})",
                r"getDeviceId\(\)\s*=\s*(\d{14,})",
            ]:
                m = re.search(pattern, isub, re.IGNORECASE)
                if m:
                    imei = m.group(1)
                    break
            # Method 2: service call iphonesubinfo 1 (older Android ≤ 7)
            if not imei:
                raw = _shell(s, "service call iphonesubinfo 1", timeout=6)
                chars = re.findall(r"'([0-9.]+)'", raw)
                candidate = "".join(c.replace(".", "") for c in chars)
                if len(candidate) >= 14:
                    imei = candidate[:15]
            # Method 3: service call phone 4 (some custom ROMs)
            if not imei:
                raw = _shell(s, "service call phone 4", timeout=5)
                chars = re.findall(r"'([0-9.]+)'", raw)
                candidate = "".join(c.replace(".", "") for c in chars)
                if len(candidate) >= 14:
                    imei = candidate[:15]
            # Method 4: getprop fallbacks
            if not imei:
                imei = _first(
                    p("ril.imei", "persist.radio.imei", "gsm.imei"),
                    _prop(s, "ril.imei"),
                    _prop(s, "gsm.imei"),
                )

            # ── SIM / Telephony ───────────────────────────────────────────
            tel  = _shell(s, "dumpsys telephony.registry", timeout=8)
            tel2 = _shell(s, "dumpsys telephony", timeout=8)

            # SIM Code (MCC+MNC)
            sim_code = _first(
                _re_first(r"mNetworkOperator\s*=\s*(\d{5,6})", tel),
                _re_first(r"mNetworkOperator\s*=\s*(\d{5,6})", tel2),
                p("gsm.operator.numeric", "persist.radio.operator.numeric"),
                _prop(s, "gsm.operator.numeric"),
            )

            # ICCID
            iccid = _first(
                _re_first(r"iccId\s*=\s*([0-9F]{15,})", tel, re.IGNORECASE),
                _re_first(r"iccId\s*=\s*([0-9F]{15,})", tel2, re.IGNORECASE),
                p("persist.radio.iccid", "gsm.iccid"),
                _prop(s, "persist.radio.iccid"),
            )

            # Subscriber ID (IMSI)
            subscriber_id = _first(
                _re_first(r"SubscriberId\s*=\s*(\d{10,})", tel2, re.IGNORECASE),
                _re_first(r"mSubscriberId\s*=\s*(\d{10,})", tel),
                p("gsm.sim.operator.numeric"),
            )

            # Phone number (MDN / Line1)
            phone = _first(
                _re_first(r"mMdn\s*=\s*(\+?[\d]{7,})", tel),
                _re_first(r"Line1Number\s*=\s*(\+?[\d]{7,})", tel2, re.IGNORECASE),
                _re_first(r"mLine1Number\s*=\s*(\+?[\d]{7,})", tel),
                _prop(s, "ril.msisdn"),
                _prop(s, "persist.radio.msisdn"),
            )
            # iphonesubinfo service call for phone number
            if not phone:
                for idx in ("15", "14", "13"):
                    raw = _shell(s, f"service call iphonesubinfo {idx}", timeout=5)
                    chars = re.findall(r"'([+\d]+)'", raw)
                    candidate = "".join(chars)
                    if len(candidate) >= 7:
                        phone = candidate
                        break

            # ── GPS location ──────────────────────────────────────────────
            lat = lon = ""
            loc = _shell(s, "dumpsys location", timeout=8)

            # Strategy 1: Look for "last known location" blocks with lat/lng
            # Android 9+: "mLastKnownLocation: Location[network X.XXX,Y.YYY ...]"
            # Android 11+: "last location=Location[gps lat=X.XX lng=Y.YY ...]"
            for lat_pat, lon_pat in [
                # "lat=12.345 lng=67.890" or "lat=12.345,lon=67.890"
                (r"lat\s*=\s*([-\d.]+)", r"l(?:ng|on)\s*=\s*([-\d.]+)"),
                # "Location[gps 12.345,67.890 ...]"
                (r"Location\[\w[\w\s]*?([-\d.]+),([-\d.]+)", None),
                # generic latitude/longitude= lines
                (r"latitude\s*[=:]\s*([-\d.]+)", r"longitude\s*[=:]\s*([-\d.]+)"),
            ]:
                if lon_pat is None:
                    # combined pattern (lat and lon in same group)
                    m = re.search(lat_pat, loc, re.IGNORECASE | re.DOTALL)
                    if m:
                        lat, lon = m.group(1), m.group(2)
                        break
                else:
                    ml = re.search(lat_pat, loc, re.IGNORECASE | re.DOTALL)
                    mo = re.search(lon_pat, loc, re.IGNORECASE | re.DOTALL)
                    if ml and mo:
                        lat, lon = ml.group(1), mo.group(1)
                        break

            # Strategy 2: Try dumpsys location providers directly
            if not lat:
                for provider in ("gps", "network", "fused"):
                    prov_out = _shell(s, f"dumpsys location | grep -A 5 'last location'", timeout=6)
                    m_lat = re.search(r"lat(?:itude)?\s*[=:]\s*([-\d.]+)", prov_out, re.IGNORECASE)
                    m_lon = re.search(r"l(?:ng|on)(?:gitude)?\s*[=:]\s*([-\d.]+)", prov_out, re.IGNORECASE)
                    if m_lat and m_lon:
                        lat, lon = m_lat.group(1), m_lon.group(1)
                        break

            # Strategy 3: Try reading last known location via content provider (Android 8+)
            if not lat:
                try:
                    gps_raw = _shell(s,
                        "content query --uri content://com.google.android.gsf.gservices/prefix --where \"name='location'\" 2>/dev/null | head -5",
                        timeout=5)
                    m_lat = re.search(r"lat(?:itude)?\s*[=:]\s*([-\d.]+)", gps_raw, re.IGNORECASE)
                    m_lon = re.search(r"l(?:ng|on)(?:gitude)?\s*[=:]\s*([-\d.]+)", gps_raw, re.IGNORECASE)
                    if m_lat and m_lon:
                        lat, lon = m_lat.group(1), m_lon.group(1)
                except Exception:
                    pass

            # ── WiFi SSID ─────────────────────────────────────────────────
            wifi_name = ""
            if self.manual_wifi:
                wifi_name = self.manual_wifi
            else:
                # wpa_supplicant (most reliable)
                wpa = _shell(s, "wpa_cli -i wlan0 status 2>/dev/null || wpa_cli status 2>/dev/null", timeout=5)
                m = re.search(r"^ssid=(.+)$", wpa, re.MULTILINE)
                if m:
                    wifi_name = m.group(1).strip()
                # dumpsys wifi
                if not wifi_name or wifi_name == "<unknown ssid>":
                    wifi_raw = _shell(s, "dumpsys wifi | grep -E 'SSID|mWifiInfo' | head -5", timeout=6)
                    m2 = re.search(r'SSID:\s*"?([^",\n<>]{2,})"?', wifi_raw)
                    if not m2:
                        m2 = re.search(r'SSID\s*=\s*"?([^",\n<>]{2,})"?', wifi_raw)
                    if m2:
                        wifi_name = m2.group(1).strip()
                # cmd wifi (Android 11+)
                if not wifi_name or wifi_name == "<unknown ssid>":
                    cmd_out = _shell(s, "cmd wifi status 2>/dev/null | grep -i ssid | head -2", timeout=5)
                    m3 = re.search(r'SSID[=:\s]+"?([^",\n<>]{2,})"?', cmd_out, re.IGNORECASE)
                    if m3:
                        wifi_name = m3.group(1).strip()
                if wifi_name in ("<unknown ssid>", "0x", ""):
                    wifi_name = ""

            # ── Uptime ────────────────────────────────────────────────────
            uptime = _shell(s, "uptime")

            self.result.emit({
                "brand":         brand,
                "model":         model,
                "manufacturer":  manufacturer,
                "android_os":    android_os,
                "sdk":           sdk,
                "serial_no":     serial_no,
                "cpu_abi":       cpu_abi,
                "resolution":    resolution,
                "ram":           ram_total,
                "fingerprint":   fingerprint,
                "imei":          imei,
                "sim_code":      sim_code,
                "iccid":         iccid,
                "subscriber_id": subscriber_id,
                "phone_number":  phone,
                "latitude":      lat,
                "longitude":     lon,
                "wifi_name":     wifi_name,
                "uptime":        uptime,
            })
        except Exception as e:
            self.error.emit(str(e))

_COUNTRIES = [
    "United States", "United Kingdom", "Canada", "Australia",
    "Germany", "France", "Japan", "South Korea", "China",
    "India", "Brazil", "Mexico", "Vietnam", "Thailand",
    "Indonesia", "Philippines", "Singapore", "Malaysia",
    "Netherlands", "Spain", "Italy", "Poland", "Russia",
    "Turkey", "Saudi Arabia", "UAE", "South Africa",
]

_CARRIERS: dict[str, list[str]] = {
    "United States": [
        "AT&T", "T-Mobile", "Verizon", "Sprint",
        "US Cellular", "Boost Mobile", "Cricket Wireless",
        "Aeris Comm. Inc.-850", "MetroPCS",
    ],
    "United Kingdom": ["EE", "O2", "Vodafone", "Three"],
    "Vietnam": ["Viettel", "Mobifone", "Vinaphone", "Gmobile", "Reddi"],
    "default": ["Carrier A", "Carrier B", "Carrier C"],
}

def _adb_info(serial: str, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        startupinfo=_si,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

def _shell_info(serial: str, cmd: str) -> str:
    r = _adb_info(serial, "shell", cmd)
    return (r.stdout or "").strip()

class _ChangeDeviceWorker(QThread):
    finished = Signal()

    def __init__(self, serial: str, settings: dict):
        super().__init__()
        self.serial = serial
        self.settings = settings

    def run(self):
        s = self.serial
        cfg = self.settings
        try:
            if cfg.get("logout_gmail"):
                _adb_info(s, "shell", "pm", "clear", "com.google.android.gms")
                time.sleep(1)
            if not cfg.get("no_wipe_google"):
                _adb_info(s, "shell", "pm", "clear", "com.google.android.gsf")
                time.sleep(0.5)
            if cfg.get("fake_sim"):
                sim_code = cfg.get("sim_code", "")
                carrier  = cfg.get("carrier", "")
                if sim_code:
                    _shell_info(s, f"setprop gsm.operator.numeric {sim_code}")
                    _shell_info(s, f"setprop persist.radio.operator.numeric {sim_code}")
                if carrier:
                    escaped = carrier.replace(" ", "\\ ")
                    _shell_info(s, f"setprop gsm.operator.alpha {escaped}")
                    _shell_info(s, f"setprop persist.radio.operator.alpha {escaped}")
            if cfg.get("fake_mac"):
                import random
                mac = ":".join(f"{random.randint(0,255):02x}" for _ in range(6))
                first = int(mac.split(":")[0], 16) | 0x02
                parts = mac.split(":")
                parts[0] = f"{first:02x}"
                mac = ":".join(parts)
                _shell_info(s, f"ip link set wlan0 address {mac} 2>/dev/null || true")
            if cfg.get("change_tz") and cfg.get("country"):
                tz_map = {
                    "United States": "America/New_York",
                    "United Kingdom": "Europe/London",
                    "Vietnam": "Asia/Ho_Chi_Minh",
                    "Japan": "Asia/Tokyo",
                    "Germany": "Europe/Berlin",
                    "France": "Europe/Paris",
                    "Australia": "Australia/Sydney",
                    "China": "Asia/Shanghai",
                    "India": "Asia/Kolkata",
                    "Brazil": "America/Sao_Paulo",
                    "Singapore": "Asia/Singapore",
                    "Thailand": "Asia/Bangkok",
                }
                tz = tz_map.get(cfg["country"], "")
                if tz:
                    _shell_info(s, f"setprop persist.sys.timezone {tz}")
                    _adb_info(s, "shell", "settings", "put", "global", "time_zone", tz)
            if cfg.get("fake_location"):
                _adb_info(s, "shell", "settings", "put", "secure", "mock_location", "1")
                _adb_info(s, "shell", "appops", "set",
                          "com.android.shell", "android:mock_location", "allow")
            if cfg.get("safetynet"):
                _shell_info(s, "setprop ro.boot.verifiedbootstate green")
                _shell_info(s, "setprop ro.boot.flash.locked 1")
        except Exception:
            pass

class _ChangeSimWorker(QThread):
    finished = Signal()

    def __init__(self, serial: str, settings: dict):
        super().__init__()
        self.serial = serial
        self.settings = settings

    def run(self):
        s = self.serial
        cfg = self.settings
        try:
            sim_code = cfg.get("sim_code", "")
            carrier  = cfg.get("carrier", "")
            if sim_code:
                _shell_info(s, f"setprop gsm.operator.numeric {sim_code}")
                _shell_info(s, f"setprop persist.radio.operator.numeric {sim_code}")
            if carrier:
                escaped = carrier.replace(" ", "\\ ")
                _shell_info(s, f"setprop gsm.operator.alpha {escaped}")
                _shell_info(s, f"setprop persist.radio.operator.alpha {escaped}")
        except Exception:
            pass

_GROUP_SS = """
    QGroupBox {
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #ddd;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 4px;
        background-color: #f8f9ff;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: #1565c0;
    }
"""

_FIELD_SS = (
    "QLineEdit {"
    "  border: 1px solid #ddd;"
    "  border-radius: 4px;"
    "  padding: 2px 6px;"
    "  background: #ffffff;"
    "  color: #212121;"
    "  font-size: 11px;"
    "  min-height: 20px;"
    "}"
    "QLineEdit:read-only { background: #f7f9ff; }"
)

_LABEL_SS = "color: #555; font-size: 11px; font-weight: bold;"

_INPUT_SS = (
    "QLineEdit {"
    "  border: 1px solid #ddd; border-radius: 4px;"
    "  padding: 2px 6px; background: #ffffff; color: #212121;"
    "  font-size: 11px; min-height: 20px;"
    "}"
    "QLineEdit:focus { border: 1px solid #1976d2; }"
)

_COMBO_SS = (
    "QComboBox {"
    "  border: 1px solid #ddd; border-radius: 4px;"
    "  padding: 2px 6px; background: #ffffff; color: #212121;"
    "  font-size: 11px; min-height: 22px;"
    "}"
    "QComboBox:focus { border: 1px solid #1976d2; }"
    "QComboBox::drop-down { border: none; }"
)

_BTN_PRIMARY_SS = (
    "QPushButton { background-color: #1976d2; color: white; font-weight: bold;"
    " padding: 5px 14px; border-radius: 4px; font-size: 11px; }"
    "QPushButton:hover { background-color: #1565c0; }"
    "QPushButton:disabled { background-color: #90caf9; }"
)

_BTN_SECONDARY_SS = (
    "QPushButton { border: 1px solid #ddd; border-radius: 4px;"
    " padding: 5px 14px; background: #f0f0f0; font-size: 11px; }"
    "QPushButton:hover { background: #e0e0e0; }"
    "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
)

_CB_SS = "QCheckBox { font-size: 11px; color: #333; }"

# ── Metrics Worker ──────────────────────────────────────────────────────
class _MetricsWorker(QThread):
    cpu_ready = Signal(float)
    ram_ready = Signal(int, int)
    battery_ready = Signal(int, bool)

    def __init__(self, serial: str):
        super().__init__()
        self.serial = serial
        self._running = True

    def run(self):
        s = self.serial
        while self._running:
            try:
                # ── CPU Usage ─────────────────────────────────────────────
                try:
                    # Get CPU usage from /proc/stat
                    stat1 = _shell(s, "cat /proc/stat | head -1", timeout=5)
                    time.sleep(0.1)  # Small delay for CPU measurement
                    stat2 = _shell(s, "cat /proc/stat | head -1", timeout=5)

                    # Parse CPU times
                    def parse_cpu_line(line: str) -> list[int]:
                        parts = line.split()
                        if len(parts) < 8:
                            return []
                        return [int(x) for x in parts[1:8]]

                    cpu1 = parse_cpu_line(stat1)
                    cpu2 = parse_cpu_line(stat2)

                    if cpu1 and cpu2:
                        total1 = sum(cpu1)
                        total2 = sum(cpu2)
                        idle1 = cpu1[3]  # idle time
                        idle2 = cpu2[3]

                        total_diff = total2 - total1
                        idle_diff = idle2 - idle1

                        if total_diff > 0:
                            cpu_pct = 100.0 * (1.0 - idle_diff / total_diff)
                            self.cpu_ready.emit(max(0.0, min(100.0, cpu_pct)))
                except Exception:
                    pass

                # ── RAM Usage ─────────────────────────────────────────────
                try:
                    meminfo = _shell(s, "cat /proc/meminfo | head -3", timeout=5)
                    mem_total = mem_used = 0

                    for line in meminfo.splitlines():
                        if line.startswith("MemTotal:"):
                            mem_total = int(re.search(r"(\d+)", line).group(1)) // 1024  # Convert to MB
                        elif line.startswith("MemAvailable:"):
                            mem_available = int(re.search(r"(\d+)", line).group(1)) // 1024
                            mem_used = mem_total - mem_available
                            break

                    if mem_total > 0:
                        self.ram_ready.emit(mem_used, mem_total)
                except Exception:
                    pass

                # ── Battery Status ────────────────────────────────────────
                try:
                    battery_info = _shell(s, "dumpsys battery", timeout=5)
                    level = 0
                    charging = False

                    for line in battery_info.splitlines():
                        line = line.strip()
                        if line.startswith("level:"):
                            try:
                                level = int(line.split(":")[1].strip())
                            except ValueError:
                                pass
                        elif line.startswith("status:"):
                            status_str = line.split(":")[1].strip()
                            # 2 = charging, 5 = full but still charging
                            charging = status_str in ("2", "5")

                    self.battery_ready.emit(level, charging)
                except Exception:
                    pass

                # Wait before next measurement
                time.sleep(1)

            except Exception:
                # If there's an error, wait a bit before retrying
                time.sleep(2)

    def stop(self):
        self._running = False
        self.wait()

# ── DeviceInfoWidget ─────────────────────────────────────────────────────
class DeviceInfoWidget(QWidget):
    """Tab page — shows live device info for the selected device."""
    status_update = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._worker: _FetchWorker | None = None
        self._change_workers: list[QThread] = []
        self._metrics_worker = None
        self._auto_timer = QTimer()
        self._auto_timer.timeout.connect(self._refresh_metrics)
        self._build_ui()

    def __del__(self):
        """Cleanup when widget is destroyed."""
        if self._metrics_worker and self._metrics_worker.isRunning():
            self._metrics_worker.stop()

    # ── public API ───────────────────────────────────────────────────────
    def set_device(self, serial: str):
        """Called when user selects a row in the table."""
        # Stop existing metrics worker when changing devices
        if self._metrics_worker and self._metrics_worker.isRunning():
            self._metrics_worker.stop()

        self._serial = serial
        label = f"Serial: {serial}" if serial else "No device selected"
        self._serial_label.setText(label)
        enabled = bool(serial)
        self._change_device_btn.setEnabled(enabled)
        self._change_sim_btn.setEnabled(enabled)
        # Auto-load diagnostics charts immediately
        if serial:
            self._diag_run_free()
            self._diag_run_top()
            self._diag_run_df()
            # Auto-start live metrics refresh
            if not self._metrics_auto_btn.isChecked():
                self._metrics_auto_btn.setChecked(True)
            else:
                self._refresh_metrics()
        else:
            if self._metrics_auto_btn.isChecked():
                self._metrics_auto_btn.setChecked(False)

    def load_device(self, serial: str):
        if not serial:
            self._clear_fields()
            self._serial_label.setText("No device selected")
            return

        self._serial = serial
        self._serial_label.setText(f"Serial: {serial}")
        self._set_state("loading")
        self._refresh_btn.setEnabled(False)

        manual_wifi = (
            self._wifi_manual_input.text().strip()
            if self._manual_wifi_cb.isChecked() else ""
        )

        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(500)

        self._worker = _FetchWorker(serial, manual_wifi=manual_wifi)
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._worker.start()

    # ── UI construction ──────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        self._serial_label = QLabel("No device selected")
        self._serial_label.setStyleSheet("font-weight: bold; color: #1565c0; font-size: 12px;")
        hdr.addWidget(self._serial_label, 1)
        self._refresh_btn = QPushButton("🔄 Refresh")
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.setStyleSheet(
            "QPushButton { border:1px solid #bdbdbd; border-radius:4px;"
            " padding:2px 10px; background:#f0f0f0; font-size:11px; }"
            "QPushButton:hover { background:#e0e0e0; }"
            "QPushButton:disabled { background:#f5f5f5; color:#aaa; }"
        )
        self._refresh_btn.clicked.connect(lambda: self.load_device(self._serial))
        hdr.addWidget(self._refresh_btn)
        root.addLayout(hdr)

        # Scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner_vl = QVBoxLayout(inner)
        inner_vl.setContentsMargins(0, 0, 4, 0)
        inner_vl.setSpacing(8)

        # ── field / label helpers ────────────────────────────────────────
        def _field() -> QLineEdit:
            le = QLineEdit()
            le.setReadOnly(True)
            le.setStyleSheet(_FIELD_SS)
            return le

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(_LABEL_SS)
            return l

        def _group(title: str) -> tuple[QGroupBox, QFormLayout]:
            g = QGroupBox(title)
            g.setStyleSheet(_GROUP_SS)
            fl = QFormLayout()
            fl.setContentsMargins(12, 6, 12, 6)
            fl.setSpacing(4)
            fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            fl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            g.setLayout(fl)
            return g, fl

        # ── Group 1: Device Information ──────────────────────────────────
        g1, f1 = _group("📱 Device Information")
        self._f_brand        = _field()
        self._f_model        = _field()
        self._f_manufacturer = _field()
        self._f_android      = _field()
        self._f_sdk          = _field()
        self._f_serial_no    = _field()
        self._f_cpu_abi      = _field()
        self._f_resolution   = _field()
        self._f_ram          = _field()
        self._f_uptime       = _field()

        f1.addRow(_lbl("🏷 Brand"),        self._f_brand)
        f1.addRow(_lbl("📋 Model"),        self._f_model)
        f1.addRow(_lbl("🏭 Manufacturer"), self._f_manufacturer)
        f1.addRow(_lbl("🤖 Android OS"),   self._f_android)
        f1.addRow(_lbl("🔧 SDK Version"),  self._f_sdk)
        f1.addRow(_lbl("🔢 Serial No."),   self._f_serial_no)
        f1.addRow(_lbl("💻 CPU ABI"),      self._f_cpu_abi)
        f1.addRow(_lbl("🖥 Resolution"),   self._f_resolution)
        f1.addRow(_lbl("🧠 RAM"),          self._f_ram)
        f1.addRow(_lbl("⏱ Uptime"),        self._f_uptime)
        # ── Group 2: SIM / Telephony ─────────────────────────────────────
        g2, f2 = _group("📡 SIM / Telephony")
        self._f_imei    = _field()
        self._f_simcode = _field()
        self._f_iccid   = _field()
        self._f_subid   = _field()
        self._f_phone   = _field()

        f2.addRow(_lbl("🔑 IMEI"),              self._f_imei)
        f2.addRow(_lbl("📶 SIM Code"),           self._f_simcode)
        f2.addRow(_lbl("🪪 ICCID"),              self._f_iccid)
        f2.addRow(_lbl("🆔 Subscriber ID"),      self._f_subid)
        f2.addRow(_lbl("📞 Phone Number"),       self._f_phone)

        # ── Group 3: Location / Network ──────────────────────────────────
        g3, f3 = _group("🌐 Location / Network")
        # Make g3 compact — only 3 rows, don't stretch vertically
        g3.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._f_lat  = _field()
        self._f_lon  = _field()
        self._f_wifi = _field()

        f3.addRow(_lbl("📍 Latitude"),  self._f_lat)
        f3.addRow(_lbl("📍 Longitude"), self._f_lon)

        # WiFi row with manual checkbox
        wifi_row = QHBoxLayout()
        wifi_row.setSpacing(6)
        wifi_row.addWidget(self._f_wifi, 1)
        self._manual_wifi_cb = QCheckBox("Manual")
        self._manual_wifi_cb.setStyleSheet("font-size: 11px;")
        self._manual_wifi_cb.toggled.connect(self._on_manual_wifi_toggled)
        wifi_row.addWidget(self._manual_wifi_cb)
        wifi_w = QWidget()
        wifi_w.setLayout(wifi_row)
        f3.addRow(_lbl("📶 WiFi Name"), wifi_w)

        self._wifi_manual_input = QLineEdit()
        self._wifi_manual_input.setPlaceholderText("Enter Wifi name manually…")
        self._wifi_manual_input.setStyleSheet(_FIELD_SS)
        self._wifi_manual_input.hide()
        self._wifi_manual_input.returnPressed.connect(
            lambda: self.load_device(self._serial)
        )
        f3.addRow(QLabel(""), self._wifi_manual_input)

        # ── 2-column top layout: Device Info (left) | SIM + Location (right) ──
        top_cols = QHBoxLayout()
        top_cols.setSpacing(8)
        top_cols.addWidget(g1, 1)

        right_col_w = QWidget()
        right_col_vl = QVBoxLayout(right_col_w)
        right_col_vl.setContentsMargins(0, 0, 0, 0)
        right_col_vl.setSpacing(8)
        right_col_vl.addWidget(g2)
        right_col_vl.addWidget(g3)
        right_col_vl.addStretch()           # push g2/g3 to top, remove dead space

        top_cols.addWidget(right_col_w, 1)
        inner_vl.addLayout(top_cols)

        # ── Group 4: Phone Settings ──────────────────────────────────────
        ps_group = QGroupBox("📱 Phone Settings")
        ps_group.setStyleSheet(_GROUP_SS)
        ps_vl = QVBoxLayout()
        ps_vl.setContentsMargins(12, 10, 12, 10)
        ps_vl.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)

        lbl_country = QLabel("Country:")
        lbl_country.setStyleSheet(_LABEL_SS)
        lbl_country.setFixedWidth(52)
        self._country_combo = QComboBox()
        self._country_combo.addItems(_COUNTRIES)
        self._country_combo.setStyleSheet(_COMBO_SS)
        self._country_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._country_combo.currentTextChanged.connect(self._on_country_changed)
        row1.addWidget(lbl_country)
        row1.addWidget(self._country_combo, 2)

        lbl_carrier = QLabel("Carrier:")
        lbl_carrier.setStyleSheet(_LABEL_SS)
        lbl_carrier.setFixedWidth(46)
        self._carrier_combo = QComboBox()
        self._carrier_combo.setStyleSheet(_COMBO_SS)
        self._carrier_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row1.addWidget(lbl_carrier)
        row1.addWidget(self._carrier_combo, 2)

        lbl_simcode = QLabel("Fixed Sim Code:")
        lbl_simcode.setStyleSheet(_LABEL_SS)
        self._simcode_input = QLineEdit()
        self._simcode_input.setPlaceholderText("e.g. 310410")
        self._simcode_input.setStyleSheet(_INPUT_SS)
        self._simcode_input.setFixedWidth(90)
        row1.addWidget(lbl_simcode)
        row1.addWidget(self._simcode_input)

        ps_vl.addLayout(row1)

        cb_grid = QGridLayout()
        cb_grid.setHorizontalSpacing(16)
        cb_grid.setVerticalSpacing(4)

        def _cb(label: str, default: bool = False) -> QCheckBox:
            c = QCheckBox(label)
            c.setStyleSheet(_CB_SS)
            c.setChecked(default)
            return c

        self._cb_safetynet   = _cb("Pass SafetyNet Device",            default=True)
        self._cb_fake_sim    = _cb("Fake Sim Info",                     default=True)
        self._cb_fake_mac    = _cb("Fake MAC Address",                  default=True)
        self._cb_logout_gm   = _cb("Logout gmail trước khi change",     default=False)
        self._cb_no_wipe     = _cb("Không wipe google data khi change", default=False)
        self._cb_uninstall   = _cb("Gỡ ứng dụng khi change",           default=False)
        self._cb_random_carr = _cb("Random Carrier By Country",         default=False)
        self._cb_change_tz   = _cb("Change Timezone",                   default=True)
        self._cb_fake_loc    = _cb("Fake Location",                     default=True)

        checkboxes = [
            (self._cb_safetynet,   0, 0),
            (self._cb_fake_sim,    1, 0),
            (self._cb_fake_mac,    2, 0),
            (self._cb_logout_gm,   0, 1),
            (self._cb_no_wipe,     1, 1),
            (self._cb_uninstall,   2, 1),
            (self._cb_random_carr, 0, 2),
            (self._cb_change_tz,   1, 2),
            (self._cb_fake_loc,    2, 2),
        ]
        for widget, row, col in checkboxes:
            cb_grid.addWidget(widget, row, col)

        ps_vl.addLayout(cb_grid)
        ps_group.setLayout(ps_vl)
        inner_vl.addWidget(ps_group)

        self._on_country_changed(self._country_combo.currentText())

        # ── Actions ──────────────────────────────────────────────────────
        act_btn_row = QHBoxLayout()
        act_btn_row.setSpacing(10)

        self._change_device_btn = QPushButton("🔄  Change Device")
        self._change_device_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._change_device_btn.setEnabled(False)
        self._change_device_btn.setMinimumHeight(32)
        self._change_device_btn.clicked.connect(self._run_change_device)
        act_btn_row.addWidget(self._change_device_btn, 1)

        self._change_sim_btn = QPushButton("📡  Change SIM Info Only")
        self._change_sim_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._change_sim_btn.setEnabled(False)
        self._change_sim_btn.setMinimumHeight(32)
        self._change_sim_btn.clicked.connect(self._run_change_sim)
        act_btn_row.addWidget(self._change_sim_btn, 1)

        inner_vl.addLayout(act_btn_row)

        # ── System Diagnostics ────────────────────────────────────────────
        from features.activities import (
            _DonutRow, _SparklineChart, _BatteryBar, _MetricsWorker,
            parse_free, parse_top_cpu, parse_df,
            _btn_primary, _btn_success,
        )

        # ── Live Device Metrics ───────────────────────────────────────────
        metrics_group = QGroupBox("📈 Live Device Metrics")
        metrics_group.setStyleSheet(_GROUP_SS)
        mg_vl = QVBoxLayout()
        mg_vl.setContentsMargins(10, 10, 10, 10)
        mg_vl.setSpacing(8)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self._cpu_chart = _SparklineChart("CPU Usage", "%",  max_val=100,  color=QColor("#1976d2"))
        self._ram_chart = _SparklineChart("RAM Used",  "MB", max_val=4096, color=QColor("#388e3c"))
        charts_row.addWidget(self._cpu_chart)
        charts_row.addWidget(self._ram_chart)
        mg_vl.addLayout(charts_row)

        # Battery + controls row
        bat_row = QHBoxLayout()
        bat_row.setSpacing(10)
        bat_lbl = QLabel("Battery:")
        bat_lbl.setStyleSheet(_LABEL_SS)
        bat_row.addWidget(bat_lbl)
        self._metrics_battery_bar = _BatteryBar()
        bat_row.addWidget(self._metrics_battery_bar)
        self._metrics_bat_detail_lbl = QLabel("–")
        self._metrics_bat_detail_lbl.setStyleSheet("font-size: 11px; color: #555;")
        bat_row.addWidget(self._metrics_bat_detail_lbl)
        bat_row.addStretch()

        interval_lbl = QLabel("Auto-refresh every:")
        interval_lbl.setStyleSheet(_LABEL_SS)
        bat_row.addWidget(interval_lbl)
        self._metrics_interval_spin = QSpinBox()
        self._metrics_interval_spin.setRange(2, 120)
        self._metrics_interval_spin.setValue(5)
        self._metrics_interval_spin.setSuffix(" s")
        self._metrics_interval_spin.setFixedWidth(72)
        self._metrics_interval_spin.setStyleSheet(
            "QSpinBox { border: 1px solid #dce3f0; border-radius: 4px;"
            " padding: 2px 6px; background: #ffffff; color: #212121; font-size: 11px; min-height: 20px; }"
            "QSpinBox:focus { border: 1px solid #1976d2; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; background: transparent; }"
        )
        bat_row.addWidget(self._metrics_interval_spin)

        self._metrics_auto_btn = QPushButton("▶ Start Auto-Refresh")
        self._metrics_auto_btn.setCheckable(True)
        self._metrics_auto_btn.setStyleSheet(
            "QPushButton { background-color: #388e3c; color: white; font-weight: bold;"
            " padding: 5px 12px; border-radius: 4px; font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #2e7d32; }"
        )
        self._metrics_auto_btn.toggled.connect(self._toggle_metrics_auto_refresh)
        bat_row.addWidget(self._metrics_auto_btn)

        metrics_refresh_btn = QPushButton("↻ Refresh Now")
        metrics_refresh_btn.setStyleSheet(
            "QPushButton { background-color: #1976d2; color: white; font-weight: bold;"
            " padding: 5px 12px; border-radius: 4px; font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #1565c0; }"
            "QPushButton:disabled { background-color: #90caf9; }"
        )
        metrics_refresh_btn.clicked.connect(self._refresh_metrics)
        bat_row.addWidget(metrics_refresh_btn)

        mg_vl.addLayout(bat_row)
        metrics_group.setLayout(mg_vl)
        inner_vl.addWidget(metrics_group)

        # ── System Diagnostics ────────────────────────────────────────────
        diag_group = QGroupBox("💻 System Diagnostics")
        diag_group.setStyleSheet(_GROUP_SS)
        diag_vl = QVBoxLayout()
        diag_vl.setContentsMargins(10, 10, 10, 10)
        diag_vl.setSpacing(8)

        # — Buttons row: Refresh only —
        diag_btn_grid = QGridLayout()
        diag_btn_grid.setSpacing(6)

        b_refresh = _btn_primary("🔄 Refresh Charts")

        b_refresh.clicked.connect(self._diag_refresh_all)

        diag_btn_grid.addWidget(b_refresh, 0, 0)
        diag_vl.addLayout(diag_btn_grid)

        # — 2-column layout: left = CPU + Memory, right = Storage Partitions —
        diag_cols = QHBoxLayout()
        diag_cols.setSpacing(12)

        # Left column: CPU Breakdown (top) + Memory (bottom)
        left_diag_col = QVBoxLayout()
        left_diag_col.setSpacing(8)

        _cpu_lbl = QLabel("⚡ CPU Breakdown")
        _cpu_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        left_diag_col.addWidget(_cpu_lbl)
        self._diag_cpu_donuts = _DonutRow([
            ("user", "User",   QColor("#1976d2")),
            ("sys",  "System", QColor("#d32f2f")),
            ("idle", "Idle",   QColor("#388e3c")),
        ], size=100)
        left_diag_col.addWidget(self._diag_cpu_donuts)

        _ram_lbl = QLabel("🧠 Memory")
        _ram_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        left_diag_col.addWidget(_ram_lbl)
        self._diag_ram_donuts = _DonutRow([
            ("mem",  "RAM",  QColor("#388e3c")),
            ("swap", "Swap", QColor("#7b1fa2")),
        ], size=100)
        left_diag_col.addWidget(self._diag_ram_donuts)
        left_diag_col.addStretch()

        left_diag_w = QWidget()
        left_diag_w.setLayout(left_diag_col)
        diag_cols.addWidget(left_diag_w, 1)

        # Right column: Storage Partitions (top 2 + bottom 2)
        right_diag_col = QVBoxLayout()
        right_diag_col.setSpacing(4)

        _stor_lbl = QLabel("💾 Storage Partitions")
        _stor_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        right_diag_col.addWidget(_stor_lbl)

        _STOR_COLORS = [QColor("#00796b"), QColor("#f57c00"), QColor("#546e7a"), QColor("#7b1fa2")]
        _STOR_KEYS   = ["s0", "s1", "s2", "s3"]

        # Top row: s0, s1
        self._diag_storage_row0 = _DonutRow(
            [(k, "–", c) for k, c in zip(_STOR_KEYS[:2], _STOR_COLORS[:2])],
            size=100,
        )
        right_diag_col.addWidget(self._diag_storage_row0)

        # Bottom row: s2, s3
        self._diag_storage_row1 = _DonutRow(
            [(k, "–", c) for k, c in zip(_STOR_KEYS[2:], _STOR_COLORS[2:])],
            size=100,
        )
        right_diag_col.addWidget(self._diag_storage_row1)
        right_diag_col.addStretch()

        right_diag_w = QWidget()
        right_diag_w.setLayout(right_diag_col)
        diag_cols.addWidget(right_diag_w, 1)

        diag_vl.addLayout(diag_cols)
        diag_group.setLayout(diag_vl)
        inner_vl.addWidget(diag_group)

        # Keep references for use in methods
        self._DonutRow = _DonutRow
        self._MetricsWorker = _MetricsWorker
        self._parse_free = parse_free
        self._parse_top_cpu = parse_top_cpu
        self._parse_df = parse_df

        inner_vl.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # Collect all data fields for bulk clear/loading operations
        self._all_data_fields = [
            self._f_brand, self._f_model, self._f_manufacturer,
            self._f_android, self._f_sdk, self._f_serial_no,
            self._f_cpu_abi, self._f_resolution, self._f_ram,
            self._f_uptime,
            self._f_imei, self._f_simcode, self._f_iccid,
            self._f_subid, self._f_phone,
            self._f_lat, self._f_lon, self._f_wifi,
        ]

    # ── Helpers ──────────────────────────────────────────────────────────
    def _on_manual_wifi_toggled(self, checked: bool):
        self._wifi_manual_input.setVisible(checked)
        if checked:
            self._wifi_manual_input.setFocus()
        else:
            self._wifi_manual_input.clear()

    def _set_state(self, state: str):
        """state: 'loading' | 'error' | 'clear'"""
        ss_map   = {"loading": _FIELD_SS + "color:#aaa;",
                    "error":   _FIELD_SS + "color:#c62828;",
                    "clear":   _FIELD_SS}
        text_map = {"loading": "Loading…", "error": "Error", "clear": ""}
        ss  = ss_map.get(state, _FIELD_SS)
        txt = text_map.get(state, "")
        for f in self._all_data_fields:
            f.setText(txt)
            f.setStyleSheet(ss)

    def _clear_fields(self):
        self._set_state("clear")

    def _on_result(self, data: dict):
        pairs = [
            (self._f_brand,        "brand"),
            (self._f_model,        "model"),
            (self._f_manufacturer, "manufacturer"),
            (self._f_android,      "android_os"),
            (self._f_sdk,          "sdk"),
            (self._f_serial_no,    "serial_no"),
            (self._f_cpu_abi,      "cpu_abi"),
            (self._f_resolution,   "resolution"),
            (self._f_ram,          "ram"),
            (self._f_uptime,       "uptime"),
            (self._f_imei,         "imei"),
            (self._f_simcode,      "sim_code"),
            (self._f_iccid,        "iccid"),
            (self._f_subid,        "subscriber_id"),
            (self._f_phone,        "phone_number"),
            (self._f_lat,          "latitude"),
            (self._f_lon,          "longitude"),
        ]
        for field, key in pairs:
            field.setText(data.get(key, ""))
            field.setStyleSheet(_FIELD_SS)
        if not self._manual_wifi_cb.isChecked():
            self._f_wifi.setText(data.get("wifi_name", ""))
            self._f_wifi.setStyleSheet(_FIELD_SS)

    def _on_error(self, msg: str):
        self._set_state("error")
        self._serial_label.setText(f"Serial: {self._serial}  ⚠ {msg}")

    # ── Phone Settings helpers ────────────────────────────────────────────
    def _on_country_changed(self, country: str):
        self._carrier_combo.clear()
        carriers = _CARRIERS.get(country, _CARRIERS["default"])
        self._carrier_combo.addItems(carriers)

    def _collect_settings(self) -> dict:
        sim_code = self._simcode_input.text().strip()
        carrier = "" if self._cb_random_carr.isChecked() else self._carrier_combo.currentText()
        return {
            "country":        self._country_combo.currentText(),
            "carrier":        carrier,
            "sim_code":       sim_code,
            "safetynet":      self._cb_safetynet.isChecked(),
            "fake_sim":       self._cb_fake_sim.isChecked(),
            "fake_mac":       self._cb_fake_mac.isChecked(),
            "logout_gmail":   self._cb_logout_gm.isChecked(),
            "no_wipe_google": self._cb_no_wipe.isChecked(),
            "uninstall_apps": self._cb_uninstall.isChecked(),
            "random_carrier": self._cb_random_carr.isChecked(),
            "change_tz":      self._cb_change_tz.isChecked(),
            "fake_location":  self._cb_fake_loc.isChecked(),
        }

    def _run_change_device(self):
        if not self._serial:
            return
        settings = self._collect_settings()
        self._change_device_btn.setEnabled(False)
        w = _ChangeDeviceWorker(self._serial, settings)
        w.finished.connect(lambda: self._change_device_btn.setEnabled(bool(self._serial)))
        w.finished.connect(lambda: self._change_workers.remove(w) if w in self._change_workers else None)
        self._change_workers.append(w)
        w.start()

    def _run_change_sim(self):
        if not self._serial:
            return
        settings = self._collect_settings()
        self._change_sim_btn.setEnabled(False)
        w = _ChangeSimWorker(self._serial, settings)
        w.finished.connect(lambda: self._change_sim_btn.setEnabled(bool(self._serial)))
        w.finished.connect(lambda: self._change_workers.remove(w) if w in self._change_workers else None)
        self._change_workers.append(w)
        w.start()

    # ── System Diagnostics helpers ────────────────────────────────────────

    def _diag_refresh_all(self):
        """Refresh all three diagnostic charts at once."""
        self._diag_run_free()
        self._diag_run_top()
        self._diag_run_df()

    def _diag_run_free(self):
        if not self._serial:
            return
        try:
            import subprocess as _sp
            r = _sp.run(
                ["adb", "-s", self._serial, "shell", "free", "-m"],
                startupinfo=_si, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            output = r.stdout or r.stderr or "(no output)"
            mem_used, mem_total, swap_used, swap_total = self._parse_free(output)
            if mem_total > 0:
                self._diag_ram_donuts.update_chart(
                    "mem", mem_used, mem_total, f"{mem_used}/{mem_total} MB"
                )
            if swap_total > 0:
                self._diag_ram_donuts.update_chart(
                    "swap", swap_used, swap_total, f"{swap_used}/{swap_total} MB"
                )
        except Exception:
            pass

    def _diag_run_top(self):
        if not self._serial:
            return
        try:
            import subprocess as _sp
            r = _sp.run(
                ["adb", "-s", self._serial, "shell", "top", "-n", "1"],
                startupinfo=_si, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            output = r.stdout or r.stderr or "(no output)"
            user, sys_, idle = self._parse_top_cpu(output)
            total = user + sys_ + idle
            if total > 0:
                self._diag_cpu_donuts.update_chart("user", user,  100.0, f"{user:.1f}%")
                self._diag_cpu_donuts.update_chart("sys",  sys_,  100.0, f"{sys_:.1f}%")
                self._diag_cpu_donuts.update_chart("idle", idle,  100.0, f"{idle:.1f}%")
        except Exception:
            pass

    def _diag_run_df(self):
        if not self._serial:
            return
        try:
            import subprocess as _sp
            r = _sp.run(
                ["adb", "-s", self._serial, "shell", "df", "-h"],
                startupinfo=_si, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            output = r.stdout or r.stderr or "(no output)"
            partitions = self._parse_df(output)
            PRIORITY = ["/data", "/", "/vendor", "/cache", "/efs"]
            partitions.sort(key=lambda x: PRIORITY.index(x[0]) if x[0] in PRIORITY else 99)
            # Row 0: s0, s1
            for i, key in enumerate(["s0", "s1"]):
                if i < len(partitions):
                    mount, used, total = partitions[i]
                    label = f"{used/1024:.1f}G/{total/1024:.1f}G"
                    chart = self._diag_storage_row0._charts.get(key)
                    if chart:
                        chart.title = mount
                        chart.set_data(used, total, label)
                    self._diag_storage_row0.update_chart(key, used, total, label)
                else:
                    chart = self._diag_storage_row0._charts.get(key)
                    if chart:
                        chart.setVisible(False)
            # Row 1: s2, s3
            for i, key in enumerate(["s2", "s3"]):
                pidx = i + 2
                if pidx < len(partitions):
                    mount, used, total = partitions[pidx]
                    label = f"{used/1024:.1f}G/{total/1024:.1f}G"
                    chart = self._diag_storage_row1._charts.get(key)
                    if chart:
                        chart.title = mount
                        chart.set_data(used, total, label)
                    self._diag_storage_row1.update_chart(key, used, total, label)
                else:
                    chart = self._diag_storage_row1._charts.get(key)
                    if chart:
                        chart.setVisible(False)
        except Exception:
            pass

    # ── Live Device Metrics helpers ───────────────────────────────────────

    def _refresh_metrics(self):
        if not self._serial:
            return
        # Stop existing worker if running
        if self._metrics_worker and self._metrics_worker.isRunning():
            self._metrics_worker.stop()
        # Start new worker
        w = self._MetricsWorker(self._serial)
        w.cpu_ready.connect(self._on_metrics_cpu)
        w.ram_ready.connect(self._on_metrics_ram)
        w.battery_ready.connect(self._on_metrics_battery)
        self._metrics_worker = w
        w.start()

    def _on_metrics_cpu(self, pct: float):
        self._cpu_chart.push(pct)

    def _on_metrics_ram(self, used: int, total: int):
        if total > 0:
            self._ram_chart.max_val = float(total)
        self._ram_chart.push(float(used))

    def _on_metrics_battery(self, level: int, charging: bool):
        self._metrics_battery_bar.set_state(level, charging)
        status = "Charging ⚡" if charging else "Discharging"
        self._metrics_bat_detail_lbl.setText(f"{level}%  —  {status}")

    def _toggle_metrics_auto_refresh(self, checked: bool):
        if checked:
            self._auto_timer.start(self._metrics_interval_spin.value() * 1000)
            self._metrics_auto_btn.setText("⏹ Stop Auto-Refresh")
            self._metrics_auto_btn.setStyleSheet(
                "QPushButton { background-color: #d32f2f; color: white; font-weight: bold;"
                " padding: 5px 12px; border-radius: 4px; font-size: 11px; border: none; }"
                "QPushButton:hover { background-color: #b71c1c; }"
            )
            self._refresh_metrics()
        else:
            self._auto_timer.stop()
            # Stop the metrics worker when disabling auto-refresh
            if self._metrics_worker and self._metrics_worker.isRunning():
                self._metrics_worker.stop()
            self._metrics_auto_btn.setText("▶ Start Auto-Refresh")
            self._metrics_auto_btn.setStyleSheet(
                "QPushButton { background-color: #388e3c; color: white; font-weight: bold;"
                " padding: 5px 12px; border-radius: 4px; font-size: 11px; border: none; }"
                "QPushButton:hover { background-color: #2e7d32; }"
            )



