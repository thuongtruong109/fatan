from __future__ import annotations

import math
import re
import subprocess
import os
import datetime
from typing import List, Tuple

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox,
    QTextEdit, QLineEdit, QScrollArea,
    QFrame, QSizePolicy, QGridLayout,
    QSpinBox, QFileDialog, QApplication,
)
from PySide6.QtCore import Qt, QThread, Signal, QRect, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont

_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

def _adb(serial: str, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        startupinfo=_si,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

# ── Stylesheet constants ──────────────────────────────────────────────────────

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

_LABEL_SS = "color: #555; font-size: 11px; font-weight: bold;"

_SPINBOX_SS = (
    "QSpinBox {"
    "  border: 1px solid #dce3f0; border-radius: 4px;"
    "  padding: 2px 6px; background: #ffffff; color: #212121;"
    "  font-size: 11px; min-height: 20px;"
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


def _btn(label: str, color: str, hover: str, disabled: str = "#bdbdbd",
         text_color: str = "white") -> QPushButton:
    """Create a styled QPushButton."""
    b = QPushButton(label)
    b.setStyleSheet(
        f"QPushButton {{ background-color: {color}; color: {text_color}; font-weight: bold;"
        f"  padding: 5px 12px; border-radius: 4px; font-size: 11px; border: none; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
        f"QPushButton:disabled {{ background-color: {disabled}; color: #888; }}"
    )
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _btn_primary(label: str)   -> QPushButton: return _btn(label, "#1976d2", "#1565c0", "#90caf9")
def _btn_success(label: str)   -> QPushButton: return _btn(label, "#388e3c", "#2e7d32", "#a5d6a7")
def _btn_warning(label: str)   -> QPushButton: return _btn(label, "#f57c00", "#e65100", "#ffcc80")
def _btn_secondary(label: str) -> QPushButton: return _btn(label, "#546e7a", "#455a64", "#b0bec5")
def _btn_danger(label: str)    -> QPushButton: return _btn(label, "#d32f2f", "#b71c1c", "#ef9a9a")
def _btn_teal(label: str)      -> QPushButton: return _btn(label, "#00796b", "#004d40", "#80cbc4")
def _btn_purple(label: str)    -> QPushButton: return _btn(label, "#7b1fa2", "#6a1b9a", "#ce93d8")


def _btn_outline(label: str) -> QPushButton:
    b = QPushButton(label)
    b.setStyleSheet(
        "QPushButton { border: 1px solid #bdbdbd; border-radius: 4px;"
        " padding: 5px 12px; background: #f5f5f5; font-size: 11px; color: #333; }"
        "QPushButton:hover { background: #e0e0e0; border-color: #9e9e9e; }"
        "QPushButton:disabled { background: #fafafa; color: #bbb; }"
    )
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


# ── Donut / arc chart widget ──────────────────────────────────────────────────

class _DonutChart(QWidget):
    """
    Single donut (ring) chart showing used/total with a percentage in the centre.
    - title   : shown below the ring
    - color   : arc fill color
    - size    : fixed widget width & height (square)
    """

    def __init__(self, title: str, color: QColor = None, size: int = 110, parent=None):
        super().__init__(parent)
        self.title = title
        self.color = color or QColor("#1976d2")
        self._size = size
        self.used: float = 0.0
        self.total: float = 1.0
        self.label: str = "–"          # human label shown inside ring
        self.setFixedSize(size, size + 22)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_data(self, used: float, total: float, label: str = ""):
        self.used = max(0.0, used)
        self.total = max(0.001, total)
        self.label = label or f"{used:.0f}/{total:.0f}"
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W = self._size
        ring = 14          # ring stroke width
        margin = 6
        cx, cy = W // 2, W // 2
        r = W // 2 - margin

        # Background circle (track)
        p.setPen(QPen(QColor("#e8e8e8"), ring, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.FlatCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(margin, margin, W - 2 * margin, W - 2 * margin)
        p.drawEllipse(rect)

        # Arc (filled portion)
        pct = min(1.0, self.used / self.total)
        span = int(-pct * 360 * 16)   # Qt uses 1/16th degree units; negative = clockwise
        arc_color = QColor(self.color)
        p.setPen(QPen(arc_color, ring, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.FlatCap))
        p.drawArc(rect, 90 * 16, span)   # start at 12 o'clock

        # Centre percentage text
        pct_str = f"{pct * 100:.0f}%"
        p.setPen(arc_color if pct > 0 else QColor("#9e9e9e"))
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        p.drawText(QRect(0, 0, W, W), Qt.AlignmentFlag.AlignCenter, pct_str)

        # Centre sub-label (small, below %)
        p.setPen(QColor("#757575"))
        p.setFont(QFont("Segoe UI", 6))
        p.drawText(QRect(0, cy + 10, W, 16), Qt.AlignmentFlag.AlignCenter, self.label)

        # Title below ring
        p.setPen(QColor("#424242"))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.drawText(QRect(0, W + 2, W, 20), Qt.AlignmentFlag.AlignCenter, self.title)
        p.end()


class _DonutRow(QWidget):
    """Horizontal row of _DonutChart widgets that can be updated by name."""

    def __init__(self, configs: List[Tuple[str, str, QColor]], size: int = 110, parent=None):
        """configs: list of (key, label, color)"""
        super().__init__(parent)
        self._charts: dict[str, _DonutChart] = {}
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        for key, label, color in configs:
            c = _DonutChart(label, color, size)
            self._charts[key] = c
            hl.addWidget(c)
        hl.addStretch()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def update_chart(self, key: str, used: float, total: float, label: str = ""):
        if key in self._charts:
            self._charts[key].set_data(used, total, label)

    def set_visible_keys(self, keys: List[str]):
        for k, c in self._charts.items():
            c.setVisible(k in keys)


# ── Sparkline chart widget ────────────────────────────────────────────────────

class _SparklineChart(QWidget):
    """Minimal live sparkline chart drawn with QPainter — no extra deps needed."""

    def __init__(self, title: str, unit: str, max_val: float = 100.0,
                 color: QColor = None, max_points: int = 40, parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.max_val = max_val
        self.color = color or QColor("#1976d2")
        self.max_points = max_points
        self.data: List[float] = []
        self.current_val: float = 0.0
        self.setMinimumHeight(130)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, value: float):
        self.current_val = value
        self.data.append(value)
        if len(self.data) > self.max_points:
            self.data.pop(0)
        self.update()

    def clear_data(self):
        self.data.clear()
        self.current_val = 0.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        PL, PR, PT, PB = 30, 8, 28, 22

        cw = W - PL - PR
        ch = H - PT - PB

        # White background with subtle border
        p.fillRect(0, 0, W, H, QColor("#ffffff"))
        p.setPen(QPen(QColor("#e0e0e0"), 1))
        p.drawRect(0, 0, W - 1, H - 1)

        # Horizontal grid lines + Y labels
        p.setFont(QFont("Segoe UI", 7))
        for i in range(5):
            frac = i / 4
            y = PT + int(ch * frac)
            val_label = int(self.max_val * (1 - frac))
            p.setPen(QPen(QColor("#eeeeee"), 1, Qt.PenStyle.DashLine))
            p.drawLine(PL, y, W - PR, y)
            p.setPen(QColor("#9e9e9e"))
            p.drawText(QRect(0, y - 7, PL - 2, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       str(val_label))

        # Title (left)
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.setPen(QColor("#424242"))
        p.drawText(QRect(PL + 2, 3, cw // 2, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.title)

        # Current value (right, colored)
        p.setPen(self.color)
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(QRect(PL, 3, cw - 2, 20),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{self.current_val:.1f} {self.unit}")

        if len(self.data) < 2:
            p.setPen(QColor("#bdbdbd"))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRect(PL, PT, cw, ch),
                       Qt.AlignmentFlag.AlignCenter, "No data — click Refresh")
            p.end()
            return

        # Helper: data index → canvas QPointF
        n = len(self.data)
        step = cw / (self.max_points - 1)

        def _pt(i: int) -> QPointF:
            x = PL + (self.max_points - n + i) * step
            ratio = max(0.0, min(1.0, self.data[i] / self.max_val))
            y = PT + ch * (1.0 - ratio)
            return QPointF(x, y)

        # Filled area
        path = QPainterPath()
        start_x = PL + (self.max_points - n) * step
        path.moveTo(start_x, PT + ch)
        path.lineTo(_pt(0))
        for i in range(1, n):
            path.lineTo(_pt(i))
        last = _pt(n - 1)
        path.lineTo(last.x(), PT + ch)
        path.closeSubpath()
        fill = QColor(self.color)
        fill.setAlpha(35)
        p.fillPath(path, QBrush(fill))

        # Line stroke
        pen = QPen(self.color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for i in range(1, n):
            p.drawLine(_pt(i - 1), _pt(i))

        # Last-point dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self.color))
        p.drawEllipse(last, 4, 4)

        # X-axis caption
        p.setPen(QColor("#9e9e9e"))
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(QRect(PL, H - PB + 2, cw, PB - 2),
                   Qt.AlignmentFlag.AlignCenter,
                   f"← last {self.max_points} samples →")
        p.end()


# ── Battery bar widget ────────────────────────────────────────────────────────

class _BatteryBar(QWidget):
    """Compact visual battery indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level: int = 0
        self.charging: bool = False
        self.setFixedSize(130, 34)

    def set_state(self, level: int, charging: bool):
        self.level = max(0, min(100, level))
        self.charging = charging
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        body_w = W - 16
        body_h = H - 8
        bx, by = 0, 4

        p.setPen(QPen(QColor("#424242"), 2))
        p.setBrush(QBrush(QColor("#f5f5f5")))
        p.drawRoundedRect(bx, by, body_w, body_h, 4, 4)

        # Nub
        nub_h = 10
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#424242")))
        p.drawRoundedRect(body_w + 2, by + (body_h - nub_h) // 2, 8, nub_h, 2, 2)

        # Fill bar
        fill_w = max(0, int((body_w - 4) * self.level / 100))
        fill_color = (QColor("#4caf50") if self.level > 40
                      else QColor("#ff9800") if self.level > 20
                      else QColor("#f44336"))
        p.setBrush(QBrush(fill_color))
        p.drawRoundedRect(bx + 2, by + 2, fill_w, body_h - 4, 3, 3)

        # Text
        p.setPen(QColor("#212121"))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        icon = " ⚡" if self.charging else ""
        p.drawText(QRect(bx, by, body_w, body_h),
                   Qt.AlignmentFlag.AlignCenter, f"{self.level}%{icon}")
        p.end()


# ── Parsers (static helpers) ──────────────────────────────────────────────────

def _parse_size_to_mb(s: str) -> float:
    """Convert human-readable size string (e.g. '2.9G', '542M', '76K') to MB."""
    s = s.strip().upper()
    try:
        if s.endswith("G"):
            return float(s[:-1]) * 1024
        if s.endswith("M"):
            return float(s[:-1])
        if s.endswith("K"):
            return float(s[:-1]) / 1024
        return float(s)
    except ValueError:
        return 0.0


def parse_df(text: str) -> List[Tuple[str, float, float]]:
    """
    Parse 'df -h' output.
    Returns list of (mount_point, used_mb, total_mb) for real block devices.
    Skips tmpfs, overlay, devpts, etc.
    """
    results: List[Tuple[str, float, float]] = []
    seen_mounts: set[str] = set()
    for line in text.splitlines():
        # Skip header and blank lines
        if not line or line.startswith("Filesystem"):
            continue
        parts = line.split()
        # df -h: Filesystem Size Used Avail Use% Mounted
        if len(parts) < 6:
            continue
        fs, size_s, used_s, avail_s, _pct, mount = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        # Only real block devices
        if not fs.startswith("/dev/block"):
            continue
        # Deduplicate by mount point
        if mount in seen_mounts:
            continue
        seen_mounts.add(mount)
        total_mb = _parse_size_to_mb(size_s)
        used_mb  = _parse_size_to_mb(used_s)
        results.append((mount, used_mb, total_mb))
    return results


def parse_free(text: str) -> Tuple[int, int, int, int]:
    """
    Parse 'free -m' output.
    Returns (mem_used, mem_total, swap_used, swap_total) in MB.
    """
    mem_used = mem_total = swap_used = swap_total = 0
    for line in text.splitlines():
        low = line.lower()
        parts = line.split()
        if low.startswith("mem:") and len(parts) >= 3:
            mem_total = int(parts[1])
            mem_used  = int(parts[2])
        elif low.startswith("swap:") and len(parts) >= 3:
            swap_total = int(parts[1])
            swap_used  = int(parts[2])
    return mem_used, mem_total, swap_used, swap_total


def parse_top_cpu(text: str) -> Tuple[float, float, float]:
    """
    Parse 'top -n 1' output.
    Returns (user_pct, sys_pct, idle_pct).
    Handles 'Cpu(s): X.X us, X.X sy' and Android '800%cpu X%user X%sys X%idle' formats.
    """
    # Android multi-core format: "800%cpu 10%user 0%nice 6%sys 784%idle ..."
    m = re.search(r"(\d+\.?\d*)%user\s+\S+\s+(\d+\.?\d*)%sys\s+(\d+\.?\d*)%idle", text)
    if m:
        cores_m = re.search(r"(\d+)%cpu", text)
        cores = int(cores_m.group(1)) / 100 if cores_m else 1.0
        user  = float(m.group(1)) / cores
        sys_  = float(m.group(2)) / cores
        idle  = float(m.group(3)) / cores
        return user, sys_, idle
    # Linux format: "%Cpu(s): X.X us, X.X sy, ..."
    m2 = re.search(r"(\d+\.?\d*)\s*us[,\s]+(\d+\.?\d*)\s*sy", text, re.IGNORECASE)
    if m2:
        user = float(m2.group(1))
        sys_ = float(m2.group(2))
        idle = max(0.0, 100.0 - user - sys_)
        return user, sys_, idle
    return 0.0, 0.0, 100.0


# ── Background metrics worker ─────────────────────────────────────────────────

class _MetricsWorker(QThread):
    cpu_ready     = Signal(float)
    ram_ready     = Signal(int, int)     # used_mb, total_mb
    battery_ready = Signal(int, bool)    # level, charging
    error         = Signal(str)

    def __init__(self, serial: str):
        super().__init__()
        self.serial = serial

    def run(self):
        for fn in (self._fetch_cpu, self._fetch_ram, self._fetch_battery):
            try:
                fn()
            except Exception as e:
                self.error.emit(str(e))

    def _fetch_cpu(self):
        r = _adb(self.serial, "shell", "top", "-n", "1", "-b")
        text = r.stdout or ""
        user, sys_, idle = parse_top_cpu(text)
        total_active = user + sys_
        if total_active > 0:
            self.cpu_ready.emit(total_active)
            return
        # fallback: dumpsys cpuinfo
        r2 = _adb(self.serial, "shell", "dumpsys", "cpuinfo")
        m2 = re.search(r"(\d+)% TOTAL", r2.stdout or "")
        if m2:
            self.cpu_ready.emit(float(m2.group(1)))

    def _fetch_ram(self):
        r = _adb(self.serial, "shell", "free", "-m")
        mem_used, mem_total, _, _ = parse_free(r.stdout or "")
        if mem_total > 0:
            self.ram_ready.emit(mem_used, mem_total)

    def _fetch_battery(self):
        r = _adb(self.serial, "shell", "dumpsys", "battery")
        text = r.stdout or ""
        level = 0
        charging = False
        m = re.search(r"level:\s*(\d+)", text)
        if m:
            level = int(m.group(1))
        m2 = re.search(r"status:\s*(\d+)", text)
        if m2:
            charging = int(m2.group(1)) == 2
        self.battery_ready.emit(level, charging)


# ── Main Activities widget ────────────────────────────────────────────────────

class ActivitiesWidget(QWidget):
    status_update = Signal(str)

    def __init__(self):
        super().__init__()
        self.selected_serial: str | None = None
        self._init_ui()

    def set_selected_serial(self, serial: str):
        self.selected_serial = serial
        self._device_label.setText(
            f"Device: {serial}" if serial else "No device selected"
        )

    # ── UI builder ────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self._device_label = QLabel("No device selected")
        self._device_label.setStyleSheet(
            "font-weight: bold; color: #1565c0; font-size: 12px;"
        )
        root.addWidget(self._device_label)

        # ── 2-column layout: left = scrollable button groups, right = output console
        body_hl = QHBoxLayout()
        body_hl.setContentsMargins(0, 0, 0, 0)
        body_hl.setSpacing(8)

        # Left column — scrollable area that holds all button groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(340)
        inner = QWidget()
        ivl = QVBoxLayout(inner)
        ivl.setContentsMargins(0, 0, 4, 0)
        ivl.setSpacing(8)

        # ── Activity Analysis ─────────────────────────────────────────────
        act_group = QGroupBox("🔍 Activity Analysis")
        act_group.setStyleSheet(_GROUP_SS)
        act_grid = QGridLayout()
        act_grid.setContentsMargins(10, 10, 10, 10)
        act_grid.setSpacing(6)

        b_activities = _btn_primary("📱 Running Activities")
        b_activities.setToolTip("dumpsys activity activities")
        b_activities.clicked.connect(self.run_activities_dump)

        b_top = _btn_teal("🔝 Top Activity")
        b_top.setToolTip("dumpsys activity top")
        b_top.clicked.connect(self.run_activities_top)

        b_focus = _btn_warning("🎯 Current Focus")
        b_focus.setToolTip("dumpsys window | grep mCurrentFocus/mFocusedApp")
        b_focus.clicked.connect(self.run_current_focus)

        b_tasks = _btn_purple("📋 Task Stack")
        b_tasks.setToolTip("dumpsys activity tasks")
        b_tasks.clicked.connect(lambda: self._run_command("shell", "dumpsys", "activity", "tasks"))

        b_ps = _btn_secondary("🖥 Processes")
        b_ps.setToolTip("adb shell ps -A")
        b_ps.clicked.connect(self.run_ps)

        b_props = _btn_outline("📦 System Props")
        b_props.setToolTip("adb shell getprop")
        b_props.clicked.connect(lambda: self._run_command("shell", "getprop"))

        b_net = _btn_teal("🌐 Network")
        b_net.setToolTip("adb shell netstat")
        b_net.clicked.connect(lambda: self._run_command("shell", "netstat"))

        act_grid.addWidget(b_activities, 0, 0)
        act_grid.addWidget(b_top,        0, 1)
        act_grid.addWidget(b_focus,      0, 2)
        act_grid.addWidget(b_tasks,      1, 0)
        act_grid.addWidget(b_ps,         1, 1)
        act_grid.addWidget(b_props,      1, 2)
        act_grid.addWidget(b_net,        2, 0)
        act_group.setLayout(act_grid)
        ivl.addWidget(act_group)

        # ── Logging ───────────────────────────────────────────────────────
        log_group = QGroupBox("📋 Logging")
        log_group.setStyleSheet(_GROUP_SS)
        log_vl = QVBoxLayout()
        log_vl.setContentsMargins(10, 10, 10, 10)
        log_vl.setSpacing(8)

        logcat_row = QHBoxLayout()
        logcat_row.setSpacing(6)
        b_logcat    = _btn_primary("📝 Dump Logcat")
        b_dmesg     = _btn_secondary("🧬 Kernel Log")
        b_bugreport = _btn_warning("🐛 Bug Report")

        b_logcat.setToolTip("adb logcat -d")
        b_dmesg.setToolTip("adb shell dmesg")
        b_bugreport.setToolTip("adb bugreport — may take a moment")

        b_logcat.clicked.connect(self.run_logcat)
        b_dmesg.clicked.connect(self.run_dmesg)
        b_bugreport.clicked.connect(self.run_bugreport)

        logcat_row.addWidget(b_logcat)
        logcat_row.addWidget(b_dmesg)
        logcat_row.addWidget(b_bugreport)
        logcat_row.addStretch()
        log_vl.addLayout(logcat_row)

        grep_row = QHBoxLayout()
        grep_row.setSpacing(6)
        grep_lbl = QLabel("Filter by package:")
        grep_lbl.setStyleSheet(_LABEL_SS)
        grep_row.addWidget(grep_lbl)
        self.grep_input = QLineEdit()
        self.grep_input.setPlaceholderText("com.example.app")
        self.grep_input.setStyleSheet(_INPUT_SS)
        self.grep_input.returnPressed.connect(self.run_logcat_grep)
        grep_row.addWidget(self.grep_input, 1)
        b_grep = _btn_teal("🔍 Filter Logcat")
        b_grep.clicked.connect(self.run_logcat_grep)
        grep_row.addWidget(b_grep)
        log_vl.addLayout(grep_row)

        log_group.setLayout(log_vl)
        ivl.addWidget(log_group)

        # ── System Dump ─────────────────────────────────────────
        dump_group = QGroupBox("🗂 System Dump")
        dump_group.setStyleSheet(_GROUP_SS)
        dump_grid = QGridLayout()
        dump_grid.setContentsMargins(10, 10, 10, 10)
        dump_grid.setSpacing(6)

        dump_items = [
            (_btn_primary("📶 Battery"),        ("shell", "dumpsys", "battery")),
            (_btn_success("🌡 Thermal"),        ("shell", "dumpsys", "thermalservice")),
            (_btn_warning("📡 Connectivity"),   ("shell", "dumpsys", "connectivity")),
            (_btn_teal("🔊 Audio"),             ("shell", "dumpsys", "audio")),
            (_btn_secondary("📳 Input"),        ("shell", "dumpsys", "input")),
            (_btn_purple("🔋 BatteryStats"),    ("shell", "dumpsys", "batterystats")),
            (_btn_outline("📷 Camera"),         ("shell", "dumpsys", "media.camera")),
            (_btn_outline("📲 Telephony"),      ("shell", "dumpsys", "telephony.registry")),
            # ── new dumpsys shortcuts ────────────────────────────────────
            (_btn_primary("🏃 Activity Dump"),  ("shell", "dumpsys", "activity")),
            (_btn_warning("⚡ Power Dump"),     ("shell", "dumpsys", "power")),
            (_btn_teal("🖥 Window Dump"),       ("shell", "dumpsys", "window")),
            (_btn_success("🧠 Memory Dump"),    ("shell", "dumpsys", "meminfo")),
            (_btn_purple("📊 Usage Dump"),      ("shell", "dumpsys", "usagestats")),
            (_btn_secondary("📦 Package Dump"), ("shell", "dumpsys", "package")),
            (_btn_danger("🔔 Notification"),    ("shell", "dumpsys", "notification")),
            (_btn_outline("🌐 WiFi Dump"),      ("shell", "dumpsys", "wifi")),
        ]

        for idx, (btn, cmd) in enumerate(dump_items):
            btn.clicked.connect(lambda _=False, c=cmd: self._run_command(*c))
            dump_grid.addWidget(btn, idx // 3, idx % 3)

        dump_group.setLayout(dump_grid)
        ivl.addWidget(dump_group)

        # ── Output console (right column) ────────────────────────────────
        out_group = QGroupBox("🖥 Output Console")
        out_group.setStyleSheet(_GROUP_SS)
        out_vl = QVBoxLayout()
        out_vl.setContentsMargins(8, 8, 8, 8)
        out_vl.setSpacing(4)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setMinimumHeight(200)
        self.output_text.setStyleSheet(
            "QTextEdit {"
            "  background: #1e1e1e; color: #d4d4d4;"
            "  font-family: Consolas, 'Courier New', monospace;"
            "  font-size: 10px; border: none; border-radius: 4px;"
            "  padding: 6px 8px;"
            "}"
        )
        out_vl.addWidget(self.output_text, 1)

        out_btn_row = QHBoxLayout()
        out_btn_row.addStretch()
        copy_btn = _btn_secondary("📋 Copy")
        copy_btn.setFixedHeight(24)
        copy_btn.setToolTip("Copy all output text to clipboard")
        copy_btn.clicked.connect(self._copy_output)
        out_btn_row.addWidget(copy_btn)

        dl_btn = _btn_teal("💾 Download")
        dl_btn.setFixedHeight(24)
        dl_btn.setToolTip("Save output to a .txt file")
        dl_btn.clicked.connect(self._download_output)
        out_btn_row.addWidget(dl_btn)

        clear_out_btn = _btn_outline("🗑 Clear")
        clear_out_btn.setFixedHeight(24)
        clear_out_btn.clicked.connect(self.output_text.clear)
        out_btn_row.addWidget(clear_out_btn)
        out_vl.addLayout(out_btn_row)

        out_group.setLayout(out_vl)

        # ── Assemble 2-column body ────────────────────────────────────────
        ivl.addStretch()
        scroll.setWidget(inner)
        body_hl.addWidget(scroll, 3)       # left: scrollable groups (3 parts)
        body_hl.addWidget(out_group, 2)    # right: output console (2 parts)
        root.addLayout(body_hl, 1)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _run_command(self, *args: str):
        if not self.selected_serial:
            self.status_update.emit("❌ No device selected")
            return
        try:
            result = _adb(self.selected_serial, *args)
            output = result.stdout or result.stderr or "(no output)"
            self._append_output(" ".join(args), output)
            self.status_update.emit("✅ Command executed")
        except Exception as e:
            self.output_text.append(
                f'<span style="color:#f48771">Error: {e}</span><br>'
            )
            self.status_update.emit(f"❌ Error: {e}")

    # ── Command shortcuts ─────────────────────────────────────────────────

    def run_activities_dump(self):
        self._run_command("shell", "dumpsys", "activity", "activities")

    def run_activities_top(self):
        self._run_command("shell", "dumpsys", "activity", "top")

    def run_current_focus(self):
        if not self.selected_serial:
            self.status_update.emit("❌ No device selected")
            return
        try:
            r = _adb(self.selected_serial, "shell", "dumpsys", "window")
            lines = [ln for ln in (r.stdout or "").splitlines()
                     if "mCurrentFocus" in ln or "mFocusedApp" in ln]
            output = "\n".join(lines) or "(not found)"
            self.output_text.append(
                '<span style="color:#569cd6">$ dumpsys window | grep Focus</span><br>'
                f'<span style="color:#d4d4d4">{output}</span>'
                '<span style="color:#444">{"─"*60}</span><br>'
            )
            self.status_update.emit("✅ Command executed")
        except Exception as e:
            self.output_text.append(f'<span style="color:#f48771">Error: {e}</span><br>')
            self.status_update.emit(f"❌ Error: {e}")

    def run_bugreport(self):
        self.status_update.emit("⏳ Generating bug report…")
        self._run_command("bugreport")

    def run_logcat(self):
        self._run_command("logcat", "-d")

    def run_logcat_grep(self):
        app = self.grep_input.text().strip()
        if not app:
            self.status_update.emit("❌ Enter a package name to filter")
            return
        if not self.selected_serial:
            self.status_update.emit("❌ No device selected")
            return
        try:
            r = _adb(self.selected_serial, "logcat", "-d")
            lines = [ln for ln in (r.stdout or "").splitlines() if app in ln]
            output = "\n".join(lines) or f"(no entries matching '{app}')"
            self.output_text.append(
                f'<span style="color:#569cd6">$ logcat -d | grep {app}</span><br>'
                f'<span style="color:#d4d4d4">{output}</span>'
                '<span style="color:#444">{"─"*60}</span><br>'
            )
            self.status_update.emit("✅ Logcat filtered")
        except Exception as e:
            self.output_text.append(f'<span style="color:#f48771">Error: {e}</span><br>')
            self.status_update.emit(f"❌ Error: {e}")

    def run_dmesg(self):
        self._run_command("shell", "dmesg")

    def run_ps(self):
        self._run_command("shell", "ps", "-A")

    def run_free(self):
        """Run free -m and show output in the console."""
        if not self.selected_serial:
            self.status_update.emit("❌ No device selected")
            return
        try:
            r = _adb(self.selected_serial, "shell", "free", "-m")
            output = r.stdout or r.stderr or "(no output)"
            self._append_output("shell free -m", output)
            self.status_update.emit("✅ Memory fetched")
        except Exception as e:
            self.output_text.append(f'<span style="color:#f48771">Error: {e}</span><br>')
            self.status_update.emit(f"❌ Error: {e}")

    def run_top(self):
        """Run top -n 1 and show output in the console."""
        if not self.selected_serial:
            self.status_update.emit("❌ No device selected")
            return
        try:
            r = _adb(self.selected_serial, "shell", "top", "-n", "1")
            output = r.stdout or r.stderr or "(no output)"
            self._append_output("shell top -n 1", output)
            self.status_update.emit("✅ CPU info fetched")
        except Exception as e:
            self.output_text.append(f'<span style="color:#f48771">Error: {e}</span><br>')
            self.status_update.emit(f"❌ Error: {e}")

    def run_df(self):
        """Run df -h and show output in the console."""
        if not self.selected_serial:
            self.status_update.emit("❌ No device selected")
            return
        try:
            r = _adb(self.selected_serial, "shell", "df", "-h")
            output = r.stdout or r.stderr or "(no output)"
            self._append_output("shell df -h", output)
            self.status_update.emit("✅ Storage fetched")
        except Exception as e:
            self.output_text.append(f'<span style="color:#f48771">Error: {e}</span><br>')
            self.status_update.emit(f"❌ Error: {e}")

    # ── Output helpers ────────────────────────────────────────────────────

    def _append_output(self, cmd: str, text: str):
        """Append a command + its output to the console."""
        self.output_text.append(
            f'<span style="color:#569cd6">$ {cmd}</span><br>'
            f'<span style="color:#d4d4d4">{text}</span>'
            f'<span style="color:#444">{"─" * 60}</span><br>'
        )

    def _copy_output(self):
        """Copy plain text from output console to clipboard."""
        text = self.output_text.toPlainText()
        if text.strip():
            QApplication.clipboard().setText(text)
            self.status_update.emit("📋 Output copied to clipboard")
        else:
            self.status_update.emit("⚠️ Output is empty")

    def _download_output(self):
        """Save plain text from output console to a .txt file."""
        text = self.output_text.toPlainText()
        if not text.strip():
            self.status_update.emit("⚠️ Output is empty")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"activities_output_{ts}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Output", default_name,
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.status_update.emit(f"💾 Saved to {path}")
            except Exception as e:
                self.status_update.emit(f"❌ Save failed: {e}")
