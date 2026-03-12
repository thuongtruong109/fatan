from __future__ import annotations

import subprocess, os, re, time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QCheckBox, QComboBox, QScrollArea, QFrame, QSizePolicy,
    QFileDialog, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
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

def _decode_iphonesubinfo(raw: str) -> str:
    """Decode the UTF-16LE parcel output of `service call iphonesubinfo N`.

    Handles two output formats:

    Multi-line addressed format (most Android versions):
      0x00000000: 00000000 0000000f 00350033 00350033 '........3.5.3.5.'

    Single-line inline format (some devices/ROMs):
      Result: Parcel(00000000 00000002 00310030 00000000 '........0.1.....')

    Each 32-bit word is printed as a big-endian hex integer representing the
    value, but the actual bytes in device memory are little-endian, so the word
    '00350033' is stored as bytes 0x33 0x00 0x35 0x00 (i.e. two UTF-16LE chars:
    0x0033='3' and 0x0035='5').

    We collect all words globally (across lines), skip the first two (status
    word i=0 and string-length word i=1), then decode pairs of bytes.
    """
    all_words: list = []
    for line in raw.splitlines():
        # Format 1: "  0x00000000: 00000000 0000000f 00350033 ..."
        m = re.match(r"\s*0x[0-9a-f]+:\s+([0-9a-f\s]+)", line, re.IGNORECASE)
        if m:
            all_words.extend(w for w in m.group(1).split() if len(w) == 8)
            continue
        # Format 2: "Result: Parcel(00000000 00000002 00310030 ... '...')"
        m2 = re.search(r"Parcel\(([0-9a-f\s]+)", line, re.IGNORECASE)
        if m2:
            # Strip the trailing ASCII representation after the last hex word
            hex_part = re.sub(r"'[^']*'.*$", "", m2.group(1))
            all_words.extend(w for w in hex_part.split() if len(w) == 8)

    chars = []
    for i, word in enumerate(all_words):
        if i < 2:
            continue  # skip status (i=0) and string-length (i=1) words
        # The word is printed as a 32-bit big-endian hex value.
        # The device stores it little-endian in memory, so the actual byte layout is:
        #   word '00350033' → val=0x00350033
        #   memory bytes: 0x33 0x00 0x35 0x00  (LE u32)
        #   UTF-16LE pair: char0 = 0x0033='3' (bytes 0-1),  char1 = 0x0035='5' (bytes 2-3)
        # In terms of the printed value: char0 = low 16-bits, char1 = high 16-bits
        # But the string is stored MSB-word first in the parcel, so high word comes
        # BEFORE low word in character order:
        #   char1 (high 16) is the FIRST char, char0 (low 16) is the SECOND.
        val = int(word, 16)
        char_first  = (val >> 16) & 0xFFFF  # high 16-bit word → first char
        char_second = val & 0xFFFF           # low  16-bit word → second char
        for cp in (char_first, char_second):
            if cp == 0:
                continue  # null / padding
            if 0x20 <= cp <= 0x7e:
                chars.append(chr(cp))

    return "".join(chars).strip()


def _decode_iphonesubinfo_int(raw: str) -> str:
    """Decode a parcel that returns a single int32 (e.g. iphonesubinfo 5).

    The shell output looks like:
      Result: Parcel(
        0x00000000: 00000000 00000001                   '........')
    Word i=0 is status (0 = OK), word i=1 is the int32 value.
    Returns the value as a string, or "" if not decodable.
    """
    all_words: list = []
    for line in raw.splitlines():
        m = re.match(r"\s*0x[0-9a-f]+:\s+([0-9a-f\s]+)", line, re.IGNORECASE)
        if m:
            all_words.extend(w for w in m.group(1).split() if len(w) == 8)
            continue
        m2 = re.search(r"Parcel\(([0-9a-f\s]+)", line, re.IGNORECASE)
        if m2:
            hex_part = re.sub(r"'[^']*'.*$", "", m2.group(1))
            all_words.extend(w for w in hex_part.split() if len(w) == 8)
    # Word 0 = status (must be 0 for OK), word 1 = the int32 result
    if len(all_words) >= 2 and all_words[0] == "00000000":
        try:
            val = int(all_words[1], 16)
            return str(val)
        except ValueError:
            pass
    return ""

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
            # Method 2: service call iphonesubinfo 1 — decode UTF-16LE parcel hex output
            if not imei:
                raw = _shell(s, "service call iphonesubinfo 1", timeout=6)
                candidate = _decode_iphonesubinfo(raw)
                if re.fullmatch(r"\d{14,15}", candidate):
                    imei = candidate
            # Method 3: service call phone 4 (some custom ROMs) — decode UTF-16LE parcel
            if not imei:
                raw = _shell(s, "service call phone 4", timeout=5)
                candidate = _decode_iphonesubinfo(raw)
                if re.fullmatch(r"\d{14,15}", candidate):
                    imei = candidate
            # Method 4: getprop fallbacks
            if not imei:
                imei = _first(
                    p("ril.imei", "persist.radio.imei", "gsm.imei"),
                    _prop(s, "ril.imei"),
                    _prop(s, "gsm.imei"),
                )

            # ── Subscription Index (iphonesubinfo 5 → sub-ID) ────────────
            # Some devices encode this as a UTF-16LE string (e.g. "10"),
            # others return a raw int32. Try string decoder first, fall back
            # to int decoder so both formats are covered.
            subscription_index = ""
            try:
                sub_raw = _shell(s, "service call iphonesubinfo 5", timeout=6)
                # Try UTF-16LE string decode first (handles inline Parcel format)
                sub_candidate = _decode_iphonesubinfo(sub_raw)
                if re.fullmatch(r"-?\d+", sub_candidate):
                    subscription_index = sub_candidate
                # Fall back to int32 decode
                if not subscription_index:
                    sub_candidate = _decode_iphonesubinfo_int(sub_raw)
                    if sub_candidate:
                        subscription_index = sub_candidate
            except Exception:
                pass

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
                "iccid":              iccid,
                "subscriber_id":      subscriber_id,
                "subscription_index": subscription_index,
                "phone_number":       phone,
                "latitude":           lat,
                "longitude":          lon,
                "wifi_name":          wifi_name,
                "uptime":             uptime,
            })
        except Exception as e:
            self.error.emit(str(e))

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

    def stop(self):
        self._running = False
        self.requestInterruption()
        self.quit()
        self.wait(2000)

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

# ── DashboardWidget ─────────────────────────────────────────────────────
class DashboardWidget(QWidget):
    """Tab page — shows live device info for the selected device."""
    status_update = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._worker: _FetchWorker | None = None
        self._metrics_worker = None
        self._top_worker = None
        self._auto_timer = QTimer()
        self._auto_timer.timeout.connect(self._refresh_metrics)
        self._build_ui()

    def __del__(self):
        """Cleanup when widget is destroyed."""
        if self._metrics_worker and self._metrics_worker.isRunning():
            if hasattr(self._metrics_worker, 'stop'):
                self._metrics_worker.stop()
            else:
                self._metrics_worker.quit()
        if self._top_worker and self._top_worker.isRunning():
            self._top_worker.stop()

    # ── public API ───────────────────────────────────────────────────────
    def set_device(self, serial: str):
        """Called when user selects a row in the table."""
        # Stop existing metrics worker when changing devices
        if self._metrics_worker and self._metrics_worker.isRunning():
            if hasattr(self._metrics_worker, 'stop'):
                self._metrics_worker.stop()
            else:
                self._metrics_worker.quit()

        self._serial = serial
        label = f"Serial: {serial}" if serial else "No device selected"
        self._serial_label.setText(label)
        enabled = bool(serial)
        # Auto-load diagnostics charts immediately
        if serial:
            self._diag_run_free()
            self._diag_run_top()
            self._diag_run_df()
            self._diag_run_procrank()
            self._diag_run_disk()
            # Start real-time top worker
            self._start_top_worker()
            # Auto-start live metrics refresh
            if not self._metrics_auto_btn.isChecked():
                self._metrics_auto_btn.setChecked(True)
            else:
                self._refresh_metrics()
        else:
            self._stop_top_worker()
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
        self._f_imei      = _field()
        self._f_simcode   = _field()
        self._f_iccid     = _field()
        self._f_subid     = _field()
        self._f_sub_index = _field()
        self._f_phone     = _field()

        f2.addRow(_lbl("🔑 IMEI"),              self._f_imei)
        f2.addRow(_lbl("📶 SIM Code"),           self._f_simcode)
        f2.addRow(_lbl("🪪 ICCID"),              self._f_iccid)
        f2.addRow(_lbl("🆔 Subscriber ID"),      self._f_subid)
        f2.addRow(_lbl("🔢 Sub. Index"),         self._f_sub_index)
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

        # ── System Diagnostics ────────────────────────────────────────────
        from features.activities import (
            _DonutRow, _SparklineChart, _BatteryBar, _MetricsWorker, _TopWorker,
            parse_free, parse_df,
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
        diag_btn_row = QHBoxLayout()
        diag_btn_row.setSpacing(6)

        b_refresh = _btn_primary("🔄 Refresh Charts")
        b_refresh.clicked.connect(self._diag_refresh_all)
        diag_btn_row.addWidget(b_refresh)
        diag_btn_row.addStretch()
        diag_vl.addLayout(diag_btn_row)

        # — Charts row: Memory + Storage Partitions auto-responsive —
        diag_cols = QHBoxLayout()
        diag_cols.setSpacing(20)

        # Memory group
        mem_col = QVBoxLayout()
        mem_col.setSpacing(4)
        _ram_lbl = QLabel("🧠 Memory")
        _ram_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        mem_col.addWidget(_ram_lbl)
        self._diag_ram_donuts = _DonutRow([
            ("mem",  "RAM",  QColor("#388e3c")),
            ("swap", "Swap", QColor("#7b1fa2")),
        ], size=100)
        mem_col.addWidget(self._diag_ram_donuts)
        mem_w = QWidget()
        mem_w.setLayout(mem_col)
        mem_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        diag_cols.addWidget(mem_w)

        # Storage Partitions group (all 4 in one row)
        stor_col = QVBoxLayout()
        stor_col.setSpacing(4)
        _stor_lbl = QLabel("💾 Storage Partitions")
        _stor_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        stor_col.addWidget(_stor_lbl)
        _STOR_COLORS = [QColor("#00796b"), QColor("#f57c00"), QColor("#546e7a"), QColor("#7b1fa2")]
        _STOR_KEYS   = ["s0", "s1", "s2", "s3"]
        self._diag_storage_row = _DonutRow(
            [(k, "–", c) for k, c in zip(_STOR_KEYS, _STOR_COLORS)],
            size=100,
        )
        stor_col.addWidget(self._diag_storage_row)
        stor_w = QWidget()
        stor_w.setLayout(stor_col)
        stor_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        diag_cols.addWidget(stor_w)

        diag_cols.addStretch()
        diag_vl.addLayout(diag_cols)

        # — Procrank process memory table —
        _proc_lbl = QLabel("🔬 Process Memory (procrank)")
        _proc_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        diag_vl.addWidget(_proc_lbl)

        self._procrank_table = QTableWidget()
        self._procrank_table.setColumnCount(7)
        self._procrank_table.setHorizontalHeaderLabels(["PID", "Vss(K)", "Rss(K)", "Pss(K)", "Uss(K)", "Swap(K)", "Process"])
        self._procrank_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._procrank_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._procrank_table.setAlternatingRowColors(True)
        self._procrank_table.verticalHeader().hide()
        self._procrank_table.setFixedHeight(200)
        ph = self._procrank_table.horizontalHeader()
        ph.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for _ci in range(6):
            ph.setSectionResizeMode(_ci, QHeaderView.ResizeMode.ResizeToContents)
        self._procrank_table.setStyleSheet(
            "QTableWidget { font-size: 10px; gridline-color: #e0e0e0; }"
            "QHeaderView::section { font-weight: bold; background: #f0f0f0; font-size: 10px; }"
        )
        diag_vl.addWidget(self._procrank_table)

        self._procrank_summary_lbl = QLabel("")
        self._procrank_summary_lbl.setStyleSheet("font-size: 10px; color: #555; padding: 2px 0;")
        diag_vl.addWidget(self._procrank_summary_lbl)

        diag_group.setLayout(diag_vl)
        inner_vl.addWidget(diag_group)

        # ── Real-time Top Process Table ───────────────────────────────────
        top_group = QGroupBox("📊 Real-time CPU Processes")
        top_group.setStyleSheet(_GROUP_SS)
        top_vl = QVBoxLayout()
        top_vl.setContentsMargins(10, 10, 10, 10)
        top_vl.setSpacing(6)

        self._top_header_lbl = QLabel("")
        self._top_header_lbl.setStyleSheet(
            "font-size: 10px; color: #1976d2; padding: 2px 6px;"
            " background: #e3f2fd; border-radius: 3px;"
        )
        self._top_header_lbl.setWordWrap(True)
        top_vl.addWidget(self._top_header_lbl)

        self._top_table = QTableWidget()
        self._top_table.setColumnCount(11)
        self._top_table.setHorizontalHeaderLabels(
            ["PID", "USER", "PR", "NI", "VIRT", "RES", "SHR", "S", "%CPU", "%MEM", "ARGS"]
        )
        self._top_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._top_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._top_table.setAlternatingRowColors(True)
        self._top_table.verticalHeader().hide()
        self._top_table.setFixedHeight(220)
        _th = self._top_table.horizontalHeader()
        _th.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)  # ARGS stretches
        for _ci in range(10):
            _th.setSectionResizeMode(_ci, QHeaderView.ResizeMode.ResizeToContents)
        self._top_table.setStyleSheet(
            "QTableWidget { font-size: 10px; gridline-color: #e0e0e0; }"
            "QHeaderView::section { font-weight: bold; background: #f0f0f0; font-size: 10px; }"
        )
        top_vl.addWidget(self._top_table)

        top_group.setLayout(top_vl)
        inner_vl.addWidget(top_group)

        # ── Disk Info ─────────────────────────────────────────────────────
        disk_group = QGroupBox("💽 Disk")
        disk_group.setStyleSheet(_GROUP_SS)
        disk_vl = QVBoxLayout()
        disk_vl.setContentsMargins(10, 10, 10, 10)
        disk_vl.setSpacing(6)

        disk_btn_row = QHBoxLayout()
        disk_btn_row.setSpacing(6)
        disk_refresh_btn = QPushButton("🔄 Refresh Disk")
        disk_refresh_btn.setFixedHeight(28)
        disk_refresh_btn.setStyleSheet(
            "QPushButton { border:1px solid #bdbdbd; border-radius:4px;"
            " padding:2px 10px; background:#f0f0f0; font-size:11px; }"
            "QPushButton:hover { background:#e0e0e0; }"
        )
        disk_refresh_btn.clicked.connect(self._diag_run_disk)
        disk_btn_row.addWidget(disk_refresh_btn)
        disk_btn_row.addStretch()
        disk_vl.addLayout(disk_btn_row)

        self._disk_table = QTableWidget()
        self._disk_table.setColumnCount(6)
        self._disk_table.setHorizontalHeaderLabels(
            ["Filesystem", "1K-blocks", "Used", "Available", "Use%", "Mounted on"]
        )
        self._disk_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._disk_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._disk_table.setAlternatingRowColors(True)
        self._disk_table.verticalHeader().hide()
        self._disk_table.setFixedHeight(220)
        _dh = self._disk_table.horizontalHeader()
        _dh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        _dh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for _ci in range(1, 5):
            _dh.setSectionResizeMode(_ci, QHeaderView.ResizeMode.ResizeToContents)
        self._disk_table.setStyleSheet(
            "QTableWidget { font-size: 10px; gridline-color: #e0e0e0; font-family: Consolas, monospace; }"
            "QHeaderView::section { font-weight: bold; background: #f0f0f0; font-size: 10px; }"
        )
        disk_vl.addWidget(self._disk_table)

        disk_group.setLayout(disk_vl)
        inner_vl.addWidget(disk_group)

        # Keep references for use in methods
        self._DonutRow = _DonutRow
        self._MetricsWorker = _MetricsWorker
        self._TopWorker = _TopWorker
        self._parse_free = parse_free
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
            self._f_subid, self._f_sub_index, self._f_phone,
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
            (self._f_sub_index,    "subscription_index"),
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

    # ── System Diagnostics helpers ────────────────────────────────────────

    def _diag_refresh_all(self):
        """Refresh all three diagnostic charts at once."""
        self._diag_run_free()
        self._diag_run_top()
        self._diag_run_df()
        self._diag_run_procrank()
        self._diag_run_disk()

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
        pass  # CPU breakdown charts removed; top process table is updated by _TopWorker

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
            for i, key in enumerate(["s0", "s1", "s2", "s3"]):
                if i < len(partitions):
                    mount, used, total = partitions[i]
                    label = f"{used/1024:.1f}G/{total/1024:.1f}G"
                    chart = self._diag_storage_row._charts.get(key)
                    if chart:
                        chart.title = mount
                        chart.set_data(used, total, label)
                    self._diag_storage_row.update_chart(key, used, total, label)
                else:
                    chart = self._diag_storage_row._charts.get(key)
                    if chart:
                        chart.setVisible(False)
        except Exception:
            pass

    def _diag_run_disk(self):
        """Populate the Disk table using `adb shell df`."""
        if not self._serial:
            return
        try:
            import subprocess as _sp
            r = _sp.run(
                ["adb", "-s", self._serial, "shell", "df"],
                startupinfo=_si, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            output = (r.stdout or r.stderr or "").strip()
            self._populate_disk_table(output)
        except Exception:
            pass

    def _populate_disk_table(self, output: str):
        """Parse `adb shell df` output and fill the disk table.

        Expected header:
          Filesystem       1K-blocks    Used Available Use% Mounted on
        """
        self._disk_table.setRowCount(0)
        lines = output.splitlines()
        # Skip header line(s)
        data_lines = [l for l in lines if l.strip() and not l.strip().startswith("Filesystem")]
        for line in data_lines:
            parts = line.split()
            # A line may be split across two lines when filesystem name is long;
            # valid data lines should have at least 6 fields.
            if len(parts) < 6:
                continue
            filesystem  = parts[0]
            blocks_1k   = parts[1]
            used        = parts[2]
            available   = parts[3]
            use_pct     = parts[4]
            mounted_on  = parts[5] if len(parts) > 5 else ""

            ri = self._disk_table.rowCount()
            self._disk_table.insertRow(ri)
            values = [filesystem, blocks_1k, used, available, use_pct, mounted_on]
            for ci, val in enumerate(values):
                item = QTableWidgetItem(val)
                # Colour Use% column by usage level
                if ci == 4:
                    try:
                        pct = int(val.rstrip("%"))
                        if pct >= 90:
                            item.setForeground(QColor("#c62828"))
                        elif pct >= 70:
                            item.setForeground(QColor("#e65100"))
                    except ValueError:
                        pass
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif ci in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self._disk_table.setItem(ri, ci, item)

    # ── Live Device Metrics helpers ───────────────────────────────────────

    def _diag_run_procrank(self):
        if not self._serial:
            return
        try:
            import subprocess as _sp
            r = _sp.run(
                ["adb", "-s", self._serial, "shell", "procrank"],
                startupinfo=_si, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            output = (r.stdout or "").strip()

            # Fallback: procrank not available → use dumpsys meminfo
            if not output or "not found" in output.lower() or "permission denied" in output.lower() or "error" in output.lower():
                r2 = _sp.run(
                    ["adb", "-s", self._serial, "shell", "dumpsys", "meminfo"],
                    startupinfo=_si, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=20,
                )
                output2 = (r2.stdout or "").strip()
                self._populate_meminfo_table(output2)
                return

            self._populate_procrank_table(output)
        except Exception:
            pass

    def _populate_procrank_table(self, output: str):
        """Parse procrank output and fill the table."""
        rows = []
        summary = ""
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("PID") or line.startswith("----"):
                continue
            # Summary lines: "RAM:" or "ZRAM:"
            if re.match(r"(RAM|ZRAM):", line, re.IGNORECASE):
                summary = (summary + "  " + line).strip() if summary else line
                continue
            # procrank line: PID Vss Rss Pss Uss [Swap] cmdline
            # format: " 1234  1234K  1234K  1234K  1234K  1234K  /init"
            m = re.match(
                r"(\d+)\s+([\d]+)K\s+([\d]+)K\s+([\d]+)K\s+([\d]+)K(?:\s+([\d]+)K)?\s+(.+)",
                line,
            )
            if m:
                pid, vss, rss, pss, uss = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
                swap = m.group(6) or "0"
                proc = m.group(7).strip()
                rows.append((pid, vss, rss, pss, uss, swap, proc))

        self._procrank_table.setRowCount(0)
        self._procrank_table.setHorizontalHeaderLabels(["PID", "Vss(K)", "Rss(K)", "Pss(K)", "Uss(K)", "Swap(K)", "Process"])
        for r_data in rows:
            ri = self._procrank_table.rowCount()
            self._procrank_table.insertRow(ri)
            for ci, val in enumerate(r_data):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if ci < 6 else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self._procrank_table.setItem(ri, ci, item)

        self._procrank_summary_lbl.setText(summary)

    def _populate_meminfo_table(self, output: str):
        """Fallback: parse `dumpsys meminfo` and populate the table.

        dumpsys meminfo format (relevant section):
          ** MEMINFO in pid 1234 [com.example.app] **
          ...
          TOTAL PSS:    4567  TOTAL RSS:  8901  ...

        Or the summary section at top:
          Total PSS by process:
               12345 kB: com.android.systemui (pid 1234)
               ...
        We parse both forms.
        """
        self._procrank_table.setRowCount(0)
        self._procrank_table.setHorizontalHeaderLabels(
            ["PID", "PSS(K)", "Rss(K)", "Pss(K)", "Uss(K)", "Swap(K)", "Process"]
        )

        rows = []  # (pid, pss_kb, proc_name)

        # Form 1: summary section lines like "   12345 kB: com.example.app (pid 6789)"
        for line in output.splitlines():
            # "      12345 kB: com.android.systemui (pid 1234)"
            m = re.match(r"\s*(\d+)\s+kB:\s+(.+?)\s+\(pid\s+(\d+)\)", line)
            if m:
                pss_kb = m.group(1)
                proc   = m.group(2).strip()
                pid    = m.group(3)
                rows.append((pid, pss_kb, proc))
                continue
            # Form 2: "** MEMINFO in pid 1234 [com.example.app] **"
            # followed later by "TOTAL PSS:  12345"
            # We handle this in the second pass below

        # Form 2 fallback: scan for "** MEMINFO in pid NNN [name] **" blocks
        if not rows:
            current_pid = ""
            current_proc = ""
            for line in output.splitlines():
                mm = re.match(r"\*+\s*MEMINFO in pid\s+(\d+)\s+\[(.+?)\]", line, re.IGNORECASE)
                if mm:
                    current_pid  = mm.group(1)
                    current_proc = mm.group(2).strip()
                    continue
                if current_pid:
                    # "TOTAL PSS:   1234  TOTAL RSS:  5678  TOTAL SWAP ..."
                    tm = re.search(r"TOTAL\s+PSS\s*:\s*(\d+)", line, re.IGNORECASE)
                    if tm:
                        rows.append((current_pid, tm.group(1), current_proc))
                        current_pid = ""
                        current_proc = ""

        # Sort by PSS descending
        try:
            rows.sort(key=lambda x: int(x[1]), reverse=True)
        except Exception:
            pass

        for pid, pss_kb, proc in rows:
            ri = self._procrank_table.rowCount()
            self._procrank_table.insertRow(ri)
            values = [pid, pss_kb, "", pss_kb, "", "", proc]
            for ci, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter if ci < 6
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self._procrank_table.setItem(ri, ci, item)

        count = self._procrank_table.rowCount()
        self._procrank_summary_lbl.setText(
            f"(fallback: dumpsys meminfo — {count} processes — install 'procrank' for Vss/Rss/Uss/Swap)"
            if count else "(dumpsys meminfo returned no process data)"
        )

    def _refresh_metrics(self):
        if not self._serial:
            return
        # Stop existing worker if running
        if self._metrics_worker and self._metrics_worker.isRunning():
            if hasattr(self._metrics_worker, 'stop'):
                self._metrics_worker.stop()
            else:
                self._metrics_worker.quit()
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
                if hasattr(self._metrics_worker, 'stop'):
                    self._metrics_worker.stop()
                else:
                    self._metrics_worker.quit()
            self._metrics_auto_btn.setText("▶ Start Auto-Refresh")
            self._metrics_auto_btn.setStyleSheet(
                "QPushButton { background-color: #388e3c; color: white; font-weight: bold;"
                " padding: 5px 12px; border-radius: 4px; font-size: 11px; border: none; }"
                "QPushButton:hover { background-color: #2e7d32; }"
            )

    # ── Real-time top process table ───────────────────────────────────────

    def _start_top_worker(self):
        """Start (or restart) the background top-polling thread."""
        self._stop_top_worker()
        if not self._serial:
            return
        w = self._TopWorker(self._serial, interval=2)
        w.header_ready.connect(self._on_top_header)
        w.rows_ready.connect(self._on_top_rows)
        self._top_worker = w
        w.start()

    def _stop_top_worker(self):
        if self._top_worker and self._top_worker.isRunning():
            self._top_worker.stop()
        self._top_worker = None

    def _on_top_header(self, header: str):
        """Update the summary label above the top table."""
        self._top_header_lbl.setText(header)

    def _on_top_rows(self, rows: list):
        """Repopulate the top process table without flicker."""
        tbl = self._top_table
        tbl.setUpdatesEnabled(False)
        tbl.setRowCount(0)

        _CPU_HIGH   = QColor("#ffebee")   # light red  — high cpu
        _CPU_MED    = QColor("#fff8e1")   # light amber — medium cpu

        for row in rows:
            ri = tbl.rowCount()
            tbl.insertRow(ri)
            values = [
                row.get("pid",  ""),
                row.get("user", ""),
                row.get("pr",   ""),
                row.get("ni",   ""),
                row.get("virt", ""),
                row.get("res",  ""),
                row.get("shr",  ""),
                row.get("s",    ""),
                row.get("cpu",  ""),
                row.get("mem",  ""),
                row.get("args", "") or row.get("time", ""),
            ]
            try:
                cpu_val = float(row.get("cpu", 0))
            except ValueError:
                cpu_val = 0.0

            for ci, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter if ci < 10
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                # Colour rows by CPU usage
                if cpu_val >= 5.0:
                    item.setBackground(_CPU_HIGH)
                elif cpu_val >= 1.0:
                    item.setBackground(_CPU_MED)
                tbl.setItem(ri, ci, item)

        tbl.setUpdatesEnabled(True)


