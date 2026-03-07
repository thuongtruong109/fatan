import sys, os, subprocess, shutil, json, time, ctypes
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QHBoxLayout,
    QStackedWidget, QLabel, QLineEdit, QTextEdit, QGroupBox, QComboBox,
)
from PySide6.QtCore import QTimer, QThread, Signal, Qt
from PySide6.QtGui import QIcon, QCloseEvent

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
from features.chrome import install_chrome, open_url_in_chrome
from features.ads import run_ads_automation
from features.ads import AdsTableWidget
from features.settings import SettingsWidget
from features.proxy import ProxyWidget
from features.info import DeviceInfoWidget
from features.actions import ActionsWidget
from features.apps import ApplicationWidget

class Worker(QThread):
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, task_type, table_data=None, settings=None):
        super().__init__()
        self.task_type = task_type
        self.table_data = table_data
        self.settings = settings or {}
        self._stop_flag = False
        # Optional callable: () -> dict, used when behavior_mode == "randomly_different"
        self._human_settings_fn = self.settings.pop("human_settings_fn", None)

    def stop(self):
        self._stop_flag = True

    def run(self):
        try:
            if self.task_type == "setup_keyboard":
                self.setup_keyboard_for_all()
            elif self.task_type == "install_chrome":
                self.install_chrome_for_all()
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

    def run_ads_for_all(self):
        row_count = len(self.table_data)
        if row_count == 0:
            self.finished.emit('No devices found in table')
            return

        ads_link = self.settings.get("ads_link", "")
        if not ads_link:
            self.finished.emit('⚠️ No Ads Link provided')
            return

        successful_devices = 0
        for idx, row in enumerate(self.table_data):
            if self._stop_flag:
                self.finished.emit(f'⏹ Stopped — {successful_devices}/{row_count} devices completed')
                return

            serial = row.get('serial', '')

            if not serial:
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
                self.progress.emit(f'🤖 Running ads automation on: {serial}')
                result = run_ads_automation(serial, ads_link, human_settings=human)
                title = result.get('title', '') if isinstance(result, dict) else str(result)
                domain = result.get('domain', '') if isinstance(result, dict) else ''
                ads_info = f"{title} | {domain}" if domain else title
                successful_devices += 1
                self.progress.emit(f'✅ Done on {serial} — {ads_info}')
            except Exception as e:
                self.progress.emit(f'❌ Error on device {serial}: {str(e)}')

        self.finished.emit(f'Ads automation done: {successful_devices}/{row_count} devices')

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
        return self.settings_widget.get("preview_height", 800)

    def initUI(self):
        self.setWindowTitle(self.app_name)
        self.setGeometry(300, 300, 900, 600)
        self.setWindowIcon(QIcon(self.icon))

        layout = QHBoxLayout()
        layout.setSpacing(0)

        # Create widgets that are always needed
        self.ads_table = AdsTableWidget(self.data_csv)
        self.ads_table.status_update.connect(self.update_status)
        # Connect preview signals from table
        self.ads_table.preview_requested.connect(self._on_table_preview_requested)
        self.ads_table.preview_closed.connect(self._on_table_preview_closed)

        self.settings_widget = SettingsWidget(self.settings_file)
        self.settings_widget.settings_saved.connect(
            lambda _: self.update_status("✅ Settings saved")
        )
        self.settings_widget.setup_keyboard_requested.connect(self.setup_keyboard_for_all)
        self.settings_widget.install_chrome_requested.connect(self.install_chrome_for_all)
        self.settings_widget._get_serials_fn = self._collect_serials

        self.proxy_widget = ProxyWidget()
        self.proxy_widget.status_update.connect(self.update_status)
        self.proxy_widget.proxy_status_updated.connect(self.ads_table.update_proxy_statuses)

        self.info_widget = DeviceInfoWidget()
        self.info_widget.status_update.connect(self.update_status)
        self.actions_widget = ActionsWidget()
        self.actions_widget.status_update.connect(self.update_status)
        self.apps_widget = ApplicationWidget()
        self.apps_widget.status_update.connect(self.update_status)

        # Preview panel (hidden by default)
        self.preview_panel = QWidget()
        self.preview_panel.setVisible(False)
        pv_layout = QVBoxLayout()
        pv_layout.setContentsMargins(4, 4, 4, 4)
        pv_layout.setSpacing(4)
        self.preview_panel.setLayout(pv_layout)

        self._preview_title = QLabel("Preview")
        self._preview_title.setStyleSheet(
            "font-weight: bold; font-size: 12px; padding: 2px 4px;"
        )
        pv_layout.addWidget(self._preview_title)

        # Placeholder container — used only to measure position for the overlay window
        self.preview_container = QWidget()
        self.preview_container.setMinimumSize(300, 500)
        self.preview_container.setStyleSheet("background: #111; border: 1px solid #555;")
        pv_layout.addWidget(self.preview_container, 1)

        # State for current preview
        self._current_preview_serial = None
        self._scrcpy_proc = None
        self._embed_hwnd = 0          # Win32 HWND of embedded scrcpy window
        self._reposition_timer = QTimer()
        self._reposition_timer.setInterval(200)
        self._reposition_timer.timeout.connect(self._reposition_scrcpy)

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

        self.info_button = _nav_btn('ℹ️ Info')
        self.info_button.clicked.connect(lambda: self._open_tab(3))
        left_layout.addWidget(self.info_button)

        self.actions_button = _nav_btn('⚡ Actions')
        self.actions_button.clicked.connect(lambda: self._open_tab(4))
        left_layout.addWidget(self.actions_button)

        self.apps_button = _nav_btn('📦 Apps')
        self.apps_button.clicked.connect(lambda: self._open_tab(5))
        left_layout.addWidget(self.apps_button)

        self.run_ads_button = QPushButton('Run Ads')
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
        ads_link_label = QLabel("🔗 Ads Link:")
        ads_link_label.setStyleSheet("font-weight: bold;")
        ads_link_row.addWidget(ads_link_label)
        self.ads_link_input = QLineEdit()
        self.ads_link_input.setPlaceholderText("Paste ads URL here…")
        # Apply consistent input styling
        self.ads_link_input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  height: 22px;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #1976d2;"
            "}"
        )
        ads_link_row.addWidget(self.ads_link_input)
        self.ads_link_copy_btn = QPushButton("📋")
        self.ads_link_copy_btn.setFixedSize(32, 32)
        self.ads_link_copy_btn.setToolTip("Copy ads link to clipboard")
        self.ads_link_copy_btn.clicked.connect(self._copy_ads_link)
        ads_link_row.addWidget(self.ads_link_copy_btn)
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
        self.view_log_button = QPushButton("📋 View Log")
        self.view_log_button.setCheckable(True)
        self.view_log_button.setChecked(False)
        self.view_log_button.setToolTip("Toggle log panel visibility")
        self.view_log_button.setStyleSheet(
            "QPushButton { background-color: #455a64; color: white; font-weight: bold;"
            " padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #37474f; }"
            "QPushButton:checked { background-color: #1976d2; }"
            "QPushButton:checked:hover { background-color: #1565c0; }"
        )
        run_btn_row = QHBoxLayout()
        run_btn_row.addWidget(self.behavior_mode_combo)
        run_btn_row.addWidget(self.run_ads_button)
        run_btn_row.addWidget(self.stop_ads_button)
        run_btn_row.addWidget(self.view_log_button)
        simulator_layout.addLayout(run_btn_row)

        # ── Log section ─────────────────────────────────────────────────
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
        log_group.hide()  # hidden by default; toggled by View Log button
        self.view_log_button.toggled.connect(log_group.setVisible)
        simulator_layout.addWidget(log_group)

        self.tab_body.addWidget(simulator_page)

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

        right_layout.addWidget(self.tab_body)

        layout.addWidget(left_panel)
        layout.addWidget(right_panel, 1)
        layout.addWidget(self.preview_panel)
        self.setLayout(layout)

        # Wire table row selection → update Info / Actions with selected serial
        self.ads_table.table.itemSelectionChanged.connect(self._on_table_selection_changed)

        # Auto-load Info when the user switches to the Info tab
        self.tab_body.currentChanged.connect(self._on_tab_changed)

        # Default to Info tab on startup
        self._open_tab(3)

    def update_status(self, text):
        if text:
            self.setWindowTitle(f'{self.app_name} - {text}')
            self.status_timer.start(5000)
        else:
            self.reset_window_title()

    def reset_window_title(self):
        self.setWindowTitle(self.app_name)

    # TAB_INDEX: 0=Simulator, 1=Proxy, 2=Settings, 3=Info, 4=Actions
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
            self.info_button,
            self.actions_button,
            self.apps_button,
        ]
        self.current_active_tab = _tab_buttons[index]
        self.current_active_tab.setChecked(True)

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
        """Copy the ads link input text to clipboard with visual feedback."""
        text = self.ads_link_input.text().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.ads_link_copy_btn.setText("✅")
            QTimer.singleShot(1000, lambda: self.ads_link_copy_btn.setText("📋"))
        else:
            self.ads_link_copy_btn.setText("❌")
            QTimer.singleShot(800, lambda: self.ads_link_copy_btn.setText("📋"))

    def _append_log(self, message: str):
        """Append a log message to the ads log panel."""
        self.ads_log.append(message)
        # Auto-scroll to bottom
        self.ads_log.verticalScrollBar().setValue(
            self.ads_log.verticalScrollBar().maximum()
        )

    def _on_table_selection_changed(self):
        """When the user clicks a row, push the serial to Info and Actions widgets."""
        selected = self.ads_table.table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        serial_item = self.ads_table.table.item(row, 2)
        serial = serial_item.text().strip() if serial_item else ""

        # Always keep Info/Actions/Apps in sync
        self.actions_widget.set_device(serial)
        self.info_widget.set_device(serial)
        self.apps_widget.set_device(serial)

        # Only auto-load Info if that tab is currently open
        if self.tab_body.isVisible() and self.tab_body.currentIndex() == 3:
            self.info_widget.load_device(serial)
        elif self.tab_body.isVisible() and self.tab_body.currentIndex() == 5:
            self.apps_widget.load_device(serial)
        else:
            # Store serial so it loads when user switches to the Info tab
            self.info_widget._serial = serial
            self.info_widget._serial_label.setText(
                f"Serial: {serial}" if serial else "No device selected"
            )

    def _on_tab_changed(self, index: int):
        """When the user switches to the Info or Apps tab, trigger a load if a device is set."""
        if index == 3 and self.info_widget._serial:
            self.info_widget.load_device(self.info_widget._serial)
        elif index == 5 and self.apps_widget._serial:
            self.apps_widget.load_device(self.apps_widget._serial)

    def stop_ads(self):
        """Signal the running worker to stop after the current device."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.update_status('⏹ Stopping after current device…')
            self.stop_ads_button.setEnabled(False)

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

    def run_ads_for_all(self):
        if self.worker and self.worker.isRunning():
            self.update_status('Task already running')
            return

        ads_link = self.ads_link_input.text().strip()
        if not ads_link:
            self.update_status('⚠️ Please enter an Ads Link in the Simulator tab')
            return

        table_data = self.ads_table.get_table_data()
        human_settings = self.ads_table.get_human_settings()
        behavior_mode = self.behavior_mode_combo.currentText()

        self.disable_buttons()

        # Auto-open the log panel when a run starts
        self.view_log_button.setChecked(True)

        worker_settings = {"ads_link": ads_link}
        if behavior_mode == "Same in series":
            worker_settings["human"] = human_settings
            self._append_log(f"▶ Starting run — behavior mode: Same in series")
        else:
            # Pass a callable so the worker can generate fresh random settings per device
            worker_settings["human_settings_fn"] = self.ads_table.get_randomized_human_settings
            self._append_log(f"▶ Starting run — behavior mode: Randomly different")

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

    def _get_screen_state(self, serial):
        """Trả về True nếu màn hình đang ON, False nếu OFF."""
        try:
            out = subprocess.check_output(
                ["adb", "-s", serial, "shell", "dumpsys", "power"],
                text=True, stderr=subprocess.DEVNULL, startupinfo=_si
            )
            return "mWakefulness=Awake" in out or "mHoldingWakeLockSuspendBlocker=true" in out
        except Exception:
            return None

    def turn_screen_on_all(self):
        """Bật màn hình tất cả devices (nếu đang tắt thì mở lên)."""
        serials = self._collect_serials()
        if not serials:
            self.update_status('No devices found')
            return
        success = 0
        for serial in serials:
            try:
                is_on = self._get_screen_state(serial)
                if not is_on:
                    subprocess.run(
                        ["adb", "-s", serial, "shell", "input", "keyevent", "26"],
                        check=True, stderr=subprocess.DEVNULL, startupinfo=_si
                    )
                success += 1
                self.update_status(f'✅ Screen ON: {serial}')
            except Exception as e:
                self.update_status(f'❌ Error screen ON {serial}: {str(e)}')
        self.update_status(f'Screen ON done: {success}/{len(serials)} devices')

    def turn_screen_off_all(self):
        """Tắt màn hình tất cả devices (nếu đang bật thì tắt đi)."""
        serials = self._collect_serials()
        if not serials:
            self.update_status('No devices found')
            return
        success = 0
        for serial in serials:
            try:
                is_on = self._get_screen_state(serial)
                if is_on:
                    subprocess.run(
                        ["adb", "-s", serial, "shell", "input", "keyevent", "26"],
                        check=True, stderr=subprocess.DEVNULL, startupinfo=_si
                    )
                success += 1
                self.update_status(f'✅ Screen OFF: {serial}')
            except Exception as e:
                self.update_status(f'❌ Error screen OFF {serial}: {str(e)}')
        self.update_status(f'Screen OFF done: {success}/{len(serials)} devices')

    def _collect_serials(self):
        table_data = self.ads_table.get_table_data()
        return [row['serial'] for row in table_data if row['serial']]

    def open_remote(self):
        """Mở scrcpy cho device đang được chọn, hoặc tất cả nếu không chọn gì."""
        selected_rows = self.ads_table.table.selectionModel().selectedRows()
        if selected_rows:
            serials = []
            for index in selected_rows:
                item = self.ads_table.table.item(index.row(), 2)
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
                )
                launched += 1
                self.update_status(f'📱 Opening remote for: {serial}')
            except FileNotFoundError:
                self.update_status('❌ scrcpy not found. Please install scrcpy and add it to PATH.')
                return
            except Exception as e:
                self.update_status(f'❌ Error opening remote for {serial}: {str(e)}')

        self.update_status(f'📱 Remote opened for {launched} device(s)')

    def _on_table_preview_requested(self, serial: str):
        """Called when AdsTable requests a preview for a serial."""
        self.show_preview(serial)

    def _on_table_preview_closed(self, serial: str):
        """Called when AdsTable requests closing a preview."""
        self.close_preview(serial)

    def show_preview(self, serial: str):
        """Launch scrcpy as a borderless popup overlaid on the preview container."""
        if not serial:
            self.update_status('No device serial provided for preview')
            return

        # Already previewing this exact device – nothing to do
        if self._current_preview_serial == serial:
            return

        # Different device already open – close it first (re-enables its button)
        if self._current_preview_serial:
            self.close_preview(self._current_preview_serial)

        scrcpy_exe = shutil.which("scrcpy") or r"C:\android-tools\scrcpy-win64-v3.3.4\scrcpy.exe"
        if not os.path.isfile(scrcpy_exe) and shutil.which("scrcpy") is None:
            self.update_status('❌ scrcpy not found. Please install scrcpy and add it to PATH.')
            return

        try:
            proc = subprocess.Popen(
                [scrcpy_exe, "-s", serial, "--window-title", serial,
                 "--window-width", str(self.preview_width),
                 "--window-height", str(self.preview_height),
                 "--always-on-top"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._scrcpy_proc = proc
            self._current_preview_serial = serial
            self.preview_panel.setVisible(True)

            # Disable the Preview button for this device
            self.ads_table.set_preview_active(serial, True)

            self.update_status(f'📱 Opening preview for: {serial}')

            # On Windows: find the window, strip its title bar, then keep it
            # positioned as a WS_POPUP overlay – this keeps input working.
            self._embed_hwnd = 0
            self._find_and_position_scrcpy(serial)

        except Exception as e:
            self.update_status(f'❌ Error opening preview for {serial}: {e}')

    def _find_and_position_scrcpy(self, title: str, timeout: float = 6.0):
        """Poll for the scrcpy HWND, strip its caption, then overlay it on
        preview_container.  We use WS_POPUP (not WS_CHILD) so the window keeps
        its own message loop and mouse/touch input continues to work correctly.
        """
        if os.name != 'nt':
            return

        user32 = ctypes.windll.user32
        deadline = time.time() + timeout
        hwnd = 0
        while time.time() < deadline:
            hwnd = user32.FindWindowW(None, ctypes.c_wchar_p(title))
            if hwnd:
                break
            time.sleep(0.12)

        if not hwnd:
            self.update_status('⚠️ Could not find scrcpy window to position')
            return

        # Strip title bar / resize border; keep WS_POPUP so input is not broken
        GWL_STYLE    = -16
        WS_POPUP     = 0x80000000
        WS_VISIBLE   = 0x10000000
        WS_CAPTION   = 0x00C00000   # title bar (WS_BORDER | WS_DLGFRAME)
        WS_THICKFRAME = 0x00040000  # resize grip

        try:
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            style = (style | WS_POPUP | WS_VISIBLE) & ~(WS_CAPTION | WS_THICKFRAME)
            user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        except Exception as e:
            self.update_status(f'⚠️ Could not restyle scrcpy window: {e}')

        self._embed_hwnd = hwnd
        self._reposition_scrcpy()
        # Keep syncing position as the main window moves / resizes
        self._reposition_timer.start()

    def _reposition_scrcpy(self):
        """Move/resize the scrcpy popup to exactly cover preview_container."""
        if not self._embed_hwnd or os.name != 'nt':
            return

        # If scrcpy exited, auto-close
        if self._scrcpy_proc and self._scrcpy_proc.poll() is not None:
            self._reposition_timer.stop()
            self.close_preview()
            return

        try:
            user32 = ctypes.windll.user32
            pos = self.preview_container.mapToGlobal(
                self.preview_container.rect().topLeft()
            )
            x, y = pos.x(), pos.y()
            w = self.preview_container.width()
            h = self.preview_container.height()

            SWP_NOZORDER   = 0x0004
            SWP_SHOWWINDOW = 0x0040
            SWP_NOACTIVATE = 0x0010
            user32.SetWindowPos(
                self._embed_hwnd, 0,
                int(x), int(y), int(w), int(h),
                SWP_NOZORDER | SWP_SHOWWINDOW | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def close_preview(self, serial: str = None):
        """Terminate scrcpy, re-enable table button, hide panel, restore window width."""
        self._reposition_timer.stop()
        self._embed_hwnd = 0

        try:
            if self._scrcpy_proc and self._scrcpy_proc.poll() is None:
                self._scrcpy_proc.terminate()
        except Exception:
            pass

        closed_serial = self._current_preview_serial
        self._scrcpy_proc = None
        self._current_preview_serial = None

        # Re-enable the Preview button for the closed device
        if closed_serial:
            self.ads_table.set_preview_active(closed_serial, False)

        self.preview_panel.setVisible(False)

        # Let the window shrink back to its natural size
        self.setMinimumWidth(0)
        self.setMaximumWidth(16_777_215)
        QTimer.singleShot(0, self.adjustSize)

        self.update_status('Preview closed')

    def closeEvent(self, event: QCloseEvent):
        """Ensure scrcpy preview is closed when the app is closing."""
        if self._current_preview_serial:
            self.close_preview()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = CookieLoaderGUI()
    gui.show()
    sys.exit(app.exec())