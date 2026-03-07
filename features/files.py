"""
Files tab — manage files between PC and Android device via ADB.
Supports:
  - Push file/folder from PC → device
  - Pull file/folder from device → PC
  - Browse device file system
"""
from __future__ import annotations

import os
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QProgressBar,
    QSplitter, QFrame, QTextEdit,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont

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
    " padding: 5px 14px; border-radius: 4px; font-size: 11px; }"
    "QPushButton:hover { background-color: #1565c0; }"
    "QPushButton:disabled { background-color: #90caf9; }"
)
_BTN_SUCCESS_SS = (
    "QPushButton { background-color: #388e3c; color: white; font-weight: bold;"
    " padding: 5px 14px; border-radius: 4px; font-size: 11px; }"
    "QPushButton:hover { background-color: #2e7d32; }"
    "QPushButton:disabled { background-color: #a5d6a7; }"
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
_LABEL_BOLD = "font-size: 11px; font-weight: bold; color: #444;"


# ── Background workers ────────────────────────────────────────────────────
class _FileTransferWorker(QThread):
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, serial: str, action: str,
                 src: str = "", dst: str = ""):
        super().__init__()
        self.serial = serial
        self.action = action   # "push" | "pull"
        self.src = src
        self.dst = dst

    def run(self):
        try:
            if self.action == "push":
                self.progress.emit(
                    f"📤 Pushing  {os.path.basename(self.src)}  →  {self.dst}  …"
                )
                r = subprocess.run(
                    ["adb", "-s", self.serial, "push", self.src, self.dst],
                    startupinfo=_si, capture_output=True, text=True, timeout=300,
                )
                out = (r.stdout + r.stderr).strip()
                if r.returncode == 0:
                    self.finished.emit(f"✅ Push complete\n{out}")
                else:
                    self.finished.emit(f"❌ Push failed\n{out}")

            elif self.action == "pull":
                self.progress.emit(
                    f"📥 Pulling  {self.src}  →  {os.path.basename(self.dst)}  …"
                )
                r = subprocess.run(
                    ["adb", "-s", self.serial, "pull", self.src, self.dst],
                    startupinfo=_si, capture_output=True, text=True, timeout=300,
                )
                out = (r.stdout + r.stderr).strip()
                if r.returncode == 0:
                    self.finished.emit(f"✅ Pull complete\n{out}")
                else:
                    self.finished.emit(f"❌ Pull failed\n{out}")
        except Exception as e:
            self.finished.emit(f"❌ Error: {e}")


class _BrowseWorker(QThread):
    result = Signal(list)   # list of (name, is_dir, size, date)
    error = Signal(str)

    def __init__(self, serial: str, path: str):
        super().__init__()
        self.serial = serial
        self.path = path

    def run(self):
        try:
            # Use ls -la for detailed listing
            raw = _shell(
                self.serial,
                f"ls -la '{self.path}' 2>/dev/null",
                timeout=15,
            )
            entries: list[tuple[str, bool, str, str]] = []
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("total"):
                    continue
                parts = line.split(None, 7)
                if len(parts) < 8:
                    # Short format fallback
                    name = parts[-1] if parts else ""
                    is_dir = line.startswith("d")
                    entries.append((name, is_dir, "", ""))
                    continue
                perm, _links, _user, _grp, size, date1, date2, name = (
                    parts[0], parts[1], parts[2], parts[3],
                    parts[4], parts[5], parts[6], parts[7],
                )
                is_dir = perm.startswith("d")
                # Handle symlinks: "name -> target"
                display_name = name.split(" -> ")[0].strip()
                date_str = f"{date1} {date2}"
                entries.append((display_name, is_dir, size, date_str))

            # Sort: dirs first, then files
            entries.sort(key=lambda x: (not x[1], x[0].lower()))
            self.result.emit(entries)
        except Exception as e:
            self.error.emit(str(e))


# ── Main widget ───────────────────────────────────────────────────────────
class FilesWidget(QWidget):
    """Tab page — transfer files between PC and Android device."""
    status_update = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: str = ""
        self._current_path: str = "/sdcard"
        self._transfer_worker: _FileTransferWorker | None = None
        self._browse_worker: _BrowseWorker | None = None
        self._build_ui()

    # ── public API ────────────────────────────────────────────────────────
    def set_device(self, serial: str):
        self._serial = serial
        lbl = f"Serial: {serial}" if serial else "No device selected"
        self._serial_label.setText(lbl)
        has = bool(serial)
        self._push_btn.setEnabled(has)
        self._pull_btn.setEnabled(has)
        self._browse_btn.setEnabled(has)
        self._go_btn.setEnabled(has)

    def load_device(self, serial: str):
        if not serial:
            return
        self._serial = serial
        self._serial_label.setText(f"Serial: {serial}")
        self._start_browse(self._current_path)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Header row
        hdr = QHBoxLayout()
        self._serial_label = QLabel("No device selected")
        self._serial_label.setStyleSheet(
            "font-weight: bold; color: #1565c0; font-size: 12px;"
        )
        hdr.addWidget(self._serial_label, 1)
        root.addLayout(hdr)

        # ── Section 1: Push PC → Device ───────────────────────────────
        push_group = QGroupBox("📤 Push  (PC → Device)")
        push_group.setStyleSheet(_GROUP_SS)
        push_vl = QVBoxLayout()
        push_vl.setContentsMargins(10, 8, 10, 10)
        push_vl.setSpacing(8)

        # Source (PC)
        row_src = QHBoxLayout()
        row_src.setSpacing(6)
        lbl_src = QLabel("📁 PC path:")
        lbl_src.setStyleSheet(_LABEL_BOLD)
        lbl_src.setFixedWidth(80)
        row_src.addWidget(lbl_src)
        self._push_src = QLineEdit()
        self._push_src.setPlaceholderText("Select file or folder on PC…")
        self._push_src.setStyleSheet(_INPUT_SS)
        row_src.addWidget(self._push_src, 1)
        browse_file_btn = QPushButton("📂 File")
        browse_file_btn.setStyleSheet(_BTN_SS)
        browse_file_btn.setFixedHeight(28)
        browse_file_btn.setToolTip("Browse for a file")
        browse_file_btn.clicked.connect(self._browse_pc_file)
        row_src.addWidget(browse_file_btn)
        browse_dir_btn = QPushButton("📂 Folder")
        browse_dir_btn.setStyleSheet(_BTN_SS)
        browse_dir_btn.setFixedHeight(28)
        browse_dir_btn.setToolTip("Browse for a folder")
        browse_dir_btn.clicked.connect(self._browse_pc_dir)
        row_src.addWidget(browse_dir_btn)
        push_vl.addLayout(row_src)

        # Destination (Device)
        row_dst = QHBoxLayout()
        row_dst.setSpacing(6)
        lbl_dst = QLabel("📱 Device path:")
        lbl_dst.setStyleSheet(_LABEL_BOLD)
        lbl_dst.setFixedWidth(80)
        row_dst.addWidget(lbl_dst)
        self._push_dst = QLineEdit("/sdcard/")
        self._push_dst.setStyleSheet(_INPUT_SS)
        self._push_dst.setToolTip("Destination path on the device, e.g. /sdcard/Download/")
        row_dst.addWidget(self._push_dst, 1)

        self._push_btn = QPushButton("⬆  Push")
        self._push_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._push_btn.setFixedHeight(30)
        self._push_btn.setEnabled(False)
        self._push_btn.setToolTip("adb push <pc_path> <device_path>")
        self._push_btn.clicked.connect(self._do_push)
        row_dst.addWidget(self._push_btn)
        push_vl.addLayout(row_dst)

        push_group.setLayout(push_vl)
        root.addWidget(push_group)

        # ── Section 2: Pull Device → PC ───────────────────────────────
        pull_group = QGroupBox("📥 Pull  (Device → PC)")
        pull_group.setStyleSheet(_GROUP_SS)
        pull_vl = QVBoxLayout()
        pull_vl.setContentsMargins(10, 8, 10, 10)
        pull_vl.setSpacing(8)

        # Source (Device)
        row_dsrc = QHBoxLayout()
        row_dsrc.setSpacing(6)
        lbl_dsrc = QLabel("📱 Device path:")
        lbl_dsrc.setStyleSheet(_LABEL_BOLD)
        lbl_dsrc.setFixedWidth(80)
        row_dsrc.addWidget(lbl_dsrc)
        self._pull_src = QLineEdit("/sdcard/")
        self._pull_src.setStyleSheet(_INPUT_SS)
        self._pull_src.setToolTip("Source path on the device, e.g. /sdcard/DCIM/photo.jpg")
        row_dsrc.addWidget(self._pull_src, 1)
        pull_vl.addLayout(row_dsrc)

        # Destination (PC)
        row_ddst = QHBoxLayout()
        row_ddst.setSpacing(6)
        lbl_ddst = QLabel("💻 Save to:")
        lbl_ddst.setStyleSheet(_LABEL_BOLD)
        lbl_ddst.setFixedWidth(80)
        row_ddst.addWidget(lbl_ddst)
        self._pull_dst = QLineEdit()
        self._pull_dst.setPlaceholderText("Select save folder on PC…")
        self._pull_dst.setStyleSheet(_INPUT_SS)
        row_ddst.addWidget(self._pull_dst, 1)
        browse_save_btn = QPushButton("📂 Browse")
        browse_save_btn.setStyleSheet(_BTN_SS)
        browse_save_btn.setFixedHeight(28)
        browse_save_btn.clicked.connect(self._browse_save_dir)
        row_ddst.addWidget(browse_save_btn)

        self._pull_btn = QPushButton("⬇  Pull")
        self._pull_btn.setStyleSheet(_BTN_SUCCESS_SS)
        self._pull_btn.setFixedHeight(30)
        self._pull_btn.setEnabled(False)
        self._pull_btn.setToolTip("adb pull <device_path> <pc_path>")
        self._pull_btn.clicked.connect(self._do_pull)
        row_ddst.addWidget(self._pull_btn)
        pull_vl.addLayout(row_ddst)

        pull_group.setLayout(pull_vl)
        root.addWidget(pull_group)

        # ── Section 3: Device File Browser ────────────────────────────
        browser_group = QGroupBox("🗂 Device File Browser")
        browser_group.setStyleSheet(_GROUP_SS)
        browser_vl = QVBoxLayout()
        browser_vl.setContentsMargins(10, 8, 10, 10)
        browser_vl.setSpacing(6)

        # Path navigation row
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)

        self._up_btn = QPushButton("⬆ Up")
        self._up_btn.setStyleSheet(_BTN_SS)
        self._up_btn.setFixedHeight(28)
        self._up_btn.setEnabled(False)
        self._up_btn.setToolTip("Go to parent directory")
        self._up_btn.clicked.connect(self._go_up)
        nav_row.addWidget(self._up_btn)

        self._path_input = QLineEdit(self._current_path)
        self._path_input.setStyleSheet(_INPUT_SS)
        self._path_input.setToolTip("Current device path")
        nav_row.addWidget(self._path_input, 1)

        self._go_btn = QPushButton("Go")
        self._go_btn.setStyleSheet(_BTN_PRIMARY_SS)
        self._go_btn.setFixedHeight(28)
        self._go_btn.setEnabled(False)
        self._go_btn.clicked.connect(lambda: self._start_browse(self._path_input.text().strip()))
        nav_row.addWidget(self._go_btn)

        self._browse_btn = QPushButton("🔄 Refresh")
        self._browse_btn.setStyleSheet(_BTN_SS)
        self._browse_btn.setFixedHeight(28)
        self._browse_btn.setEnabled(False)
        self._browse_btn.clicked.connect(lambda: self._start_browse(self._current_path))
        nav_row.addWidget(self._browse_btn)

        browser_vl.addLayout(nav_row)

        # Quick-access shortcuts
        shortcuts_row = QHBoxLayout()
        shortcuts_row.setSpacing(4)
        for label, path in [
            ("📁 /sdcard", "/sdcard"),
            ("📥 Downloads", "/sdcard/Download"),
            ("📷 DCIM", "/sdcard/DCIM"),
            ("📦 /data/app", "/data/app"),
            ("🗃 /data/data", "/data/data"),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(_BTN_SS)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #bbb; border-radius: 3px;"
                " padding: 2px 8px; background: #efefff; font-size: 10px; }"
                "QPushButton:hover { background: #d0d8ff; }"
            )
            _path = path  # capture
            btn.clicked.connect(lambda checked, p=_path: self._start_browse(p))
            shortcuts_row.addWidget(btn)
        shortcuts_row.addStretch()
        browser_vl.addLayout(shortcuts_row)

        # Progress bar
        self._browse_progress = QProgressBar()
        self._browse_progress.setRange(0, 0)
        self._browse_progress.setFixedHeight(3)
        self._browse_progress.setTextVisible(False)
        self._browse_progress.setStyleSheet(
            "QProgressBar { background: #f0f0f0; border-radius: 2px; border: none; }"
            "QProgressBar::chunk { background: #1976d2; border-radius: 2px; }"
        )
        self._browse_progress.hide()
        browser_vl.addWidget(self._browse_progress)

        # File table
        self._file_table = QTableWidget(0, 4)
        self._file_table.setHorizontalHeaderLabels(["Name", "Size", "Date", "Type"])
        self._file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._file_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._file_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._file_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._file_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._file_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._file_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._file_table.setAlternatingRowColors(True)
        self._file_table.verticalHeader().setDefaultSectionSize(20)
        self._file_table.verticalHeader().hide()
        self._file_table.setStyleSheet(
            "QTableWidget { font-size: 11px; border: 1px solid #ddd; border-radius: 4px; }"
            "QTableWidget::item:selected { background-color: #bbdefb; color: #000; }"
            "QHeaderView::section { background-color: #e8eaf6; font-weight: bold;"
            " padding: 3px; border: none; font-size: 11px; }"
        )
        self._file_table.doubleClicked.connect(self._on_file_double_clicked)
        self._file_table.itemSelectionChanged.connect(self._on_file_selection_changed)
        browser_vl.addWidget(self._file_table, 1)

        # Quick actions for selected file
        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)
        self._sel_label = QLabel("No item selected")
        self._sel_label.setStyleSheet("font-size: 11px; color: #666;")
        sel_row.addWidget(self._sel_label, 1)

        self._use_as_pull_src_btn = QPushButton("📥 Use as Pull source")
        self._use_as_pull_src_btn.setStyleSheet(_BTN_SS)
        self._use_as_pull_src_btn.setFixedHeight(26)
        self._use_as_pull_src_btn.setEnabled(False)
        self._use_as_pull_src_btn.setToolTip(
            "Copy the selected path to the Pull source field above"
        )
        self._use_as_pull_src_btn.clicked.connect(self._use_selected_as_pull_src)
        sel_row.addWidget(self._use_as_pull_src_btn)

        browser_vl.addLayout(sel_row)
        browser_group.setLayout(browser_vl)
        root.addWidget(browser_group, 1)

        # ── Transfer log ──────────────────────────────────────────────
        log_group = QGroupBox("📋 Transfer Log")
        log_group.setStyleSheet(_GROUP_SS)
        log_vl = QVBoxLayout()
        log_vl.setContentsMargins(8, 6, 8, 8)
        log_vl.setSpacing(4)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4;"
            " font-family: Consolas, monospace; font-size: 11px;"
            " border: none; border-radius: 6px; padding: 4px 6px; }"
        )
        log_vl.addWidget(self._log)

        clr_row = QHBoxLayout()
        clr_row.addStretch()
        clr_btn = QPushButton("🗑 Clear")
        clr_btn.setFixedHeight(22)
        clr_btn.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 1px 8px;"
            " border: 1px solid #bbb; border-radius: 3px; background: #f0f0f0; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        clr_btn.clicked.connect(self._log.clear)
        clr_row.addWidget(clr_btn)
        log_vl.addLayout(clr_row)

        log_group.setLayout(log_vl)
        root.addWidget(log_group)

    # ── Helpers ───────────────────────────────────────────────────────────
    def _log_msg(self, msg: str):
        self._log.append(msg)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )
        # Emit first line as status update
        self.status_update.emit(msg.split("\n")[0])

    def _browse_pc_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select file to push", "", "All files (*)"
        )
        if path:
            self._push_src.setText(path)

    def _browse_pc_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select folder to push"
        )
        if path:
            self._push_src.setText(path)

    def _browse_save_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select save folder on PC"
        )
        if path:
            self._pull_dst.setText(path)

    def _do_push(self):
        if not self._serial:
            return
        src = self._push_src.text().strip()
        dst = self._push_dst.text().strip()
        if not src:
            self._log_msg("⚠ Please select a file or folder to push.")
            return
        if not dst:
            self._log_msg("⚠ Please enter a destination path on the device.")
            return
        self._run_transfer("push", src, dst)

    def _do_pull(self):
        if not self._serial:
            return
        src = self._pull_src.text().strip()
        dst = self._pull_dst.text().strip()
        if not src:
            self._log_msg("⚠ Please enter a source path on the device.")
            return
        if not dst:
            self._log_msg("⚠ Please select a save folder on PC.")
            return
        self._run_transfer("pull", src, dst)

    def _run_transfer(self, action: str, src: str, dst: str):
        if self._transfer_worker and self._transfer_worker.isRunning():
            self._log_msg("⚠ A transfer is already in progress.")
            return
        self._push_btn.setEnabled(False)
        self._pull_btn.setEnabled(False)
        worker = _FileTransferWorker(self._serial, action, src, dst)
        worker.progress.connect(self._log_msg)
        worker.finished.connect(self._on_transfer_done)
        self._transfer_worker = worker
        worker.start()

    def _on_transfer_done(self, msg: str):
        self._log_msg(msg)
        has = bool(self._serial)
        self._push_btn.setEnabled(has)
        self._pull_btn.setEnabled(has)
        # Refresh browser if a pull updated the current path area
        self._start_browse(self._current_path)

    # ── Browser ───────────────────────────────────────────────────────────
    def _start_browse(self, path: str):
        if not self._serial or not path:
            return
        self._current_path = path
        self._path_input.setText(path)
        self._file_table.setRowCount(0)
        self._browse_progress.show()

        if self._browse_worker and self._browse_worker.isRunning():
            self._browse_worker.quit()
            self._browse_worker.wait(300)

        self._browse_worker = _BrowseWorker(self._serial, path)
        self._browse_worker.result.connect(self._on_browse_result)
        self._browse_worker.error.connect(self._on_browse_error)
        self._browse_worker.finished.connect(self._browse_progress.hide)
        self._browse_worker.start()

        # Enable the Up button unless we're at root
        self._up_btn.setEnabled(bool(self._serial) and path not in ("/", ""))

    def _on_browse_result(self, entries: list):
        self._file_table.setRowCount(len(entries))
        for row, (name, is_dir, size, date_str) in enumerate(entries):
            icon = "📁" if is_dir else "📄"
            name_item = QTableWidgetItem(f"{icon} {name}")
            size_item = QTableWidgetItem(size if not is_dir else "—")
            date_item = QTableWidgetItem(date_str)
            type_item = QTableWidgetItem("Dir" if is_dir else "File")

            if is_dir:
                name_item.setForeground(QColor("#1565c0"))
                font = QFont()
                font.setBold(True)
                name_item.setFont(font)

            for item in (name_item, size_item, date_item, type_item):
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
            self._file_table.setItem(row, 0, name_item)
            self._file_table.setItem(row, 1, size_item)
            self._file_table.setItem(row, 2, date_item)
            self._file_table.setItem(row, 3, type_item)

    def _on_browse_error(self, msg: str):
        self._log_msg(f"❌ Browse error: {msg}")

    def _on_file_double_clicked(self, index):
        """Double-click a directory to navigate into it."""
        row = index.row()
        type_item = self._file_table.item(row, 3)
        name_item = self._file_table.item(row, 0)
        if not type_item or not name_item:
            return
        if type_item.text() == "Dir":
            # Strip the icon prefix
            raw_name = name_item.text().lstrip("📁").strip()
            if raw_name in (".", ".."):
                if raw_name == "..":
                    self._go_up()
                return
            new_path = self._current_path.rstrip("/") + "/" + raw_name
            self._start_browse(new_path)

    def _go_up(self):
        parent = self._current_path.rstrip("/").rsplit("/", 1)[0]
        if not parent:
            parent = "/"
        self._start_browse(parent)

    def _on_file_selection_changed(self):
        rows = self._file_table.selectionModel().selectedRows()
        if not rows:
            self._sel_label.setText("No item selected")
            self._use_as_pull_src_btn.setEnabled(False)
            return
        row = rows[0].row()
        name_item = self._file_table.item(row, 0)
        raw_name = name_item.text().lstrip("📁📄").strip() if name_item else ""
        full_path = self._current_path.rstrip("/") + "/" + raw_name
        self._sel_label.setText(full_path)
        self._use_as_pull_src_btn.setEnabled(True)

    def _use_selected_as_pull_src(self):
        path = self._sel_label.text()
        if path and path != "No item selected":
            self._pull_src.setText(path)
