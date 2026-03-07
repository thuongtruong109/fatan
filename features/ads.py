import time, random, logging
from urllib.parse import urlparse
from utils.cdp_chrome import ChromeCDP
from utils.cdp_helpers import InputDriver, get_webpage_safe_zone
from features.session_engine import browse_session

logger = logging.getLogger("fatan.ads")

def run_ads_automation(
    serial: str,
    url: str,
    human_settings: dict = None,
):
    """
    Flow:
      1. Mở link ads ban đầu (url ở ô Ads Link).
      2. Đợi modal "Link to ad" xuất hiện, cuộn xuống tìm nút "Learn more".
      3. Click "Learn more" → vào trang đích thật.
      4. Thu thập ads info (title + domain).
      5. Thực hiện hành vi lướt ngẫu nhiên như người thật (≥ 60s).

    Args:
        serial: ADB serial của device
        url: link ads ban đầu (ô Ads Link)

    Raises:
        RuntimeError: nếu Chrome không chạy hoặc lỗi kết nối
    """

    with ChromeCDP(serial=serial, initial_url=url) as cdp:

        # ── Bước 1: Đợi trang ads load ──────────────────────────────────
        print(f"⏳ Waiting for ads page to load on {serial}...")
        time.sleep(5)

        # ── Bước 2: Đợi modal "Link to ad" xuất hiện ────────────────────
        print(f"⏳ Waiting for 'Link to ad' modal on {serial}...")
        modal_appeared = False
        for _ in range(15):  # Đợi tối đa 15 giây
            time.sleep(1)
            check_modal = cdp.execute_js("""
            (function() {
                const dialogs = document.querySelectorAll('[role="dialog"]');
                for (const dialog of dialogs) {
                    if (dialog.textContent && dialog.textContent.toLowerCase().includes('link to ad')) {
                        return true;
                    }
                }
                return false;
            })()
            """)
            if check_modal:
                modal_appeared = True
                print(f"✅ 'Link to ad' modal appeared on {serial}")
                break

        if not modal_appeared:
            print(f"⚠️  'Link to ad' modal not found on {serial}, collecting current page info...")
            page_title = cdp.get_page_title()
            page_url = cdp.get_current_url()
            domain = urlparse(page_url).netloc if page_url else ""
            return {"title": page_title, "domain": domain, "url": page_url}

        # ── Bước 3: Cuộn trong modal để nút "Learn more" hiện ra ─────────
        print(f"� Scrolling modal to reveal 'Learn more' button on {serial}...")
        cdp.execute_js("""
        (function() {
            const dialogs = document.querySelectorAll('[role="dialog"]');
            for (const dialog of dialogs) {
                if (dialog.textContent && dialog.textContent.toLowerCase().includes('link to ad')) {
                    dialog.scrollTop = dialog.scrollHeight;
                    return;
                }
            }
            window.scrollTo(0, document.body.scrollHeight);
        })()
        """)
        time.sleep(1)

        # ── Bước 4: Tìm và click nút "Learn more" ───────────────────────
        page_title = ""
        page_url = ""
        try:
            js_rect = """
            (function() {
                const dialogs = document.querySelectorAll('[role="dialog"]');
                let targetDialog = null;
                for (const dialog of dialogs) {
                    if (dialog.textContent && dialog.textContent.toLowerCase().includes('link to ad')) {
                        targetDialog = dialog;
                        break;
                    }
                }
                if (!targetDialog) return null;

                const btn = Array.from(targetDialog.querySelectorAll('a, button, [role="button"]')).find(el =>
                    el.textContent && el.textContent.trim().toLowerCase().includes('learn more')
                );
                if (!btn) return null;

                btn.scrollIntoView({block: 'center'});
                const rect = btn.getBoundingClientRect();
                return {
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2)
                };
            })()
            """
            rect = cdp.execute_js(js_rect)
            if rect and rect.get('x') and rect.get('y'):
                x, y = rect['x'], rect['y']
                logger.info("'Learn more' button at CSS(%d, %d) on %s", x, y, serial)

                # Use InputDriver for consistent CSS-pixel click via CDP touch
                zone = get_webpage_safe_zone(cdp)
                inp = InputDriver(serial, cdp,
                                  chrome_top=zone.get("chrome_top", 150),
                                  dpr=zone.get("dpr", 1.0),
                                  backend="cdp")
                inp.tap_css(x, y)
                logger.info("Clicked 'Learn more' on %s, waiting for destination page...", serial)

                # ── Bước 5: Đợi trang đích load ─────────────────────────
                time.sleep(5)
                page_title = cdp.get_page_title()
                page_url = cdp.get_current_url()
                domain = urlparse(page_url).netloc if page_url else ""
                logger.info("Landed on: %s | %s (%s)", page_title, domain, page_url)

                # ── Bước 6: Hành vi lướt như người thật (≥ 60s) ─────────
                logger.info("Starting human browsing on %s...", serial)
                hs = human_settings or {}
                browse_session(serial, cdp,
                               original_url=page_url,
                               min_duration=hs.get("min_duration", 60.0),
                               max_duration=hs.get("max_duration", 90.0),
                               click_prob=hs.get("click_prob", 0.30),
                               burst_prob=hs.get("burst_prob", 0.35),
                               scroll_dist_min=hs.get("scroll_dist_min", 500),
                               scroll_dist_max=hs.get("scroll_dist_max", 1400),
                               read_pause_min=hs.get("read_pause_min", None),
                               read_pause_max=hs.get("read_pause_max", None),
                               scroll_focus=hs.get("scroll_focus", 1.0),
                               swipe_speed_min_ms=hs.get("swipe_speed_min_ms", None),
                               swipe_speed_max_ms=hs.get("swipe_speed_max_ms", None),
                               overshoot_prob=hs.get("overshoot_prob", None),
                               scroll_style_weights=hs.get("scroll_style_weights", None),
                               profile=hs.get("profile", None))

                # Nghỉ cuối phiên
                time.sleep(random.uniform(2.0, 4.0))

            else:
                print(f"⚠️  'Learn more' button not found in modal on {serial}")
                page_title = cdp.get_page_title()
                page_url = cdp.get_current_url()
                domain = urlparse(page_url).netloc if page_url else ""

        except Exception as e:
            print(f"⚠️  Error clicking 'Learn more' on {serial}: {e}")
            page_title = cdp.get_page_title()
            page_url = cdp.get_current_url()
            domain = urlparse(page_url).netloc if page_url else ""

        return {"title": page_title, "domain": domain, "url": page_url}

# GUI Components for Ads Management
import sys, os, subprocess, shutil, json
from functools import partial
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QTableWidget, QTableWidgetItem, QHBoxLayout, QDialog, QLineEdit, QLabel, QDialogButtonBox, QFormLayout, QStyledItemDelegate, QTextEdit, QSizePolicy, QGroupBox, QDoubleSpinBox, QSpinBox, QSlider, QFrame, QComboBox, QGridLayout
from PySide6.QtCore import QTimer, QThread, Signal, Qt, QRect
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

class SerialDelegate(QStyledItemDelegate):
    """Delegate giới hạn editor của cột Serial đúng bằng width của ô."""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        return editor

    def updateEditorGeometry(self, editor, option, index):
        # Đặt geometry của editor khớp đúng với rect của ô, không tràn ra ngoài
        editor.setGeometry(option.rect)


class AdsLinkWidget(QWidget):
    """Custom widget for ads link column with truncated text and copy button."""

    link_changed = Signal(str)  # Signal emitted when link is changed

    def __init__(self, link_text="", parent=None):
        super().__init__(parent)
        self.full_link = link_text
        self.initUI()

    def initUI(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Truncated link label
        self.link_label = QLabel(self.truncate_link(self.full_link))
        self.link_label.setStyleSheet("""
            QLabel {
                color: blue;
                text-decoration: underline;
            }
            QLabel:hover {
                color: blue;
            }
        """)
        layout.addWidget(self.link_label)

        # Inline edit input (hidden by default)
        self.link_input = QLineEdit()
        self.link_input.setVisible(False)
        self.link_input.returnPressed.connect(self.finish_inline_edit)
        self.link_input.editingFinished.connect(self.finish_inline_edit)
        layout.addWidget(self.link_input)

        # Copy button
        self.copy_button = QPushButton("📋")
        self.copy_button.setFixedSize(32, 32)
        self.copy_button.setToolTip("Copy link to clipboard")
        self.copy_button.clicked.connect(self.copy_link)
        layout.addWidget(self.copy_button)

        layout.addStretch()

    def truncate_link(self, link, max_length=30):
        """Truncate link to max_length characters with ellipsis."""
        if len(link) <= max_length:
            return link
        return link[:max_length-3] + "..."

    def copy_link(self):
        """Copy the full link to clipboard."""
        if self.full_link:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.full_link)
            # Show temporary feedback
            original_text = self.copy_button.text()
            self.copy_button.setText("✅")
            QTimer.singleShot(1000, lambda: self.copy_button.setText(original_text))

    def start_inline_edit(self):
        """Start inline editing of the link."""
        self.link_input.setText(self.full_link)
        self.link_label.setVisible(False)
        self.copy_button.setVisible(False)  # Ẩn nút copy để input chiếm full width
        self.link_input.setVisible(True)
        self.link_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.link_input.setFocus()
        self.link_input.selectAll()

    def finish_inline_edit(self):
        """Finish inline editing and update the link."""
        if not self.link_input.isVisible():
            return
        new_link = self.link_input.text().strip()
        self.set_link(new_link)
        self.link_label.setVisible(True)
        self.link_input.setVisible(False)
        self.copy_button.setVisible(True)  # Hiện lại nút copy
        self.link_changed.emit(new_link)

    def set_link(self, link_text):
        self.full_link = link_text
        self.link_label.setText(self.truncate_link(link_text))

    def get_link(self):
        return self.full_link

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to start inline editing."""
        self.start_inline_edit()
        event.accept()

class AdsTableWidget(QWidget):
    """Widget containing the ads table with device management functionality."""

    status_update = Signal(str)
    preview_requested = Signal(str)   # emitted when user clicks Preview button (serial)
    preview_closed = Signal(str)      # emitted when user clicks Close button (serial)

    def __init__(self, data_csv="data/data.csv", parent=None):
        super().__init__(parent)
        self.data_csv = data_csv
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(['No', 'Device Name', 'Serial', 'Model', 'Proxy Type', 'Host:Port', 'Preview'])
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        from PySide6.QtWidgets import QHeaderView
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)           # No
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)         # Device Name – takes remaining space
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Serial
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Model
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Proxy Type
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # Host:Port
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)           # Actions
        self.table.itemChanged.connect(self.on_table_item_changed)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.mousePressEvent = self.table_mouse_press_event
        self.table.focusOutEvent = self.table_focus_out_event
        self.table.mouseDoubleClickEvent = self.table_mouse_double_click_event

        # Dùng delegate riêng cho cột Device Name để editor không bị tràn ra ngoài ô
        self._device_name_delegate = SerialDelegate(self.table)
        self.table.setItemDelegateForColumn(1, self._device_name_delegate)

        # Remove cell hover effect but keep row selection, make header text bolder
        self.table.setStyleSheet("""
            QTableWidget::item:hover {
                background-color: transparent;
                border: none;
                outline: none;
                color: inherit;
            }
            QTableWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
            QTableWidget::item:selected:hover {
                background-color: #e3f2fd;
                border: none;
                outline: none;
                color: black;
            }
            QTableWidget::item:focus {
                border: 1px solid transparent;
                outline: none;
                background-color: inherit;
            }
            QTableWidget::item:selected:focus {
                background-color: #e3f2fd;
                border: 1px solid transparent;
                outline: none;
                color: black;
            }
            QTableWidget {
                selection-background-color: #e3f2fd;
                gridline-color: #ddd;
            }
            QHeaderView::section {
                font-weight: bold;
                background-color: #f0f0f0;
            }
        """)

        layout.addWidget(self.table)

        # ── Like Human Settings Section ──────────────────────────────────
        self._human_settings_group = self._build_human_settings_section(layout)

        self.refresh_table()

    def _build_human_settings_section(self, parent_layout: QVBoxLayout):
        """Tạo section 'Like Human Behavior' bên dưới table."""
        group = QGroupBox("🤖 Behaviors")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 2px;
                background-color: #f5f7ff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #1565c0;
            }
        """)

        grid = QGridLayout()
        grid.setSpacing(0)
        grid.setContentsMargins(8, 6, 8, 8)

        # Shared style for all spinboxes, combos and slider-value labels
        _SPIN_W = 72   # fixed width for every spin-box
        _LABEL_W = 90  # fixed width for every row label

        _input_ss = (
            "QSpinBox, QDoubleSpinBox, QComboBox {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 1px 5px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  min-height: 20px;"
            "  max-height: 20px;"
            "}"
            "QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {"
            "  border: 1px solid #1976d2;"
            "}"
            "QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {"
            "  background: #f5f5f5; color: #9e9e9e;"
            "}"
            "QSpinBox::up-button, QSpinBox::down-button,"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {"
            "  width: 8px; height: 9px;"
            "  border: none;"
            "  border-radius: 1px;"
            "  background: #ddd;"
            "}"
            "QComboBox::drop-down {"
            "  border: none; width: 20px;"
            "}"
            "QSlider::groove:horizontal {"
            "  height: 4px;"
            "  background: #e0e0e0;"
            "  border-radius: 2px;"
            "}"
            "QSlider::handle:horizontal {"
            "  width: 14px; height: 14px;"
            "  background: #1976d2;"
            "  border-radius: 7px;"
            "  margin: -5px 0;"
            "}"
            "QSlider::sub-page:horizontal {"
            "  background: #90caf9;"
            "  border-radius: 2px;"
            "}"
        )

        def _header(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "font-weight: bold; color: #1565c0; font-size: 11px;"
                " padding-bottom: 4px; background: transparent; border: none;"
            )
            return lbl

        def _row_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(_LABEL_W)
            lbl.setStyleSheet("color: #555; font-size: 11px; background: transparent; border: none;")
            return lbl

        def _value_label(text: str, width: int = 36) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setStyleSheet("color: #1976d2; font-weight: bold; font-size: 11px; background: transparent; border: none;")
            return lbl

        def _spin(parent, attr, vmin, vmax, val, suffix="", step=1, special="", tip=""):
            s = QSpinBox()
            s.setRange(vmin, vmax)
            s.setValue(val)
            s.setFixedWidth(_SPIN_W)
            s.setSingleStep(step)
            if suffix: s.setSuffix(suffix)
            if special: s.setSpecialValueText(special)
            if tip: s.setToolTip(tip)
            s.setStyleSheet(_input_ss)
            setattr(parent, attr, s)
            return s

        def _dspin(parent, attr, vmin, vmax, val, suffix="", step=0.5, tip=""):
            s = QDoubleSpinBox()
            s.setRange(vmin, vmax)
            s.setValue(val)
            s.setFixedWidth(_SPIN_W)
            s.setSingleStep(step)
            if suffix: s.setSuffix(suffix)
            if tip: s.setToolTip(tip)
            s.setStyleSheet(_input_ss)
            setattr(parent, attr, s)
            return s

        def _slider(parent, attr, vmin, vmax, val, tip=""):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(vmin, vmax)
            s.setValue(val)
            s.setMinimumWidth(80)
            if tip: s.setToolTip(tip)
            s.setStyleSheet(_input_ss)
            setattr(parent, attr, s)
            return s

        def _sep() -> QFrame:
            """Thin horizontal separator line."""
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet("color: #e0e0e0; margin: 2px 0; background: transparent; border: none;")
            return line

        def _cell_widget(rows_content) -> QWidget:
            """Build a uniform cell widget from a list of QHBoxLayout / QWidget rows."""
            w = QWidget()
            # Use objectName-scoped style so it doesn't bleed into child input widgets
            w.setObjectName("behaviorCell")
            w.setStyleSheet(
                "#behaviorCell {"
                "  background: #f8f9ff;"
                "  border: 1px solid #ddd;"
                "  border-radius: 6px;"
                "}"
            )
            vl = QVBoxLayout(w)
            vl.setContentsMargins(10, 6, 10, 8)
            vl.setSpacing(4)
            for item in rows_content:
                if isinstance(item, QHBoxLayout):
                    vl.addLayout(item)
                else:
                    vl.addWidget(item)
            return w

        def _hrow(*widgets) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.setContentsMargins(0, 0, 0, 0)
            for w in widgets:
                row.addWidget(w)
            return row

        # ── Cell (0,0): ⏱ Duration & Read Pause ──────────────────────────
        self._hs_min_dur  = _spin(self, "_hs_min_dur",  10, 600, 60,  "s", tip="Min session duration")
        self._hs_max_dur  = _spin(self, "_hs_max_dur",  10, 600, 90,  "s", tip="Max session duration")
        self._hs_read_min = _dspin(self, "_hs_read_min", 0.5, 30.0, 1.5, "s", tip="Min read pause")
        self._hs_read_max = _dspin(self, "_hs_read_max", 0.5, 60.0, 6.0, "s", tip="Max read pause")

        duration_row = QHBoxLayout()
        duration_row.setSpacing(6)
        duration_row.setContentsMargins(0, 0, 0, 0)
        duration_row.addWidget(_row_label("Duration:"))
        duration_row.addWidget(self._hs_min_dur)
        duration_row.addWidget(QLabel("-"))
        duration_row.addWidget(self._hs_max_dur)
        duration_row.addStretch()

        read_pause_row = QHBoxLayout()
        read_pause_row.setSpacing(6)
        read_pause_row.setContentsMargins(0, 0, 0, 0)
        read_pause_row.addWidget(_row_label("Read pause:"))
        read_pause_row.addWidget(self._hs_read_min)
        read_pause_row.addWidget(QLabel("-"))
        read_pause_row.addWidget(self._hs_read_max)
        read_pause_row.addStretch()

        c00 = _cell_widget([
            _header("⏱ Duration & Read Pause"),
            duration_row,
            _sep(),
            read_pause_row,
        ])

        # ── Cell (0,1): 🖱 Scroll Distance & Focus ───────────────────────
        self._hs_scroll_min   = _spin(self, "_hs_scroll_min",   50, 3000, 500,  "px", step=50, tip="Min scroll distance")
        self._hs_scroll_max   = _spin(self, "_hs_scroll_max",  100, 4000, 1400, "px", step=50, tip="Max scroll distance")
        self._hs_scroll_focus = _slider(self, "_hs_scroll_focus", 5, 30, 10,
            "Scroll focus weight (1.0× = balanced, 3.0× = scroll only)")
        self._hs_scroll_focus_label = _value_label("1.0×", 36)
        self._hs_scroll_focus.valueChanged.connect(
            lambda v: self._hs_scroll_focus_label.setText(f"{v/10:.1f}×")
        )
        self._hs_overshoot       = _slider(self, "_hs_overshoot", 0, 60, 20, "Overshoot probability")
        self._hs_overshoot_label = _value_label("20%", 36)
        self._hs_overshoot.valueChanged.connect(
            lambda v: self._hs_overshoot_label.setText(f"{v}%")
        )

        focus_row = QHBoxLayout(); focus_row.setSpacing(6); focus_row.setContentsMargins(0,0,0,0)
        focus_row.addWidget(_row_label("Scroll focus:"))
        focus_row.addWidget(self._hs_scroll_focus, 1)
        focus_row.addWidget(self._hs_scroll_focus_label)

        over_row = QHBoxLayout(); over_row.setSpacing(6); over_row.setContentsMargins(0,0,0,0)
        over_row.addWidget(_row_label("Overshoot:"))
        over_row.addWidget(self._hs_overshoot, 1)
        over_row.addWidget(self._hs_overshoot_label)

        scroll_distance_row = QHBoxLayout()
        scroll_distance_row.setSpacing(6)
        scroll_distance_row.setContentsMargins(0, 0, 0, 0)
        scroll_distance_row.addWidget(_row_label("Scroll dist:"))
        scroll_distance_row.addWidget(self._hs_scroll_min)
        scroll_distance_row.addWidget(QLabel("-"))
        scroll_distance_row.addWidget(self._hs_scroll_max)
        scroll_distance_row.addStretch()

        c01 = _cell_widget([
            _header("🖱 Scroll Distance & Focus"),
            scroll_distance_row,
            _sep(),
            focus_row,
            over_row,
        ])

        # ── Cell (1,0): ⚡ Swipe Speed & Style ──────────────────────────
        self._hs_speed_min = _spin(self, "_hs_speed_min", 0, 2000, 0, "ms", step=20,
            special="Auto", tip="Min swipe duration (0 = auto)")
        self._hs_speed_max = _spin(self, "_hs_speed_max", 0, 3000, 0, "ms", step=20,
            special="Auto", tip="Max swipe duration (0 = auto)")
        self._hs_scroll_style = QComboBox()
        self._hs_scroll_style.addItems([
            "Mixed (auto)", "Normal (Bezier)", "Flash (fast flick)",
            "Zigzag (drift)", "Stutter (hesitant)",
        ])
        self._hs_scroll_style.setStyleSheet(_input_ss)
        self._hs_scroll_style.setToolTip(
            "Mixed = random (most natural)\nNormal = Bezier\n"
            "Flash = fast flick\nZigzag = drift\nStutter = hesitant"
        )

        c10 = _cell_widget([
            _header("⚡ Swipe Speed & Style"),
            _hrow(_row_label("Speed:"), self._hs_speed_min, QLabel("-"), self._hs_speed_max),
            _sep(),
            _hrow(_row_label("Scroll style:"), self._hs_scroll_style),
        ])

        # ── Cell (1,1): 👆 Click, Burst & Profile ───────────────────────
        self._hs_click_prob  = _slider(self, "_hs_click_prob",  5, 80, 30, "Click probability")
        self._hs_click_label = _value_label("30%", 36)
        self._hs_click_prob.valueChanged.connect(lambda v: self._hs_click_label.setText(f"{v}%"))

        self._hs_burst_prob  = _slider(self, "_hs_burst_prob",  5, 80, 35, "Burst scroll probability")
        self._hs_burst_label = _value_label("35%", 36)
        self._hs_burst_prob.valueChanged.connect(lambda v: self._hs_burst_label.setText(f"{v}%"))

        self._hs_profile = QComboBox()
        self._hs_profile.addItems(["Auto (random)", "Fast scroller", "Careful reader", "Distracted"])
        self._hs_profile.setStyleSheet(_input_ss)
        self._hs_profile.setToolTip(
            "Auto = random each session\nFast = quick scroll\n"
            "Careful = slow, reads more\nDistracted = irregular"
        )

        click_row2 = QHBoxLayout(); click_row2.setSpacing(6); click_row2.setContentsMargins(0,0,0,0)
        click_row2.addWidget(_row_label("Click %:"))
        click_row2.addWidget(self._hs_click_prob, 1)
        click_row2.addWidget(self._hs_click_label)

        burst_row2 = QHBoxLayout(); burst_row2.setSpacing(6); burst_row2.setContentsMargins(0,0,0,0)
        burst_row2.addWidget(_row_label("Burst %:"))
        burst_row2.addWidget(self._hs_burst_prob, 1)
        burst_row2.addWidget(self._hs_burst_label)

        c11 = _cell_widget([
            _header("👆 Click & Profile"),
            click_row2,
            burst_row2,
            _sep(),
            _hrow(_row_label("Profile:"), self._hs_profile),
        ])

        # Place cells with equal stretch so all 4 have same height
        grid.addWidget(c00, 0, 0)
        grid.addWidget(c01, 0, 1)
        grid.addWidget(c10, 1, 0)
        grid.addWidget(c11, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        group.setLayout(grid)
        parent_layout.addWidget(group)
        return group

    def get_human_settings_widget(self) -> "QGroupBox":
        """Return the 'Like Human Behavior' QGroupBox to embed anywhere."""
        # The widgets (_hs_*) were already created in _build_human_settings_section
        # during initUI.  We just need to return the stored reference.
        return self._human_settings_group

    # ── Style key lookup ─────────────────────────────────────────────────
    _STYLE_MAP = {
        "Mixed (auto)":     None,
        "Normal (Bezier)":  {"normal": 1, "flash": 0, "zigzag": 0, "stutter": 0},
        "Flash (fast flick)": {"normal": 0, "flash": 1, "zigzag": 0, "stutter": 0},
        "Zigzag (drift)":   {"normal": 0, "flash": 0, "zigzag": 1, "stutter": 0},
        "Stutter (hesitant)": {"normal": 0, "flash": 0, "zigzag": 0, "stutter": 1},
    }
    _PROFILE_MAP = {
        "Auto (random)":    None,
        "Fast scroller":    "fast_scroller",
        "Careful reader":   "careful_reader",
        "Distracted":       "distracted",
    }

    def get_human_settings(self) -> dict:
        """Trả về dict settings 'like human' từ UI controls."""
        style_label = self._hs_scroll_style.currentText()
        profile_label = self._hs_profile.currentText()
        speed_min = self._hs_speed_min.value() or None
        speed_max = self._hs_speed_max.value() or None
        return {
            "min_duration":         float(self._hs_min_dur.value()),
            "max_duration":         float(self._hs_max_dur.value()),
            "click_prob":           self._hs_click_prob.value() / 100.0,
            "burst_prob":           self._hs_burst_prob.value() / 100.0,
            "scroll_dist_min":      self._hs_scroll_min.value(),
            "scroll_dist_max":      self._hs_scroll_max.value(),
            "read_pause_min":       self._hs_read_min.value(),
            "read_pause_max":       self._hs_read_max.value(),
            "scroll_focus":         self._hs_scroll_focus.value() / 10.0,
            "overshoot_prob":       self._hs_overshoot.value() / 100.0,
            "swipe_speed_min_ms":   speed_min,
            "swipe_speed_max_ms":   speed_max,
            "scroll_style_weights": self._STYLE_MAP.get(style_label),
            "profile":              self._PROFILE_MAP.get(profile_label),
        }

    def get_randomized_human_settings(self) -> dict:
        """Generate a randomized settings dict using UI values as bounds.

        Each call produces independent random values within the ranges set
        in the UI controls — used for the 'Randomly different' behavior mode.
        """
        import random as _rnd

        # Duration: random point within [min_dur, max_dur]
        min_dur = float(self._hs_min_dur.value())
        max_dur = float(self._hs_max_dur.value())
        dur = _rnd.uniform(min_dur, max_dur)

        # Read pause: random within [read_min, read_max]
        read_min = self._hs_read_min.value()
        read_max = self._hs_read_max.value()
        read_p = _rnd.uniform(read_min, read_max)

        # Scroll distance: random range within the UI bounds
        sd_min = self._hs_scroll_min.value()
        sd_max = self._hs_scroll_max.value()
        a = _rnd.randint(sd_min, sd_max)
        b = _rnd.randint(sd_min, sd_max)
        scroll_dist_min, scroll_dist_max = (min(a, b), max(a, b)) if a != b else (a, a + 50)

        # Click / burst prob: random within [0, UI value]
        click_prob = _rnd.uniform(0.05, self._hs_click_prob.value() / 100.0)
        burst_prob = _rnd.uniform(0.05, self._hs_burst_prob.value() / 100.0)

        # Scroll focus / overshoot: random within full slider range
        scroll_focus = _rnd.randint(5, 30) / 10.0
        overshoot_prob = _rnd.randint(0, 60) / 100.0

        # Swipe speed: random within [0, UI values], None = auto
        raw_speed_min = self._hs_speed_min.value()
        raw_speed_max = self._hs_speed_max.value()
        if raw_speed_max:
            speed_min_r = _rnd.randint(0, raw_speed_max) or None
            speed_max_r = _rnd.randint(speed_min_r or 0, raw_speed_max) or None
        else:
            speed_min_r = speed_max_r = None

        # Scroll style: random from all options (ignore UI selection)
        style_keys = list(self._STYLE_MAP.keys())
        style_label = _rnd.choice(style_keys)

        # Profile: random from all options (ignore UI selection)
        profile_keys = list(self._PROFILE_MAP.keys())
        profile_label = _rnd.choice(profile_keys)

        return {
            "min_duration":         dur,
            "max_duration":         dur,
            "click_prob":           click_prob,
            "burst_prob":           burst_prob,
            "scroll_dist_min":      scroll_dist_min,
            "scroll_dist_max":      scroll_dist_max,
            "read_pause_min":       read_p,
            "read_pause_max":       read_p,
            "scroll_focus":         scroll_focus,
            "overshoot_prob":       overshoot_prob,
            "swipe_speed_min_ms":   speed_min_r,
            "swipe_speed_max_ms":   speed_max_r,
            "scroll_style_weights": self._STYLE_MAP.get(style_label),
            "profile":              self._PROFILE_MAP.get(profile_label),
        }
        try:
            out = subprocess.check_output(
                ["adb", "devices", "-l"],
                text=True, startupinfo=_si, stderr=subprocess.DEVNULL
            )
            lines = out.strip().splitlines()[1:]

            devices = []
            for line in lines:
                if "device" not in line:
                    continue

                parts = line.split()
                serial = parts[0]

                model = "UNKNOWN"
                for p in parts:
                    if p.startswith("model:"):
                        model = p.split("model:")[1]
                        break

                devices.append({
                    "serial": serial,
                    "model": model,
                    "raw": line
                })

            return devices
        except Exception as e:
            print(f"Error getting devices: {e}")
            return []

    def refresh_table(self):
        try:
            try:
                rows = CSVHelper.read_csv(self.data_csv)
            except FileNotFoundError:
                rows = []

            num_rows = len(rows)
            if num_rows == 0:
                self.table.setRowCount(0)
                self.status_update.emit('No data in CSV found')
                return

            self.table.blockSignals(True)
            self.table.setRowCount(num_rows)
            self.table.setColumnCount(7)

            non_editable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            editable = non_editable | Qt.ItemFlag.ItemIsEditable

            for row_idx in range(num_rows):
                model = rows[row_idx][0] if len(rows[row_idx]) > 0 else ""
                serial = rows[row_idx][1] if len(rows[row_idx]) > 1 else ""
                device_name = rows[row_idx][2] if len(rows[row_idx]) > 2 else ""

                # col 0 – # (row number, read-only)
                num_item = QTableWidgetItem(str(row_idx + 1))
                num_item.setFlags(non_editable)
                num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_idx, 0, num_item)

                device_name_item = QTableWidgetItem(device_name)
                device_name_item.setFlags(editable)
                self.table.setItem(row_idx, 1, device_name_item)

                serial_item = QTableWidgetItem(serial)
                serial_item.setFlags(non_editable)
                self.table.setItem(row_idx, 2, serial_item)

                model_item = QTableWidgetItem(model)
                model_item.setFlags(non_editable)
                self.table.setItem(row_idx, 3, model_item)

                # Proxy cols — placeholder until updated externally
                for col in (4, 5):
                    ph = QTableWidgetItem("—")
                    ph.setFlags(non_editable)
                    ph.setForeground(Qt.GlobalColor.gray)
                    self.table.setItem(row_idx, col, ph)

                # Preview column: contains Preview and Close buttons
                preview_widget = QWidget()
                ph_layout = QHBoxLayout(preview_widget)
                ph_layout.setContentsMargins(2, 2, 2, 2)
                ph_layout.setSpacing(4)
                open_btn = QPushButton("Open")
                open_btn.setFixedSize(64, 24)
                close_btn = QPushButton("Close")
                close_btn.setFixedSize(48, 24)

                # Connect buttons — use partial to capture serial
                open_btn.clicked.connect(partial(self._on_preview_clicked, serial))
                close_btn.clicked.connect(partial(self._on_close_preview_clicked, serial))

                ph_layout.addWidget(open_btn)
                ph_layout.addWidget(close_btn)
                ph_layout.addStretch()
                self.table.setCellWidget(row_idx, 6, preview_widget)

            self.table.setColumnWidth(0, 36)   # No
            self.table.setColumnWidth(6, 140)  # Actions (Preview + Close buttons)
            self.table.blockSignals(False)

            self.status_update.emit(f'Loaded {len(rows)} rows from CSV')

        except Exception as e:
            self.status_update.emit(f'Error refreshing table: {str(e)}')
            print(f"Error details: {e}")

    def refresh_devices_and_csv(self):
        try:
            devices = self.get_devices_with_model()

            # Đọc device_name cũ từ CSV (nếu có) để giữ lại khi refresh
            try:
                existing = CSVHelper.read_csv(self.data_csv)
                existing_names = {row[1]: row[2] for row in existing if len(row) > 2}
            except Exception:
                existing_names = {}

            rows = []
            for device in devices:
                serial = device["serial"]
                device_name = existing_names.get(serial, "")
                rows.append([device["model"], serial, device_name])

            CSVHelper.write_csv(self.data_csv, rows)

            self.refresh_table()
            self.status_update.emit(f'Updated with {len(devices)} devices')

        except Exception as e:
            self.status_update.emit(f'Error refreshing devices: {str(e)}')
            print(f"Error details: {e}")

    def on_ads_link_changed(self, row_idx, new_link):
        """Kept for backward compatibility — no longer used."""
        pass

    def on_selection_changed(self):
        """Clear focus when selection changes."""
        self.table.clearFocus()

    def table_mouse_press_event(self, event):
        """Handle mouse press to clear focus before normal processing."""
        # Clear focus first
        self.table.clearFocus()
        self.table.setCurrentItem(None)
        # Then call the original mouse press event
        QTableWidget.mousePressEvent(self.table, event)

    def table_focus_out_event(self, event):
        """Handle focus out to clear cell focus."""
        # Clear focus when table loses focus
        self.table.clearFocus()
        self.table.setCurrentItem(None)
        # Call original focus out event
        QTableWidget.focusOutEvent(self.table, event)

    def table_mouse_double_click_event(self, event):
        """Handle double-click on table cells for inline editing."""
        index = self.table.indexAt(event.pos())
        if index.isValid():
            row = index.row()
            col = index.column()

            if col == 1:  # Device Name column
                item = self.table.item(row, col)
                if item:
                    self.table.editItem(item)

        QTableWidget.mouseDoubleClickEvent(self.table, event)

    def on_table_item_changed(self, item):
        """Lưu CSV khi user chỉnh sửa ô Device Name (cột 1)."""
        if item.column() != 1:
            return
        self.save_csv_changes()

    def save_csv_changes(self):
        """Save current table data to CSV."""
        try:
            rows = []
            for row_idx in range(self.table.rowCount()):
                device_name = self.table.item(row_idx, 1)
                serial = self.table.item(row_idx, 2)
                model = self.table.item(row_idx, 3)
                rows.append([
                    model.text() if model else "",
                    serial.text() if serial else "",
                    device_name.text() if device_name else "",
                ])
            CSVHelper.write_csv(self.data_csv, rows)
        except Exception as e:
            print(f"Error saving CSV: {e}")

    # Preview button callbacks
    def _on_preview_clicked(self, serial: str):
        try:
            self.preview_requested.emit(serial)
        except Exception:
            pass

    def _on_close_preview_clicked(self, serial: str):
        try:
            self.preview_closed.emit(serial)
        except Exception:
            pass

    def set_preview_active(self, serial: str, active: bool):
        """Enable or disable the Preview button for the row matching `serial`.
        When active=True the Preview button is disabled (greyed out).
        """
        for row in range(self.table.rowCount()):
            serial_item = self.table.item(row, 2)
            if serial_item and serial_item.text().strip() == serial:
                cell_w = self.table.cellWidget(row, 6)
                if cell_w:
                    # The first child button is Preview
                    btns = cell_w.findChildren(QPushButton)
                    if btns:
                        btns[0].setEnabled(not active)
                        btns[0].setStyleSheet(
                            "QPushButton { background: #bbb; color: #777; border-radius:3px; font-size:11px; }"
                            if active else ""
                        )
                break

    def update_proxy_statuses(self, proxy_data: dict):
        """Update proxy status columns (4, 5) keyed by serial.
        proxy_data = { serial: {"type": str, "host_port": str} }
        """
        non_editable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        self.table.blockSignals(True)
        for row_idx in range(self.table.rowCount()):
            serial_item = self.table.item(row_idx, 2)
            serial = serial_item.text() if serial_item else ""
            info = proxy_data.get(serial, {})
            ptype = info.get("type", "—")
            hport = info.get("host_port", "—")

            t_item = QTableWidgetItem(ptype)
            t_item.setFlags(non_editable)
            h_item = QTableWidgetItem(hport)
            h_item.setFlags(non_editable)

            if ptype not in ("—", "None"):
                t_item.setForeground(Qt.GlobalColor.darkGreen)
                h_item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                t_item.setForeground(Qt.GlobalColor.gray)
                h_item.setForeground(Qt.GlobalColor.gray)

            self.table.setItem(row_idx, 4, t_item)
            self.table.setItem(row_idx, 5, h_item)
        self.table.blockSignals(False)

    def get_table_data(self):
        """Get table data for worker operations."""
        table_data = []
        row_count = self.table.rowCount()
        for row in range(row_count):
            serial_item = self.table.item(row, 2)
            serial = serial_item.text() if serial_item else ""
            table_data.append({'serial': serial, 'row_index': row})
        return table_data

    def get_devices_with_model(self):
        try:
            # Get connected devices
            result = subprocess.run(
                ["adb", "devices"],
                startupinfo=subprocess.STARTUPINFO() if os.name == 'nt' else None,
                capture_output=True,
                text=True,
                timeout=10
            )

            devices = []
            lines = result.stdout.strip().split('\n')

            # Skip header line, process device lines
            for line in lines[1:]:
                if line.strip() and '\tdevice' in line:
                    serial = line.split('\t')[0].strip()
                    if serial:
                        # Get model for this device
                        try:
                            model_result = subprocess.run(
                                ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
                                startupinfo=subprocess.STARTUPINFO() if os.name == 'nt' else None,
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            model = model_result.stdout.strip() or "Unknown"
                        except Exception:
                            model = "Unknown"

                        devices.append({
                            "serial": serial,
                            "model": model
                        })

            return devices

        except Exception as e:
            print(f"Error getting devices: {e}")
            return []
