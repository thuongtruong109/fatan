from __future__ import annotations

import subprocess
import os
import time
import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QCheckBox, QScrollArea, QFrame, QSpinBox,
    QListWidget, QRadioButton, QComboBox,
    QDialog, QApplication,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap

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
        border: 1px solid #ccc;
        border-radius: 6px;
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
    "QPushButton { border: 1px solid #ccc; border-radius: 4px;"
    " padding: 5px 14px; background: #f0f0f0; font-size: 11px; }"
    "QPushButton:hover { background: #e0e0e0; }"
    "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
)

_LABEL_SS  = "color: #555; font-size: 11px; font-weight: bold;"
_CB_SS     = "QCheckBox { font-size: 11px; color: #333; }"

_SPINBOX_SS = (
    "QSpinBox {"
    "  border: 1px solid #dce3f0; border-radius: 4px;"
    "  padding: 2px 6px; background: #ffffff; color: #212121;"
    "  font-size: 11px; min-height: 18px;"
    "}"
    "QSpinBox:focus { border: 1px solid #1976d2; }"
    "QSpinBox::up-button, QSpinBox::down-button {"
    "  width: 16px; border: none; background: transparent;"
    "}"
    "QSpinBox::up-arrow { image: none; border-left: 4px solid transparent;"
    "  border-right: 4px solid transparent; border-bottom: 5px solid #888;"
    "  width: 0; height: 0; margin: 2px; }"
    "QSpinBox::down-arrow { image: none; border-left: 4px solid transparent;"
    "  border-right: 4px solid transparent; border-top: 5px solid #888;"
    "  width: 0; height: 0; margin: 2px; }"
)

_COMBO_SS = (
    "QComboBox {"
    "  border: 1px solid #dce3f0; border-radius: 4px;"
    "  padding: 2px 6px; background: #ffffff; color: #212121;"
    "  font-size: 11px; min-height: 22px;"
    "}"
    "QComboBox:focus { border: 1px solid #1976d2; }"
    "QComboBox::drop-down { border: none; width: 20px; }"
    "QComboBox::down-arrow {"
    "  border-left: 4px solid transparent;"
    "  border-right: 4px solid transparent;"
    "  border-top: 5px solid #888;"
    "  width: 0; height: 0;"
    "}"
)

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

# ── Hunt-coordinate worker ────────────────────────────────────────────────────
class _HuntCoordWorker(QThread):
    """Listen for the next tap on the device and emit the raw touch coordinates."""
    coord_found = Signal(int, int)
    error = Signal(str)

    def __init__(self, serial: str):
        super().__init__()
        self.serial = serial
        self._proc = None

    def stop(self):
        try:
            if self._proc:
                self._proc.terminate()
        except Exception:
            pass

    def run(self):
        try:
            # Use getevent without -l so we get raw numeric type/code/value.
            # Format per line: /dev/input/eventN: TTTT CCCC VVVVVVVV
            #   EV_ABS (0003) + ABS_MT_POSITION_X (0035) → X coordinate
            #   EV_ABS (0003) + ABS_MT_POSITION_Y (0036) → Y coordinate
            # getevent is a passive listener — it does NOT send any tap to the device.
            self._proc = subprocess.Popen(
                ["adb", "-s", self.serial, "shell", "getevent"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                startupinfo=_si, text=True, bufsize=1,
            )
            x = y = None
            for line in self._proc.stdout:
                # Typical line: "/dev/input/event1: 0003 0035 0000017a"
                parts = line.strip().split()
                # Need at least 3 tokens: [device:] type code value
                # Lines with device prefix have 4 tokens; raw have 3.
                if len(parts) >= 3:
                    # Strip trailing colon from device name if present
                    if parts[0].endswith(":"):
                        parts = parts[1:]
                    if len(parts) >= 3:
                        ev_type = parts[0].lstrip("0") or "0"
                        ev_code = parts[1].lstrip("0") or "0"
                        ev_val  = parts[2]
                        try:
                            val = int(ev_val, 16)
                        except ValueError:
                            continue
                        # EV_ABS = 3, ABS_MT_POSITION_X = 53 (0x35), ABS_MT_POSITION_Y = 54 (0x36)
                        if ev_type in ("3", "03", "003", "0003"):
                            if ev_code in ("35", "035", "0035"):   # ABS_MT_POSITION_X
                                x = val
                            elif ev_code in ("36", "036", "0036"): # ABS_MT_POSITION_Y
                                y = val
                if x is not None and y is not None:
                    self.coord_found.emit(x, y)
                    break  # capture only the first complete touch
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                if self._proc:
                    self._proc.terminate()
            except Exception:
                pass


# ── Auto-click worker ─────────────────────────────────────────────────────────
class _AutoClickWorker(QThread):
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, serial: str, coords: list, clicks_per_coord: int,
                 delay_ms: int, repeat: int):
        super().__init__()
        self.serial = serial
        self.coords = coords          # list of (x, y) tuples
        self.clicks_per_coord = clicks_per_coord
        self.delay_ms = delay_ms
        self.repeat = repeat          # 0 = infinite
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = 0
        loop = 0
        while not self._stop:
            loop += 1
            for (x, y) in self.coords:
                if self._stop:
                    break
                for _ in range(self.clicks_per_coord):
                    if self._stop:
                        break
                    _adb(self.serial, "shell", "input", "tap", str(x), str(y))
                    total += 1
                    self.progress.emit(f"🖱 Tapped ({x}, {y}) — total: {total}")
                    if self.delay_ms > 0:
                        time.sleep(self.delay_ms / 1000)
            if self.repeat > 0 and loop >= self.repeat:
                break
        self.finished.emit(f"✅ Auto click done — {total} taps total")


# ── Screenshot worker ─────────────────────────────────────────────────────────
class _ScreenshotWorker(QThread):
    """Take a screenshot from an Android device.

    mode:
      'device'  – screencap saved on device at remote_path, then pulled to save_dir
      'direct'  – exec-out screencap piped directly to PC (no file left on device)
    """
    finished = Signal(str, str)  # (status_msg, local_path_or_empty)
    error    = Signal(str)

    def __init__(self, serial: str, mode: str, save_dir: str, remote_path: str = "/sdcard/screen_tmp.png"):
        super().__init__()
        self.serial      = serial
        self.mode        = mode        # 'device' | 'direct'
        self.save_dir    = save_dir
        self.remote_path = remote_path

    def run(self):
        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"screenshot_{ts}.png"
        local = os.path.join(self.save_dir, fname)
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            if self.mode == "device":
                # 1) take screenshot on device
                r = subprocess.run(
                    ["adb", "-s", self.serial, "shell", "screencap", self.remote_path],
                    startupinfo=_si, capture_output=True, timeout=15,
                )
                if r.returncode != 0:
                    self.error.emit(f"screencap failed: {r.stderr.decode(errors='replace').strip()}")
                    return
                # 2) pull to PC
                r2 = subprocess.run(
                    ["adb", "-s", self.serial, "pull", self.remote_path, local],
                    startupinfo=_si, capture_output=True, timeout=15,
                )
                if r2.returncode != 0:
                    self.error.emit(f"pull failed: {r2.stderr.decode(errors='replace').strip()}")
                    return
                self.finished.emit(f"✅ Screenshot saved (device + PC): {fname}", local)

            elif self.mode == "direct":
                # exec-out — piped directly, no file on device
                proc = subprocess.Popen(
                    ["adb", "-s", self.serial, "exec-out", "screencap", "-p"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    startupinfo=_si,
                )
                data, err = proc.communicate(timeout=20)
                if proc.returncode != 0 or not data:
                    self.error.emit(f"exec-out failed: {err.decode(errors='replace').strip()}")
                    return
                with open(local, "wb") as f:
                    f.write(data)
                self.finished.emit(f"✅ Screenshot (direct to PC): {fname}", local)

        except Exception as e:
            self.error.emit(str(e))


# ── Screen record worker ──────────────────────────────────────────────────────
class _ScreenRecordWorker(QThread):
    """Run adb shell screenrecord in a background thread.

    Signals:
      started(remote_path)  – recording has begun
      finished(local_path)  – recording stopped and file pulled to PC
      error(msg)
    """
    started  = Signal(str)   # remote path on device
    finished = Signal(str)   # local path on PC
    error    = Signal(str)

    def __init__(self, serial: str, remote_path: str, save_dir: str,
                 time_limit: int = 0, audio: bool = False):
        super().__init__()
        self.serial      = serial
        self.remote_path = remote_path   # e.g. /sdcard/rec_20260311_123456.mp4
        self.save_dir    = save_dir
        self.time_limit  = time_limit    # 0 = no explicit --time-limit flag
        self.audio       = audio
        self._proc: subprocess.Popen | None = None
        self._local_path = ""

    # ── public control ────────────────────────────────────────────────────
    def stop(self):
        """Gracefully stop screenrecord by sending Ctrl-C (SIGINT)."""
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.send_signal(__import__("signal").SIGTERM)
        except Exception:
            try:
                if self._proc:
                    self._proc.terminate()
            except Exception:
                pass

    def pause(self):
        """SIGSTOP the screenrecord process (best-effort; not all devices support it)."""
        try:
            import signal as _s
            if self._proc and self._proc.poll() is None:
                self._proc.send_signal(_s.SIGSTOP)
        except Exception:
            pass

    def resume(self):
        """SIGCONT to resume a paused screenrecord process."""
        try:
            import signal as _s
            if self._proc and self._proc.poll() is None:
                self._proc.send_signal(_s.SIGCONT)
        except Exception:
            pass

    # ── thread body ───────────────────────────────────────────────────────
    def run(self):
        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"recording_{ts}.mp4"
        local = os.path.join(self.save_dir, fname)
        self._local_path = local
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            cmd = ["adb", "-s", self.serial, "shell", "screenrecord"]
            if self.time_limit and self.time_limit > 0:
                cmd += ["--time-limit", str(self.time_limit)]
            if self.audio:
                cmd += ["--audio"]     # Android 10+ only
            cmd.append(self.remote_path)

            self._proc = subprocess.Popen(
                cmd, startupinfo=_si,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.started.emit(self.remote_path)
            self._proc.wait()   # blocks until stop() is called or time-limit reached

            # Pull the recorded file to PC
            r = subprocess.run(
                ["adb", "-s", self.serial, "pull", self.remote_path, local],
                startupinfo=_si, capture_output=True, timeout=60,
            )
            if r.returncode == 0 and os.path.isfile(local):
                self.finished.emit(local)
            else:
                self.error.emit(f"Pull failed: {r.stderr.decode(errors='replace').strip()}")
        except Exception as e:
            self.error.emit(str(e))


class ActionsWidget(QWidget):
    status_update = Signal(str)
    hunt_mode_active = Signal(bool)   # True when waiting for a tap coordinate

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._workers: list[QThread] = []
        self._auto_click_worker: _AutoClickWorker | None = None
        self._hunt_active: bool = False
        self._screenshot_paths: list[str] = []
        self._screenshot_save_dir: str = os.path.join(os.path.expanduser("~"), "Pictures", "fatan_screenshots")
        # Screen recording state
        self._rec_worker: _ScreenRecordWorker | None = None
        self._rec_paused: bool = False
        self._rec_save_dir: str = os.path.join(os.path.expanduser("~"), "Videos", "fatan_recordings")
        self._rec_elapsed_timer: QTimer | None = None
        self._rec_elapsed_secs: int = 0
        self._build_ui()

    def set_device(self, serial: str):
        self._serial = serial
        label = f"Device: {serial}" if serial else "No device selected"
        self._device_label.setText(label)
        enabled = bool(serial)
        for btn in (self._open_url_btn, self._login_gmail_btn,
                    self._ss_take_btn, self._rec_start_btn):
            btn.setEnabled(enabled)
        self._start_click_btn.setEnabled(enabled and self._coord_list.count() > 0)
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

        # ── Auto Click group ──────────────────────────────────────────────
        click_group = QGroupBox("🖱 Auto Click")
        click_group.setStyleSheet(_GROUP_SS)
        click_hl = QHBoxLayout()  # Main horizontal layout for two columns
        click_hl.setContentsMargins(12, 10, 12, 10)
        click_hl.setSpacing(12)

        # Left column - Controls and inputs
        left_column = QWidget()
        left_vl = QVBoxLayout(left_column)
        left_vl.setContentsMargins(0, 0, 0, 0)
        left_vl.setSpacing(8)

        # Right column - Coordinate list
        right_column = QWidget()
        right_vl = QVBoxLayout(right_column)
        right_vl.setContentsMargins(0, 0, 0, 0)
        right_vl.setSpacing(8)

        # — Mode selection row —
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        lbl_mode = QLabel("Set coord mode:")
        lbl_mode.setStyleSheet(_LABEL_SS)
        mode_row.addWidget(lbl_mode)
        self._rb_input = QRadioButton("Input")
        self._rb_input.setStyleSheet(_CB_SS)
        self._rb_input.setChecked(True)
        self._rb_hunt = QRadioButton("Hunt (tap device)")
        self._rb_hunt.setStyleSheet(_CB_SS)
        mode_row.addWidget(self._rb_input)
        mode_row.addWidget(self._rb_hunt)
        mode_row.addStretch()
        self._rb_input.toggled.connect(self._toggle_coord_mode)
        left_vl.addLayout(mode_row)

        # — Input mode row —
        self._input_coord_row = QWidget()
        irow = QHBoxLayout(self._input_coord_row)
        irow.setContentsMargins(0, 0, 0, 0)
        irow.setSpacing(6)
        lbl_x = QLabel("X:")
        lbl_x.setStyleSheet(_LABEL_SS)
        irow.addWidget(lbl_x)
        self._coord_x_input = QLineEdit()
        self._coord_x_input.setPlaceholderText("0")
        self._coord_x_input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #e3f2fd; border-radius: 6px;"
            "  padding: 2px 8px; background: #ffffff; color: #1565c0;"
            "  font-size: 12px; font-weight: bold; min-height: 20px;"
            "  text-align: center;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #1976d2; background: #f8f9ff;"
            "}"
            "QLineEdit:hover {"
            "  border: 1px solid #42a5f5;"
            "}"
        )
        self._coord_x_input.setFixedWidth(80)
        irow.addWidget(self._coord_x_input)
        lbl_y = QLabel("Y:")
        lbl_y.setStyleSheet(_LABEL_SS)
        irow.addWidget(lbl_y)
        self._coord_y_input = QLineEdit()
        self._coord_y_input.setPlaceholderText("0")
        self._coord_y_input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #e3f2fd; border-radius: 6px;"
            "  padding: 2px 8px; background: #ffffff; color: #1565c0;"
            "  font-size: 12px; font-weight: bold; min-height: 20px;"
            "  text-align: center;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #1976d2; background: #f8f9ff;"
            "}"
            "QLineEdit:hover {"
            "  border: 1px solid #42a5f5;"
            "}"
        )
        self._coord_y_input.setFixedWidth(80)
        irow.addWidget(self._coord_y_input)
        self._add_coord_btn = QPushButton("＋ Add")
        self._add_coord_btn.setStyleSheet(
            "QPushButton {"
            "  background: linear-gradient(135deg, #1976d2, #42a5f5);"
            "  color: white; font-weight: bold; border: none;"
            "  padding: 6px 12px; border-radius: 6px; font-size: 11px;"
            "  min-height: 24px;"
            "}"
            "QPushButton:hover {"
            "  background: linear-gradient(135deg, #1565c0, #1976d2);"
            "}"
            "QPushButton:pressed {"
            "  background: linear-gradient(135deg, #0d47a1, #1565c0);"
            "}"
        )
        self._add_coord_btn.clicked.connect(self._add_coord_from_input)
        irow.addWidget(self._add_coord_btn)
        irow.addStretch()
        left_vl.addWidget(self._input_coord_row)

        # — Hunt mode row —
        self._hunt_coord_row = QWidget()
        hrow = QHBoxLayout(self._hunt_coord_row)
        hrow.setContentsMargins(0, 0, 0, 0)
        hrow.setSpacing(8)
        self._hunt_btn = QPushButton("🎯 Hunt 1 Tap")
        self._hunt_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._hunt_btn.clicked.connect(self._start_hunt)
        hrow.addWidget(self._hunt_btn)
        self._hunt_status_lbl = QLabel("Press Hunt then tap on device")
        self._hunt_status_lbl.setStyleSheet("color: #888; font-size: 10px;")
        hrow.addWidget(self._hunt_status_lbl, 1)
        self._hunt_coord_row.setVisible(False)
        left_vl.addWidget(self._hunt_coord_row)

        # — Coordinates list —
        lbl_coords = QLabel("Coordinates (click order):")
        lbl_coords.setStyleSheet(_LABEL_SS)
        right_vl.addWidget(lbl_coords)
        self._coord_list = QListWidget()
        self._coord_list.setStyleSheet(
            "QListWidget { border: 1px solid #dce3f0; border-radius: 4px;"
            " background: #fff; font-size: 11px; }"
            "QListWidget::item:selected { background: #bbdefb; color: #000; }"
        )
        self._coord_list.setFixedHeight(100)
        right_vl.addWidget(self._coord_list)

        # List management buttons
        list_btn_row = QHBoxLayout()
        list_btn_row.setSpacing(4)
        self._remove_coord_btn = QPushButton("Remove")
        self._remove_coord_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._remove_coord_btn.clicked.connect(self._remove_coord)
        list_btn_row.addWidget(self._remove_coord_btn)
        self._clear_coords_btn = QPushButton("Clear All")
        self._clear_coords_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._clear_coords_btn.clicked.connect(self._clear_coords)
        list_btn_row.addWidget(self._clear_coords_btn)
        self._move_up_btn = QPushButton("↑ Up")
        self._move_up_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._move_up_btn.clicked.connect(self._move_coord_up)
        list_btn_row.addWidget(self._move_up_btn)
        self._move_down_btn = QPushButton("↓ Down")
        self._move_down_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._move_down_btn.clicked.connect(self._move_coord_down)
        list_btn_row.addWidget(self._move_down_btn)
        list_btn_row.addStretch()
        right_vl.addLayout(list_btn_row)

        # — Click settings row —
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(10)
        lbl_cpc = QLabel("Clicks/coord:")
        lbl_cpc.setStyleSheet(_LABEL_SS)
        cfg_row.addWidget(lbl_cpc)
        self._clicks_per_coord = QSpinBox()
        self._clicks_per_coord.setRange(1, 9999)
        self._clicks_per_coord.setValue(1)
        self._clicks_per_coord.setFixedWidth(70)
        self._clicks_per_coord.setStyleSheet(_SPINBOX_SS)
        self._clicks_per_coord.valueChanged.connect(self._update_completion_time)
        cfg_row.addWidget(self._clicks_per_coord)
        lbl_delay = QLabel("Delay (ms):")
        lbl_delay.setStyleSheet(_LABEL_SS)
        cfg_row.addWidget(lbl_delay)
        self._click_delay_ms = QSpinBox()
        self._click_delay_ms.setRange(0, 60000)
        self._click_delay_ms.setValue(500)
        self._click_delay_ms.setSingleStep(100)
        self._click_delay_ms.setFixedWidth(80)
        self._click_delay_ms.setStyleSheet(_SPINBOX_SS)
        self._click_delay_ms.valueChanged.connect(self._update_completion_time)
        cfg_row.addWidget(self._click_delay_ms)
        cfg_row.addStretch()
        left_vl.addLayout(cfg_row)

        # — Completion time + Repeat mode row —
        time_row = QHBoxLayout()
        time_row.setSpacing(10)
        lbl_est = QLabel("Est. time:")
        lbl_est.setStyleSheet(_LABEL_SS)
        time_row.addWidget(lbl_est)
        self._completion_time_lbl = QLabel("—")
        self._completion_time_lbl.setStyleSheet("color: #1976d2; font-size: 11px; font-weight: bold;")
        time_row.addWidget(self._completion_time_lbl)
        lbl_repeat = QLabel("Repeat:")
        lbl_repeat.setStyleSheet(_LABEL_SS)
        time_row.addWidget(lbl_repeat)
        self._repeat_combo = QComboBox()
        self._repeat_combo.addItems(["1× (once)", "N times", "Infinite (∞)"])
        self._repeat_combo.setStyleSheet(_COMBO_SS)
        self._repeat_combo.currentIndexChanged.connect(self._on_repeat_changed)
        time_row.addWidget(self._repeat_combo)
        self._repeat_n = QSpinBox()
        self._repeat_n.setRange(2, 9999)
        self._repeat_n.setValue(2)
        self._repeat_n.setFixedWidth(60)
        self._repeat_n.setStyleSheet(_SPINBOX_SS)
        self._repeat_n.setVisible(False)
        self._repeat_n.valueChanged.connect(self._update_completion_time)
        time_row.addWidget(self._repeat_n)
        time_row.addStretch()
        left_vl.addLayout(time_row)

        # — Start / Stop buttons —
        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        self._start_click_btn = QPushButton("▶ Start Auto Click")
        self._start_click_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._start_click_btn.setEnabled(False)
        self._start_click_btn.clicked.connect(self._start_auto_click)
        run_row.addWidget(self._start_click_btn)
        self._stop_click_btn = QPushButton("■ Stop")
        self._stop_click_btn.setStyleSheet(
            "QPushButton { background:#e53935; color:white; font-weight:bold;"
            " padding:5px 14px; border-radius:4px; font-size:11px; }"
            "QPushButton:hover { background:#c62828; }"
            "QPushButton:disabled { background:#ef9a9a; }"
        )
        self._stop_click_btn.setEnabled(False)
        self._stop_click_btn.clicked.connect(self._stop_auto_click)
        run_row.addWidget(self._stop_click_btn)
        run_row.addStretch()
        left_vl.addLayout(run_row)

        # Add columns to main horizontal layout
        click_hl.addWidget(left_column, 1)   # Left column takes flexible space
        click_hl.addWidget(right_column, 1)  # Right column takes flexible space

        click_group.setLayout(click_hl)
        ivl.addWidget(click_group)

        # ── Screenshot group ──────────────────────────────────────────────
        ss_group = QGroupBox("📸 Screenshot")
        ss_group.setStyleSheet(_GROUP_SS)
        ss_vl = QVBoxLayout()
        ss_vl.setContentsMargins(12, 10, 12, 10)
        ss_vl.setSpacing(6)

        # Option row: radio buttons to choose mode
        ss_opt_row = QHBoxLayout()
        ss_opt_row.setSpacing(12)
        ss_mode_lbl = QLabel("Mode:")
        ss_mode_lbl.setStyleSheet(_LABEL_SS)
        ss_opt_row.addWidget(ss_mode_lbl)
        self._ss_rb_device = QRadioButton("💾 Save on Device + PC")
        self._ss_rb_device.setStyleSheet(_CB_SS)
        self._ss_rb_device.setToolTip(
            "adb shell screencap /sdcard/screen_tmp.png  →  adb pull\n"
            "File is saved on device AND downloaded to PC."
        )
        self._ss_rb_device.setChecked(True)
        ss_opt_row.addWidget(self._ss_rb_device)
        self._ss_rb_direct = QRadioButton("📥 Direct to PC only")
        self._ss_rb_direct.setStyleSheet(_CB_SS)
        self._ss_rb_direct.setToolTip(
            "adb exec-out screencap -p  (nothing left on device)\n"
            "Pipes screenshot bytes straight to PC."
        )
        ss_opt_row.addWidget(self._ss_rb_direct)
        ss_opt_row.addStretch()
        ss_vl.addLayout(ss_opt_row)

        # Action row: Take button + open folder
        ss_action_row = QHBoxLayout()
        ss_action_row.setSpacing(6)
        self._ss_take_btn = QPushButton("📸 Take Screenshot")
        self._ss_take_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._ss_take_btn.setEnabled(False)
        self._ss_take_btn.clicked.connect(self._take_screenshot_ui)
        ss_action_row.addWidget(self._ss_take_btn)
        ss_folder_btn = QPushButton("📂 Open Folder")
        ss_folder_btn.setStyleSheet(_BTN_SECONDARY_SS)
        ss_folder_btn.clicked.connect(self._open_ss_folder)
        ss_action_row.addWidget(ss_folder_btn)
        ss_action_row.addStretch()
        ss_vl.addLayout(ss_action_row)

        # List of captured screenshots
        ss_list_lbl = QLabel("Captured (double-click to preview):")
        ss_list_lbl.setStyleSheet(_LABEL_SS)
        ss_vl.addWidget(ss_list_lbl)

        self._ss_list = QListWidget()
        self._ss_list.setStyleSheet(
            "QListWidget { border: 1px solid #dce3f0; border-radius: 4px;"
            " background: #fff; font-size: 11px; }"
            "QListWidget::item:selected { background: #bbdefb; color: #000; }"
        )
        self._ss_list.setFixedHeight(90)
        self._ss_list.itemDoubleClicked.connect(self._on_ss_list_double_click)
        ss_vl.addWidget(self._ss_list)

        # List action buttons
        ss_list_btn_row = QHBoxLayout()
        ss_list_btn_row.setSpacing(4)
        ss_preview_btn = QPushButton("👁 Preview")
        ss_preview_btn.setStyleSheet(_BTN_SECONDARY_SS)
        ss_preview_btn.clicked.connect(self._preview_selected_screenshot)
        ss_list_btn_row.addWidget(ss_preview_btn)
        ss_del_btn = QPushButton("🗑 Delete")
        ss_del_btn.setStyleSheet(
            "QPushButton { border: 1px solid #ef9a9a; border-radius: 4px;"
            " padding: 4px 10px; background: #ffebee; font-size: 11px; }"
            "QPushButton:hover { background: #ffcdd2; }"
        )
        ss_del_btn.clicked.connect(self._delete_selected_screenshot)
        ss_list_btn_row.addWidget(ss_del_btn)
        ss_list_btn_row.addStretch()
        ss_vl.addLayout(ss_list_btn_row)

        ss_group.setLayout(ss_vl)
        ivl.addWidget(ss_group)

        # ── Screen Recording group ────────────────────────────────────────
        rec_group = QGroupBox("🎬 Screen Recording")
        rec_group.setStyleSheet(_GROUP_SS)
        rec_vl = QVBoxLayout()
        rec_vl.setContentsMargins(12, 10, 12, 10)
        rec_vl.setSpacing(6)

        # Options row 1: time limit + audio
        rec_opt1 = QHBoxLayout()
        rec_opt1.setSpacing(10)

        lbl_timelimit = QLabel("Time limit (s):")
        lbl_timelimit.setStyleSheet(_LABEL_SS)
        rec_opt1.addWidget(lbl_timelimit)
        self._rec_timelimit = QSpinBox()
        self._rec_timelimit.setRange(0, 1800)
        self._rec_timelimit.setValue(180)
        self._rec_timelimit.setSpecialValueText("∞ No limit")
        self._rec_timelimit.setSuffix(" s")
        self._rec_timelimit.setFixedWidth(90)
        self._rec_timelimit.setStyleSheet(_SPINBOX_SS)
        self._rec_timelimit.setToolTip("0 = no limit (up to 3 min Android default)")
        rec_opt1.addWidget(self._rec_timelimit)

        lbl_delay = QLabel("Start delay (s):")
        lbl_delay.setStyleSheet(_LABEL_SS)
        rec_opt1.addWidget(lbl_delay)
        self._rec_delay = QSpinBox()
        self._rec_delay.setRange(0, 30)
        self._rec_delay.setValue(0)
        self._rec_delay.setSuffix(" s")
        self._rec_delay.setFixedWidth(65)
        self._rec_delay.setStyleSheet(_SPINBOX_SS)
        self._rec_delay.setToolTip("Wait N seconds before starting to record")
        rec_opt1.addWidget(self._rec_delay)

        self._rec_audio_cb = QCheckBox("🔊 With audio")
        self._rec_audio_cb.setStyleSheet(_CB_SS)
        self._rec_audio_cb.setToolTip("Include device audio (requires Android 10+, --audio flag)")
        rec_opt1.addWidget(self._rec_audio_cb)

        rec_opt1.addStretch()
        rec_vl.addLayout(rec_opt1)

        # Control buttons row: Start / Pause / Stop + screenshot-while-recording
        rec_ctrl_row = QHBoxLayout()
        rec_ctrl_row.setSpacing(6)

        self._rec_start_btn = QPushButton("▶ Start Recording")
        self._rec_start_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._rec_start_btn.setEnabled(False)
        self._rec_start_btn.clicked.connect(self._start_recording)
        rec_ctrl_row.addWidget(self._rec_start_btn)

        self._rec_pause_btn = QPushButton("⏸ Pause")
        self._rec_pause_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._rec_pause_btn.setEnabled(False)
        self._rec_pause_btn.setToolTip("Send SIGSTOP to pause / SIGCONT to resume")
        self._rec_pause_btn.clicked.connect(self._pause_resume_recording)
        rec_ctrl_row.addWidget(self._rec_pause_btn)

        self._rec_stop_btn = QPushButton("■ Stop")
        self._rec_stop_btn.setStyleSheet(
            "QPushButton { background:#e53935; color:white; font-weight:bold;"
            " padding:5px 14px; border-radius:4px; font-size:11px; }"
            "QPushButton:hover { background:#c62828; }"
            "QPushButton:disabled { background:#ef9a9a; }"
        )
        self._rec_stop_btn.setEnabled(False)
        self._rec_stop_btn.clicked.connect(self._stop_recording)
        rec_ctrl_row.addWidget(self._rec_stop_btn)

        self._rec_snap_btn = QPushButton("📸 Snapshot")
        self._rec_snap_btn.setStyleSheet(_BTN_SECONDARY_SS)
        self._rec_snap_btn.setEnabled(False)
        self._rec_snap_btn.setToolTip("Take a screenshot while recording is active")
        self._rec_snap_btn.clicked.connect(lambda: self._take_screenshot_ui(during_record=True))
        rec_ctrl_row.addWidget(self._rec_snap_btn)

        rec_ctrl_row.addStretch()

        self._rec_status_lbl = QLabel("Idle")
        self._rec_status_lbl.setStyleSheet("color:#888; font-size:10px; font-style:italic;")
        rec_ctrl_row.addWidget(self._rec_status_lbl)

        rec_vl.addLayout(rec_ctrl_row)

        # Elapsed time label
        self._rec_elapsed_lbl = QLabel("")
        self._rec_elapsed_lbl.setStyleSheet("color:#1976d2; font-size:10px; font-weight:bold;")
        rec_vl.addWidget(self._rec_elapsed_lbl)

        # Recorded videos list
        rec_list_lbl = QLabel("Recorded videos (double-click to play):")
        rec_list_lbl.setStyleSheet(_LABEL_SS)
        rec_vl.addWidget(rec_list_lbl)

        self._rec_list = QListWidget()
        self._rec_list.setStyleSheet(
            "QListWidget { border: 1px solid #dce3f0; border-radius: 4px;"
            " background: #fff; font-size: 11px; }"
            "QListWidget::item:selected { background: #c8e6c9; color: #000; }"
        )
        self._rec_list.setFixedHeight(90)
        self._rec_list.itemDoubleClicked.connect(self._on_rec_list_double_click)
        rec_vl.addWidget(self._rec_list)

        # List action buttons
        rec_list_btn_row = QHBoxLayout()
        rec_list_btn_row.setSpacing(4)
        rec_play_btn = QPushButton("▶ Play")
        rec_play_btn.setStyleSheet(_BTN_SECONDARY_SS)
        rec_play_btn.clicked.connect(self._play_selected_video)
        rec_list_btn_row.addWidget(rec_play_btn)
        rec_open_folder_btn = QPushButton("📂 Open Folder")
        rec_open_folder_btn.setStyleSheet(_BTN_SECONDARY_SS)
        rec_open_folder_btn.clicked.connect(self._open_rec_folder)
        rec_list_btn_row.addWidget(rec_open_folder_btn)
        rec_del_btn = QPushButton("🗑 Delete")
        rec_del_btn.setStyleSheet(
            "QPushButton { border: 1px solid #ef9a9a; border-radius: 4px;"
            " padding: 4px 10px; background: #ffebee; font-size: 11px; }"
            "QPushButton:hover { background: #ffcdd2; }"
        )
        rec_del_btn.clicked.connect(self._delete_selected_video)
        rec_list_btn_row.addWidget(rec_del_btn)
        rec_list_btn_row.addStretch()
        rec_vl.addLayout(rec_list_btn_row)

        rec_group.setLayout(rec_vl)
        ivl.addWidget(rec_group)

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

    # ── Auto Click handlers ───────────────────────────────────────────────────
    def _toggle_coord_mode(self, input_checked: bool):
        self._input_coord_row.setVisible(input_checked)
        self._hunt_coord_row.setVisible(not input_checked)

    def _add_coord_from_input(self):
        try:
            x = int(self._coord_x_input.text().strip())
            y = int(self._coord_y_input.text().strip())
        except ValueError:
            self.status_update.emit("⚠ Invalid coordinates. Enter integers for X and Y.")
            return
        n = self._coord_list.count() + 1
        self._coord_list.addItem(f"#{n}: ({x}, {y})")
        self._coord_x_input.clear()
        self._coord_y_input.clear()
        self._update_completion_time()
        self._start_click_btn.setEnabled(bool(self._serial))

    def _start_hunt(self):
        if not self._serial:
            return
        self._hunt_status_lbl.setText("⏳ Waiting for tap on device or preview window…")
        self._hunt_btn.setEnabled(False)
        self._hunt_active = True
        self.hunt_mode_active.emit(True)
        w = _HuntCoordWorker(self._serial)
        w.coord_found.connect(self._on_hunt_coord)
        w.error.connect(lambda e: self.status_update.emit(f"❌ Hunt error: {e}"))
        w.finished.connect(lambda: self._hunt_btn.setEnabled(True))
        w.finished.connect(lambda: self._hunt_status_lbl.setText("Press Hunt then tap on device"))
        w.finished.connect(lambda: self._set_hunt_inactive())
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _set_hunt_inactive(self):
        self._hunt_active = False
        self.hunt_mode_active.emit(False)

    def receive_preview_click(self, device_x: int, device_y: int):
        """Called from gui.py when the user clicks the preview window during hunt mode."""
        if not self._hunt_active:
            return
        # Stop any running hunt worker (getevent) since we got coords from the preview
        for w in list(self._workers):
            if isinstance(w, _HuntCoordWorker) and w.isRunning():
                w.stop()
                w.wait(500)
        self._on_hunt_coord(device_x, device_y)

    def _on_hunt_coord(self, x: int, y: int):
        n = self._coord_list.count() + 1
        self._coord_list.addItem(f"#{n}: ({x}, {y})")
        self._hunt_status_lbl.setText(f"✅ Captured ({x}, {y})")
        self._hunt_active = False
        self.hunt_mode_active.emit(False)
        self._update_completion_time()
        self._start_click_btn.setEnabled(bool(self._serial))

    def _remove_coord(self):
        row = self._coord_list.currentRow()
        if row >= 0:
            self._coord_list.takeItem(row)
            self._renumber_coords()
            self._update_completion_time()
        if self._coord_list.count() == 0:
            self._start_click_btn.setEnabled(False)

    def _clear_coords(self):
        self._coord_list.clear()
        self._update_completion_time()
        self._start_click_btn.setEnabled(False)

    def _move_coord_up(self):
        row = self._coord_list.currentRow()
        if row > 0:
            item = self._coord_list.takeItem(row)
            self._coord_list.insertItem(row - 1, item)
            self._coord_list.setCurrentRow(row - 1)
            self._renumber_coords()

    def _move_coord_down(self):
        row = self._coord_list.currentRow()
        if 0 <= row < self._coord_list.count() - 1:
            item = self._coord_list.takeItem(row)
            self._coord_list.insertItem(row + 1, item)
            self._coord_list.setCurrentRow(row + 1)
            self._renumber_coords()

    def _renumber_coords(self):
        for i in range(self._coord_list.count()):
            item = self._coord_list.item(i)
            text = item.text()
            try:
                coords_part = text.split(": ", 1)[1]
                item.setText(f"#{i + 1}: {coords_part}")
            except Exception:
                pass

    def _on_repeat_changed(self, idx: int):
        self._repeat_n.setVisible(idx == 1)
        self._update_completion_time()

    def _update_completion_time(self):
        n_coords = self._coord_list.count()
        clicks = self._clicks_per_coord.value()
        delay = self._click_delay_ms.value()
        repeat_idx = self._repeat_combo.currentIndex()
        if repeat_idx == 2:
            self._completion_time_lbl.setText("∞")
            return
        repeat = self._repeat_n.value() if repeat_idx == 1 else 1
        total_ms = n_coords * clicks * repeat * delay
        if total_ms == 0:
            self._completion_time_lbl.setText("~0 ms")
        elif total_ms < 1000:
            self._completion_time_lbl.setText(f"~{total_ms} ms")
        elif total_ms < 60000:
            self._completion_time_lbl.setText(f"~{total_ms / 1000:.1f} s")
        else:
            self._completion_time_lbl.setText(f"~{total_ms / 60000:.1f} min")

    def _start_auto_click(self):
        if not self._serial or self._coord_list.count() == 0:
            return
        coords = []
        for i in range(self._coord_list.count()):
            text = self._coord_list.item(i).text()
            try:
                coords_part = text.split(": ", 1)[1].strip("()")
                x_str, y_str = coords_part.split(",")
                coords.append((int(x_str.strip()), int(y_str.strip())))
            except Exception:
                self.status_update.emit(f"⚠ Could not parse coordinate: {text}")
                return
        repeat_idx = self._repeat_combo.currentIndex()
        repeat = 0 if repeat_idx == 2 else (self._repeat_n.value() if repeat_idx == 1 else 1)
        self._start_click_btn.setEnabled(False)
        self._stop_click_btn.setEnabled(True)
        w = _AutoClickWorker(
            self._serial, coords,
            self._clicks_per_coord.value(),
            self._click_delay_ms.value(),
            repeat,
        )
        w.progress.connect(self.status_update)
        w.finished.connect(self.status_update)
        w.finished.connect(lambda: self._start_click_btn.setEnabled(
            bool(self._serial) and self._coord_list.count() > 0
        ))
        w.finished.connect(lambda: self._stop_click_btn.setEnabled(False))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._auto_click_worker = w
        self._workers.append(w)
        w.start()

    def _stop_auto_click(self):
        if self._auto_click_worker:
            self._auto_click_worker.stop()
        self._stop_click_btn.setEnabled(False)

    # ── Screenshot handlers ───────────────────────────────────────────────────

    def _take_screenshot_ui(self, during_record: bool = False):
        """Take a screenshot using the selected mode."""
        if not self._serial:
            return
        mode = "device" if self._ss_rb_device.isChecked() else "direct"
        self._take_screenshot(mode)

    def _take_screenshot(self, mode: str):
        if not self._serial:
            return
        w = _ScreenshotWorker(self._serial, mode, self._screenshot_save_dir)
        w.finished.connect(self._on_screenshot_done)
        w.error.connect(lambda e: self.status_update.emit(f"❌ Screenshot error: {e}"))
        w.finished.connect(lambda _msg, _p, ww=w: self._workers.remove(ww) if ww in self._workers else None)
        self._workers.append(w)
        w.start()
        self.status_update.emit("📸 Taking screenshot…")

    def _on_screenshot_done(self, msg: str, local_path: str):
        self.status_update.emit(msg)
        if local_path and os.path.isfile(local_path):
            self._screenshot_paths.append(local_path)
            fname = os.path.basename(local_path)
            item_text = f"📷 {fname}"
            self._ss_list.addItem(item_text)
            # Store path in item data
            self._ss_list.item(self._ss_list.count() - 1).setData(Qt.ItemDataRole.UserRole, local_path)
            self._ss_list.scrollToBottom()

    def _on_ss_list_double_click(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._preview_screenshot(path)

    def _preview_selected_screenshot(self):
        item = self._ss_list.currentItem()
        if not item:
            self.status_update.emit("⚠ Select a screenshot first")
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._preview_screenshot(path)

    def _delete_selected_screenshot(self):
        row = self._ss_list.currentRow()
        if row < 0:
            self.status_update.emit("⚠ Select a screenshot to delete")
            return
        item = self._ss_list.item(row)
        path = item.data(Qt.ItemDataRole.UserRole)
        try:
            if path and os.path.isfile(path):
                os.remove(path)
            if path in self._screenshot_paths:
                self._screenshot_paths.remove(path)
        except Exception as e:
            self.status_update.emit(f"❌ Delete failed: {e}")
            return
        self._ss_list.takeItem(row)
        self.status_update.emit(f"🗑 Deleted: {os.path.basename(path)}")

    def _preview_screenshot(self, path: str):
        """Open a dialog showing a full-size preview of the screenshot."""
        if not os.path.isfile(path):
            self.status_update.emit("❌ File not found")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Preview — {os.path.basename(path)}")
        dlg.setMinimumSize(400, 600)
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(8, 8, 8, 8)

        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        px = QPixmap(path)
        if not px.isNull():
            screen = QApplication.primaryScreen().availableGeometry()
            max_w = int(screen.width() * 0.6)
            max_h = int(screen.height() * 0.8)
            lbl.setPixmap(px.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        else:
            lbl.setText("Cannot load image")
        vl.addWidget(lbl)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("📂 Open in Explorer")
        open_btn.clicked.connect(lambda: os.startfile(os.path.dirname(path)))
        btn_row.addWidget(open_btn)
        close_btn = QPushButton("✖ Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        vl.addLayout(btn_row)

        dlg.exec()

    def _open_ss_folder(self):
        os.makedirs(self._screenshot_save_dir, exist_ok=True)
        try:
            os.startfile(self._screenshot_save_dir)
        except Exception as e:
            self.status_update.emit(f"❌ Cannot open folder: {e}")

    # ── Screen recording handlers ─────────────────────────────────────────────

    def _start_recording(self):
        if not self._serial:
            return
        delay = self._rec_delay.value()
        if delay > 0:
            self._rec_status_lbl.setText(f"⏳ Starting in {delay}s…")
            self._rec_start_btn.setEnabled(False)
            QTimer.singleShot(delay * 1000, self._do_start_recording)
        else:
            self._do_start_recording()

    def _do_start_recording(self):
        if not self._serial:
            return
        ts          = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_path = f"/sdcard/rec_{ts}.mp4"
        time_limit  = self._rec_timelimit.value()   # 0 = no limit
        audio       = self._rec_audio_cb.isChecked()

        self._rec_paused = False
        self._rec_elapsed_secs = 0
        self._rec_elapsed_lbl.setText("⏺ 00:00")

        self._rec_worker = _ScreenRecordWorker(
            self._serial, remote_path, self._rec_save_dir, time_limit, audio
        )
        self._rec_worker.started.connect(self._on_rec_started)
        self._rec_worker.finished.connect(self._on_rec_finished)
        self._rec_worker.error.connect(lambda e: self.status_update.emit(f"❌ Record error: {e}"))
        self._rec_worker.finished.connect(self._on_rec_worker_done)
        self._rec_worker.start()

        # Elapsed timer
        self._rec_elapsed_timer = QTimer(self)
        self._rec_elapsed_timer.setInterval(1000)
        self._rec_elapsed_timer.timeout.connect(self._tick_elapsed)
        self._rec_elapsed_timer.start()

    def _on_rec_started(self, remote_path: str):
        self._rec_start_btn.setEnabled(False)
        self._rec_pause_btn.setEnabled(True)
        self._rec_stop_btn.setEnabled(True)
        self._rec_snap_btn.setEnabled(True)
        self._rec_status_lbl.setText("⏺ Recording…")
        self.status_update.emit(f"🎬 Recording started: {remote_path}")

    def _on_rec_finished(self, local_path: str):
        fname = os.path.basename(local_path)
        self.status_update.emit(f"✅ Video saved: {fname}")

    def _on_rec_worker_done(self, local_path: str):
        self._stop_elapsed_timer()
        self._rec_start_btn.setEnabled(bool(self._serial))
        self._rec_pause_btn.setEnabled(False)
        self._rec_pause_btn.setText("⏸ Pause")
        self._rec_stop_btn.setEnabled(False)
        self._rec_snap_btn.setEnabled(False)
        self._rec_status_lbl.setText("Idle")
        self._rec_elapsed_lbl.setText("")
        self._rec_paused = False
        if local_path and os.path.isfile(local_path):
            item_text = f"🎬 {os.path.basename(local_path)}"
            self._rec_list.addItem(item_text)
            self._rec_list.item(self._rec_list.count() - 1).setData(Qt.ItemDataRole.UserRole, local_path)
            self._rec_list.scrollToBottom()

    def _pause_resume_recording(self):
        if not self._rec_worker:
            return
        if self._rec_paused:
            self._rec_worker.resume()
            self._rec_paused = False
            self._rec_pause_btn.setText("⏸ Pause")
            self._rec_status_lbl.setText("⏺ Recording…")
            if self._rec_elapsed_timer:
                self._rec_elapsed_timer.start()
        else:
            self._rec_worker.pause()
            self._rec_paused = True
            self._rec_pause_btn.setText("▶ Resume")
            self._rec_status_lbl.setText("⏸ Paused")
            if self._rec_elapsed_timer:
                self._rec_elapsed_timer.stop()

    def _stop_recording(self):
        if self._rec_worker:
            self._rec_worker.stop()
        self._rec_status_lbl.setText("⏹ Stopping…")
        self._rec_stop_btn.setEnabled(False)
        self._rec_pause_btn.setEnabled(False)

    def _tick_elapsed(self):
        self._rec_elapsed_secs += 1
        m, s = divmod(self._rec_elapsed_secs, 60)
        self._rec_elapsed_lbl.setText(f"⏺ {m:02d}:{s:02d}")

    def _stop_elapsed_timer(self):
        if self._rec_elapsed_timer:
            self._rec_elapsed_timer.stop()
            self._rec_elapsed_timer.deleteLater()
            self._rec_elapsed_timer = None

    def _on_rec_list_double_click(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.isfile(path):
            self._play_video(path)

    def _play_selected_video(self):
        item = self._rec_list.currentItem()
        if not item:
            self.status_update.emit("⚠ Select a video first")
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._play_video(path)

    def _play_video(self, path: str):
        try:
            os.startfile(path)
        except Exception as e:
            self.status_update.emit(f"❌ Cannot open video: {e}")

    def _delete_selected_video(self):
        row = self._rec_list.currentRow()
        if row < 0:
            self.status_update.emit("⚠ Select a video to delete")
            return
        item = self._rec_list.item(row)
        path = item.data(Qt.ItemDataRole.UserRole)
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except Exception as e:
            self.status_update.emit(f"❌ Delete failed: {e}")
            return
        self._rec_list.takeItem(row)
        self.status_update.emit(f"🗑 Deleted: {os.path.basename(path)}")

    def _open_rec_folder(self):
        os.makedirs(self._rec_save_dir, exist_ok=True)
        try:
            os.startfile(self._rec_save_dir)
        except Exception as e:
            self.status_update.emit(f"❌ Cannot open folder: {e}")

