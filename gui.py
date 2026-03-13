import sys, os, subprocess, shutil, json, time, ctypes, threading
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QHBoxLayout,
    QStackedWidget, QLabel, QLineEdit, QTextEdit, QGroupBox, QComboBox,
    QSpinBox, QDialog, QDialogButtonBox, QFormLayout, QScrollArea,
)
from PySide6.QtCore import QTimer, QThread, Signal, Qt, QPoint, QEvent
from PySide6.QtGui import QIcon, QCloseEvent, QCursor

_ANDROID_TOOLS_PATHS = [
    r"C:\android-tools\platform-tools",
    r"C:\android-tools\scrcpy-win64-v3.3.4",
]
for _p in _ANDROID_TOOLS_PATHS:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
from helpers.csv import CSVHelper
from utils.adb import setup_adb_keyboard
from features.chrome import install_chrome, install_gmail, install_socksdroid, open_url_in_chrome
from features.ads import run_ads_automation
from features.ads import AdsTableWidget
from features.settings import SettingsWidget
from features.proxy import ProxyWidget
from features.dashboard import DashboardWidget
from features.actions import ActionsWidget
from features.packages import PackageWidget
from features.files import FilesWidget
from features.activities import ActivitiesWidget
from features.toolbox import ToolboxWidget
from features.titlebar import TitleBar
from features.services import ServicesWidget

class Worker(QThread):
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, task_type, table_data=None, settings=None):
        super().__init__()
        self.task_type = task_type
        self.table_data = table_data
        self.settings = settings or {}
        self._stop_flag = False
        self._stop_event = threading.Event()
        # Optional callable: () -> dict, used when behavior_mode == "randomly_different"
        self._human_settings_fn = self.settings.pop("human_settings_fn", None)

    def stop(self):
        self._stop_flag = True
        self._stop_event.set()

    def run(self):
        try:
            if self.task_type == "setup_keyboard":
                self.setup_keyboard_for_all()
            elif self.task_type == "install_chrome":
                self.install_chrome_for_all()
            elif self.task_type == "install_gmail":
                self.install_gmail_for_all()
            elif self.task_type == "install_socksdroid":
                self.install_socksdroid_for_all()
            elif self.task_type == "run_ads":
                self.run_ads_for_all()
        except Exception as e:
            self.finished.emit(f'Error: {str(e)}')

    def setup_keyboard_for_all(self):
        row_count = len(self.table_data)
        if row_count == 0:
            self.finished.emit('No devices found in table')
            return

        successful_devices = 0
        for row in range(row_count):
            serial = self.table_data[row].get('serial', '')

            if serial:
                try:
                    self.progress.emit(f'Setting up keyboard for: {serial}')
                    setup_adb_keyboard(serial)
                    successful_devices += 1
                    self.progress.emit(f'✅ Setup keyboard for device: {serial}')
                except Exception as e:
                    self.progress.emit(f'❌ Error setting up keyboard for device {serial}: {str(e)}')

        self.finished.emit(f'Successfully setup keyboard for {successful_devices} out of {row_count} devices')

    def install_chrome_for_all(self):
        row_count = len(self.table_data)
        if row_count == 0:
            self.finished.emit('No devices found in table')
            return

        successful_devices = 0
        for row in range(row_count):
            serial = self.table_data[row].get('serial', '')

            if serial:
                try:
                    self.progress.emit(f'Installing Chrome for: {serial}')
                    install_chrome(serial)
                    successful_devices += 1
                    self.progress.emit(f'✅ Installed Chrome for device: {serial}')
                except Exception as e:
                    self.progress.emit(f'❌ Error installing Chrome for device {serial}: {str(e)}')

        self.finished.emit(f'Successfully installed Chrome for {successful_devices} out of {row_count} devices')

    def install_socksdroid_for_all(self):
        row_count = len(self.table_data)
        if row_count == 0:
            self.finished.emit('No devices found in table')
            return

        successful_devices = 0
        for row in range(row_count):
            serial = self.table_data[row].get('serial', '')

            if serial:
                try:
                    self.progress.emit(f'Installing SocksDroid for: {serial}')
                    install_socksdroid(serial)
                    successful_devices += 1
                    self.progress.emit(f'✅ Installed SocksDroid for device: {serial}')
                except Exception as e:
                    self.progress.emit(f'❌ Error installing SocksDroid for device {serial}: {str(e)}')

        self.finished.emit(f'Successfully installed SocksDroid for {successful_devices} out of {row_count} devices')

    def install_gmail_for_all(self):
        row_count = len(self.table_data)
        if row_count == 0:
            self.finished.emit('No devices found in table')
            return

        successful_devices = 0
        for row in range(row_count):
            serial = self.table_data[row].get('serial', '')

            if serial:
                try:
                    self.progress.emit(f'Installing Gmail for: {serial}')
                    install_gmail(serial)
                    successful_devices += 1
                    self.progress.emit(f'✅ Installed Gmail for device: {serial}')
                except Exception as e:
                    self.progress.emit(f'❌ Error installing Gmail for device {serial}: {str(e)}')

        self.finished.emit(f'Successfully installed Gmail for {successful_devices} out of {row_count} devices')

    def run_ads_for_all(self):
        row_count = len(self.table_data)
        if row_count == 0:
            self.finished.emit('No devices found in table')
            return

        ads_links = self.settings.get("ads_links", {})
        if not ads_links:
            self.finished.emit('⚠️ No Ads Links provided')
            return

        repeat_count = max(1, self.settings.get("repeat_count", 1))
        successful_devices = 0
        total_runs = 0

        for iteration in range(1, repeat_count + 1):
            if self._stop_flag:
                self.finished.emit(
                    f'⏹ Stopped at iteration {iteration}/{repeat_count} '
                    f'— {successful_devices}/{total_runs} runs completed'
                )
                return

            if repeat_count > 1:
                self.progress.emit(f'🔁 Iteration {iteration}/{repeat_count}')

            for idx, row in enumerate(self.table_data):
                if self._stop_flag:
                    self.finished.emit(
                        f'⏹ Stopped — {successful_devices}/{total_runs} runs completed'
                    )
                    return

                serial = row.get('serial', '')
                if not serial:
                    continue

                ads_link = ads_links.get(serial, "")
                if not ads_link:
                    self.progress.emit(f'⚠️ No ads link for device {serial}, skipping')
                    continue

                # Resolve human settings: fixed or freshly randomized per device
                if self._human_settings_fn is not None:
                    human = self._human_settings_fn()
                    self.progress.emit(
                        f'🎲 Randomized behavior for {serial} — '
                        f'duration={human.get("min_duration", "?"):.0f}s  '
                        f'profile={human.get("profile") or "auto"}'
                    )
                else:
                    human = self.settings.get("human", {})

                try:
                    self.progress.emit(f'🤖 Running ads automation on: {serial} → {ads_link}')
                    result = run_ads_automation(
                        serial, ads_link,
                        human_settings=human,
                        stop_event=self._stop_event,
                    )
                    title = result.get('title', '') if isinstance(result, dict) else str(result)
                    domain = result.get('domain', '') if isinstance(result, dict) else ''
                    ads_info = f"{title} | {domain}" if domain else title
                    successful_devices += 1
                    self.progress.emit(f'✅ Done on {serial} — {ads_info}')
                except Exception as e:
                    self.progress.emit(f'❌ Error on device {serial}: {str(e)}')
                finally:
                    total_runs += 1

        self.finished.emit(
            f'Ads automation done: {successful_devices}/{total_runs} runs '
            f'({repeat_count} iteration{"s" if repeat_count > 1 else ""}, {row_count} device{"s" if row_count > 1 else ""})'
        )

# ── Screen toggle worker (on/off for all devices) ────────────────────────────
class ScreenToggleWorker(QThread):
    """Toggle screen on or off for a list of devices in a background thread."""
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, serials: list, action: str):
        super().__init__()
        self.serials = serials          # list of adb serial strings
        self.action  = action           # "on" | "off"

    def _screen_is_on(self, serial: str) -> bool | None:
        try:
            out = subprocess.check_output(
                ["adb", "-s", serial, "shell", "dumpsys", "power"],
                text=True, stderr=subprocess.DEVNULL, startupinfo=_si,
                timeout=10,
            )
            return "mWakefulness=Awake" in out or "mHoldingWakeLockSuspendBlocker=true" in out
        except Exception:
            return None

    def run(self):
        label   = "ON" if self.action == "on" else "OFF"
        icon    = "💡" if self.action == "on" else "🌙"
        success = 0
        for serial in self.serials:
            try:
                is_on = self._screen_is_on(serial)
                # Only send keyevent when state differs from desired
                if (self.action == "on" and not is_on) or (self.action == "off" and is_on):
                    subprocess.run(
                        ["adb", "-s", serial, "shell", "input", "keyevent", "26"],
                        check=True, stderr=subprocess.DEVNULL, startupinfo=_si,
                        timeout=10,
                    )
                success += 1
                self.progress.emit(f'✅ Screen {label}: {serial}')
            except Exception as e:
                self.progress.emit(f'❌ Error screen {label} {serial}: {str(e)}')
        self.finished.emit(f'Screen {label} done: {success}/{len(self.serials)} devices')

# ── Generic single adb command worker ────────────────────────────────────────
class AdbCommandWorker(QThread):
    """Run one adb command in a background thread and emit stdout."""
    result = Signal(str)   # stripped stdout on success
    error  = Signal(str)   # error message on failure

    def __init__(self, serial: str, *args: str, timeout: int = 10):
        super().__init__()
        self.serial  = serial
        self.args    = args
        self.timeout = timeout

    def run(self):
        try:
            r = subprocess.run(
                ["adb", "-s", self.serial, *self.args],
                startupinfo=_si,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            self.result.emit((r.stdout or "").strip())
        except Exception as e:
            self.error.emit(str(e))

class CookieLoaderGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.app_name = "Fatan"
        self.icon = "data/icon.png"
        self.data_csv = "data/data.csv"
        self.settings_file = "data/settings.json"

        self.status_timer = QTimer()
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(self.reset_window_title)

        self.worker = None
        self.current_active_tab = None  # Track currently active tab button

        self.initUI()

    @property
    def preview_width(self) -> int:
        return self.settings_widget.get("preview_width", 300)

    @property
    def preview_height(self) -> int:
        return self.settings_widget.get("preview_height", 600)

    def initUI(self):
        self.setWindowTitle(self.app_name)
        self.setGeometry(300, 100, 940, 600)
        self.setFixedHeight(600)
        self.setWindowIcon(QIcon(self.icon))
        # Remove OS title bar – we draw our own
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ── Outer wrapper: title bar on top, content below ───────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Rounded frame container — gives the whole window rounded corners
        self._frame = QWidget(self)
        self._frame.setObjectName("AppFrame")
        self._frame.setStyleSheet(
            "QWidget#AppFrame {"
            "  background-color: #f4f6fc;"
            "  border-radius: 10px;"
            "  border: 1px solid #c5cae9;"
            "}"
        )
        frame_vl = QVBoxLayout(self._frame)
        frame_vl.setContentsMargins(0, 0, 0, 0)
        frame_vl.setSpacing(0)
        outer.addWidget(self._frame)

        self.title_bar = TitleBar(self, title=self.app_name, icon_path=self.icon)
        self.title_bar.setStyleSheet(
            self.title_bar.styleSheet() +
            "QWidget#TitleBar { border-top-left-radius: 10px; border-top-right-radius: 10px; }"
        )
        self.title_bar.menu_settings_clicked.connect(lambda: self._open_tab(2))
        self.title_bar.menu_help_clicked.connect(self._show_help)
        # menu_about_clicked is handled internally by TitleBar (opens AboutDialog)
        frame_vl.addWidget(self.title_bar)

        # Content widget holds the original horizontal layout
        content_widget = QWidget()
        content_widget.setObjectName("ContentWidget")
        content_widget.setStyleSheet(
            "#ContentWidget { background-color: #f4f6fc; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; }"
        )
        layout = QHBoxLayout(content_widget)
        layout.setSpacing(0)

        # Create widgets that are always needed
        self.ads_table = AdsTableWidget(self.data_csv)
        self.ads_table.status_update.connect(self.update_status)

        self.settings_widget = SettingsWidget(self.settings_file)
        self.settings_widget.settings_saved.connect(
            lambda _: self.update_status("✅ Settings saved")
        )
        self.settings_widget._get_serials_fn = self._collect_serials

        self.proxy_widget = ProxyWidget()
        self.proxy_widget.status_update.connect(self.update_status)
        self.proxy_widget.proxy_status_updated.connect(self.ads_table.update_proxy_statuses)

        self.info_widget = DashboardWidget()
        self.info_widget.status_update.connect(self.update_status)
        self.actions_widget = ActionsWidget()
        self.actions_widget.status_update.connect(self.update_status)
        self.apps_widget = PackageWidget()
        self.apps_widget.status_update.connect(self.update_status)
        self.apps_widget.install_chrome_requested.connect(self.install_chrome_for_all)
        self.apps_widget.set_install_serials_provider(self._collect_serials)
        self.files_widget = FilesWidget()
        self.files_widget.status_update.connect(self.update_status)

        self.activities_widget = ActivitiesWidget()
        self.activities_widget.status_update.connect(self.update_status)

        self.toolbox_widget = ToolboxWidget()
        self.toolbox_widget.status_update.connect(self.update_status)
        self.toolbox_widget.setup_keyboard_requested.connect(self.setup_keyboard_for_all)
        self.toolbox_widget.install_chrome_requested.connect(self.install_chrome_for_all)
        self.toolbox_widget.install_gmail_requested.connect(self.install_gmail_for_all)
        self.toolbox_widget.install_socksdroid_requested.connect(self.install_socksdroid_for_all)
        self.toolbox_widget._get_serials_fn = self._collect_serials

        self.services_widget = ServicesWidget()
        self.services_widget.status_update.connect(self.update_status)


        # ── Left navigation panel ────────────────────────────────────────
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_panel.setLayout(left_layout)

        _NAV_BTN_STYLE = (
            "QPushButton {"
            "  text-align: left;"
            "  padding: 6px 10px;"
            "  border-radius: 4px;"
            "  border: none;"
            "  background: transparent;"
            "}"
            "QPushButton:hover, QPushButton:checked {"
            "  background-color: #e8eaf6;"
            "}"
            "QPushButton:pressed { background-color: #c5cae9; }"
        )

        def _nav_btn(label: str) -> QPushButton:
            btn = QPushButton(label)
            btn.setStyleSheet(_NAV_BTN_STYLE)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)  # Make buttons checkable for active state
            return btn

        self.load_devices_button = _nav_btn('🔃 Load devices')
        self.load_devices_button.clicked.connect(self.ads_table.refresh_devices_and_csv)
        left_layout.addWidget(self.load_devices_button)

        self.screen_on_button = _nav_btn('💡 Screen ON')
        self.screen_on_button.clicked.connect(self.turn_screen_on_all)
        left_layout.addWidget(self.screen_on_button)

        self.screen_off_button = _nav_btn('🌙 Screen OFF')
        self.screen_off_button.clicked.connect(self.turn_screen_off_all)
        left_layout.addWidget(self.screen_off_button)

        self.remote_button = _nav_btn('📱 Remote')
        self.remote_button.setToolTip('Open scrcpy screen preview for selected device (or all if none selected)')
        self.remote_button.clicked.connect(self.open_remote)
        left_layout.addWidget(self.remote_button)

        left_layout.addStretch()

        self.dashboard_button = _nav_btn('ℹ️ Dashboard')
        self.dashboard_button.clicked.connect(lambda: self._open_tab(3))
        left_layout.addWidget(self.dashboard_button)

        self.actions_button = _nav_btn('⚡ Actions')
        self.actions_button.clicked.connect(lambda: self._open_tab(4))
        left_layout.addWidget(self.actions_button)

        self.pkgs_button = _nav_btn('📦 Packages')
        self.pkgs_button.clicked.connect(lambda: self._open_tab(5))
        left_layout.addWidget(self.pkgs_button)

        self.files_button = _nav_btn('📁 Files')
        self.files_button.clicked.connect(lambda: self._open_tab(6))
        left_layout.addWidget(self.files_button)

        self.activities_button = _nav_btn('📊 Activities')
        self.activities_button.clicked.connect(lambda: self._open_tab(7))
        left_layout.addWidget(self.activities_button)

        self.toolbox_button = _nav_btn('🛠 Toolbox')
        self.toolbox_button.clicked.connect(lambda: self._open_tab(8))
        left_layout.addWidget(self.toolbox_button)

        self.services_button = _nav_btn('⚙ Services')
        self.services_button.clicked.connect(lambda: self._open_tab(9))
        left_layout.addWidget(self.services_button)

        self.run_ads_button = QPushButton('▶ Run Ads')
        self.run_ads_button.clicked.connect(self.run_ads_for_all)

        self.simulator_button = _nav_btn('🤖 Simulator')
        self.simulator_button.clicked.connect(lambda: self._open_tab(0))
        left_layout.addWidget(self.simulator_button)

        self.proxy_button = _nav_btn('🔗 Proxy')
        self.proxy_button.clicked.connect(lambda: self._open_tab(1))
        left_layout.addWidget(self.proxy_button)

        self.settings_button = _nav_btn('⚙️ Settings')
        self.settings_button.clicked.connect(lambda: self._open_tab(2))
        left_layout.addWidget(self.settings_button)

        # ── Right content panel ──────────────────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_panel.setLayout(right_layout)

        # Ads table — always visible at the top, takes 3× more space than tab body
        right_layout.addWidget(self.ads_table, 3)

        # Tab body — QStackedWidget, hidden until a nav button is clicked
        self.tab_body = QStackedWidget()
        self.tab_body.hide()

        # Page 0 – Simulator: Ads Link input + Like Human Behavior + Run Ads
        simulator_page = QWidget()
        simulator_layout = QVBoxLayout()
        simulator_layout.setContentsMargins(0, 0, 0, 0)
        simulator_layout.setSpacing(8)
        simulator_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        simulator_page.setLayout(simulator_layout)

        # Ads Link input row
        ads_link_row = QHBoxLayout()
        self.ads_link_input = QTextEdit()
        self.ads_link_input.setPlaceholderText("Paste one ads URL per line…")
        self.ads_link_input.setFixedHeight(72)
        # Apply consistent input styling
        self.ads_link_input.setStyleSheet(
            "QTextEdit {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 4px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "}"
            "QTextEdit:focus {"
            "  border: 1px solid #1976d2;"
            "}"
        )
        # Load saved ads links
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r") as _f:
                    _saved = json.load(_f)
                    _links = _saved.get("ads_links", "")
                    if _links:
                        self.ads_link_input.setPlainText(_links)
        except Exception:
            pass
        self.ads_link_input.textChanged.connect(self._save_ads_links)
        ads_link_row.addWidget(self.ads_link_input)
        self.ads_link_copy_btn = QPushButton("📋 Copy")
        self.ads_link_copy_btn.setFixedSize(70, 32)
        self.ads_link_copy_btn.setToolTip("Copy ads links to clipboard")
        self.ads_link_copy_btn.clicked.connect(self._copy_ads_link)
        ads_link_clear_btn = QPushButton("🗑 Clear")
        ads_link_clear_btn.setFixedSize(70, 32)
        ads_link_clear_btn.setToolTip("Clear ads links")
        ads_link_clear_btn.clicked.connect(self.ads_link_input.clear)
        from PySide6.QtWidgets import QVBoxLayout as _QVBoxLayout
        _right_btn_vl = _QVBoxLayout()
        _right_btn_vl.setSpacing(2)
        _right_btn_vl.setContentsMargins(0, 0, 0, 0)
        _right_btn_vl.addWidget(self.ads_link_copy_btn)
        _right_btn_vl.addWidget(ads_link_clear_btn)
        _right_btn_vl.addStretch()
        ads_link_row.addLayout(_right_btn_vl)
        simulator_layout.addLayout(ads_link_row)

        # Like Human Behavior group
        simulator_layout.addWidget(self.ads_table.get_human_settings_widget())

        # Run Ads button
        self.run_ads_button.setStyleSheet(
            "QPushButton { background-color: #1976d2; color: white; font-weight: bold;"
            " padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1565c0; }"
            "QPushButton:disabled { background-color: #90caf9; }"
        )
        self.stop_ads_button = QPushButton("⏹ Stop")
        self.stop_ads_button.setEnabled(False)
        self.stop_ads_button.setToolTip("Stop the current ads automation")
        self.stop_ads_button.setStyleSheet(
            "QPushButton { background-color: #d32f2f; color: white; font-weight: bold;"
            " padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #b71c1c; }"
            "QPushButton:disabled { background-color: #ef9a9a; }"
        )
        self.stop_ads_button.clicked.connect(self.stop_ads)
        self.behavior_mode_combo = QComboBox()
        self.behavior_mode_combo.addItems(["Same in series", "Randomly different"])
        self.behavior_mode_combo.setToolTip(
            "Same in series: all devices use identical behavior options for this run.\n"
            "Randomly different: each device gets independently randomized options."
        )
        self.behavior_mode_combo.setStyleSheet(
            "QComboBox {"
            "  border: 1px solid #ddd; border-radius: 4px;"
            "  padding: 2px 6px; background: #ffffff; color: #212121;"
            "  font-size: 11px; min-height: 20px; max-height: 28px;"
            "}"
            "QComboBox:focus { border: 1px solid #1976d2; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
        )
        self.behavior_mode_combo.setCurrentIndex(1)  # default: Randomly different

        # ── Repeat count selector ─────────────────────────────────────────
        _combo_ss = (
            "QComboBox {"
            "  border: 1px solid #ddd; border-radius: 4px;"
            "  padding: 2px 6px; background: #ffffff; color: #212121;"
            "  font-size: 11px; min-height: 20px; max-height: 28px;"
            "}"
            "QComboBox:focus { border: 1px solid #1976d2; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
        )
        self._repeat_count: int = 1   # actual value used by run_ads_for_all
        self.repeat_combo = QComboBox()
        self.repeat_combo.addItems(["🔁 1× (once)", "2×", "3×", "5×", "10×", "Custom…"])
        self.repeat_combo.setToolTip(
            "Number of times to repeat the full automation run across all devices.\n"
            "Choose 'Custom…' to enter any value."
        )
        self.repeat_combo.setStyleSheet(_combo_ss)
        self.repeat_combo.setFixedWidth(110)
        self.repeat_combo.currentIndexChanged.connect(self._on_repeat_combo_changed)

        run_btn_row = QHBoxLayout()
        run_btn_row.addWidget(self.behavior_mode_combo)
        run_btn_row.addWidget(self.repeat_combo)
        run_btn_row.addWidget(self.run_ads_button)
        run_btn_row.addWidget(self.stop_ads_button)
        simulator_layout.addLayout(run_btn_row)

        # ── Log section (always visible) ──────────────────────────────────
        log_group = QGroupBox("📋 Log")
        log_group.setStyleSheet(
            "QGroupBox {"
            "  font-weight: bold;"
            "  font-size: 12px;"
            "  border: 1px solid #ccc;"
            "  border-radius: 6px;"
            "  margin-top: 6px;"
            "  padding-top: 4px;"
            "  background-color: #f5f7ff;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin;"
            "  left: 10px;"
            "  padding: 0 6px;"
            "  color: #1565c0;"
            "}"
        )
        log_vl = QVBoxLayout()
        log_vl.setContentsMargins(6, 6, 6, 6)
        log_vl.setSpacing(4)

        self.ads_log = QTextEdit()
        self.ads_log.setReadOnly(True)
        self.ads_log.setMinimumHeight(120)
        self.ads_log.setStyleSheet(
            "QTextEdit {"
            "  background: #1e1e1e;"
            "  color: #d4d4d4;"
            "  font-family: Consolas, monospace;"
            "  font-size: 11px;"
            "  border: none;"
            "  border-radius: 8px;"
            "  padding: 6px 8px;"
            "}"
        )
        log_vl.addWidget(self.ads_log)

        clear_log_btn = QPushButton("🗑 Clear")
        clear_log_btn.setFixedHeight(24)
        clear_log_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px;"
            " border: 1px solid #bdbdbd; border-radius: 4px; background: #f0f0f0; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        clear_log_btn.clicked.connect(self.ads_log.clear)
        clear_log_row = QHBoxLayout()
        clear_log_row.addStretch()
        clear_log_row.addWidget(clear_log_btn)
        log_vl.addLayout(clear_log_row)

        log_group.setLayout(log_vl)
        simulator_layout.addWidget(log_group)

        # Wrap simulator_page in a QScrollArea for overflow
        simulator_scroll = QScrollArea()
        simulator_scroll.setWidgetResizable(True)
        simulator_scroll.setWidget(simulator_page)
        simulator_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self.tab_body.addWidget(simulator_scroll)

        # Page 1 – Proxy      # index 1
        self.tab_body.addWidget(self.proxy_widget)

        # Page 2 – Settings      # index 2
        self.tab_body.addWidget(self.settings_widget)

        # Page 3 – Device Info      # index 3
        self.tab_body.addWidget(self.info_widget)

        # Page 4 – Actions      # index 4
        self.tab_body.addWidget(self.actions_widget)

        # Page 5 – Applications      # index 5
        self.tab_body.addWidget(self.apps_widget)

        # Page 6 – Files      # index 6
        self.tab_body.addWidget(self.files_widget)

        # Page 7 – Activities      # index 7
        self.tab_body.addWidget(self.activities_widget)

        # Page 8 – Toolbox      # index 8
        self.tab_body.addWidget(self.toolbox_widget)

        # Page 9 – Services     # index 9
        self.tab_body.addWidget(self.services_widget)

        right_layout.addWidget(self.tab_body)

        layout.addWidget(left_panel)
        layout.addWidget(right_panel, 1)

        frame_vl.addWidget(content_widget, 1)
        self.setLayout(outer)

        # Wire table selection changes to tab-specific device selection models
        self.ads_table.focused_serial_changed.connect(self._on_focused_serial_changed)
        self.ads_table.checked_serials_changed.connect(self._on_checked_serials_changed)

        # Auto-load Info when the user switches to the Info tab
        self.tab_body.currentChanged.connect(self._on_tab_changed)

        # Default to Info tab on startup
        self._open_tab(3)

    def update_status(self, text):
        if text:
            self.setWindowTitle(f'{self.app_name} - {text}')
            self.title_bar.set_title(f'{self.app_name}  –  {text}')
            self.status_timer.start(5000)
        else:
            self.reset_window_title()

    def reset_window_title(self):
        self.setWindowTitle(self.app_name)
        self.title_bar.set_title(self.app_name)

    # TAB_INDEX: 0=Simulator, 1=Proxy, 2=Settings, 3=Info, 4=Actions, 5=Packages, 6=Files, 7=Activities
    def _open_tab(self, index: int):
        """Show tab_body and switch to the given page index."""
        self.tab_body.setCurrentIndex(index)
        self.tab_body.show()

        # Update active tab highlighting
        if self.current_active_tab:
            self.current_active_tab.setChecked(False)
        _tab_buttons = [
            self.simulator_button,
            self.proxy_button,
            self.settings_button,
            self.dashboard_button,
            self.actions_button,
            self.pkgs_button,
            self.files_button,
            self.activities_button,
            self.toolbox_button,
            self.services_button,
        ]
        self.current_active_tab = _tab_buttons[index]
        self.current_active_tab.setChecked(True)

    def _show_help(self):
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Help")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            "<b>Fatan – ADB Automation Tool</b><br><br>"
            "1. Connect Android devices via USB / WiFi ADB.<br>"
            "2. Click <b>🔃 Load devices</b> to detect them.<br>"
            "3. Select a device row to inspect or control it.<br>"
            "4. Use the <b>Simulator</b> tab to run ads automation.<br>"
            "5. Use <b>Actions / Packages / Files</b> for device control.<br>"
            "6. Check the <b>Services</b> tab to inspect running Binder services."
        )
        msg.exec()

    def on_worker_finished(self, message):
        self.update_status(message)
        self.enable_buttons()
        self.worker = None

    def disable_buttons(self):
        self.load_devices_button.setEnabled(False)
        self.run_ads_button.setEnabled(False)
        self.stop_ads_button.setEnabled(True)
        self.screen_on_button.setEnabled(False)
        self.screen_off_button.setEnabled(False)
        self.remote_button.setEnabled(False)
        self.settings_button.setEnabled(False)

    def enable_buttons(self):
        self.load_devices_button.setEnabled(True)
        self.run_ads_button.setEnabled(True)
        self.stop_ads_button.setEnabled(False)
        self.screen_on_button.setEnabled(True)
        self.screen_off_button.setEnabled(True)
        self.remote_button.setEnabled(True)
        self.settings_button.setEnabled(True)

    def _copy_ads_link(self):
        """Copy the ads link textarea text to clipboard with visual feedback."""
        text = self.ads_link_input.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.ads_link_copy_btn.setText("✅")
            QTimer.singleShot(1000, lambda: self.ads_link_copy_btn.setText("📋"))
        else:
            self.ads_link_copy_btn.setText("❌")
            QTimer.singleShot(800, lambda: self.ads_link_copy_btn.setText("📋"))

    def _save_ads_links(self):
        """Persist the ads links textarea value to settings.json."""
        try:
            data = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
            data["ads_links"] = self.ads_link_input.toPlainText()
            with open(self.settings_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _append_log(self, message: str):
        """Append a log message to the ads log panel."""
        self.ads_log.append(message)
        # Auto-scroll to bottom
        self.ads_log.verticalScrollBar().setValue(
            self.ads_log.verticalScrollBar().maximum()
        )

    def _on_focused_serial_changed(self, serial: str):
        """When the user clicks a row, push the serial to focus-based tabs (Dashboard,
        Packages, Activities, Services). At most one device at a time."""
        # Always keep focus-based tabs in sync
        self.info_widget.set_device(serial)
        self.apps_widget.set_device(serial)
        self.activities_widget.set_selected_serial(serial)
        self.services_widget.set_device(serial)

        if not serial:
            return

        # Only auto-load if that tab is currently open
        if self.tab_body.isVisible() and self.tab_body.currentIndex() == 3:
            self.info_widget.load_device(serial)
        elif self.tab_body.isVisible() and self.tab_body.currentIndex() == 5:
            self.apps_widget.load_device(serial)
        elif self.tab_body.isVisible() and self.tab_body.currentIndex() == 6:
            self.files_widget.load_device(serial)
        else:
            # Store serial so it loads when user switches to the Info tab
            self.info_widget._serial = serial
            self.info_widget._serial_label.setText(
                f"Serial: {serial}" if serial else "No device selected"
            )

    def _on_checked_serials_changed(self, serials: list[str]):
        """Sync checkbox-based tabs to checkbox selection."""
        serial = serials[0] if serials else ""
        self.actions_widget.set_device(serial)
        self.files_widget.set_device(serial)
        self.toolbox_widget.set_device(serial)

        if self.tab_body.isVisible() and self.tab_body.currentIndex() == 6:
            if serial:
                self.files_widget.load_device(serial)
            else:
                self.files_widget.set_device("")

    def _on_tab_changed(self, index: int):
        """When the user switches to the Info or Apps tab, trigger a load if a device is set."""
        if index == 3 and self.info_widget._serial:
            self.info_widget.load_device(self.info_widget._serial)
        elif index == 5 and self.apps_widget._serial:
            self.apps_widget.load_device(self.apps_widget._serial)
        elif index == 6 and self.files_widget._serial:
            self.files_widget.load_device(self.files_widget._serial)
        elif index == 9 and self.services_widget._serial:
            self.services_widget.load_device()

    def stop_ads(self):
        """Signal the running worker to stop after the current device."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.update_status('⏹ Stopping after current device…')
            self.stop_ads_button.setEnabled(False)

    def _on_repeat_combo_changed(self, index: int):
        """Handle repeat count combo selection, show custom dialog for 'Custom…'."""
        text = self.repeat_combo.currentText()
        preset_map = {
            "🔁 1× (once)": 1,
            "2×": 2,
            "3×": 3,
            "5×": 5,
            "10×": 10,
        }
        if text in preset_map:
            self._repeat_count = preset_map[text]
            return
        # "Custom…" — show a small dialog with a QSpinBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Set Repeat Count")
        dlg.setMinimumWidth(280)
        dlg.setStyleSheet(
            "QDialog { background: #f8f9ff; }"
            "QLabel { font-size: 11px; color: #333; }"
            "QSpinBox {"
            "  border: 1px solid #dce3f0; border-radius: 4px;"
            "  padding: 2px 6px; background: #ffffff; color: #212121;"
            "  font-size: 12px; min-height: 18px; max-height: 22px;"
            "}"
            "QSpinBox::up-button, QSpinBox::down-button {"
            "  width: 10px; border: none;"
            "}"
            "QSpinBox::up-arrow { width: 0px; height: 0px; margin: 0px; }"
            "QSpinBox::down-arrow { width: 0px; height: 0px; margin: 0px; }"
            "QPushButton { background: #1976d2; color: white; font-weight: bold;"
            "  padding: 5px 14px; border-radius: 4px; font-size: 11px; border: none; }"
            "QPushButton:hover { background: #1565c0; }"
            "QPushButton[text='Cancel'] { background: #546e7a; }"
            "QPushButton[text='Cancel']:hover { background: #455a64; }"
        )
        fl = QFormLayout(dlg)
        fl.setContentsMargins(16, 16, 16, 12)
        fl.setSpacing(10)
        lbl = QLabel("Number of iterations:")
        spin = QSpinBox()
        spin.setRange(1, 9999)
        spin.setValue(max(1, self._repeat_count))
        fl.addRow(lbl, spin)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._repeat_count = spin.value()
            # Update combo label to show the chosen value
            self.repeat_combo.blockSignals(True)
            # Replace "Custom…" entry text temporarily to display current value
            self.repeat_combo.setItemText(5, f"Custom ({self._repeat_count}×)")
            self.repeat_combo.blockSignals(False)
        else:
            # Revert to index 0 if cancelled
            self.repeat_combo.blockSignals(True)
            self.repeat_combo.setCurrentIndex(0)
            self._repeat_count = 1
            self.repeat_combo.blockSignals(False)

    def install_chrome_for_all(self):
        if self.worker and self.worker.isRunning():
            self.update_status('Task already running')
            return

        table_data = self.ads_table.get_table_data()

        self.disable_buttons()

        self.worker = Worker("install_chrome", table_data)
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def install_gmail_for_all(self):
        if self.worker and self.worker.isRunning():
            self.update_status('Task already running')
            return

        table_data = self.ads_table.get_table_data()

        self.disable_buttons()

        self.worker = Worker("install_gmail", table_data)
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def install_socksdroid_for_all(self):
        if self.worker and self.worker.isRunning():
            self.update_status('Task already running')
            return

        table_data = self.ads_table.get_table_data()

        self.disable_buttons()

        self.worker = Worker("install_socksdroid", table_data)
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def run_ads_for_all(self):
        if self.worker and self.worker.isRunning():
            self.update_status('Task already running')
            return

        raw_links = self.ads_link_input.toPlainText()
        ads_links = [ln.strip() for ln in raw_links.splitlines() if ln.strip()]
        if not ads_links:
            self.update_status('⚠️ Please enter at least one Ads Link in the Simulator tab')
            return

        all_table_data = self.ads_table.get_table_data()
        # Limit devices to number of links
        table_data = all_table_data[:len(ads_links)]
        if not table_data:
            self.update_status('⚠️ No devices found in table')
            return

        human_settings = self.ads_table.get_human_settings()
        behavior_mode = self.behavior_mode_combo.currentText()

        self.disable_buttons()

        # Build per-device (serial → ads_link) mapping
        per_device_links = {row['serial']: ads_links[i] for i, row in enumerate(table_data) if row['serial']}

        worker_settings = {"ads_links": per_device_links}
        repeat = getattr(self, "_repeat_count", 1)
        worker_settings["repeat_count"] = repeat

        # Calculate and log estimated completion time
        num_devices = len(per_device_links)
        min_dur = human_settings.get("min_duration", 60.0)
        max_dur = human_settings.get("max_duration", 90.0)
        avg_dur = (min_dur + max_dur) / 2.0
        # ~5s for page load + ~5s for modal wait + ~5s for click & landing + avg browse
        per_device_est = avg_dur + 15.0
        total_est = per_device_est * num_devices * repeat
        est_min = int(total_est // 60)
        est_sec = int(total_est % 60)
        est_str = f"{est_min}m {est_sec}s" if est_min > 0 else f"{est_sec}s"
        self._append_log(f"⏱ Estimated completion time: ~{est_str} ({num_devices} device(s) × {repeat} iteration(s) × ~{per_device_est:.0f}s each)")

        if behavior_mode == "Same in series":
            worker_settings["human"] = human_settings
            self._append_log(f"▶ Starting run — behavior mode: Same in series | iterations: {repeat}× | links: {len(ads_links)}")
        else:
            worker_settings["human_settings_fn"] = self.ads_table.get_randomized_human_settings
            self._append_log(f"▶ Starting run — behavior mode: Randomly different | iterations: {repeat}× | links: {len(ads_links)}")

        self.worker = Worker("run_ads", table_data, settings=worker_settings)
        self.worker.progress.connect(self.update_status)
        self.worker.progress.connect(self._append_log)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.finished.connect(self._append_log)
        self.worker.start()

    def setup_keyboard_for_all(self):
        if self.worker and self.worker.isRunning():
            self.update_status('Task already running')
            return

        table_data = self.ads_table.get_table_data()

        self.disable_buttons()

        self.worker = Worker("setup_keyboard", table_data)
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def turn_screen_on_all(self):
        """Bật màn hình tất cả devices trong background thread."""
        serials = self._collect_serials()
        if not serials:
            self.update_status('No devices found')
            return
        w = ScreenToggleWorker(serials, "on")
        w.progress.connect(self.update_status)
        w.finished.connect(self.update_status)
        w.finished.connect(lambda _: w.deleteLater())
        w.start()
        self._screen_workers = getattr(self, '_screen_workers', [])
        self._screen_workers.append(w)

    def turn_screen_off_all(self):
        """Tắt màn hình tất cả devices trong background thread."""
        serials = self._collect_serials()
        if not serials:
            self.update_status('No devices found')
            return
        w = ScreenToggleWorker(serials, "off")
        w.progress.connect(self.update_status)
        w.finished.connect(self.update_status)
        w.finished.connect(lambda _: w.deleteLater())
        w.start()
        self._screen_workers = getattr(self, '_screen_workers', [])
        self._screen_workers.append(w)

    def _collect_serials(self):
        return self.ads_table.get_selected_serials()

    def open_remote(self):
        """Mở scrcpy cho device đang được chọn, hoặc tất cả nếu không chọn gì."""
        selected_rows = self.ads_table.table.selectionModel().selectedRows()
        if selected_rows:
            serials = []
            for index in selected_rows:
                item = self.ads_table.table.item(index.row(), 3)
                serial = item.text().strip() if item else ""
                if serial:
                    serials.append(serial)
        else:
            serials = self._collect_serials()

        if not serials:
            self.update_status('No devices found to remote')
            return

        launched = 0
        for serial in serials:
            try:
                scrcpy_exe = (
                    shutil.which("scrcpy")
                    or r"C:\android-tools\scrcpy-win64-v3.3.4\scrcpy.exe"
                )
                if not os.path.isfile(scrcpy_exe) and scrcpy_exe != "scrcpy":
                    raise FileNotFoundError(f"scrcpy not found at: {scrcpy_exe}")

                subprocess.Popen(
                    [scrcpy_exe, "-s", serial, "--window-title", serial,
                     "--window-width", str(self.preview_width),
                     "--window-height", str(self.preview_height)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                launched += 1
                self.update_status(f'📱 Opening remote for: {serial}')
            except FileNotFoundError:
                self.update_status('❌ scrcpy not found. Please install scrcpy and add it to PATH.')
                return
            except Exception as e:
                self.update_status(f'❌ Error opening remote for {serial}: {str(e)}')

        self.update_status(f'📱 Remote opened for {launched} device(s)')

    def changeEvent(self, event):
        """Handle window state changes."""
        super().changeEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """Handle app close."""
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = CookieLoaderGUI()
    gui.show()
    sys.exit(app.exec())