from __future__ import annotations

import subprocess, os, time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QScrollArea, QFrame, QSizePolicy,
    QComboBox, QLineEdit, QCheckBox,
)
from PySide6.QtCore import Qt, Signal, QSize, QThread

from features.actions import _PlayStoreWorker

# ── ADB bootstrap ────────────────────────────────────────────────────────
# (shared with Phone Settings workers below)
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

# ── Phone Settings data ──────────────────────────────────────────────────
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

def _adb_info_tb(serial: str, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        startupinfo=_si,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

def _shell_info_tb(serial: str, cmd: str) -> str:
    r = _adb_info_tb(serial, "shell", cmd)
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
                _adb_info_tb(s, "shell", "pm", "clear", "com.google.android.gms")
                time.sleep(1)
            if not cfg.get("no_wipe_google"):
                _adb_info_tb(s, "shell", "pm", "clear", "com.google.android.gsf")
                time.sleep(0.5)
            if cfg.get("fake_sim"):
                sim_code = cfg.get("sim_code", "")
                carrier  = cfg.get("carrier", "")
                if sim_code:
                    _shell_info_tb(s, f"setprop gsm.operator.numeric {sim_code}")
                    _shell_info_tb(s, f"setprop persist.radio.operator.numeric {sim_code}")
                if carrier:
                    escaped = carrier.replace(" ", "\\ ")
                    _shell_info_tb(s, f"setprop gsm.operator.alpha {escaped}")
                    _shell_info_tb(s, f"setprop persist.radio.operator.alpha {escaped}")
            if cfg.get("fake_mac"):
                import random
                mac = ":".join(f"{random.randint(0,255):02x}" for _ in range(6))
                first = int(mac.split(":")[0], 16) | 0x02
                parts = mac.split(":")
                parts[0] = f"{first:02x}"
                mac = ":".join(parts)
                _shell_info_tb(s, f"ip link set wlan0 address {mac} 2>/dev/null || true")
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
                    _shell_info_tb(s, f"setprop persist.sys.timezone {tz}")
                    _adb_info_tb(s, "shell", "settings", "put", "global", "time_zone", tz)
            if cfg.get("fake_location"):
                _adb_info_tb(s, "shell", "settings", "put", "secure", "mock_location", "1")
                _adb_info_tb(s, "shell", "appops", "set",
                             "com.android.shell", "android:mock_location", "allow")
            if cfg.get("safetynet"):
                _shell_info_tb(s, "setprop ro.boot.verifiedbootstate green")
                _shell_info_tb(s, "setprop ro.boot.flash.locked 1")
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
                _shell_info_tb(s, f"setprop gsm.operator.numeric {sim_code}")
                _shell_info_tb(s, f"setprop persist.radio.operator.numeric {sim_code}")
            if carrier:
                escaped = carrier.replace(" ", "\\ ")
                _shell_info_tb(s, f"setprop gsm.operator.alpha {escaped}")
                _shell_info_tb(s, f"setprop persist.radio.operator.alpha {escaped}")
        except Exception:
            pass


# ── Stylesheet constants ─────────────────────────────────────────────────
_GROUP_SS = """
QGroupBox {
    font-weight: bold; font-size: 12px;
    border: 1px solid #ddd; border-radius: 6px;
    margin-top: 8px; padding-top: 4px;
    background-color: #fafafa;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px;
    padding: 0 6px; color: #1565c0;
}
"""

# Card button: white background, rounded, icon on top, label below
_CARD_SS = """
QPushButton {{
    background-color: #ffffff;
    border: 1.5px solid #e0e0e0;
    border-radius: 12px;
    color: #212121;
    font-size: 11px;
    font-weight: 500;
    padding: 0px;
}}
QPushButton:hover {{
    background-color: #f0f4ff;
    border-color: {accent};
}}
QPushButton:pressed {{
    background-color: #e3eaff;
}}
QPushButton:disabled {{
    background-color: #f5f5f5;
    border-color: #e0e0e0;
    color: #bdbdbd;
}}
"""

_BTN_SS = (
    "QPushButton { border: 1px solid #ccc; border-radius: 4px;"
    " padding: 5px 14px; background: #f0f0f0; font-size: 11px; }"
    "QPushButton:hover { background: #e0e0e0; }"
    "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
)
_BTN_ON_SS = (
    "QPushButton { border: 1px solid #43a047; border-radius: 4px;"
    " padding: 5px 14px; background: #e8f5e9; color: #2e7d32; font-size: 11px; font-weight:bold; }"
    "QPushButton:hover { background: #c8e6c9; }"
    "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
)
_BTN_OFF_SS = (
    "QPushButton { border: 1px solid #e53935; border-radius: 4px;"
    " padding: 5px 14px; background: #ffebee; color: #c62828; font-size: 11px; font-weight:bold; }"
    "QPushButton:hover { background: #ffcdd2; }"
    "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
)


def _make_card_btn(emoji: str, label: str, accent: str = "#1976d2") -> QPushButton:
    """Create a card-style button: large emoji on top, text label below."""
    btn = QPushButton()
    btn.setFixedSize(90, 88)
    btn.setStyleSheet(_CARD_SS.format(accent=accent))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    # Overlay a transparent child widget that holds the layout
    inner = QWidget(btn)
    inner.setGeometry(0, 0, 90, 88)
    inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    vl = QVBoxLayout(inner)
    vl.setContentsMargins(6, 10, 6, 8)
    vl.setSpacing(4)
    vl.setAlignment(Qt.AlignmentFlag.AlignCenter)

    icon_lbl = QLabel(emoji)
    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_lbl.setStyleSheet(
        f"font-size: 30px; background: transparent; border: none; color: {accent};"
    )
    icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    text_lbl = QLabel(label)
    text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    text_lbl.setWordWrap(True)
    text_lbl.setStyleSheet(
        "font-size: 10px; color: #424242; background: transparent;"
        " border: none; font-weight: bold;"
    )
    text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    vl.addWidget(icon_lbl)
    vl.addWidget(text_lbl)

    return btn



_LABEL_SS_PS = "color: #555; font-size: 11px; font-weight: bold;"
_INPUT_SS_PS = (
    "QLineEdit {"
    "  border: 1px solid #ddd; border-radius: 4px;"
    "  padding: 2px 6px; background: #ffffff; color: #212121;"
    "  font-size: 11px; min-height: 20px;"
    "}"
    "QLineEdit:focus { border: 1px solid #1976d2; }"
)
_COMBO_SS_PS = (
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
_CB_SS_PS = "QCheckBox { font-size: 11px; color: #333; }"


class ToolboxWidget(QWidget):
    status_update = Signal(str)
    setup_keyboard_requested = Signal()
    install_chrome_requested = Signal()
    install_gmail_requested = Signal()
    install_socksdroid_requested = Signal()

    # (emoji, short label, adb reboot argument, accent color)
    _REBOOT_MODES = [
        ("🔁", "Normal",      "",           "#1976d2"),
        ("🔓", "Bootloader",  "bootloader", "#7b1fa2"),
        ("🛠",  "Recovery",    "recovery",   "#e65100"),
        ("📦", "Sideload",    "sideload",   "#388e3c"),
        ("⚡", "Fastboot",    "fastboot",   "#f57f17"),
        ("🔴", "EDL",         "edl",        "#c62828"),
        ("🔒", "Safe Mode",   "safemode",   "#546e7a"),
        ("⬇️", "Odin Boot",   "download",   "#0288d1"),
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._serial: str = ""
        self._get_serials_fn = None   # set by gui after construction
        self._workers: list = []
        self._change_workers: list = []
        self._build_ui()

    def set_device(self, serial: str):
        self._serial = serial or ""
        has_device = bool(self._serial)
        self._device_lbl.setText(
            f"📱  {self._serial}" if has_device else "📱  No device selected"
        )
        self._device_lbl.setStyleSheet(
            "font-weight: bold; color: #1565c0; font-size: 12px;"
            if has_device else
            "font-weight: bold; color: #aaa; font-size: 12px;"
        )
        for btn in self._reboot_buttons:
            btn.setEnabled(has_device)
            # dim the icon label when disabled
            inner = btn.findChild(QWidget)
            if inner:
                for lbl in inner.findChildren(QLabel):
                    ss = lbl.styleSheet()
                    if "font-size: 30px" in ss:
                        if has_device:
                            # restore accent color stored in btn property
                            accent = btn.property("accent") or "#1976d2"
                            lbl.setStyleSheet(
                                f"font-size: 30px; background: transparent;"
                                f" border: none; color: {accent};"
                            )
                        else:
                            lbl.setStyleSheet(
                                "font-size: 30px; background: transparent;"
                                " border: none; color: #bdbdbd;"
                            )
        self._change_device_btn.setEnabled(has_device)
        self._change_sim_btn.setEnabled(has_device)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        self._device_lbl = QLabel("📱  No device selected")
        self._device_lbl.setStyleSheet("font-weight: bold; color: #aaa; font-size: 12px;")
        hdr.addWidget(self._device_lbl, 1)
        root.addLayout(hdr)

        # Scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner_vl = QVBoxLayout(inner)
        inner_vl.setContentsMargins(0, 0, 4, 0)
        inner_vl.setSpacing(12)

        # ── Reboot section ───────────────────────────────────────────────
        reboot_group = QGroupBox("🔄 Reboot")
        reboot_group.setStyleSheet(_GROUP_SS)
        reboot_grid = QGridLayout()
        reboot_grid.setSpacing(8)
        reboot_grid.setContentsMargins(14, 10, 14, 14)

        self._reboot_buttons: list[QPushButton] = []

        COLS = 7
        for idx, (emoji, label, mode, accent) in enumerate(self._REBOOT_MODES):
            btn = _make_card_btn(emoji, label, accent)
            btn.setProperty("accent", accent)
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked=False, m=mode, lbl=label: self._do_reboot(m, lbl))
            self._reboot_buttons.append(btn)
            row, col = divmod(idx, COLS)
            reboot_grid.addWidget(btn, row, col, Qt.AlignmentFlag.AlignLeft)

        reboot_group.setLayout(reboot_grid)
        inner_vl.addWidget(reboot_group)

        # ── Device Actions ────────────────────────────────────────────────
        _GROUP_ACTIONS_SS = _GROUP_SS.replace("background-color: #fafafa;", "background-color: #f8f9ff;")
        actions_group = QGroupBox("🛠 Device Actions")
        actions_group.setStyleSheet(_GROUP_ACTIONS_SS)
        actions_vl = QVBoxLayout()
        actions_vl.setContentsMargins(12, 10, 12, 10)
        actions_vl.setSpacing(8)

        _action_btns = []

        self._tb_disable_play_btn = QPushButton("🚫 Disable Play Store")
        self._tb_disable_play_btn.setStyleSheet(_BTN_SS)
        self._tb_disable_play_btn.setMinimumHeight(30)
        self._tb_disable_play_btn.setToolTip(
            "Disable Google Play Store on all devices\n"
            "adb shell pm disable-user --user 0 com.android.vending"
        )
        self._tb_disable_play_btn.clicked.connect(lambda: self._run_play_store(enable=False))
        _action_btns.append(self._tb_disable_play_btn)

        self._tb_enable_play_btn = QPushButton("✅ Enable Play Store")
        self._tb_enable_play_btn.setStyleSheet(_BTN_SS)
        self._tb_enable_play_btn.setMinimumHeight(30)
        self._tb_enable_play_btn.setToolTip(
            "Enable Google Play Store on all devices\n"
            "adb shell pm enable com.android.vending"
        )
        self._tb_enable_play_btn.clicked.connect(lambda: self._run_play_store(enable=True))
        _action_btns.append(self._tb_enable_play_btn)

        self._tb_setup_keyboard_btn = QPushButton("⌨️ Install ADB Keyboard")
        self._tb_setup_keyboard_btn.setStyleSheet(_BTN_SS)
        self._tb_setup_keyboard_btn.setMinimumHeight(30)
        self._tb_setup_keyboard_btn.setToolTip("Install ADB keyboard on all devices in the table")
        self._tb_setup_keyboard_btn.clicked.connect(self.setup_keyboard_requested.emit)
        _action_btns.append(self._tb_setup_keyboard_btn)

        self._tb_install_chrome_btn = QPushButton("🌐 Install Chrome")
        self._tb_install_chrome_btn.setStyleSheet(_BTN_SS)
        self._tb_install_chrome_btn.setMinimumHeight(30)
        self._tb_install_chrome_btn.setToolTip("Install Chrome on all devices in the table")
        self._tb_install_chrome_btn.clicked.connect(self.install_chrome_requested.emit)
        _action_btns.append(self._tb_install_chrome_btn)

        self._tb_install_gmail_btn = QPushButton("📧 Install Gmail")
        self._tb_install_gmail_btn.setStyleSheet(_BTN_SS)
        self._tb_install_gmail_btn.setMinimumHeight(30)
        self._tb_install_gmail_btn.setToolTip("Install Gmail from /data/apps/gmail.apkm on all devices")
        self._tb_install_gmail_btn.clicked.connect(self.install_gmail_requested.emit)
        _action_btns.append(self._tb_install_gmail_btn)

        self._tb_install_socksdroid_btn = QPushButton("🧦 Install SocksDroid")
        self._tb_install_socksdroid_btn.setStyleSheet(_BTN_SS)
        self._tb_install_socksdroid_btn.setMinimumHeight(30)
        self._tb_install_socksdroid_btn.setToolTip("Install SocksDroid from /data/apps/SocksDroid.apk on all devices")
        self._tb_install_socksdroid_btn.clicked.connect(self.install_socksdroid_requested.emit)
        _action_btns.append(self._tb_install_socksdroid_btn)

        _COLS = 3
        act_grid = QGridLayout()
        act_grid.setSpacing(8)
        for _i, _btn in enumerate(_action_btns):
            act_grid.addWidget(_btn, _i // _COLS, _i % _COLS)
        for _col in range(_COLS):
            act_grid.setColumnStretch(_col, 1)
        actions_vl.addLayout(act_grid)

        self._tb_action_status = QLabel("")
        self._tb_action_status.setStyleSheet("color: #2e7d32; font-size: 11px;")
        actions_vl.addWidget(self._tb_action_status)

        actions_group.setLayout(actions_vl)
        inner_vl.addWidget(actions_group)

        # ── Phone Settings ──────────────────────────────────────────────────
        ps_group = QGroupBox("📱 Phone Settings")
        ps_group.setStyleSheet(_GROUP_SS)
        ps_vl = QVBoxLayout()
        ps_vl.setContentsMargins(12, 10, 12, 10)
        ps_vl.setSpacing(8)

        ps_row1 = QHBoxLayout()
        ps_row1.setSpacing(8)

        lbl_country = QLabel("Country:")
        lbl_country.setStyleSheet(_LABEL_SS_PS)
        lbl_country.setFixedWidth(52)
        self._country_combo = QComboBox()
        self._country_combo.addItems(_COUNTRIES)
        self._country_combo.setStyleSheet(_COMBO_SS_PS)
        self._country_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._country_combo.currentTextChanged.connect(self._on_country_changed)
        ps_row1.addWidget(lbl_country)
        ps_row1.addWidget(self._country_combo, 2)

        lbl_carrier = QLabel("Carrier:")
        lbl_carrier.setStyleSheet(_LABEL_SS_PS)
        lbl_carrier.setFixedWidth(46)
        self._carrier_combo = QComboBox()
        self._carrier_combo.setStyleSheet(_COMBO_SS_PS)
        self._carrier_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        ps_row1.addWidget(lbl_carrier)
        ps_row1.addWidget(self._carrier_combo, 2)

        lbl_simcode = QLabel("Fixed Sim Code:")
        lbl_simcode.setStyleSheet(_LABEL_SS_PS)
        self._simcode_input = QLineEdit()
        self._simcode_input.setPlaceholderText("e.g. 310410")
        self._simcode_input.setStyleSheet(_INPUT_SS_PS)
        self._simcode_input.setFixedWidth(90)
        ps_row1.addWidget(lbl_simcode)
        ps_row1.addWidget(self._simcode_input)

        ps_vl.addLayout(ps_row1)

        cb_grid = QGridLayout()
        cb_grid.setHorizontalSpacing(16)
        cb_grid.setVerticalSpacing(4)

        def _cb(label: str, default: bool = False) -> QCheckBox:
            c = QCheckBox(label)
            c.setStyleSheet(_CB_SS_PS)
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

        for widget, r, c in [
            (self._cb_safetynet,   0, 0),
            (self._cb_fake_sim,    1, 0),
            (self._cb_fake_mac,    2, 0),
            (self._cb_logout_gm,   0, 1),
            (self._cb_no_wipe,     1, 1),
            (self._cb_uninstall,   2, 1),
            (self._cb_random_carr, 0, 2),
            (self._cb_change_tz,   1, 2),
            (self._cb_fake_loc,    2, 2),
        ]:
            cb_grid.addWidget(widget, r, c)

        ps_vl.addLayout(cb_grid)
        ps_group.setLayout(ps_vl)
        inner_vl.addWidget(ps_group)

        self._on_country_changed(self._country_combo.currentText())

        # ── Change Device actions ──────────────────────────────────────────
        act_btn_row = QHBoxLayout()
        act_btn_row.setSpacing(10)

        self._change_device_btn = QPushButton("🔄  Change Device")
        self._change_device_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._change_device_btn.setEnabled(False)
        self._change_device_btn.setMinimumHeight(32)
        self._change_device_btn.clicked.connect(self._run_change_device)
        act_btn_row.addWidget(self._change_device_btn, 1)

        self._change_sim_btn = QPushButton("📡  Change SIM Info Only")
        self._change_sim_btn.setStyleSheet(_BTN_SS)
        self._change_sim_btn.setEnabled(False)
        self._change_sim_btn.setMinimumHeight(32)
        self._change_sim_btn.clicked.connect(self._run_change_sim)
        act_btn_row.addWidget(self._change_sim_btn, 1)

        inner_vl.addLayout(act_btn_row)

        inner_vl.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    def _do_reboot(self, mode: str, label: str = ""):
        if not self._serial:
            return
        display = label or mode or "normal"
        try:
            cmd = ["adb", "-s", self._serial, "reboot"] + ([mode] if mode else [])
            subprocess.Popen(
                cmd,
                startupinfo=_si,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.status_update.emit(f"🔄 Rebooting {self._serial} → {display}…")
        except Exception as e:
            self.status_update.emit(f"⚠ Reboot failed: {e}")

    def _get_serials(self) -> list:
        return self._get_serials_fn() if callable(self._get_serials_fn) else []

    def _set_action_status(self, msg: str, ok: bool = True):
        color = "#2e7d32" if ok else "#c62828"
        self._tb_action_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._tb_action_status.setText(msg)
        self.status_update.emit(msg)

    def _run_play_store(self, enable: bool):
        serials = self._get_serials()
        if not serials:
            self._set_action_status("⚠ No devices found in table.", ok=False)
            return
        btn = self._tb_enable_play_btn if enable else self._tb_disable_play_btn
        btn.setEnabled(False)
        w = _PlayStoreWorker(serials, enable)
        w.progress.connect(lambda msg: self._set_action_status(msg))
        w.finished.connect(lambda msg: self._set_action_status(msg))
        w.finished.connect(lambda: btn.setEnabled(True))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    # ── Phone Settings helpers ──────────────────────────────────────────
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
