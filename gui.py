import sys, os, subprocess, shutil, json
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QTableWidget, QTableWidgetItem, QHBoxLayout, QDialog, QLineEdit, QLabel, QDialogButtonBox, QFormLayout
from PySide6.QtCore import QTimer, QThread, Signal, Qt
from PySide6.QtGui import QIcon

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

class Worker(QThread):
    progress = Signal(str)
    finished = Signal(str)
    row_result = Signal(int, str)  # (row_index, ads_info text)

    def __init__(self, task_type, table_data=None, settings=None):
        super().__init__()
        self.task_type = task_type
        self.table_data = table_data
        self.settings = settings or {}

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

        successful_devices = 0
        for idx, row in enumerate(self.table_data):
            serial = row.get('serial', '')
            ads_link = row.get('ads_link', '')

            if not serial:
                continue
            if not ads_link:
                self.progress.emit(f'⚠️ No ads link for device: {serial}')
                continue

            try:
                self.progress.emit(f'🤖 Running ads automation on: {serial}')
                result = run_ads_automation(serial, ads_link,
                                            human_settings=self.settings.get("human", {}))
                title = result.get('title', '') if isinstance(result, dict) else str(result)
                domain = result.get('domain', '') if isinstance(result, dict) else ''
                ads_info = f"{title} | {domain}" if domain else title
                successful_devices += 1
                self.progress.emit(f'✅ Done on {serial} — {ads_info}')
                self.row_result.emit(row.get('row_index', idx), ads_info)
            except Exception as e:
                self.progress.emit(f'❌ Error on device {serial}: {str(e)}')

        self.finished.emit(f'Ads automation done: {successful_devices}/{row_count} devices')

class CookieLoaderGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.app_name = "Adbflow"
        self.icon = "icon.png"
        self.data_csv = "data.csv"
        self.settings_file = "settings.json"

        # Default settings
        self.preview_width = 400
        self.preview_height = 800

        self.load_settings()
        self.status_timer = QTimer()
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(self.reset_window_title)

        self.worker = None

        self.initUI()

    def initUI(self):
        self.setWindowTitle(self.app_name)
        self.setGeometry(300, 300, 900, 600)
        self.setWindowIcon(QIcon(self.icon))

        layout = QHBoxLayout()
        layout.setSpacing(0)

        # Create ads table first
        self.ads_table = AdsTableWidget(self.data_csv)
        self.ads_table.status_update.connect(self.update_status)

        # Left navigation panel
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_panel.setLayout(left_layout)

        self.refresh_button = QPushButton('Refresh data')
        self.refresh_button.clicked.connect(self.ads_table.refresh_devices_and_csv)
        left_layout.addWidget(self.refresh_button)

        self.setup_keyboard_button = QPushButton('Setup Keyboard')
        self.setup_keyboard_button.clicked.connect(self.setup_keyboard_for_all)
        left_layout.addWidget(self.setup_keyboard_button)

        self.install_chrome_button = QPushButton('Install Chrome')
        self.install_chrome_button.clicked.connect(self.install_chrome_for_all)
        left_layout.addWidget(self.install_chrome_button)

        self.run_ads_button = QPushButton('Run Ads')
        self.run_ads_button.clicked.connect(self.run_ads_for_all)
        left_layout.addWidget(self.run_ads_button)

        self.screen_on_button = QPushButton('Screen ON')
        self.screen_on_button.clicked.connect(self.turn_screen_on_all)
        left_layout.addWidget(self.screen_on_button)

        self.screen_off_button = QPushButton('Screen OFF')
        self.screen_off_button.clicked.connect(self.turn_screen_off_all)
        left_layout.addWidget(self.screen_off_button)

        self.remote_button = QPushButton('📱 Remote')
        self.remote_button.setToolTip('Open scrcpy screen preview for selected device (or all if none selected)')
        self.remote_button.clicked.connect(self.open_remote)
        left_layout.addWidget(self.remote_button)

        # Add stretch to push main buttons to top
        left_layout.addStretch()

        self.settings_button = QPushButton('⚙️ Settings')
        self.settings_button.clicked.connect(self.open_settings)
        left_layout.addWidget(self.settings_button)

        # Right content panel
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_panel.setLayout(right_layout)

        right_layout.addWidget(self.ads_table)

        layout.addWidget(left_panel)
        layout.addWidget(right_panel)
        self.setLayout(layout)

    def update_status(self, text):
        if text:
            self.setWindowTitle(f'{self.app_name} - {text}')
            self.status_timer.start(5000)
        else:
            self.reset_window_title()

    def reset_window_title(self):
        self.setWindowTitle(self.app_name)

    def update_status(self, text):
        if text:
            self.setWindowTitle(f'{self.app_name} - {text}')
            self.status_timer.start(5000)
        else:
            self.reset_window_title()

    def on_worker_finished(self, message):
        self.update_status(message)
        self.enable_buttons()
        self.worker = None

    def disable_buttons(self):
        self.refresh_button.setEnabled(False)
        self.setup_keyboard_button.setEnabled(False)
        self.install_chrome_button.setEnabled(False)
        self.run_ads_button.setEnabled(False)
        self.screen_on_button.setEnabled(False)
        self.screen_off_button.setEnabled(False)
        self.remote_button.setEnabled(False)
        self.settings_button.setEnabled(False)

    def enable_buttons(self):
        self.refresh_button.setEnabled(True)
        self.setup_keyboard_button.setEnabled(True)
        self.install_chrome_button.setEnabled(True)
        self.run_ads_button.setEnabled(True)
        self.screen_on_button.setEnabled(True)
        self.screen_off_button.setEnabled(True)
        self.remote_button.setEnabled(True)
        self.settings_button.setEnabled(True)

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

        table_data = self.ads_table.get_table_data()
        human_settings = self.ads_table.get_human_settings()

        self.disable_buttons()

        self.worker = Worker("run_ads", table_data, settings={"human": human_settings})
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.row_result.connect(self.ads_table.on_row_result)
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

    def load_settings(self):
        """Load settings from JSON file."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    self.preview_width = settings.get('preview_width', 400)
                    self.preview_height = settings.get('preview_height', 800)
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_settings(self):
        """Save settings to JSON file."""
        try:
            settings = {
                'preview_width': self.preview_width,
                'preview_height': self.preview_height
            }
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def open_settings(self):
        """Open settings dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setModal(True)

        layout = QFormLayout()

        # Width input
        width_label = QLabel("Preview Width:")
        self.width_input = QLineEdit(str(self.preview_width))
        layout.addRow(width_label, self.width_input)

        # Height input
        height_label = QLabel("Preview Height:")
        self.height_input = QLineEdit(str(self.preview_height))
        layout.addRow(height_label, self.height_input)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.preview_width = int(self.width_input.text())
                self.preview_height = int(self.height_input.text())
                self.save_settings()
                self.update_status('Settings saved')
            except ValueError:
                self.update_status('Invalid width or height values')

    def open_remote(self):
        """Mở scrcpy cho device đang được chọn, hoặc tất cả nếu không chọn gì."""
        selected_rows = self.ads_table.table.selectionModel().selectedRows()
        if selected_rows:
            serials = []
            for index in selected_rows:
                item = self.ads_table.table.item(index.row(), 1)
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

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = CookieLoaderGUI()
    gui.show()
    sys.exit(app.exec())