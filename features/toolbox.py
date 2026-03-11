from __future__ import annotations

import subprocess, os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize

# ── ADB bootstrap ────────────────────────────────────────────────────────
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

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


def _make_card_btn(emoji: str, label: str, accent: str = "#1976d2") -> QPushButton:
    """Create a card-style button: large emoji on top, text label below."""
    btn = QPushButton()
    btn.setFixedSize(100, 96)
    btn.setStyleSheet(_CARD_SS.format(accent=accent))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    # Overlay a transparent child widget that holds the layout
    inner = QWidget(btn)
    inner.setGeometry(0, 0, 100, 96)
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


class ToolboxWidget(QWidget):
    status_update = Signal(str)

    # (emoji, short label, adb reboot argument, accent color)
    _REBOOT_MODES = [
        ("🔁", "Normal",      "",           "#1976d2"),
        ("🔓", "Bootloader",  "bootloader", "#7b1fa2"),
        ("🛠",  "Recovery",    "recovery",   "#e65100"),
        ("📦", "Sideload",    "sideload",   "#388e3c"),
        ("⚡", "Fastboot",    "fastboot",   "#f57f17"),
        ("�", "EDL",         "edl",        "#c62828"),
        ("🔒", "Safe Mode",   "safemode",   "#546e7a"),
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._serial: str = ""
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

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
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

        COLS = 6
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
