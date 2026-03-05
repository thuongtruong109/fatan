"""
Actions tab.
Provides quick device actions for the selected device:
  • Setup Keyboard  — install ADB keyboard on all devices
  • Install Chrome  — install Chrome on all devices
  • Open URL        — opens any URL in Chrome via ADB intent
  • Login Gmail     — fills Google account credentials in Chrome
"""
from __future__ import annotations

import subprocess
import os
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QCheckBox, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal

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

_LABEL_SS  = "color: #555; font-size: 11px; font-weight: bold;"
_CB_SS     = "QCheckBox { font-size: 11px; color: #333; }"

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

# ── Play Store toggle worker ──────────────────────────────────────────────
_PLAY_STORE_PKG = "com.android.vending"

class _PlayStoreWorker(QThread):
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, serials: list, enable: bool):
        super().__init__()
        self.serials = serials
        self.enable = enable

    def run(self):
        action = "enable" if self.enable else "disable-user --user 0"
        label  = "Enabled" if self.enable else "Disabled"
        ok = 0
        for serial in self.serials:
            try:
                _adb(serial, "shell", "pm", *action.split(), _PLAY_STORE_PKG)
                ok += 1
                self.progress.emit(f"✅ {label} Play Store: {serial}")
            except Exception as e:
                self.progress.emit(f"❌ {serial}: {e}")
        self.finished.emit(f"{label} Play Store — {ok}/{len(self.serials)} devices")


class ActionsWidget(QWidget):
    status_update = Signal(str)
    setup_keyboard_requested = Signal()
    install_chrome_requested = Signal()
    get_all_serials_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._workers: list[QThread] = []
        self._get_serials_fn = None   # set by gui after construction
        self._build_ui()

    def set_device(self, serial: str):
        self._serial = serial
        label = f"Device: {serial}" if serial else "No device selected"
        self._device_label.setText(label)
        enabled = bool(serial)
        for btn in (self._open_url_btn, self._login_gmail_btn):
            btn.setEnabled(enabled)
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

        # ── Device Setup group ────────────────────────────────────────────
        setup_group = QGroupBox("🛠 Device Setup")
        setup_group.setStyleSheet(_GROUP_SS)
        setup_vl = QVBoxLayout()
        setup_vl.setContentsMargins(12, 10, 12, 10)
        setup_vl.setSpacing(8)

        setup_btn_row = QHBoxLayout()
        setup_btn_row.setSpacing(10)

        self._disable_play_btn = QPushButton("🚫  Disable Play Store")
        self._disable_play_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._disable_play_btn.setMinimumHeight(32)
        self._disable_play_btn.setToolTip(
            "Disable Google Play Store on all devices\n"
            "adb shell pm disable-user --user 0 com.android.vending"
        )
        self._disable_play_btn.clicked.connect(lambda: self._run_play_store(enable=False))
        setup_btn_row.addWidget(self._disable_play_btn, 1)

        self._enable_play_btn = QPushButton("✅  Enable Play Store")
        self._enable_play_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._enable_play_btn.setMinimumHeight(32)
        self._enable_play_btn.setToolTip(
            "Enable Google Play Store on all devices\n"
            "adb shell pm enable com.android.vending"
        )
        self._enable_play_btn.clicked.connect(lambda: self._run_play_store(enable=True))
        setup_btn_row.addWidget(self._enable_play_btn, 1)

        self._setup_keyboard_btn = QPushButton("⌨️  Setup Keyboard")
        self._setup_keyboard_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._setup_keyboard_btn.setMinimumHeight(32)
        self._setup_keyboard_btn.setToolTip("Install ADB keyboard on all devices in the table")
        self._setup_keyboard_btn.clicked.connect(self.setup_keyboard_requested.emit)
        setup_btn_row.addWidget(self._setup_keyboard_btn, 1)

        self._install_chrome_btn = QPushButton("🌐  Install Chrome")
        self._install_chrome_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._install_chrome_btn.setMinimumHeight(32)
        self._install_chrome_btn.setToolTip("Install Chrome on all devices in the table")
        self._install_chrome_btn.clicked.connect(self.install_chrome_requested.emit)
        setup_btn_row.addWidget(self._install_chrome_btn, 1)

        setup_vl.addLayout(setup_btn_row)
        setup_group.setLayout(setup_vl)
        ivl.addWidget(setup_group)

        # ── Open URL group ────────────────────────────────────────────────
        url_group = QGroupBox("🌐 Open URL")
        url_group.setStyleSheet(_GROUP_SS)
        url_vl = QVBoxLayout()
        url_vl.setContentsMargins(12, 10, 12, 10)
        url_vl.setSpacing(8)

        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        lbl_url = QLabel("URL:")
        lbl_url.setStyleSheet(_LABEL_SS)
        url_row.addWidget(lbl_url)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://example.com")
        self._url_input.setStyleSheet(_INPUT_SS)
        self._url_input.returnPressed.connect(self._run_open_url)
        url_row.addWidget(self._url_input, 1)
        self._open_url_btn = QPushButton("▶ Open URL")
        self._open_url_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._open_url_btn.setEnabled(False)
        self._open_url_btn.clicked.connect(self._run_open_url)
        url_row.addWidget(self._open_url_btn)
        url_vl.addLayout(url_row)

        url_group.setLayout(url_vl)
        ivl.addWidget(url_group)

        # ── Login Gmail group ─────────────────────────────────────────────
        gmail_group = QGroupBox("📧 Login Gmail")
        gmail_group.setStyleSheet(_GROUP_SS)
        gmail_vl = QVBoxLayout()
        gmail_vl.setContentsMargins(12, 10, 12, 10)
        gmail_vl.setSpacing(8)

        # Email + Password on the same row
        cred_row = QHBoxLayout()
        cred_row.setSpacing(6)
        lbl_email = QLabel("Email:")
        lbl_email.setStyleSheet(_LABEL_SS)
        cred_row.addWidget(lbl_email)
        self._gmail_input = QLineEdit()
        self._gmail_input.setPlaceholderText("user@gmail.com")
        self._gmail_input.setStyleSheet(_INPUT_SS)
        cred_row.addWidget(self._gmail_input, 2)
        lbl_pwd = QLabel("Password:")
        lbl_pwd.setStyleSheet(_LABEL_SS)
        cred_row.addWidget(lbl_pwd)
        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("Password")
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setStyleSheet(_INPUT_SS)
        self._password_input.returnPressed.connect(self._run_login_gmail)
        cred_row.addWidget(self._password_input, 2)
        gmail_vl.addLayout(cred_row)

        # Clear checkbox + Login button on the same row
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self._clear_account_cb = QCheckBox("Clear account data first")
        self._clear_account_cb.setStyleSheet(_CB_SS)
        action_row.addWidget(self._clear_account_cb, 1)
        self._login_gmail_btn = QPushButton("▶ Login Gmail")
        self._login_gmail_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._login_gmail_btn.setEnabled(False)
        self._login_gmail_btn.clicked.connect(self._run_login_gmail)
        action_row.addWidget(self._login_gmail_btn)
        gmail_vl.addLayout(action_row)

        gmail_group.setLayout(gmail_vl)
        ivl.addWidget(gmail_group)
        ivl.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

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

    def _run_play_store(self, enable: bool):
        serials = self._get_serials_fn() if callable(self._get_serials_fn) else []
        if not serials:
            self.status_update.emit("⚠ No devices found in table.")
            return
        btn = self._enable_play_btn if enable else self._disable_play_btn
        btn.setEnabled(False)
        w = _PlayStoreWorker(serials, enable)
        w.progress.connect(self.status_update)
        w.finished.connect(self.status_update)
        w.finished.connect(lambda: btn.setEnabled(True))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()
