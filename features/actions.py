"""
Actions tab.
Provides quick device actions for the selected device:
  • Phone Settings  — Country / Carrier / SIM spoofing options
  • Device Filter   — filter which devices the change applies to
  • Change Device   — apply full device profile change
  • Open URL        — opens any URL in Chrome via ADB intent
  • Login Gmail     — fills Google account credentials in Chrome
"""
from __future__ import annotations

import subprocess
import os
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QTextEdit, QCheckBox, QComboBox, QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal

# ── ADB helper ───────────────────────────────────────────────────────────
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")


def _adb(serial: str, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        startupinfo=_si,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _shell(serial: str, cmd: str) -> str:
    r = _adb(serial, "shell", cmd)
    return (r.stdout or "").strip()


# ── Styles ────────────────────────────────────────────────────────────────
_GROUP_SS = """
    QGroupBox {
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #c8d0e0;
        border-radius: 8px;
        margin-top: 8px;
        padding-top: 6px;
        background-color: #f8f9ff;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: #1565c0;
    }
"""

_INPUT_SS = (
    "QLineEdit {"
    "  border: 1px solid #dce3f0; border-radius: 4px;"
    "  padding: 2px 6px; background: #ffffff; color: #212121;"
    "  font-size: 11px; min-height: 20px;"
    "}"
    "QLineEdit:focus { border: 1px solid #1976d2; }"
)

_COMBO_SS = (
    "QComboBox {"
    "  border: 1px solid #dce3f0; border-radius: 4px;"
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
    "QPushButton { border: 1px solid #bdbdbd; border-radius: 4px;"
    " padding: 5px 14px; background: #f0f0f0; font-size: 11px; }"
    "QPushButton:hover { background: #e0e0e0; }"
    "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
)

_LOG_SS = (
    "QTextEdit {"
    "  background: #1e1e1e; color: #d4d4d4;"
    "  font-family: Consolas, monospace; font-size: 11px;"
    "  border: none; border-radius: 8px; padding: 6px 8px;"
    "}"
)

_LABEL_SS  = "color: #555; font-size: 11px; font-weight: bold;"
_CB_SS     = "QCheckBox { font-size: 11px; color: #333; }"


# ── Country / carrier data ────────────────────────────────────────────────
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


# ── Background workers ────────────────────────────────────────────────────
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
            # ── Logout Gmail if requested ─────────────────────────────────
            if cfg.get("logout_gmail"):
                _adb(s, "shell", "pm", "clear", "com.google.android.gms")
                time.sleep(1)

            # ── Wipe Google data ──────────────────────────────────────────
            if not cfg.get("no_wipe_google"):
                _adb(s, "shell", "pm", "clear", "com.google.android.gsf")
                time.sleep(0.5)

            # ── Fake SIM Info ─────────────────────────────────────────────
            if cfg.get("fake_sim"):
                sim_code = cfg.get("sim_code", "")
                country  = cfg.get("country", "")
                carrier  = cfg.get("carrier", "")
                if sim_code:
                    _shell(s, f"setprop gsm.operator.numeric {sim_code}")
                    _shell(s, f"setprop persist.radio.operator.numeric {sim_code}")
                if carrier:
                    escaped = carrier.replace(" ", "\\ ")
                    _shell(s, f"setprop gsm.operator.alpha {escaped}")
                    _shell(s, f"setprop persist.radio.operator.alpha {escaped}")

            # ── Fake MAC Address ──────────────────────────────────────────
            if cfg.get("fake_mac"):
                import random
                mac = ":".join(f"{random.randint(0,255):02x}" for _ in range(6))
                # Locally-administered bit
                first = int(mac.split(":")[0], 16) | 0x02
                parts = mac.split(":")
                parts[0] = f"{first:02x}"
                mac = ":".join(parts)
                _shell(s, f"ip link set wlan0 address {mac} 2>/dev/null || true")

            # ── Change Timezone ───────────────────────────────────────────
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
                    _shell(s, f"setprop persist.sys.timezone {tz}")
                    _adb(s, "shell", "settings", "put", "global", "time_zone", tz)

            # ── Fake GPS location ─────────────────────────────────────────
            if cfg.get("fake_location"):
                _adb(s, "shell", "settings", "put", "secure",
                     "mock_location", "1")
                _adb(s, "shell", "appops", "set",
                     "com.android.shell", "android:mock_location", "allow")

            # ── Pass SafetyNet ────────────────────────────────────────────
            if cfg.get("safetynet"):
                _shell(s, "setprop ro.boot.verifiedbootstate green")
                _shell(s, "setprop ro.boot.flash.locked 1")

            # ── Uninstall apps ────────────────────────────────────────────
            if cfg.get("uninstall_apps"):
                pass  # stub

        except Exception as e:
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
            country  = cfg.get("country", "")
            if sim_code:
                _shell(s, f"setprop gsm.operator.numeric {sim_code}")
                _shell(s, f"setprop persist.radio.operator.numeric {sim_code}")
            if carrier:
                escaped = carrier.replace(" ", "\\ ")
                _shell(s, f"setprop gsm.operator.alpha {escaped}")
                _shell(s, f"setprop persist.radio.operator.alpha {escaped}")
        except Exception as e:
            pass


class _OpenUrlWorker(QThread):
    finished = Signal()

    def __init__(self, serial: str, url: str):
        super().__init__()
        self.serial = serial
        self.url = url

    def run(self):
        try:
            r = _adb(
                self.serial,
                "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", self.url,
            )
        except Exception:
            pass


class _LoginGmailWorker(QThread):
    finished = Signal()

    def __init__(self, serial: str, email: str, password: str, clear_first: bool = False):
        super().__init__()
        self.serial = serial
        self.email = email
        self.password = password
        self.clear_first = clear_first

    def _input_text(self, text: str):
        escaped = (text
                   .replace("'", "\\'")
                   .replace('"', '\\"')
                   .replace(" ", "%s")
                   .replace("&", "\\&"))
        _adb(self.serial, "shell", f"input text '{escaped}'")

    def run(self):
        try:
            s = self.serial
            if self.clear_first:
                _adb(s, "shell", "pm", "clear", "com.google.android.gms")
                time.sleep(2)
            _adb(
                s, "shell", "am", "start",
                "-a", "android.settings.ADD_ACCOUNT_SETTINGS",
                "--es", "account_types", "com.google",
            )
            time.sleep(3)
            _adb(s, "shell", "input", "keyevent", "KEYCODE_TAB")
            time.sleep(0.5)
            self._input_text(self.email)
            time.sleep(0.5)
            _adb(s, "shell", "input", "keyevent", "KEYCODE_ENTER")
            time.sleep(3)
            self._input_text(self.password)
            time.sleep(0.5)
            _adb(s, "shell", "input", "keyevent", "KEYCODE_ENTER")
            time.sleep(4)
        except Exception as e:
            pass


# ── ActionsWidget ─────────────────────────────────────────────────────────
class ActionsWidget(QWidget):
    status_update = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._workers: list[QThread] = []
        self._build_ui()

    # ── public API ────────────────────────────────────────────────────────
    def set_device(self, serial: str):
        self._serial = serial
        label = f"Device: {serial}" if serial else "No device selected"
        self._device_label.setText(label)
        enabled = bool(serial)
        for btn in (self._change_device_btn, self._change_sim_btn,
                    self._open_url_btn, self._login_gmail_btn):
            btn.setEnabled(enabled)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Header
        self._device_label = QLabel("No device selected")
        self._device_label.setStyleSheet("font-weight: bold; color: #1565c0; font-size: 12px;")
        root.addWidget(self._device_label)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        ivl = QVBoxLayout(inner)
        ivl.setContentsMargins(0, 0, 4, 0)
        ivl.setSpacing(8)

        # ── Phone Settings group ──────────────────────────────────────────
        ps_group = QGroupBox("📱 Phone Settings")
        ps_group.setStyleSheet(_GROUP_SS)
        ps_vl = QVBoxLayout()
        ps_vl.setContentsMargins(12, 10, 12, 10)
        ps_vl.setSpacing(8)

        # Row 1: Country / Carrier / Fixed Sim Code
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

        # Row 2: Checkboxes (3 columns × 3 rows)
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
            # col 0
            (self._cb_safetynet,   0, 0),
            (self._cb_fake_sim,    1, 0),
            (self._cb_fake_mac,    2, 0),
            # col 1
            (self._cb_logout_gm,   0, 1),
            (self._cb_no_wipe,     1, 1),
            (self._cb_uninstall,   2, 1),
            # col 2
            (self._cb_random_carr, 0, 2),
            (self._cb_change_tz,   1, 2),
            (self._cb_fake_loc,    2, 2),
        ]
        for widget, row, col in checkboxes:
            cb_grid.addWidget(widget, row, col)

        ps_vl.addLayout(cb_grid)
        ps_group.setLayout(ps_vl)
        ivl.addWidget(ps_group)

        # Populate carriers for default country
        self._on_country_changed(self._country_combo.currentText())

        # ── Device Filter group ───────────────────────────────────────────
        df_group = QGroupBox("🔍 Device Filter")
        df_group.setStyleSheet(_GROUP_SS)
        df_fl = QFormLayout()
        df_fl.setContentsMargins(12, 10, 12, 10)
        df_fl.setSpacing(6)
        df_fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        df_fl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        def _flbl(t: str) -> QLabel:
            l = QLabel(t); l.setStyleSheet(_LABEL_SS); return l

        self._filter_brand = QLineEdit()
        self._filter_brand.setPlaceholderText("e.g. Samsung  (blank = all)")
        self._filter_brand.setStyleSheet(_INPUT_SS)

        self._filter_model = QLineEdit()
        self._filter_model.setPlaceholderText("e.g. SM-G991  (blank = all)")
        self._filter_model.setStyleSheet(_INPUT_SS)

        self._filter_os = QLineEdit()
        self._filter_os.setPlaceholderText("e.g. 12  (blank = all)")
        self._filter_os.setStyleSheet(_INPUT_SS)

        df_fl.addRow(_flbl("Brand:"),       self._filter_brand)
        df_fl.addRow(_flbl("Model:"),       self._filter_model)
        df_fl.addRow(_flbl("Android OS:"),  self._filter_os)
        df_group.setLayout(df_fl)
        ivl.addWidget(df_group)

        # ── Actions group ─────────────────────────────────────────────────
        act_group = QGroupBox("⚡ Actions")
        act_group.setStyleSheet(_GROUP_SS)
        act_vl = QVBoxLayout()
        act_vl.setContentsMargins(12, 10, 12, 10)
        act_vl.setSpacing(8)

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

        act_vl.addLayout(act_btn_row)
        act_group.setLayout(act_vl)
        ivl.addWidget(act_group)

        # ── Open URL group ────────────────────────────────────────────────
        url_group = QGroupBox("🌐 Open URL")
        url_group.setStyleSheet(_GROUP_SS)
        url_vl = QVBoxLayout()
        url_vl.setContentsMargins(12, 10, 12, 10)
        url_vl.setSpacing(8)

        url_form = QFormLayout()
        url_form.setSpacing(6)
        url_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        url_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://example.com")
        self._url_input.setStyleSheet(_INPUT_SS)
        self._url_input.returnPressed.connect(self._run_open_url)
        lbl_url = QLabel("URL:")
        lbl_url.setStyleSheet(_LABEL_SS)
        url_form.addRow(lbl_url, self._url_input)
        url_vl.addLayout(url_form)

        self._open_url_btn = QPushButton("▶ Open URL")
        self._open_url_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._open_url_btn.setEnabled(False)
        self._open_url_btn.clicked.connect(self._run_open_url)
        btn_row_url = QHBoxLayout()
        btn_row_url.addStretch()
        btn_row_url.addWidget(self._open_url_btn)
        url_vl.addLayout(btn_row_url)

        url_group.setLayout(url_vl)
        ivl.addWidget(url_group)

        # ── Login Gmail group ─────────────────────────────────────────────
        gmail_group = QGroupBox("📧 Login Gmail")
        gmail_group.setStyleSheet(_GROUP_SS)
        gmail_vl = QVBoxLayout()
        gmail_vl.setContentsMargins(12, 10, 12, 10)
        gmail_vl.setSpacing(8)

        gmail_form = QFormLayout()
        gmail_form.setSpacing(6)
        gmail_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        gmail_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._gmail_input = QLineEdit()
        self._gmail_input.setPlaceholderText("user@gmail.com")
        self._gmail_input.setStyleSheet(_INPUT_SS)
        lbl_email = QLabel("Email:")
        lbl_email.setStyleSheet(_LABEL_SS)
        gmail_form.addRow(lbl_email, self._gmail_input)

        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("Password")
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setStyleSheet(_INPUT_SS)
        self._password_input.returnPressed.connect(self._run_login_gmail)
        lbl_pwd = QLabel("Password:")
        lbl_pwd.setStyleSheet(_LABEL_SS)
        gmail_form.addRow(lbl_pwd, self._password_input)
        gmail_vl.addLayout(gmail_form)

        self._clear_account_cb = QCheckBox("Clear existing account data before login")
        self._clear_account_cb.setStyleSheet(_CB_SS)
        gmail_vl.addWidget(self._clear_account_cb)

        self._login_gmail_btn = QPushButton("▶ Login Gmail")
        self._login_gmail_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._login_gmail_btn.setEnabled(False)
        self._login_gmail_btn.clicked.connect(self._run_login_gmail)
        btn_row_gmail = QHBoxLayout()
        btn_row_gmail.addStretch()
        btn_row_gmail.addWidget(self._login_gmail_btn)
        gmail_vl.addLayout(btn_row_gmail)

        gmail_group.setLayout(gmail_vl)
        ivl.addWidget(gmail_group)
        ivl.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    # ── Carrier combo update ──────────────────────────────────────────────
    def _on_country_changed(self, country: str):
        self._carrier_combo.clear()
        carriers = _CARRIERS.get(country, _CARRIERS["default"])
        self._carrier_combo.addItems(carriers)

    # ── Build settings dict from UI ───────────────────────────────────────
    def _collect_settings(self) -> dict:
        sim_code = self._simcode_input.text().strip()
        # If random carrier by country is checked, ignore manual carrier
        carrier = "" if self._cb_random_carr.isChecked() else self._carrier_combo.currentText()
        return {
            "country":       self._country_combo.currentText(),
            "carrier":       carrier,
            "sim_code":      sim_code,
            "safetynet":     self._cb_safetynet.isChecked(),
            "fake_sim":      self._cb_fake_sim.isChecked(),
            "fake_mac":      self._cb_fake_mac.isChecked(),
            "logout_gmail":  self._cb_logout_gm.isChecked(),
            "no_wipe_google": self._cb_no_wipe.isChecked(),
            "uninstall_apps": self._cb_uninstall.isChecked(),
            "random_carrier": self._cb_random_carr.isChecked(),
            "change_tz":     self._cb_change_tz.isChecked(),
            "fake_location": self._cb_fake_loc.isChecked(),
            # filters (for multi-device future use)
            "filter_brand":  self._filter_brand.text().strip(),
            "filter_model":  self._filter_model.text().strip(),
            "filter_os":     self._filter_os.text().strip(),
        }

    # ── Action handlers ───────────────────────────────────────────────────
    def _run_change_device(self):
        if not self._serial:
            return
        settings = self._collect_settings()
        self._change_device_btn.setEnabled(False)
        w = _ChangeDeviceWorker(self._serial, settings)
        w.finished.connect(lambda: self._change_device_btn.setEnabled(bool(self._serial)))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _run_change_sim(self):
        if not self._serial:
            return
        settings = self._collect_settings()
        self._change_sim_btn.setEnabled(False)
        w = _ChangeSimWorker(self._serial, settings)
        w.finished.connect(lambda: self._change_sim_btn.setEnabled(bool(self._serial)))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _run_open_url(self):
        if not self._serial:
            return
        url = self._url_input.text().strip()
        if not url:
            self.status_update.emit("⚠ Please enter a URL first.")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self._url_input.setText(url)
        w = _OpenUrlWorker(self._serial, url)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _run_login_gmail(self):
        if not self._serial:
            return
        email    = self._gmail_input.text().strip()
        password = self._password_input.text()
        if not email or not password:
            self.status_update.emit("⚠ Please enter email and password.")
            return
        self._login_gmail_btn.setEnabled(False)
        w = _LoginGmailWorker(self._serial, email, password, self._clear_account_cb.isChecked())
        w.finished.connect(lambda: self._login_gmail_btn.setEnabled(bool(self._serial)))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

