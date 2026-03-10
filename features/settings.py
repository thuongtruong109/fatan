"""
Settings tab content widget.
Replaces the old modal dialog — lives as a tab page in the right panel.
"""
from __future__ import annotations

import json
import os
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QSpacerItem, QSizePolicy,
    QComboBox, QSlider, QCheckBox, QScrollArea, QFrame,
)
from PySide6.QtCore import Signal, Qt, QThread, QTimer

from features.actions import _PlayStoreWorker

_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")


def _adb(serial: str, *args: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["adb", "-s", serial, *args],
            startupinfo=_si, capture_output=True, text=True, timeout=timeout,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""

def _shell(serial: str, cmd: str, timeout: int = 10) -> str:
    return _adb(serial, "shell", cmd, timeout=timeout)


class _DeviceControlWorker(QThread):
    finished = Signal(str)

    def __init__(self, serials: list[str], action: str, value=None):
        super().__init__()
        self.serials = serials
        self.action = action
        self.value = value

    def run(self):
        results = []
        for s in self.serials:
            try:
                if self.action == "reboot":
                    _adb(s, "reboot")
                    results.append(f"✅ Rebooted {s}")
                elif self.action == "screen_lock_none":
                    _shell(s, "locksettings clear --old 0000 2>/dev/null; "
                              "settings put secure lockscreen.disabled 1; "
                              "settings put global screen_off_timeout 30000")
                    results.append(f"✅ Screen lock → None on {s}")
                elif self.action == "screen_lock_swipe":
                    _shell(s, "settings put secure lockscreen.disabled 0; "
                              "settings put global screen_off_timeout 30000")
                    results.append(f"✅ Screen lock → Swipe on {s}")
                elif self.action == "wifi_on":
                    _shell(s, "svc wifi enable")
                    results.append(f"✅ WiFi ON on {s}")
                elif self.action == "wifi_off":
                    _shell(s, "svc wifi disable")
                    results.append(f"✅ WiFi OFF on {s}")
                elif self.action == "data_on":
                    _shell(s, "svc data enable")
                    results.append(f"✅ Mobile data ON on {s}")
                elif self.action == "data_off":
                    _shell(s, "svc data disable")
                    results.append(f"✅ Mobile data OFF on {s}")
                elif self.action == "airplane_on":
                    _shell(s, "settings put global airplane_mode_on 1; "
                              "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true")
                    results.append(f"✅ Airplane mode ON on {s}")
                elif self.action == "airplane_off":
                    _shell(s, "settings put global airplane_mode_on 0; "
                              "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false")
                    results.append(f"✅ Airplane mode OFF on {s}")
                elif self.action == "brightness":
                    val = int(self.value)
                    _shell(s, f"settings put system screen_brightness_mode 0; "
                              f"settings put system screen_brightness {val}")
                    results.append(f"✅ Brightness → {val} on {s}")
                elif self.action == "volume":
                    val = int(self.value)
                    # STREAM_MUSIC = 3, setStreamVolume via media command
                    _shell(s, f"media volume --stream 3 --set {val}")
                    results.append(f"✅ Volume → {val} on {s}")
                elif self.action == "bluetooth_on":
                    _shell(s, "svc bluetooth enable")
                    results.append(f"✅ Bluetooth ON on {s}")
                elif self.action == "bluetooth_off":
                    _shell(s, "svc bluetooth disable")
                    results.append(f"✅ Bluetooth OFF on {s}")
                elif self.action == "disable_animations":
                    _shell(s, "settings put global window_animation_scale 0; "
                              "settings put global transition_animation_scale 0; "
                              "settings put global animator_duration_scale 0")
                    results.append(f"✅ Animations disabled on {s}")
                elif self.action == "enable_animations":
                    _shell(s, "settings put global window_animation_scale 1; "
                              "settings put global transition_animation_scale 1; "
                              "settings put global animator_duration_scale 1")
                    results.append(f"✅ Animations enabled on {s}")
                elif self.action == "dark_mode_on":
                    _shell(s, "cmd uimode night yes")
                    results.append(f"✅ Dark mode ON on {s}")
                elif self.action == "dark_mode_off":
                    _shell(s, "cmd uimode night no")
                    results.append(f"✅ Dark mode OFF on {s}")
                elif self.action == "stay_on_charging_on":
                    _shell(s, "settings put global stay_on_while_plugged_in 3")
                    results.append(f"✅ Stay on while charging ON on {s}")
                elif self.action == "stay_on_charging_off":
                    _shell(s, "settings put global stay_on_while_plugged_in 0")
                    results.append(f"✅ Stay on while charging OFF on {s}")
                elif self.action == "set_dpi":
                    val = int(self.value)
                    _shell(s, f"wm density {val}")
                    results.append(f"✅ DPI → {val} on {s}")
                elif self.action == "reset_dpi":
                    _shell(s, "wm density reset")
                    results.append(f"✅ DPI reset on {s}")
                elif self.action == "set_resolution":
                    _shell(s, f"wm size {self.value}")
                    results.append(f"✅ Resolution → {self.value} on {s}")
                elif self.action == "reset_resolution":
                    _shell(s, "wm size reset")
                    results.append(f"✅ Resolution reset on {s}")
            except Exception as e:
                results.append(f"❌ {s}: {e}")
        self.finished.emit("\n".join(results) if results else "Done")

class SettingsWidget(QWidget):
    """Settings form rendered as an inline tab content (no modal)."""

    settings_saved = Signal(dict)        # emitted after user saves
    setup_keyboard_requested = Signal()  # emit to trigger keyboard setup on all devices
    install_chrome_requested = Signal()  # emit to trigger Chrome install on all devices
    install_socksdroid_requested = Signal()  # emit to trigger SocksDroid install on all devices

    DEFAULTS = {
        "preview_width": 300,
        "preview_height": 600,
    }

    def __init__(self, settings_file: str = "data/settings.json", parent=None):
        super().__init__(parent)
        self.settings_file = settings_file
        self._data: dict = dict(self.DEFAULTS)
        self._get_serials_fn = None   # set by gui after construction
        self._workers: list = []
        self._brightness_timer = QTimer()
        self._brightness_timer.setSingleShot(True)
        self._brightness_timer.setInterval(1000)
        self._brightness_timer.timeout.connect(self._apply_brightness)
        self._volume_timer = QTimer()
        self._volume_timer.setSingleShot(True)
        self._volume_timer.setInterval(600)
        self._volume_timer.timeout.connect(self._apply_volume_debounced)
        self._load()
        self._build_ui()

    # ── persistence ─────────────────────────────────────────────────────
    def _load(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r") as f:
                    saved = json.load(f)
                self._data.update({k: saved[k] for k in self.DEFAULTS if k in saved})
        except Exception as e:
            print(f"[Settings] load error: {e}")

    def _save(self):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            print(f"[Settings] save error: {e}")

    # ── public accessors ─────────────────────────────────────────────────
    def get(self, key: str, default=None):
        return self._data.get(key, default)

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        vl = QVBoxLayout(inner)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(8)

        _GROUP_SS = """
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 6px;
                background-color: #fafafa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #333;
            }
        """
        _GROUP_BLUE_SS = _GROUP_SS.replace("background-color: #fafafa;", "background-color: #f8f9ff;").replace("color: #333;", "color: #1565c0;")
        _INPUT_SS = (
            "QLineEdit { border: 1px solid #ddd; border-radius: 4px;"
            " padding: 2px 6px; background: #ffffff; color: #212121;"
            " font-size: 11px; min-height: 20px; max-height: 24px; }"
            "QLineEdit:focus { border: 1px solid #1976d2; }"
        )
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
        _LABEL_SS = "font-size: 11px; color: #555; font-weight: bold;"

        # ── Device Controls ──────────────────────────────────────────────
        ctrl_group = QGroupBox("🎛 Device Controls")
        ctrl_group.setStyleSheet(_GROUP_BLUE_SS)
        ctrl_vl = QVBoxLayout()
        ctrl_vl.setContentsMargins(12, 10, 12, 12)
        ctrl_vl.setSpacing(10)

        row_wh = QHBoxLayout()
        row_wh.setSpacing(8)

        # Row 1: Screen lock + Bluetooth (same row)
        lbl_lock = QLabel("🔒 Screen lock:")
        lbl_lock.setStyleSheet(_LABEL_SS)
        lbl_lock.setFixedWidth(90)
        row_wh.addWidget(lbl_lock)
        self._lock_combo = QComboBox()
        self._lock_combo.addItems(["None (disabled)", "Swipe"])
        self._lock_combo.setStyleSheet(
            "QComboBox { border: 1px solid #ddd; border-radius: 4px; padding: 2px 6px;"
            " background: #fff; font-size: 11px; min-height: 22px; }"
            "QComboBox:focus { border: 1px solid #1976d2; }"
            "QComboBox::drop-down { border: none; }"
        )
        self._lock_combo.setMaximumWidth(140)
        row_wh.addWidget(self._lock_combo)
        self._lock_combo.currentIndexChanged.connect(lambda _: self._apply_screen_lock())

        sep_bt = QLabel("|")
        sep_bt.setStyleSheet("color: #ccc; margin-left: 10px")
        row_wh.addWidget(sep_bt)

        lbl_stay = QLabel("� Stay on charging:")
        lbl_stay.setStyleSheet(_LABEL_SS)
        lbl_stay.setFixedWidth(120)
        row_wh.addWidget(lbl_stay)
        btn_stay_on = QPushButton("ON")
        btn_stay_on.setStyleSheet(_BTN_ON_SS)
        btn_stay_on.setFixedHeight(26)
        btn_stay_on.setToolTip("adb shell settings put global stay_on_while_plugged_in 3")
        btn_stay_on.clicked.connect(lambda: self._device_action("stay_on_charging_on"))
        row_wh.addWidget(btn_stay_on)
        btn_stay_off = QPushButton("OFF")
        btn_stay_off.setStyleSheet(_BTN_OFF_SS)
        btn_stay_off.setFixedHeight(26)
        btn_stay_off.setToolTip("adb shell settings put global stay_on_while_plugged_in 0")
        btn_stay_off.clicked.connect(lambda: self._device_action("stay_on_charging_off"))
        row_wh.addWidget(btn_stay_off)

        row_wh.addStretch()
        ctrl_vl.addLayout(row_wh)

        # Row 2: WiFi + Mobile Data + Airplane toggles
        row_toggles = QHBoxLayout()
        row_toggles.setSpacing(8)

        lbl_wifi = QLabel("📶 WiFi:")
        lbl_wifi.setStyleSheet(_LABEL_SS)
        lbl_wifi.setFixedWidth(80)
        row_toggles.addWidget(lbl_wifi)
        btn_wifi_on = QPushButton("ON")
        btn_wifi_on.setStyleSheet(_BTN_ON_SS)
        btn_wifi_on.setFixedHeight(26)
        btn_wifi_on.clicked.connect(lambda: self._device_action("wifi_on"))
        row_toggles.addWidget(btn_wifi_on)
        btn_wifi_off = QPushButton("OFF")
        btn_wifi_off.setStyleSheet(_BTN_OFF_SS)
        btn_wifi_off.setFixedHeight(26)
        btn_wifi_off.clicked.connect(lambda: self._device_action("wifi_off"))
        row_toggles.addWidget(btn_wifi_off)

        sep2 = QLabel("|")
        sep2.setStyleSheet("color: #ccc; margin-left: 10px")
        row_toggles.addWidget(sep2)

        lbl_data = QLabel("📡 Mobile Data:")
        lbl_data.setStyleSheet(_LABEL_SS)
        lbl_data.setFixedWidth(90)
        row_toggles.addWidget(lbl_data)
        btn_data_on = QPushButton("ON")
        btn_data_on.setStyleSheet(_BTN_ON_SS)
        btn_data_on.setFixedHeight(26)
        btn_data_on.clicked.connect(lambda: self._device_action("data_on"))
        row_toggles.addWidget(btn_data_on)
        btn_data_off = QPushButton("OFF")
        btn_data_off.setStyleSheet(_BTN_OFF_SS)
        btn_data_off.setFixedHeight(26)
        btn_data_off.clicked.connect(lambda: self._device_action("data_off"))
        row_toggles.addWidget(btn_data_off)

        sep3 = QLabel("|")
        sep3.setStyleSheet("color: #ccc; margin-left: 10px")
        row_toggles.addWidget(sep3)

        lbl_airplane = QLabel("✈ Airplane:")
        lbl_airplane.setStyleSheet(_LABEL_SS)
        lbl_airplane.setFixedWidth(70)
        row_toggles.addWidget(lbl_airplane)
        btn_ap_on = QPushButton("ON")
        btn_ap_on.setStyleSheet(_BTN_ON_SS)
        btn_ap_on.setFixedHeight(26)
        btn_ap_on.clicked.connect(lambda: self._device_action("airplane_on"))
        row_toggles.addWidget(btn_ap_on)
        btn_ap_off = QPushButton("OFF")
        btn_ap_off.setStyleSheet(_BTN_OFF_SS)
        btn_ap_off.setFixedHeight(26)
        btn_ap_off.clicked.connect(lambda: self._device_action("airplane_off"))
        row_toggles.addWidget(btn_ap_off)

        row_toggles.addStretch()
        ctrl_vl.addLayout(row_toggles)

        # Row 3: Brightness + Volume on same row
        row_bright = QHBoxLayout()
        row_bright.setSpacing(8)
        lbl_bright = QLabel("☀ Brightness:")
        lbl_bright.setStyleSheet(_LABEL_SS)
        lbl_bright.setFixedWidth(80)
        row_bright.addWidget(lbl_bright)
        self._brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self._brightness_slider.setMinimum(0)
        self._brightness_slider.setMaximum(100)
        self._brightness_slider.setValue(50)
        self._brightness_slider.setSingleStep(1)
        self._brightness_slider.setFixedWidth(110)
        _SLIDER_SS = (
            "QSlider::groove:horizontal { height: 4px; background: #ddd; border-radius: 2px; }"
            "QSlider::handle:horizontal { background: #1976d2; border-radius: 6px;"
            " width: 14px; height: 14px; margin: -5px 0; }"
            "QSlider::sub-page:horizontal { background: #90caf9; border-radius: 2px; }"
        )
        self._brightness_slider.setStyleSheet(_SLIDER_SS)
        self._bright_val_lbl = QLabel("50")
        self._bright_val_lbl.setStyleSheet("font-size: 11px; color: #333; min-width: 20px;")
        self._brightness_slider.valueChanged.connect(
            lambda v: (
                self._bright_val_lbl.setText(str(v)),
                self._brightness_timer.start(),
            )
        )
        row_bright.addWidget(self._brightness_slider)
        row_bright.addWidget(self._bright_val_lbl)

        # Volume slider (same row as Brightness)
        row_bright.addSpacing(12)
        lbl_vol = QLabel("🔊 Volume:")
        lbl_vol.setStyleSheet(_LABEL_SS)
        lbl_vol.setFixedWidth(70)
        row_bright.addWidget(lbl_vol)
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setMinimum(0)
        self._volume_slider.setMaximum(15)
        self._volume_slider.setValue(7)
        self._volume_slider.setSingleStep(1)
        self._volume_slider.setFixedWidth(110)
        self._volume_slider.setStyleSheet(_SLIDER_SS)
        self._vol_val_lbl = QLabel("7")
        self._vol_val_lbl.setStyleSheet("font-size: 11px; color: #333; min-width: 20px;")
        self._volume_slider.valueChanged.connect(
            lambda v: (
                self._vol_val_lbl.setText(str(v)),
                self._volume_timer.start(),
            )
        )
        row_bright.addWidget(self._volume_slider)
        row_bright.addWidget(self._vol_val_lbl)

        row_bright.addStretch()
        ctrl_vl.addLayout(row_bright)

        # Row A: Speed boost (disable/enable animations)
        row_anim = QHBoxLayout()
        row_anim.setSpacing(8)
        lbl_anim = QLabel("🚀 Animation:")
        lbl_anim.setStyleSheet(_LABEL_SS)
        lbl_anim.setFixedWidth(80)
        row_anim.addWidget(lbl_anim)
        btn_anim_on = QPushButton("Disable")
        btn_anim_on.setStyleSheet(_BTN_ON_SS)
        btn_anim_on.setFixedHeight(26)
        btn_anim_on.setToolTip(
            "adb shell settings put global window_animation_scale 0\n"
            "adb shell settings put global transition_animation_scale 0\n"
            "adb shell settings put global animator_duration_scale 0"
        )
        btn_anim_on.clicked.connect(lambda: self._device_action("disable_animations"))
        row_anim.addWidget(btn_anim_on)
        btn_anim_off = QPushButton("Enable")
        btn_anim_off.setStyleSheet(_BTN_OFF_SS)
        btn_anim_off.setFixedHeight(26)
        btn_anim_off.setToolTip("Restore animation scales to 1")
        btn_anim_off.clicked.connect(lambda: self._device_action("enable_animations"))
        row_anim.addWidget(btn_anim_off)

        # Row B: Dark mode and Stay on charging — same row

        sep4 = QLabel("|")
        sep4.setStyleSheet("color: #ccc; margin-left: 8px")
        row_anim.addWidget(sep4)

        lbl_dark = QLabel("🌙 Dark Mode:")
        lbl_dark.setStyleSheet(_LABEL_SS)
        lbl_dark.setFixedWidth(90)
        row_anim.addWidget(lbl_dark)
        btn_dark_on = QPushButton("ON")
        btn_dark_on.setStyleSheet(_BTN_ON_SS)
        btn_dark_on.setFixedHeight(26)
        btn_dark_on.setToolTip("adb shell cmd uimode night yes")
        btn_dark_on.clicked.connect(lambda: self._device_action("dark_mode_on"))
        row_anim.addWidget(btn_dark_on)
        btn_dark_off = QPushButton("OFF")
        btn_dark_off.setStyleSheet(_BTN_OFF_SS)
        btn_dark_off.setFixedHeight(26)
        btn_dark_off.setToolTip("adb shell cmd uimode night no")
        btn_dark_off.clicked.connect(lambda: self._device_action("dark_mode_off"))
        row_anim.addWidget(btn_dark_off)

        sep5 = QLabel("|")
        sep5.setStyleSheet("color: #ccc; margin-left: 8px")
        row_anim.addWidget(sep5)

        lbl_bt = QLabel("� Bluetooth:")
        lbl_bt.setStyleSheet(_LABEL_SS)
        lbl_bt.setFixedWidth(80)
        row_anim.addWidget(lbl_bt)
        btn_bt_on = QPushButton("ON")
        btn_bt_on.setStyleSheet(_BTN_ON_SS)
        btn_bt_on.setFixedHeight(26)
        btn_bt_on.setToolTip("adb shell svc bluetooth enable")
        btn_bt_on.clicked.connect(lambda: self._device_action("bluetooth_on"))
        row_anim.addWidget(btn_bt_on)
        btn_bt_off = QPushButton("OFF")
        btn_bt_off.setStyleSheet(_BTN_OFF_SS)
        btn_bt_off.setFixedHeight(26)
        btn_bt_off.setToolTip("adb shell svc bluetooth disable")
        btn_bt_off.clicked.connect(lambda: self._device_action("bluetooth_off"))
        row_anim.addWidget(btn_bt_off)
        row_anim.addStretch()
        ctrl_vl.addLayout(row_anim)

        ctrl_group.setLayout(ctrl_vl)
        vl.addWidget(ctrl_group)

        # ── Display Settings (Width/Height + DPI + Resolution) ────────────────────────
        display_group = QGroupBox("🖥 Display Settings")
        display_group.setStyleSheet(_GROUP_BLUE_SS)
        display_vl = QVBoxLayout()
        display_vl.setContentsMargins(12, 10, 12, 12)
        display_vl.setSpacing(10)

        # Two-column layout: left = width/height, right = DPI/resolution
        display_cols = QHBoxLayout()
        display_cols.setSpacing(16)

        # ── Left column: Preview Width & Height ──────────────────────────
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        lbl_w = QLabel("↔️ Width (px):")
        lbl_w.setStyleSheet(_LABEL_SS)
        lbl_w.setFixedWidth(90)
        self._width_input = QLineEdit(str(self._data["preview_width"]))
        self._width_input.setPlaceholderText("e.g. 400")
        self._width_input.setMaximumWidth(90)
        self._width_input.setStyleSheet(_INPUT_SS)
        row_w = QHBoxLayout()
        row_w.setSpacing(6)
        row_w.addWidget(lbl_w)
        row_w.addWidget(self._width_input)
        row_w.addStretch()
        left_col.addLayout(row_w)

        lbl_h = QLabel("↕️ Height (px):")
        lbl_h.setStyleSheet(_LABEL_SS)
        lbl_h.setFixedWidth(90)
        self._height_input = QLineEdit(str(self._data["preview_height"]))
        self._height_input.setPlaceholderText("e.g. 600")
        self._height_input.setMaximumWidth(90)
        self._height_input.setStyleSheet(_INPUT_SS)
        row_h = QHBoxLayout()
        row_h.setSpacing(6)
        row_h.addWidget(lbl_h)
        row_h.addWidget(self._height_input)
        row_h.addStretch()
        left_col.addLayout(row_h)
        left_col.addStretch()

        # ── Right column: DPI density & Resolution ────────────────────────
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # DPI row
        row_dpi = QHBoxLayout()
        row_dpi.setSpacing(8)
        lbl_dpi = QLabel("🧠 DPI density:")
        lbl_dpi.setStyleSheet(_LABEL_SS)
        lbl_dpi.setFixedWidth(100)
        row_dpi.addWidget(lbl_dpi)
        self._dpi_input = QLineEdit()
        self._dpi_input.setPlaceholderText("e.g. 300")
        self._dpi_input.setMaximumWidth(80)
        self._dpi_input.setStyleSheet(_INPUT_SS)
        self._dpi_input.setToolTip("adb shell wm density <value>")
        row_dpi.addWidget(self._dpi_input)
        btn_dpi_set = QPushButton("✔ Set DPI")
        btn_dpi_set.setStyleSheet(_BTN_ON_SS)
        btn_dpi_set.setFixedHeight(26)
        btn_dpi_set.setToolTip("adb shell wm density <value>")
        btn_dpi_set.clicked.connect(self._apply_dpi)
        row_dpi.addWidget(btn_dpi_set)
        btn_dpi_reset = QPushButton("↩ Reset DPI")
        btn_dpi_reset.setStyleSheet(_BTN_OFF_SS)
        btn_dpi_reset.setFixedHeight(26)
        btn_dpi_reset.setToolTip("adb shell wm density reset")
        btn_dpi_reset.clicked.connect(lambda: self._device_action("reset_dpi"))
        row_dpi.addWidget(btn_dpi_reset)
        row_dpi.addStretch()
        right_col.addLayout(row_dpi)

        # Resolution row
        row_res = QHBoxLayout()
        row_res.setSpacing(8)
        lbl_res = QLabel("📱 Resolution:")
        lbl_res.setStyleSheet(_LABEL_SS)
        lbl_res.setFixedWidth(100)
        row_res.addWidget(lbl_res)
        self._res_input = QLineEdit()
        self._res_input.setPlaceholderText("e.g. 1080x1920")
        self._res_input.setMaximumWidth(110)
        self._res_input.setStyleSheet(_INPUT_SS)
        self._res_input.setToolTip("adb shell wm size <WxH>  e.g. 1080x1920")
        row_res.addWidget(self._res_input)
        btn_res_set = QPushButton("✔ Set Size")
        btn_res_set.setStyleSheet(_BTN_ON_SS)
        btn_res_set.setFixedHeight(26)
        btn_res_set.setToolTip("adb shell wm size <WxH>")
        btn_res_set.clicked.connect(self._apply_resolution)
        row_res.addWidget(btn_res_set)
        btn_res_reset = QPushButton("↩ Reset Size")
        btn_res_reset.setStyleSheet(_BTN_OFF_SS)
        btn_res_reset.setFixedHeight(26)
        btn_res_reset.setToolTip("adb shell wm size reset")
        btn_res_reset.clicked.connect(lambda: self._device_action("reset_resolution"))
        row_res.addWidget(btn_res_reset)
        row_res.addStretch()
        right_col.addLayout(row_res)
        right_col.addStretch()

        # Vertical divider
        vline = QFrame()
        vline.setFrameShape(QFrame.Shape.VLine)
        vline.setFrameShadow(QFrame.Shadow.Sunken)
        vline.setStyleSheet("color: #ddd;")

        display_cols.addLayout(left_col)
        display_cols.addWidget(vline)
        display_cols.addLayout(right_col, 1)
        display_vl.addLayout(display_cols)

        display_group.setLayout(display_vl)
        vl.addWidget(display_group)

        # ── Device Actions ─────────────────────────────────────────────────
        setup_group = QGroupBox("🛠 Device Actions")
        setup_group.setStyleSheet(_GROUP_BLUE_SS)
        setup_vl = QVBoxLayout()
        setup_vl.setContentsMargins(12, 10, 12, 10)
        setup_vl.setSpacing(8)

        setup_btn_row1 = QHBoxLayout()
        setup_btn_row1.setSpacing(10)

        self._disable_play_btn = QPushButton("🚫 Disable Play Store")
        self._disable_play_btn.setStyleSheet(_BTN_SS)
        self._disable_play_btn.setMinimumHeight(30)
        self._disable_play_btn.setToolTip(
            "Disable Google Play Store on all devices\n"
            "adb shell pm disable-user --user 0 com.android.vending"
        )
        self._disable_play_btn.clicked.connect(lambda: self._run_play_store(enable=False))
        setup_btn_row1.addWidget(self._disable_play_btn, 1)

        self._enable_play_btn = QPushButton("✅ Enable Play Store")
        self._enable_play_btn.setStyleSheet(_BTN_SS)
        self._enable_play_btn.setMinimumHeight(30)
        self._enable_play_btn.setToolTip(
            "Enable Google Play Store on all devices\n"
            "adb shell pm enable com.android.vending"
        )
        self._enable_play_btn.clicked.connect(lambda: self._run_play_store(enable=True))
        setup_btn_row1.addWidget(self._enable_play_btn, 1)

        self._setup_keyboard_btn = QPushButton("⌨️ Setup Keyboard")
        self._setup_keyboard_btn.setStyleSheet(_BTN_SS)
        self._setup_keyboard_btn.setMinimumHeight(30)
        self._setup_keyboard_btn.setToolTip("Install ADB keyboard on all devices in the table")
        self._setup_keyboard_btn.clicked.connect(self.setup_keyboard_requested.emit)
        setup_btn_row1.addWidget(self._setup_keyboard_btn, 1)

        self._reboot_btn = QPushButton("🔁 Reboot Device")
        self._reboot_btn.setStyleSheet(_BTN_SS)
        self._reboot_btn.setMinimumHeight(30)
        self._reboot_btn.setToolTip("Reboot all devices in the table  (adb reboot)")
        self._reboot_btn.clicked.connect(lambda: self._device_action("reboot"))
        setup_btn_row1.addWidget(self._reboot_btn, 1)

        self._install_chrome_btn = QPushButton("🌐 Install Chrome")
        self._install_chrome_btn.setStyleSheet(_BTN_SS)
        self._install_chrome_btn.setMinimumHeight(30)
        self._install_chrome_btn.setToolTip("Install Chrome on all devices in the table")
        self._install_chrome_btn.clicked.connect(self.install_chrome_requested.emit)
        setup_btn_row1.addWidget(self._install_chrome_btn, 1)

        self._install_socksdroid_btn = QPushButton("🧦 Install SocksDroid")
        self._install_socksdroid_btn.setStyleSheet(_BTN_SS)
        self._install_socksdroid_btn.setMinimumHeight(30)
        self._install_socksdroid_btn.setToolTip("Install SocksDroid from /data/apps/SocksDroid.apk on all devices")
        self._install_socksdroid_btn.clicked.connect(self.install_socksdroid_requested.emit)
        setup_btn_row1.addWidget(self._install_socksdroid_btn, 1)

        setup_vl.addLayout(setup_btn_row1)

        setup_group.setLayout(setup_vl)
        vl.addWidget(setup_group)

        # ── Save button row ──────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch()

        reset_btn = QPushButton("🔄 Reset to defaults")
        reset_btn.setMinimumHeight(36)
        reset_btn.setStyleSheet(
            "QPushButton { padding: 5px 10px; }"
        )
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)

        save_btn = QPushButton("💾 Save settings")
        save_btn.setMinimumHeight(30)
        save_btn.setStyleSheet(
            "QPushButton { border: 1px solid #FFB872; border-radius: 4px;"
            " padding: 5px 10px; background: #fff3e0; color: #e65100;"
            " font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #ffe0b2; border: 1px solid #f57c00; }"
            "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        vl.addLayout(btn_row)
        vl.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll)

    def _get_serials(self) -> list[str]:
        return self._get_serials_fn() if callable(self._get_serials_fn) else []

    def _apply_dpi(self):
        serials = self._get_serials()
        if not serials:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ No devices found.")
            return
        raw = self._dpi_input.text().strip()
        if not raw.isdigit():
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ DPI must be a number (e.g. 300).")
            return
        w = _DeviceControlWorker(serials, "set_dpi", value=int(raw))
        self._start_worker(w)

    def _apply_resolution(self):
        serials = self._get_serials()
        if not serials:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ No devices found.")
            return
        raw = self._res_input.text().strip()
        import re as _re
        if not _re.match(r"^\d+x\d+$", raw):
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ Format must be WxH (e.g. 1080x1920).")
            return
        w = _DeviceControlWorker(serials, "set_resolution", value=raw)
        self._start_worker(w)

    def _apply_screen_lock(self):
        serials = self._get_serials()
        if not serials:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ No devices found.")
            return
        idx = self._lock_combo.currentIndex()
        action = "screen_lock_none" if idx == 0 else "screen_lock_swipe"
        self._device_action(action)

    def _apply_brightness(self):
        serials = self._get_serials()
        if not serials:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ No devices found.")
            return
        # Map 0–100 slider value to 0–255 Android brightness
        pct = self._brightness_slider.value()
        val = round(pct * 255 / 100)
        w = _DeviceControlWorker(serials, "brightness", value=val)
        self._start_worker(w)

    def _apply_volume_debounced(self):
        serials = self._get_serials()
        if not serials:
            return
        val = self._volume_slider.value()
        w = _DeviceControlWorker(serials, "volume", value=val)
        self._start_worker(w)

    def _device_action(self, action: str):
        serials = self._get_serials()
        if not serials:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ No devices found.")
            return
        w = _DeviceControlWorker(serials, action)
        self._start_worker(w)

    def _start_worker(self, w: QThread):
        self._status_label.setStyleSheet("color: #555; font-size: 12px;")
        self._status_label.setText("⏳ Running…")
        w.finished.connect(lambda msg: (
            self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;"),
            self._status_label.setText(msg.split("\n")[0]),
        ))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _run_play_store(self, enable: bool):
        serials = self._get_serials_fn() if callable(self._get_serials_fn) else []
        if not serials:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠ No devices found in table.")
            return
        btn = self._enable_play_btn if enable else self._disable_play_btn
        btn.setEnabled(False)
        w = _PlayStoreWorker(serials, enable)
        w.progress.connect(lambda msg: (
            self._status_label.setStyleSheet("color: #555; font-size: 12px;"),
            self._status_label.setText(msg),
        ))
        w.finished.connect(lambda msg: (
            self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;"),
            self._status_label.setText(msg),
        ))
        w.finished.connect(lambda: btn.setEnabled(True))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _on_save(self):
        try:
            w = int(self._width_input.text())
            h = int(self._height_input.text())
        except ValueError:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠️ Invalid values — enter integers only.")
            return

        self._data["preview_width"] = w
        self._data["preview_height"] = h
        self._save()
        self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")
        self._status_label.setText("✅ Settings saved.")
        self.settings_saved.emit(dict(self._data))

    def _on_reset(self):
        """Reset settings to default values."""
        self._data = dict(self.DEFAULTS)
        self._width_input.setText(str(self._data["preview_width"]))
        self._height_input.setText(str(self._data["preview_height"]))
        self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")
        self._status_label.setText("🔄 Settings reset to defaults.")
