"""
Device Information tab.
Shows detailed hardware / SIM / network info for the selected device,
fetched on-demand via ADB — uses every available method to maximise data coverage.
"""
from __future__ import annotations

import subprocess
import os
import re

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QCheckBox, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal

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
            # Pattern: lat=12.345 / latitude=12.345
            for lat_pat in [
                r"lat(?:itude)?\s*[=:]\s*([-\d.]+)",
                r"mLastKnownLocation.*?lat\s*[=:]\s*([-\d.]+)",
            ]:
                m = re.search(lat_pat, loc, re.IGNORECASE | re.DOTALL)
                if m:
                    lat = m.group(1)
                    break
            for lon_pat in [
                r"lon(?:gitude)?\s*[=:]\s*([-\d.]+)",
                r"mLastKnownLocation.*?lon(?:gitude)?\s*[=:]\s*([-\d.]+)",
            ]:
                m = re.search(lon_pat, loc, re.IGNORECASE | re.DOTALL)
                if m:
                    lon = m.group(1)
                    break
            # Compact form: Location[gps 12.345,-67.890]
            if not lat:
                m = re.search(r"Location\[[\w\s]+([-\d.]+),([-\d.]+)", loc)
                if m:
                    lat, lon = m.group(1), m.group(2)

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
            })
        except Exception as e:
            self.error.emit(str(e))


# ── Styles ────────────────────────────────────────────────────────────────
_GROUP_SS = """
    QGroupBox {
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #c8d0e0;
        border-radius: 8px;
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
    "  border: 1px solid #dce3f0;"
    "  border-radius: 4px;"
    "  padding: 2px 6px;"
    "  background: #ffffff;"
    "  color: #212121;"
    "  font-size: 11px;"
    "  min-height: 20px;"
    "}"
    "QLineEdit:read-only { background: #f7f9ff; }"
    "QLineEdit:focus { border: 1px solid #1976d2; }"
)

_LABEL_SS = "color: #555; font-size: 11px; font-weight: bold;"


# ── DeviceInfoWidget ─────────────────────────────────────────────────────
class DeviceInfoWidget(QWidget):
    """Tab page — shows live device info for the selected device."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._worker: _FetchWorker | None = None
        self._build_ui()

    # ── public API ───────────────────────────────────────────────────────
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
            fl.setContentsMargins(12, 10, 12, 10)
            fl.setSpacing(6)
            fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            fl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            g.setLayout(fl)
            return g, fl

        # ── Group 1: Device Information ──────────────────────────────────
        g1, f1 = _group("Device Information")
        self._f_brand        = _field()
        self._f_model        = _field()
        self._f_manufacturer = _field()
        self._f_android      = _field()
        self._f_sdk          = _field()
        self._f_serial_no    = _field()
        self._f_cpu_abi      = _field()
        self._f_resolution   = _field()
        self._f_ram          = _field()

        f1.addRow(_lbl("Brand"),        self._f_brand)
        f1.addRow(_lbl("Model"),        self._f_model)
        f1.addRow(_lbl("Manufacturer"), self._f_manufacturer)
        f1.addRow(_lbl("Android OS"),   self._f_android)
        f1.addRow(_lbl("SDK Version"),  self._f_sdk)
        f1.addRow(_lbl("Serial No."),   self._f_serial_no)
        f1.addRow(_lbl("CPU ABI"),      self._f_cpu_abi)
        f1.addRow(_lbl("Resolution"),   self._f_resolution)
        f1.addRow(_lbl("RAM"),          self._f_ram)
        inner_vl.addWidget(g1)

        # ── Group 2: SIM / Telephony ─────────────────────────────────────
        g2, f2 = _group("SIM / Telephony")
        self._f_imei    = _field()
        self._f_simcode = _field()
        self._f_iccid   = _field()
        self._f_subid   = _field()
        self._f_phone   = _field()

        f2.addRow(_lbl("IMEI"),              self._f_imei)
        f2.addRow(_lbl("SIM CODE"),          self._f_simcode)
        f2.addRow(_lbl("ICCID"),             self._f_iccid)
        f2.addRow(_lbl("Sim Subscriber ID"), self._f_subid)
        f2.addRow(_lbl("Phone Number"),      self._f_phone)
        inner_vl.addWidget(g2)

        # ── Group 3: Location / Network ──────────────────────────────────
        g3, f3 = _group("Location / Network")
        self._f_lat  = _field()
        self._f_lon  = _field()
        self._f_wifi = _field()

        f3.addRow(_lbl("Latitude"),  self._f_lat)
        f3.addRow(_lbl("Longitude"), self._f_lon)

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
        f3.addRow(_lbl("Wifi Name"), wifi_w)

        self._wifi_manual_input = QLineEdit()
        self._wifi_manual_input.setPlaceholderText("Enter Wifi name manually…")
        self._wifi_manual_input.setStyleSheet(_FIELD_SS)
        self._wifi_manual_input.hide()
        self._wifi_manual_input.returnPressed.connect(
            lambda: self.load_device(self._serial)
        )
        f3.addRow(QLabel(""), self._wifi_manual_input)
        inner_vl.addWidget(g3)
        inner_vl.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # Collect all data fields for bulk clear/loading operations
        self._all_data_fields = [
            self._f_brand, self._f_model, self._f_manufacturer,
            self._f_android, self._f_sdk, self._f_serial_no,
            self._f_cpu_abi, self._f_resolution, self._f_ram,
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
