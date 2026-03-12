from __future__ import annotations

import re, subprocess, os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QTabWidget, QTextEdit,
    QSplitter, QFrame, QComboBox, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont

# ── ADB bootstrap ─────────────────────────────────────────────────────────
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")


def _adb(serial: str, *args: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["adb", "-s", serial, *args],
            startupinfo=_si, capture_output=True, text=True, timeout=timeout,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _shell(serial: str, cmd: str, timeout: int = 20) -> str:
    return _adb(serial, "shell", cmd, timeout=timeout)


# ── Service category mapping ───────────────────────────────────────────────
# Each tuple: (display_name, color_hex, [keywords_that_belong_to_group])
_CATEGORIES: list[tuple[str, str, list[str]]] = [
    ("📞 Telephony / SIM", "#1a237e", [
        "phone", "isms", "imms", "iphonesubinfo", "isub", "sip",
        "telecom", "telephony", "carrier_config", "simphonebook",
    ]),
    ("🌐 Network / WiFi", "#006064", [
        "connectivity", "wifi", "wifip2p", "wifiaware", "wifiscanner",
        "ethernet", "netstats", "netpolicy", "netd", "dnsresolver",
        "network_management", "tethering", "vpn", "lowpan",
    ]),
    ("🖥 System UI", "#4a148c", [
        "statusbar", "window", "display", "SurfaceFlinger", "overlay",
        "uimode", "wallpaper", "recents", "dream", "notification",
    ]),
    ("🕹 Input / Interaction", "#bf360c", [
        "input", "inputflinger", "input_method", "accessibility",
        "gesture", "autofill", "textservices", "voice_interaction",
    ]),
    ("📱 App Lifecycle", "#1b5e20", [
        "activity", "activity_task", "package", "appops", "usagestats",
        "procstats", "shortcut", "content", "account", "user",
        "persistent_data_block", "cross_profile_apps",
    ]),
    ("🔋 Power / Battery", "#f57f17", [
        "power", "battery", "batterystats", "thermalservice",
        "deviceidle", "thermal", "hint",
    ]),
    ("🎵 Media / Audio / Camera", "#880e4f", [
        "audio", "media", "camera", "drm", "media_session",
        "midi", "soundtrigger", "ringtone",
    ]),
    ("📡 Sensors / Hardware", "#006064", [
        "sensorservice", "vibrator", "usb", "serial",
        "consumer_ir", "hardware", "nfc", "fingerprint",
        "face", "iris", "biometric",
    ]),
    ("🔐 Security", "#37474f", [
        "device_policy", "permission", "lock_settings", "keystore",
        "gatekeeper", "role", "credential", "attestation",
        "keychain", "security",
    ]),
    ("💾 Storage / Filesystem", "#4e342e", [
        "mount", "vold", "storaged", "installd",
        "blob_store", "file", "storage",
    ]),
    ("⏰ Jobs / Scheduling", "#827717", [
        "jobscheduler", "alarm", "scheduling_policy",
        "rollback", "time_detector", "timezone_detector",
    ]),
    ("🐛 Debug / Dev", "#263238", [
        "adb", "bugreport", "dropbox", "stats",
        "incident", "profiling", "graphicsstats",
    ]),
    ("🔷 LineageOS / Custom", "#0d47a1", [
        "lineage", "custom_tile", "performance", "trust",
        "livedisplay", "twierdza",
    ]),
]

def _categorize(name: str) -> int:
    """Return the index into _CATEGORIES for this service name, or -1 = Other."""
    lname = name.lower()
    for idx, (_, _, keywords) in enumerate(_CATEGORIES):
        for kw in keywords:
            if kw.lower() in lname:
                return idx
    return -1


def _parse_service_list(raw: str) -> list[tuple[str, str]]:
    """
    Parse output of `adb shell service list`.

    Each line looks like:
        42\tpackage: [android.content.pm.IPackageManager]
    or:
        42  package: [android.content.pm.IPackageManager]

    Returns list of (service_name, interface) tuples.
    """
    results: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        # skip header "Found N services:"
        if line.startswith("Found") or not line:
            continue
        # strip leading index
        m = re.match(r"^\d+[\t\s]+(.+)", line)
        if m:
            rest = m.group(1).strip()
        else:
            rest = line
        if ":" in rest:
            name, iface = rest.split(":", 1)
            name  = name.strip()
            iface = iface.strip().strip("[]")
        else:
            name  = rest.strip()
            iface = ""
        if name:
            results.append((name, iface))
    return results


# ── Styles ────────────────────────────────────────────────────────────────
_GROUP_SS = """
    QGroupBox {
        font-weight: bold;
        font-size: 12px;
        border: 1px solid #ddd;
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

_TABLE_SS = """
    QTableWidget {
        border: none;
        background: #ffffff;
        gridline-color: #e8eaf6;
        font-size: 11px;
    }
    QHeaderView::section {
        background-color: #e8eaf6;
        color: #1a237e;
        font-weight: bold;
        font-size: 11px;
        padding: 4px;
        border: none;
        border-bottom: 2px solid #9fa8da;
    }
    QTableWidget::item { padding: 3px 6px; }
    QTableWidget::item:hover { background: none}
    QTableWidget::item:selected { background: #c5cae9; color: #1a237e; }
"""

_BTN_PRIMARY = (
    "QPushButton { background-color: #1976d2; color: white; font-weight: bold;"
    " padding: 5px 14px; border-radius: 4px; font-size: 11px; border: none; }"
    "QPushButton:hover { background-color: #1565c0; }"
    "QPushButton:disabled { background-color: #90caf9; }"
)
_BTN_SECONDARY = (
    "QPushButton { background-color: #455a64; color: white; font-weight: bold;"
    " padding: 5px 14px; border-radius: 4px; font-size: 11px; border: none; }"
    "QPushButton:hover { background-color: #37474f; }"
)


# ── Worker thread ─────────────────────────────────────────────────────────
class _ServiceWorker(QThread):
    done = Signal(str, str)   # (service_list_raw, cmd_list_raw)
    error = Signal(str)

    def __init__(self, serial: str):
        super().__init__()
        self.serial = serial

    def run(self):
        try:
            svc_raw = _shell(self.serial, "service list", timeout=30)
            cmd_raw = _adb(self.serial, "shell", "cmd", "-l", timeout=15)
            self.done.emit(svc_raw, cmd_raw)
        except Exception as e:
            self.error.emit(str(e))

# ── Main widget ───────────────────────────────────────────────────────────
class ServicesWidget(QWidget):
    """Services tab — shows all running Binder services grouped by category."""

    status_update = Signal(str)

    # Built from _CATEGORIES + "Other"
    _CAT_NAMES: list[str] = [c[0] for c in _CATEGORIES] + ["🔧 Other"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._all_services: list[tuple[str, str]] = []  # (name, iface)
        self._worker: _ServiceWorker | None = None

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Header row ─────────────────────────────────────────────────
        hdr = QHBoxLayout()

        self._serial_lbl = QLabel("No device selected")
        self._serial_lbl.setStyleSheet(
            "font-size: 11px; color: #546e7a; font-style: italic;"
        )
        hdr.addWidget(self._serial_lbl, 1)

        self._refresh_btn = QPushButton("🔄 Refresh")
        self._refresh_btn.setStyleSheet(_BTN_PRIMARY)
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._load)
        hdr.addWidget(self._refresh_btn)

        root.addLayout(hdr)

        # ── Search bar ─────────────────────────────────────────────────
        search_row = QHBoxLayout()
        search_lbl = QLabel("🔍")
        search_row.addWidget(search_lbl)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter services…")
        self._search.setStyleSheet(
            "QLineEdit { border: 1px solid #ddd; border-radius: 4px;"
            " padding: 4px 8px; font-size: 11px; background: #fff; }"
            "QLineEdit:focus { border: 1px solid #1976d2; }"
        )
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search, 1)

        self._cat_combo = QComboBox()
        self._cat_combo.addItem("All categories")
        for name in self._CAT_NAMES:
            self._cat_combo.addItem(name)
        self._cat_combo.setStyleSheet(
            "QComboBox { border: 1px solid #ddd; border-radius: 4px;"
            " padding: 3px 8px; font-size: 11px; background: #fff; }"
            "QComboBox:focus { border: 1px solid #1976d2; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
        )
        self._cat_combo.currentIndexChanged.connect(self._apply_filter)
        search_row.addWidget(self._cat_combo)

        self._count_lbl = QLabel("0 services")
        self._count_lbl.setStyleSheet("font-size: 11px; color: #546e7a;")
        search_row.addWidget(self._count_lbl)

        root.addLayout(search_row)

        # ── Tab widget: Grouped view | Raw cmd list ────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                background: #ffffff;
            }
            QTabBar::tab {
                background: #e8eaf6;
                color: #1a237e;
                padding: 5px 14px;
                border-radius: 4px 4px 0 0;
                font-size: 11px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1976d2;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected { background: #c5cae9; }
        """)

        # ── Corner widget: selected-service call action ───────────────
        # Lives on the same row as the tab buttons (right side of tab bar)
        corner = QWidget()
        corner_lay = QHBoxLayout(corner)
        corner_lay.setContentsMargins(0, 0, 0, 0)
        corner_lay.setSpacing(6)

        self._call_name_lbl = QLabel("—")
        self._call_name_lbl.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #1a237e;"
        )
        corner_lay.addWidget(self._call_name_lbl)

        self._call_btn = QPushButton("📡 Call (code 1)")
        self._call_btn.setStyleSheet(_BTN_SECONDARY)
        self._call_btn.setFixedHeight(24)
        self._call_btn.setEnabled(False)
        self._call_btn.setToolTip("adb shell service call <name> 1")
        self._call_btn.clicked.connect(self._call_selected_service)
        corner_lay.addWidget(self._call_btn)

        self._tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        root.addWidget(self._tabs, 1)

        # ── Tab 1: Service table ───────────────────────────────────────
        svc_page = QWidget()
        svc_vl = QVBoxLayout(svc_page)
        svc_vl.setContentsMargins(0, 0, 0, 0)
        svc_vl.setSpacing(0)

        self._table = QTableWidget(0, 3)
        self._table.setStyleSheet(_TABLE_SS)
        self._table.setHorizontalHeaderLabels(["Service Name", "Category", "Interface"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        svc_vl.addWidget(self._table)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._tabs.addTab(svc_page, "📋 Binder Services")

        # ── Tab 2: cmd -l ─────────────────────────────────────────────
        cmd_page = QWidget()
        cmd_vl = QVBoxLayout(cmd_page)
        cmd_vl.setContentsMargins(4, 4, 4, 4)

        self._cmd_text = QTextEdit()
        self._cmd_text.setReadOnly(True)
        self._cmd_text.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4;"
            " font-family: Consolas, monospace; font-size: 11px;"
            " border: none; border-radius: 4px; padding: 6px 8px; }"
        )
        cmd_vl.addWidget(self._cmd_text, 1)
        self._tabs.addTab(cmd_page, "⌨️ cmd -l")

        # ── Status bar ─────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            "font-size: 10px; color: #888; padding: 2px 4px;"
        )
        root.addWidget(self._status_lbl)

    # ── Public API ────────────────────────────────────────────────────

    def set_device(self, serial: str):
        self._serial = serial
        if serial:
            self._serial_lbl.setText(f"Serial: {serial}")
        else:
            self._serial_lbl.setText("No device selected")

    def load_device(self, serial: str | None = None):
        if serial is not None:
            self.set_device(serial)
        self._load()

    # ── Load logic ────────────────────────────────────────────────────

    def _load(self):
        if not self._serial:
            self.status_update.emit("⚠️ No device selected for Services tab")
            return
        if self._worker and self._worker.isRunning():
            return

        self._refresh_btn.setEnabled(False)
        self._status_lbl.setText("Loading services…")
        self.status_update.emit(f"⏳ Loading services for {self._serial}…")

        self._worker = _ServiceWorker(self._serial)
        self._worker.done.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, svc_raw: str, cmd_raw: str):
        self._refresh_btn.setEnabled(True)

        # ── Parse & store ─────────────────────────────────────────────
        self._all_services = _parse_service_list(svc_raw)
        total = len(self._all_services)
        self._status_lbl.setText(f"Loaded {total} services")
        self.status_update.emit(f"✅ Found {total} services on {self._serial}")

        # ── Populate table ────────────────────────────────────────────
        self._populate_table(self._all_services)

        # ── cmd -l tab ────────────────────────────────────────────────
        if cmd_raw:
            self._cmd_text.setPlainText(cmd_raw)
        else:
            self._cmd_text.setPlainText("(no output — device may not support 'cmd -l')")

    def _on_error(self, msg: str):
        self._refresh_btn.setEnabled(True)
        self._status_lbl.setText(f"Error: {msg}")
        self.status_update.emit(f"❌ Services error: {msg}")

    # ── Table population ──────────────────────────────────────────────

    def _populate_table(self, services: list[tuple[str, str]]):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        for name, iface in services:
            cat_idx = _categorize(name)
            if cat_idx == -1:
                cat_name = "🔧 Other"
                cat_color = "#546e7a"
            else:
                cat_name  = _CATEGORIES[cat_idx][0]
                cat_color = _CATEGORIES[cat_idx][1]

            row = self._table.rowCount()
            self._table.insertRow(row)

            name_item = QTableWidgetItem(name)
            # name_item.setFont(QFont("Consolas", 10))

            cat_item  = QTableWidgetItem(cat_name)
            cat_item.setForeground(QColor(cat_color))
            # cat_item.setFont(QFont("Consolas", 8, QFont.Weight.Bold))

            iface_item = QTableWidgetItem(iface)
            iface_item.setForeground(QColor("#546e7a"))

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, cat_item)
            self._table.setItem(row, 2, iface_item)

        self._table.setSortingEnabled(True)
        self._count_lbl.setText(f"{len(services)} services")

    # ── Filter ────────────────────────────────────────────────────────

    def _apply_filter(self):
        query = self._search.text().strip().lower()
        cat_filter_idx = self._cat_combo.currentIndex()  # 0 = All

        if not self._all_services:
            return

        filtered: list[tuple[str, str]] = []
        for name, iface in self._all_services:
            # Category filter
            if cat_filter_idx > 0:
                # index 1…len(_CATEGORIES) → category; last = Other
                desired_cat = cat_filter_idx - 1
                if desired_cat < len(_CATEGORIES):
                    if _categorize(name) != desired_cat:
                        continue
                else:
                    # "Other" bucket
                    if _categorize(name) != -1:
                        continue

            # Text filter
            if query and query not in name.lower() and query not in iface.lower():
                continue

            filtered.append((name, iface))

        self._populate_table(filtered)

    # ── Selection / call service ──────────────────────────────────────

    def _on_selection_changed(self):
        rows = self._table.selectedItems()
        if rows:
            name = self._table.item(self._table.currentRow(), 0)
            if name:
                self._call_name_lbl.setText(name.text())
                self._call_btn.setEnabled(True)
                return
        self._call_name_lbl.setText("—")
        self._call_btn.setEnabled(False)

    def _call_selected_service(self):
        name = self._call_name_lbl.text()
        if not name or name == "—" or not self._serial:
            return
        try:
            out = _shell(self._serial, f"service call {name} 1", timeout=10)
            self.status_update.emit(f"📡 service call {name} 1 → {out[:80] if out else '(empty)'}")
        except Exception as e:
            self.status_update.emit(f"❌ service call failed: {e}")
