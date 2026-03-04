import time, random, logging
from urllib.parse import urlparse
from utils.cdp_chrome import ChromeCDP
from utils.cdp_helpers import InputDriver, get_webpage_safe_zone
from features.session_engine import browse_session

logger = logging.getLogger("adbflow.ads")




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
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QTableWidget, QTableWidgetItem, QHBoxLayout, QDialog, QLineEdit, QLabel, QDialogButtonBox, QFormLayout, QStyledItemDelegate, QTextEdit, QSizePolicy, QGroupBox, QDoubleSpinBox, QSpinBox, QSlider, QFrame, QComboBox
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
        self.copy_button.setFixedSize(24, 24)
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

    def edit_link(self, event=None):
        """Open dialog to edit the link."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Ads Link")
        dialog.setModal(True)

        layout = QVBoxLayout()

        link_input = QLineEdit(self.full_link)
        layout.addWidget(link_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_link = link_input.text().strip()
            self.set_link(new_link)
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
    ads_link_changed = Signal(int, str)  # Signal for ads link changes (row_idx, new_link)

    def __init__(self, data_csv="data.csv", parent=None):
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
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Model', 'Serial', 'Ads Link', 'Ads Info'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.on_table_item_changed)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.mousePressEvent = self.table_mouse_press_event
        self.table.focusOutEvent = self.table_focus_out_event
        self.table.mouseDoubleClickEvent = self.table_mouse_double_click_event

        # Dùng delegate riêng cho cột Serial để editor không bị tràn ra ngoài ô
        self._serial_delegate = SerialDelegate(self.table)
        self.table.setItemDelegateForColumn(1, self._serial_delegate)

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
        self._build_human_settings_section(layout)

        self.refresh_table()

    def _build_human_settings_section(self, parent_layout: QVBoxLayout):
        """Tạo section 'Like Human Behavior' bên dưới table."""
        group = QGroupBox("🤖 Like Human Behavior")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #ccc;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 4px;
                background-color: #fafafa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #333;
            }
        """)

        grid = QHBoxLayout()
        grid.setSpacing(16)
        grid.setContentsMargins(10, 6, 10, 8)

        # ── Cột 1: Duration & Read Pause ────────────────────────────────
        col1 = QVBoxLayout()
        col1.setSpacing(4)
        col1_title = QLabel("⏱ Duration (s)")
        col1_title.setStyleSheet("font-weight: bold; color: #555;")
        col1.addWidget(col1_title)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Min:"))
        self._hs_min_dur = QSpinBox()
        self._hs_min_dur.setRange(10, 600)
        self._hs_min_dur.setValue(60)
        self._hs_min_dur.setSuffix("s")
        self._hs_min_dur.setToolTip("Thời gian tối thiểu mỗi phiên lướt")
        dur_row.addWidget(self._hs_min_dur)
        dur_row.addWidget(QLabel("Max:"))
        self._hs_max_dur = QSpinBox()
        self._hs_max_dur.setRange(10, 600)
        self._hs_max_dur.setValue(90)
        self._hs_max_dur.setSuffix("s")
        self._hs_max_dur.setToolTip("Thời gian tối đa mỗi phiên lướt")
        dur_row.addWidget(self._hs_max_dur)
        col1.addLayout(dur_row)

        read_row = QHBoxLayout()
        read_row.addWidget(QLabel("Read min:"))
        self._hs_read_min = QDoubleSpinBox()
        self._hs_read_min.setRange(0.5, 30.0)
        self._hs_read_min.setValue(1.5)
        self._hs_read_min.setSuffix("s")
        self._hs_read_min.setSingleStep(0.5)
        self._hs_read_min.setToolTip("Thời gian dừng đọc tối thiểu")
        read_row.addWidget(self._hs_read_min)
        read_row.addWidget(QLabel("max:"))
        self._hs_read_max = QDoubleSpinBox()
        self._hs_read_max.setRange(0.5, 60.0)
        self._hs_read_max.setValue(6.0)
        self._hs_read_max.setSuffix("s")
        self._hs_read_max.setSingleStep(0.5)
        self._hs_read_max.setToolTip("Thời gian dừng đọc tối đa")
        read_row.addWidget(self._hs_read_max)
        col1.addLayout(read_row)
        grid.addLayout(col1)

        # ── Separator ────────────────────────────────────────────────────
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #ddd;")
        grid.addWidget(sep1)

        # ── Cột 2: Scroll Distance & Focus ──────────────────────────────
        col2 = QVBoxLayout()
        col2.setSpacing(4)
        col2_title = QLabel("� Scroll Distance & Focus")
        col2_title.setStyleSheet("font-weight: bold; color: #555;")
        col2.addWidget(col2_title)

        sdist_row = QHBoxLayout()
        sdist_row.addWidget(QLabel("Min:"))
        self._hs_scroll_min = QSpinBox()
        self._hs_scroll_min.setRange(50, 3000)
        self._hs_scroll_min.setValue(500)
        self._hs_scroll_min.setSuffix("px")
        self._hs_scroll_min.setSingleStep(50)
        self._hs_scroll_min.setToolTip("Khoảng cách scroll tối thiểu mỗi lần (px vật lý). 1080p ≈ 500–800")
        sdist_row.addWidget(self._hs_scroll_min)
        sdist_row.addWidget(QLabel("Max:"))
        self._hs_scroll_max = QSpinBox()
        self._hs_scroll_max.setRange(100, 4000)
        self._hs_scroll_max.setValue(1400)
        self._hs_scroll_max.setSuffix("px")
        self._hs_scroll_max.setSingleStep(50)
        self._hs_scroll_max.setToolTip("Khoảng cách scroll tối đa. 1080p ≈ 1200–1800")
        sdist_row.addWidget(self._hs_scroll_max)
        col2.addLayout(sdist_row)

        focus_row = QHBoxLayout()
        focus_row.addWidget(QLabel("Scroll focus:"))
        self._hs_scroll_focus = QSlider(Qt.Orientation.Horizontal)
        self._hs_scroll_focus.setRange(5, 30)   # maps to 0.5–3.0
        self._hs_scroll_focus.setValue(10)       # default 1.0
        self._hs_scroll_focus.setFixedWidth(90)
        self._hs_scroll_focus.setToolTip(
            "Tăng độ ưu tiên scroll so với click.\n"
            "1.0 = cân bằng  |  2.0 = scroll nhiều gấp đôi  |  3.0 = gần như chỉ scroll"
        )
        self._hs_scroll_focus_label = QLabel("1.0×")
        self._hs_scroll_focus_label.setFixedWidth(32)
        self._hs_scroll_focus.valueChanged.connect(
            lambda v: self._hs_scroll_focus_label.setText(f"{v/10:.1f}×")
        )
        focus_row.addWidget(self._hs_scroll_focus)
        focus_row.addWidget(self._hs_scroll_focus_label)
        col2.addLayout(focus_row)

        overshoot_row = QHBoxLayout()
        overshoot_row.addWidget(QLabel("Overshoot %:"))
        self._hs_overshoot = QSlider(Qt.Orientation.Horizontal)
        self._hs_overshoot.setRange(0, 60)
        self._hs_overshoot.setValue(20)
        self._hs_overshoot.setFixedWidth(90)
        self._hs_overshoot.setToolTip(
            "Xác suất scroll vượt đích rồi kéo lại (tự nhiên hơn)\n"
            "0% = không overshoot  |  60% = rất hay overshoot"
        )
        self._hs_overshoot_label = QLabel("20%")
        self._hs_overshoot_label.setFixedWidth(32)
        self._hs_overshoot.valueChanged.connect(
            lambda v: self._hs_overshoot_label.setText(f"{v}%")
        )
        overshoot_row.addWidget(self._hs_overshoot)
        overshoot_row.addWidget(self._hs_overshoot_label)
        col2.addLayout(overshoot_row)
        grid.addLayout(col2)

        # ── Separator ────────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #ddd;")
        grid.addWidget(sep2)

        # ── Cột 3: Swipe Speed & Style ───────────────────────────────────
        col3 = QVBoxLayout()
        col3.setSpacing(4)
        col3_title = QLabel("⚡ Swipe Speed & Style")
        col3_title.setStyleSheet("font-weight: bold; color: #555;")
        col3.addWidget(col3_title)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Min ms:"))
        self._hs_speed_min = QSpinBox()
        self._hs_speed_min.setRange(50, 2000)
        self._hs_speed_min.setValue(0)
        self._hs_speed_min.setSpecialValueText("Auto")
        self._hs_speed_min.setSuffix("ms")
        self._hs_speed_min.setSingleStep(20)
        self._hs_speed_min.setToolTip(
            "Thời gian ngắn nhất của 1 lần swipe (0 = tự động theo profile).\n"
            "Nhỏ = nhanh; lớn = chậm, cẩn thận hơn."
        )
        speed_row.addWidget(self._hs_speed_min)
        speed_row.addWidget(QLabel("Max:"))
        self._hs_speed_max = QSpinBox()
        self._hs_speed_max.setRange(50, 3000)
        self._hs_speed_max.setValue(0)
        self._hs_speed_max.setSpecialValueText("Auto")
        self._hs_speed_max.setSuffix("ms")
        self._hs_speed_max.setSingleStep(20)
        self._hs_speed_max.setToolTip("Thời gian dài nhất của 1 lần swipe (0 = tự động)")
        speed_row.addWidget(self._hs_speed_max)
        col3.addLayout(speed_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Scroll style:"))
        self._hs_scroll_style = QComboBox()
        self._hs_scroll_style.addItems([
            "Mixed (auto)",
            "Normal (Bezier)",
            "Flash (fast flick)",
            "Zigzag (drift)",
            "Stutter (hesitant)",
        ])
        self._hs_scroll_style.setCurrentIndex(0)
        self._hs_scroll_style.setToolTip(
            "Mixed = tự chọn ngẫu nhiên (tự nhiên nhất)\n"
            "Normal = Bezier cong, giống ngón tay thật\n"
            "Flash = vuốt nhanh liên tục\n"
            "Zigzag = kéo lệch sang hai bên\n"
            "Stutter = dừng ngắn giữa chừng"
        )
        style_row.addWidget(self._hs_scroll_style)
        col3.addLayout(style_row)
        grid.addLayout(col3)

        # ── Separator ────────────────────────────────────────────────────
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet("color: #ddd;")
        grid.addWidget(sep3)

        # ── Cột 4: Click, Burst & Profile ───────────────────────────────
        col4 = QVBoxLayout()
        col4.setSpacing(4)
        col4_title = QLabel("👆 Click & Profile")
        col4_title.setStyleSheet("font-weight: bold; color: #555;")
        col4.addWidget(col4_title)

        click_row = QHBoxLayout()
        click_row.addWidget(QLabel("Click %:"))
        self._hs_click_prob = QSlider(Qt.Orientation.Horizontal)
        self._hs_click_prob.setRange(5, 80)
        self._hs_click_prob.setValue(30)
        self._hs_click_prob.setFixedWidth(90)
        self._hs_click_prob.setToolTip("Xác suất click vào element (cao = click nhiều hơn)")
        self._hs_click_label = QLabel("30%")
        self._hs_click_label.setFixedWidth(36)
        self._hs_click_prob.valueChanged.connect(lambda v: self._hs_click_label.setText(f"{v}%"))
        click_row.addWidget(self._hs_click_prob)
        click_row.addWidget(self._hs_click_label)
        col4.addLayout(click_row)

        burst_row = QHBoxLayout()
        burst_row.addWidget(QLabel("Burst %:"))
        self._hs_burst_prob = QSlider(Qt.Orientation.Horizontal)
        self._hs_burst_prob.setRange(5, 80)
        self._hs_burst_prob.setValue(35)
        self._hs_burst_prob.setFixedWidth(90)
        self._hs_burst_prob.setToolTip("Xác suất burst scroll liên tiếp nhiều lần")
        self._hs_burst_label = QLabel("35%")
        self._hs_burst_label.setFixedWidth(36)
        self._hs_burst_prob.valueChanged.connect(lambda v: self._hs_burst_label.setText(f"{v}%"))
        burst_row.addWidget(self._hs_burst_prob)
        burst_row.addWidget(self._hs_burst_label)
        col4.addLayout(burst_row)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self._hs_profile = QComboBox()
        self._hs_profile.addItems([
            "Auto (random)",
            "Fast scroller",
            "Careful reader",
            "Distracted",
        ])
        self._hs_profile.setCurrentIndex(0)
        self._hs_profile.setToolTip(
            "Auto = chọn ngẫu nhiên mỗi session\n"
            "Fast scroller = scroll nhanh, ít đọc\n"
            "Careful reader = scroll chậm, dừng đọc nhiều\n"
            "Distracted = không đều, thỉnh thoảng bỏ dở"
        )
        profile_row.addWidget(self._hs_profile)
        col4.addLayout(profile_row)
        grid.addLayout(col4)

        group.setLayout(grid)
        parent_layout.addWidget(group)

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

    def get_devices_with_model(self):
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
            self.table.setColumnCount(4)

            for row_idx in range(num_rows):
                model = rows[row_idx][0] if len(rows[row_idx]) > 0 else ""
                serial = rows[row_idx][1] if len(rows[row_idx]) > 1 else ""
                ads_link = rows[row_idx][2] if len(rows[row_idx]) > 2 else ""
                ads_info = rows[row_idx][3] if len(rows[row_idx]) > 3 else ""

                model_item = QTableWidgetItem(model)
                serial_item = QTableWidgetItem(serial)
                ads_link_widget = AdsLinkWidget(ads_link)
                ads_info_item = QTableWidgetItem(ads_info)

                # Model và Ads Info không cho edit trực tiếp, Serial cho phép edit
                non_editable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                model_item.setFlags(non_editable)
                # Serial column is now editable
                serial_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
                ads_info_item.setFlags(non_editable)

                self.table.setItem(row_idx, 0, model_item)
                self.table.setItem(row_idx, 1, serial_item)
                self.table.setCellWidget(row_idx, 2, ads_link_widget)  # Use setCellWidget for custom widget
                ads_link_widget.link_changed.connect(lambda new_link, row=row_idx: self.on_ads_link_changed(row, new_link))
                self.table.setItem(row_idx, 3, ads_info_item)

            self.table.resizeColumnsToContents()
            # Set minimum width for ads link column to accommodate the buttons
            if self.table.columnCount() > 2:
                min_width = 200  # Minimum width to show truncated text + buttons
                current_width = self.table.columnWidth(2)
                if current_width < min_width:
                    self.table.setColumnWidth(2, min_width)
            self.table.blockSignals(False)

            self.status_update.emit(f'Loaded {len(rows)} rows from CSV')

        except Exception as e:
            self.status_update.emit(f'Error refreshing table: {str(e)}')
            print(f"Error details: {e}")

    def refresh_devices_and_csv(self):
        try:
            devices = self.get_devices_with_model()

            # Đọc ads_link cũ từ CSV (nếu có) để giữ lại khi refresh
            try:
                existing = CSVHelper.read_csv(self.data_csv)
                existing_links = {row[1]: row[2] for row in existing if len(row) > 2}
                existing_info = {row[1]: row[3] for row in existing if len(row) > 3}
            except Exception:
                existing_links = {}
                existing_info = {}

            rows = []
            for device in devices:
                serial = device["serial"]
                ads_link = existing_links.get(serial, "")
                ads_info = existing_info.get(serial, "")
                rows.append([device["model"], serial, ads_link, ads_info])

            CSVHelper.write_csv(self.data_csv, rows)

            self.refresh_table()
            self.status_update.emit(f'Updated with {len(devices)} devices')

        except Exception as e:
            self.status_update.emit(f'Error refreshing devices: {str(e)}')
            print(f"Error details: {e}")

    def on_ads_link_changed(self, row_idx, new_link):
        """Handle ads link changes from custom widget."""
        self.ads_link_changed.emit(row_idx, new_link)
        self.save_csv_changes()

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
        # Get the index at the double-click position
        index = self.table.indexAt(event.pos())
        if index.isValid():
            row = index.row()
            col = index.column()

            if col == 1:  # Serial column
                item = self.table.item(row, col)
                if item:
                    self.table.editItem(item)
            elif col == 2:  # Ads link column
                # Get the AdsLinkWidget and trigger inline editing
                widget = self.table.cellWidget(row, col)
                if isinstance(widget, AdsLinkWidget):
                    widget.start_inline_edit()
            elif col == 3:  # Ads Info column — mở modal xem full text
                item = self.table.item(row, col)
                full_text = item.text() if item else ""
                self.show_ads_info_modal(full_text)

        # Call parent event
        QTableWidget.mouseDoubleClickEvent(self.table, event)

    def show_ads_info_modal(self, text: str):
        """Mở dialog hiển thị đầy đủ nội dung Ads Info."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Ads Info")
        dialog.setModal(True)
        dialog.resize(520, 320)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text if text else "(Chưa có thông tin)")
        text_edit.setStyleSheet("""
            QTextEdit {
                font-size: 13px;
                padding: 6px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #fafafa;
            }
        """)
        layout.addWidget(text_edit)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        dialog.exec()

    def on_table_item_changed(self, item):
        """Lưu CSV khi user chỉnh sửa ô Serial (cột 1).
        Cột 2 (Ads Link) dùng setCellWidget nên itemChanged không bắn cho nó —
        thay vào đó, AdsLinkWidget.link_changed signal xử lý riêng.
        """
        if item.column() != 1:
            return
        self.save_csv_changes()

    def save_csv_changes(self):
        """Save current table data to CSV."""
        try:
            rows = []
            for row_idx in range(self.table.rowCount()):
                model = self.table.item(row_idx, 0)
                serial = self.table.item(row_idx, 1)
                # For ads link, get from custom widget
                ads_widget = self.table.cellWidget(row_idx, 2)
                ads_link = ads_widget.get_link() if ads_widget else ""
                ads_info = self.table.item(row_idx, 3)
                rows.append([
                    model.text() if model else "",
                    serial.text() if serial else "",
                    ads_link,
                    ads_info.text() if ads_info else "",
                ])
            CSVHelper.write_csv(self.data_csv, rows)
        except Exception as e:
            print(f"Error saving CSV: {e}")

    def on_row_result(self, row_idx: int, ads_info: str):
        """Cập nhật cột Ads Info khi một device chạy xong."""
        self.table.blockSignals(True)
        item = QTableWidgetItem(ads_info)
        non_editable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        item.setFlags(non_editable)
        self.table.setItem(row_idx, 3, item)
        self.table.resizeColumnToContents(3)
        self.table.blockSignals(False)
        # Lưu CSV ngay
        try:
            rows = []
            for r in range(self.table.rowCount()):
                model = self.table.item(r, 0)
                serial = self.table.item(r, 1)
                # For ads link, get from custom widget
                ads_widget = self.table.cellWidget(r, 2)
                ads_link = ads_widget.get_link() if ads_widget else ""
                ads_info = self.table.item(r, 3)
                rows.append([
                    model.text() if model else "",
                    serial.text() if serial else "",
                    ads_link,
                    ads_info.text() if ads_info else "",
                ])
            CSVHelper.write_csv(self.data_csv, rows)
        except Exception as e:
            print(f"Error saving ads info: {e}")

    def get_table_data(self):
        """Get table data for worker operations."""
        table_data = []
        row_count = self.table.rowCount()
        for row in range(row_count):
            serial_item = self.table.item(row, 1)
            # Get ads link from custom widget
            ads_widget = self.table.cellWidget(row, 2)
            ads_link = ads_widget.get_link() if ads_widget else ""
            serial = serial_item.text() if serial_item else ""
            table_data.append({'serial': serial, 'ads_link': ads_link, 'row_index': row})
        return table_data
