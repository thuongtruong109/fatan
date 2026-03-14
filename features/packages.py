"""
Application Manager tab — lists installed apps and provides
uninstall / clear data / reinstall / install-from-APK actions.
"""
from __future__ import annotations

import os
import subprocess
import re
import zipfile
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox,
    QComboBox, QCheckBox, QFrame, QSplitter,
    QProgressBar,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor

# ── ADB bootstrap ─────────────────────────────────────────────────────────
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

for _p in [r"C:\android-tools\platform-tools"]:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

def _adb(serial: str, *args: str, timeout: int = 30) -> str:
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
_BTN_SS = (
    "QPushButton { border: 1px solid #ccc; border-radius: 4px;"
    " padding: 5px 12px; background: #f0f0f0; font-size: 11px; }"
    "QPushButton:hover { background: #e0e0e0; }"
    "QPushButton:disabled { background: #f5f5f5; color: #aaa; }"
)
_BTN_PRIMARY_SS = (
    "QPushButton { background-color: #1976d2; color: white; font-weight: bold;"
    " padding: 4px 14px; border-radius: 4px; font-size: 11px; }"
    "QPushButton:hover { background-color: #1565c0; }"
    "QPushButton:disabled { background-color: #90caf9; }"
)
_BTN_DANGER_SS = (
    "QPushButton { background-color: #d32f2f; color: white; font-weight: bold;"
    " padding: 5px 12px; border-radius: 4px; font-size: 11px; }"
    "QPushButton:hover { background-color: #b71c1c; }"
    "QPushButton:disabled { background-color: #ef9a9a; }"
)
_BTN_WARN_SS = (
    "QPushButton { background-color: #f57c00; color: white; font-weight: bold;"
    " padding: 5px 12px; border-radius: 4px; font-size: 11px; }"
    "QPushButton:hover { background-color: #e65100; }"
    "QPushButton:disabled { background-color: #ffcc80; }"
)
_INPUT_SS = (
    "QLineEdit { border: 1px solid #ddd; border-radius: 4px; padding: 2px 6px;"
    " background: #ffffff; color: #212121; font-size: 11px; min-height: 20px; }"
    "QLineEdit:focus { border: 1px solid #1976d2; }"
)

# ── Background workers ────────────────────────────────────────────────────
class _ListAppsWorker(QThread):
    result = Signal(list)   # list of (package_name, is_system, apk_path)
    error  = Signal(str)

    def __init__(self, serial: str, show_system: bool = False):
        super().__init__()
        self.serial = serial
        self.show_system = show_system

    def run(self):
        try:
            # Get all packages with flags
            raw_all = _shell(self.serial,
                             "pm list packages -f 2>/dev/null || pm list packages",
                             timeout=30)
            raw_sys = _shell(self.serial,
                             "pm list packages -s 2>/dev/null",
                             timeout=20)

            sys_pkgs: set[str] = set()
            for line in raw_sys.splitlines():
                m = re.match(r"package:(.+)", line.strip())
                if m:
                    sys_pkgs.add(m.group(1).strip())

            apps: list[tuple[str, bool, str]] = []
            for line in raw_all.splitlines():
                # "package:/data/app/com.example-1/base.apk=com.example"
                # or "package:com.example"
                m = re.match(r"package:([^=]+=)?(.+)", line.strip())
                if not m:
                    continue
                apk_path = (m.group(1) or "").rstrip("=").strip()
                pkg = m.group(2).strip()
                if not pkg:
                    continue
                is_sys = pkg in sys_pkgs
                if not self.show_system and is_sys:
                    continue
                apps.append((pkg, is_sys, apk_path))

            apps.sort(key=lambda x: x[0].lower())
            self.result.emit(apps)
        except Exception as e:
            self.error.emit(str(e))

class _AppActionWorker(QThread):
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, serial: str | list[str], action: str, packages: list[str],
                 apk_path: str = "", reinstall: bool = False):
        super().__init__()
        if isinstance(serial, list):
            self.serials = [s for s in serial if s]
        else:
            self.serials = [serial] if serial else []
        self.serial = self.serials[0] if self.serials else ""
        self.action = action
        self.packages = packages
        self.apk_path = apk_path
        self.reinstall = reinstall

    def run(self):
        results = []
        if self.action == "install_apk":
            apk = self.apk_path
            ext = os.path.splitext(apk)[1].lower()
            targets = self.serials or ([self.serial] if self.serial else [])
            if not targets:
                self.finished.emit("❌ No selected device for APK install")
                return

            extracted = None
            tmp_dir = None
            if ext == ".xapk" or ext == ".apkm":
                tmp_dir = tempfile.mkdtemp(prefix="xapk_")
                try:
                    with zipfile.ZipFile(apk, "r") as z:
                        apk_files = [n for n in z.namelist() if n.endswith(".apk")]
                        if not apk_files:
                            self.finished.emit("❌ No APK files found inside XAPK archive")
                            return
                        z.extractall(tmp_dir, members=apk_files)
                        extracted = [os.path.join(tmp_dir, n) for n in apk_files]
                except zipfile.BadZipFile:
                    self.finished.emit("❌ Invalid XAPK file (not a valid ZIP archive)")
                    return
                except Exception as e:
                    self.finished.emit(f"❌ XAPK install error: {e}")
                    return

            flags = ["-r"] if self.reinstall else []
            for target in targets:
                self.progress.emit(f"📦 Installing {os.path.basename(apk)} on {target}…")
                if extracted is not None:
                    r = subprocess.run(
                        ["adb", "-s", target, "install-multiple"] + flags + extracted,
                        startupinfo=_si, capture_output=True, text=True, timeout=180,
                    )
                    out = (r.stdout + r.stderr).strip()
                    if "Success" in out:
                        results.append(f"✅ [{target}] Installed (XAPK) {os.path.basename(apk)}")
                    else:
                        results.append(f"❌ [{target}] Install failed: {out[:200]}")
                else:
                    r = subprocess.run(
                        ["adb", "-s", target, "install"] + flags + [apk],
                        startupinfo=_si, capture_output=True, text=True, timeout=120,
                    )
                    out = (r.stdout + r.stderr).strip()
                    if "Success" in out:
                        results.append(f"✅ [{target}] Installed {os.path.basename(apk)}")
                    else:
                        results.append(f"❌ [{target}] Install failed: {out[:200]}")

            if tmp_dir:
                import shutil as _shutil
                try:
                    _shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass
        else:
            for pkg in self.packages:
                try:
                    if self.action == "uninstall":
                        self.progress.emit(f"🗑 Uninstalling {pkg}…")
                        out = _adb(self.serial, "uninstall", pkg, timeout=30)
                        if "Success" in out:
                            results.append(f"✅ Uninstalled {pkg}")
                        else:
                            out2 = _shell(self.serial,
                                          f"pm uninstall --user 0 {pkg}", timeout=20)
                            if "Success" in out2:
                                results.append(f"✅ Uninstalled (user) {pkg}")
                            else:
                                results.append(f"❌ Failed to uninstall {pkg}: {out or out2}")
                    elif self.action == "clear":
                        self.progress.emit(f"🧹 Clearing data for {pkg}…")
                        out = _shell(self.serial, f"pm clear {pkg}", timeout=20)
                        if "Success" in out:
                            results.append(f"✅ Cleared data for {pkg}")
                        else:
                            results.append(f"❌ Failed to clear {pkg}: {out}")
                    elif self.action == "reinstall_apk":
                        # Pull APK from device and reinstall
                        self.progress.emit(f"🔄 Extracting APK for {pkg}…")
                        path_raw = _shell(self.serial,
                                          f"pm path {pkg}", timeout=10)
                        m = re.search(r"package:(.+)", path_raw)
                        if not m:
                            results.append(f"❌ Cannot find APK path for {pkg}")
                            continue
                        apk_device = m.group(1).strip()
                        local_tmp = os.path.join(os.environ.get("TEMP", "."),
                                                 f"{pkg}_tmp.apk")
                        subprocess.run(
                            ["adb", "-s", self.serial, "pull", apk_device, local_tmp],
                            startupinfo=_si, capture_output=True, timeout=60,
                        )
                        if not os.path.isfile(local_tmp):
                            results.append(f"❌ Could not pull APK for {pkg}")
                            continue
                        r2 = subprocess.run(
                            ["adb", "-s", self.serial, "install", "-r", local_tmp],
                            startupinfo=_si, capture_output=True, text=True, timeout=120,
                        )
                        try:
                            os.remove(local_tmp)
                        except Exception:
                            pass
                        out2 = (r2.stdout + r2.stderr).strip()
                        if "Success" in out2:
                            results.append(f"✅ Reinstalled {pkg}")
                        else:
                            results.append(f"❌ Reinstall failed for {pkg}: {out2[:200]}")
                    elif self.action == "force_stop":
                        self.progress.emit(f"⏹ Force stopping {pkg}…")
                        _shell(self.serial, f"am force-stop {pkg}")
                        results.append(f"✅ Force-stopped {pkg}")
                    elif self.action == "pull_apk":
                        self.progress.emit(f"📦 Pulling APK for {pkg}…")
                        path_raw = _shell(self.serial,
                                          f"pm path {pkg}", timeout=10)
                        m = re.search(r"package:(.+)", path_raw)
                        if not m:
                            results.append(f"❌ Cannot find APK path for {pkg}")
                            continue
                        apk_device = m.group(1).strip()
                        # Save alongside apk_path (passed via constructor) or fallback to Desktop
                        if self.apk_path:
                            save_dir = self.apk_path
                        else:
                            save_dir = os.path.join(
                                os.path.expanduser("~"), "Desktop"
                            )
                        os.makedirs(save_dir, exist_ok=True)
                        local_file = os.path.join(save_dir, f"{pkg}.apk")
                        self.progress.emit(
                            f"  ↳ {apk_device}  →  {local_file}"
                        )
                        r = subprocess.run(
                            ["adb", "-s", self.serial, "pull",
                             apk_device, local_file],
                            startupinfo=_si, capture_output=True,
                            text=True, timeout=120,
                        )
                        out = (r.stdout + r.stderr).strip()
                        if r.returncode == 0:
                            results.append(
                                f"✅ Pulled APK → {local_file}"
                            )
                        else:
                            results.append(
                                f"❌ Pull failed for {pkg}: {out[:200]}"
                            )
                except Exception as e:
                    results.append(f"❌ {pkg}: {e}")

        self.finished.emit("\n".join(results) if results else "Done (no packages selected)")


# ── Main widget ───────────────────────────────────────────────────────────
class PackageWidget(QWidget):
    """Tab page — manage applications on the selected device."""
    status_update = Signal(str)
    install_chrome_requested = Signal()   # emit to trigger Chrome install on all devices

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._get_install_serials_fn = None
        self._list_worker: _ListAppsWorker | None = None
        self._action_worker: _AppActionWorker | None = None
        self._all_apps: list[tuple[str, bool, str]] = []
        self._build_ui()

    # ── public API ────────────────────────────────────────────────────────
    def set_device(self, serial: str):
        self._serial = serial
        lbl = f"Serial: {serial}" if serial else "No device selected"
        self._serial_label.setText(lbl)
        has = bool(serial)
        self._refresh_btn.setEnabled(has)
        self._install_btn.setEnabled(has)
        self._uninstall_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)
        self._force_stop_btn.setEnabled(False)
        self._reinstall_btn.setEnabled(False)
        self._pull_apk_btn.setEnabled(False)
        if not has:
            self._app_table.setRowCount(0)

    def load_device(self, serial: str):
        if not serial:
            return
        self._serial = serial
        self._serial_label.setText(f"Serial: {serial}")
        self._start_list_apps()

    def set_install_serials_provider(self, fn):
        """Inject callback returning checkbox-selected serials for Install APK."""
        self._get_install_serials_fn = fn

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        self._serial_label = QLabel("No device selected")
        self._serial_label.setStyleSheet("font-weight: bold; color: #1565c0; font-size: 12px;")
        hdr.addWidget(self._serial_label, 1)

        self._show_system_cb = QCheckBox("Show system apps")
        self._show_system_cb.setStyleSheet("font-size: 11px;")
        self._show_system_cb.toggled.connect(self._on_filter_changed)
        hdr.addWidget(self._show_system_cb)

        self._refresh_btn = QPushButton("🔄 Refresh")
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.setStyleSheet(_BTN_SS)
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self._start_list_apps)
        hdr.addWidget(self._refresh_btn)
        root.addLayout(hdr)

        # Search
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        lbl_search = QLabel("🔍")
        lbl_search.setStyleSheet("font-size: 14px;")
        search_row.addWidget(lbl_search)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter by package name…")
        self._search_input.setStyleSheet(_INPUT_SS)
        self._search_input.textChanged.connect(self._on_filter_changed)
        search_row.addWidget(self._search_input, 1)

        self._pkg_count_lbl = QLabel("0 apps")
        self._pkg_count_lbl.setStyleSheet("font-size: 11px; color: #666;")
        search_row.addWidget(self._pkg_count_lbl)
        root.addLayout(search_row)

        # Progress bar (hidden normally)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { background: #f0f0f0; border-radius: 2px; border: none; }"
            "QProgressBar::chunk { background: #1976d2; border-radius: 2px; }"
        )
        self._progress.hide()
        root.addWidget(self._progress)

        # App table
        self._app_table = QTableWidget(0, 2)
        self._app_table.setHorizontalHeaderLabels(["Package Name", "APK Path"])
        self._app_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._app_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._app_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._app_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._app_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._app_table.setAlternatingRowColors(True)
        self._app_table.verticalHeader().setDefaultSectionSize(22)
        self._app_table.verticalHeader().hide()
        self._app_table.setStyleSheet(
            "QTableWidget { font-size: 11px; border: 1px solid #ddd; border-radius: 4px; }"
            "QTableWidget::item:selected { background-color: #bbdefb; color: #000; }"
            "QHeaderView::section { background-color: #e8eaf6; font-weight: bold;"
            " padding: 4px; border: none; font-size: 11px; }"
        )
        self._app_table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._app_table, 1)

        # Action buttons
        act_group = QGroupBox("⚙ Actions")
        act_group.setStyleSheet(_GROUP_SS)
        act_vl = QVBoxLayout()
        act_vl.setContentsMargins(10, 8, 10, 10)
        act_vl.setSpacing(8)

        # Row 1: package actions
        act_row1 = QHBoxLayout()
        act_row1.setSpacing(8)

        self._uninstall_btn = QPushButton("🗑 Uninstall")
        self._uninstall_btn.setStyleSheet(_BTN_DANGER_SS)
        self._uninstall_btn.setMinimumHeight(32)
        self._uninstall_btn.setEnabled(False)
        self._uninstall_btn.setToolTip("Uninstall selected app(s)")
        self._uninstall_btn.clicked.connect(lambda: self._confirm_action("uninstall"))
        act_row1.addWidget(self._uninstall_btn)

        self._clear_btn = QPushButton("🧹 Clear Data")
        self._clear_btn.setStyleSheet(_BTN_WARN_SS)
        self._clear_btn.setMinimumHeight(32)
        self._clear_btn.setEnabled(False)
        self._clear_btn.setToolTip("Clear app data/cache for selected app(s)")
        self._clear_btn.clicked.connect(lambda: self._confirm_action("clear"))
        act_row1.addWidget(self._clear_btn)

        self._force_stop_btn = QPushButton("⏹ Force Stop")
        self._force_stop_btn.setStyleSheet(_BTN_SS)
        self._force_stop_btn.setMinimumHeight(32)
        self._force_stop_btn.setEnabled(False)
        self._force_stop_btn.setToolTip("Force stop selected app(s)")
        self._force_stop_btn.clicked.connect(lambda: self._run_action("force_stop"))
        act_row1.addWidget(self._force_stop_btn)

        self._reinstall_btn = QPushButton("🔄 Reinstall (overwrite)")
        self._reinstall_btn.setStyleSheet(_BTN_SS)
        self._reinstall_btn.setMinimumHeight(32)
        self._reinstall_btn.setEnabled(False)
        self._reinstall_btn.setToolTip("Re-pull APK from device and reinstall (keeps data)")
        self._reinstall_btn.clicked.connect(lambda: self._run_action("reinstall_apk"))
        act_row1.addWidget(self._reinstall_btn)

        self._pull_apk_btn = QPushButton("⬇ Pull APK")
        self._pull_apk_btn.setStyleSheet(_BTN_SS)
        self._pull_apk_btn.setMinimumHeight(32)
        self._pull_apk_btn.setEnabled(False)
        self._pull_apk_btn.setToolTip(
            "Pull the selected app's APK from the device to a folder on PC\n"
            "adb pull /data/app/<pkg>/base.apk"
        )
        self._pull_apk_btn.clicked.connect(self._pull_apk_to_pc)
        act_row1.addWidget(self._pull_apk_btn)

        act_vl.addLayout(act_row1)

        # Row 2: install from APK
        act_row2 = QHBoxLayout()
        act_row2.setSpacing(8)

        lbl_apk = QLabel("📦 Install APK:")
        lbl_apk.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        act_row2.addWidget(lbl_apk)

        self._apk_path_input = QLineEdit()
        self._apk_path_input.setPlaceholderText("Select .apk, .apks or .xapk file…")
        self._apk_path_input.setStyleSheet(_INPUT_SS)
        self._apk_path_input.setReadOnly(True)
        act_row2.addWidget(self._apk_path_input, 1)

        browse_btn = QPushButton("📂 Browse")
        browse_btn.setStyleSheet(_BTN_SS)
        browse_btn.setFixedHeight(30)
        browse_btn.clicked.connect(self._browse_apk)
        act_row2.addWidget(browse_btn)

        self._overwrite_cb = QCheckBox("overwrite")
        self._overwrite_cb.setChecked(True)
        self._overwrite_cb.setStyleSheet("font-size: 11px;")
        act_row2.addWidget(self._overwrite_cb)

        self._install_btn = QPushButton("⬇ Install")
        self._install_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._install_btn.setFixedHeight(30)
        self._install_btn.setEnabled(False)
        self._install_btn.clicked.connect(self._install_apk)
        act_row2.addWidget(self._install_btn)

        act_vl.addLayout(act_row2)

        # Log area
        self._log_label = QLabel("")
        self._log_label.setWordWrap(True)
        self._log_label.setStyleSheet(
            "font-size: 11px; color: #333; background: #f9fbe7;"
            " border: 1px solid #ddd; border-radius: 4px; padding: 4px 6px;"
        )
        self._log_label.hide()
        act_vl.addWidget(self._log_label)

        act_group.setLayout(act_vl)
        root.addWidget(act_group)

    # ── Helpers ───────────────────────────────────────────────────────────
    def _start_list_apps(self):
        if not self._serial:
            return
        self._progress.show()
        self._refresh_btn.setEnabled(False)
        self._app_table.setRowCount(0)
        self._pkg_count_lbl.setText("Loading…")
        show_sys = self._show_system_cb.isChecked()

        if self._list_worker and self._list_worker.isRunning():
            self._list_worker.quit()
            self._list_worker.wait(500)

        self._list_worker = _ListAppsWorker(self._serial, show_system=show_sys)
        self._list_worker.result.connect(self._on_apps_loaded)
        self._list_worker.error.connect(self._on_list_error)
        self._list_worker.finished.connect(lambda: (
            self._progress.hide(),
            self._refresh_btn.setEnabled(True),
        ))
        self._list_worker.start()

    def _on_apps_loaded(self, apps: list[tuple[str, bool]]):
        self._all_apps = apps
        self._populate_table(apps)

    def _on_list_error(self, msg: str):
        self._pkg_count_lbl.setText("Error loading apps")
        self.status_update.emit(f"❌ {msg}")

    def _populate_table(self, apps: list[tuple[str, bool, str]]):
        query = self._search_input.text().strip().lower()
        filtered = [(p, s, a) for p, s, a in apps if not query or query in p.lower()]
        self._app_table.setRowCount(len(filtered))
        for row, (pkg, is_sys, apk_path) in enumerate(filtered):
            pkg_item = QTableWidgetItem(pkg)
            path_item = QTableWidgetItem(apk_path)
            if is_sys:
                pkg_item.setForeground(QColor("#9e9e9e"))
                path_item.setForeground(QColor("#9e9e9e"))
            for item in (pkg_item, path_item):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._app_table.setItem(row, 0, pkg_item)
            self._app_table.setItem(row, 1, path_item)
        self._pkg_count_lbl.setText(f"{len(filtered)} apps")
        self._update_action_btns()

    def _on_filter_changed(self):
        self._populate_table(self._all_apps)

    def _on_selection_changed(self):
        self._update_action_btns()

    def _update_action_btns(self):
        has_sel = bool(self._app_table.selectionModel().selectedRows())
        has_dev = bool(self._serial)
        self._uninstall_btn.setEnabled(has_sel and has_dev)
        self._clear_btn.setEnabled(has_sel and has_dev)
        self._force_stop_btn.setEnabled(has_sel and has_dev)
        self._reinstall_btn.setEnabled(has_sel and has_dev)
        self._pull_apk_btn.setEnabled(has_sel and has_dev)

    def _selected_packages(self) -> list[str]:
        rows = self._app_table.selectionModel().selectedRows()
        pkgs = []
        for idx in rows:
            item = self._app_table.item(idx.row(), 0)
            if item:
                pkgs.append(item.text())
        return pkgs

    def _browse_apk(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select APK file", "",
            "APK files (*.apk *.apks *.xapk *.apkm);;All files (*)"
        )
        if path:
            self._apk_path_input.setText(path)

    def _install_apk(self):
        targets = []
        if callable(self._get_install_serials_fn):
            try:
                targets = [s for s in (self._get_install_serials_fn() or []) if s]
            except Exception:
                targets = []
        if not targets and self._serial:
            targets = [self._serial]
        if not targets:
            QMessageBox.warning(self, "No Device", "Please select at least one device by checkbox.")
            return

        apk = self._apk_path_input.text().strip()
        if not apk or not os.path.isfile(apk):
            QMessageBox.warning(self, "No APK", "Please select a valid APK file first.")
            return

        reinstall = self._overwrite_cb.isChecked()
        if len(targets) > 1:
            reply = QMessageBox.question(
                self,
                "Install APK",
                f"Install on {len(targets)} selected devices?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._run_action_worker(
            _AppActionWorker(targets, "install_apk", [], apk_path=apk,
                             reinstall=reinstall)
        )

    def _confirm_action(self, action: str):
        pkgs = self._selected_packages()
        if not pkgs:
            return
        names = {
            "uninstall": ("Uninstall", f"Uninstall {len(pkgs)} app(s)?"),
            "clear": ("Clear Data", f"Clear data for {len(pkgs)} app(s)?"),
        }
        title, msg = names.get(action, ("Confirm", "Proceed?"))
        if len(pkgs) > 0:
            reply = QMessageBox.question(
                self, title,
                f"{msg}\n\n" + "\n".join(pkgs[:10]) + ("\n…" if len(pkgs) > 10 else ""),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._run_action(action)

    def _pull_apk_to_pc(self):
        """Ask user for a save folder then pull the selected app's APK to PC."""
        pkgs = self._selected_packages()
        if not pkgs:
            return
        save_dir = QFileDialog.getExistingDirectory(
            self, "Select folder to save APK(s)"
        )
        if not save_dir:
            return
        # Reuse the generic worker with apk_path = save_dir
        worker = _AppActionWorker(
            self._serial, "pull_apk", pkgs, apk_path=save_dir
        )
        self._run_action_worker(worker)

    def _run_action(self, action: str):
        pkgs = self._selected_packages()
        if not pkgs and action not in ("install_apk",):
            return
        worker = _AppActionWorker(self._serial, action, pkgs)
        self._run_action_worker(worker)

    def _run_action_worker(self, worker: _AppActionWorker):
        if self._action_worker and self._action_worker.isRunning():
            self.status_update.emit("⚠ Another operation is already running.")
            return
        self._set_actions_enabled(False)
        self._log_label.setStyleSheet(
            "font-size: 11px; color: #555; background: #f9fbe7;"
            " border: 1px solid #ddd; border-radius: 4px; padding: 4px 6px;"
        )
        self._log_label.setText("⏳ Working…")
        self._log_label.show()

        worker.progress.connect(self.status_update)
        worker.progress.connect(lambda m: self._log_label.setText(m))
        worker.finished.connect(self._on_action_done)
        self._action_worker = worker
        worker.start()

    def _on_action_done(self, msg: str):
        self._set_actions_enabled(True)
        self._update_action_btns()
        first_line = msg.split("\n")[0]
        ok = first_line.startswith("✅")
        self._log_label.setStyleSheet(
            f"font-size: 11px; color: {'#2e7d32' if ok else '#c62828'};"
            " background: #f9fbe7; border: 1px solid #ddd;"
            " border-radius: 4px; padding: 4px 6px;"
        )
        self._log_label.setText(msg)
        self.status_update.emit(first_line)
        # If uninstalled successfully, refresh list
        if "✅ Uninstalled" in msg or "✅ Installed" in msg or "✅ Reinstalled" in msg:
            QTimer.singleShot(800, self._start_list_apps)

    def _set_actions_enabled(self, enabled: bool):
        for btn in (self._uninstall_btn, self._clear_btn, self._reinstall_btn,
                    self._force_stop_btn, self._install_btn, self._refresh_btn,
                    self._pull_apk_btn):
            btn.setEnabled(enabled)
