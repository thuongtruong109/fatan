from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QDialog, QVBoxLayout, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QPixmap, QFont, QColor

# ── Palette ───────────────────────────────────────────────────────────────
_BAR_BG    = "#1e2a78"          # title bar fill
_TEXT      = "#222222"          # title label
_TEXT_MUT  = "rgba(255,255,255,0.65)"  # muted / secondary text on bar

# Win11-like button colours (at rest: transparent; hover: tinted)
_WIN_HOVER     = "rgba(255,255,255,0.10)"   # min / max subtle hover
_WIN_CLOSE_HOV = "#c42b1c"                  # close red hover
_MENU_HOVER    = "rgba(255,255,255,0.12)"   # ☰ / ℹ hover

# Dropdown menu
_DD_BG     = "#252b6b"
_DD_BORDER = "rgba(255,255,255,0.15)"
_DD_SEL    = "rgba(255,255,255,0.12)"

# ── Shared stylesheet helpers ──────────────────────────────────────────────
_TITLEBAR_SS = f"""
QWidget#TitleBar {{
    background-color: {_BAR_BG};
    border-bottom: 1px solid rgba(255,255,255,0.08);
}}
"""

# Generic transparent button used for all titlebar buttons
_BTN_BASE = """
QPushButton {{
    color: {fg};
    background: transparent;
    border: none;
    border-radius: {r}px;
    font-size: {fs}px;
    font-weight: {fw};
    padding: 0px;
    min-width: {w}px;
    max-width: {w}px;
    min-height: {h}px;
    max-height: {h}px;
}}
QPushButton:hover {{ background-color: {hover}; }}
QPushButton:pressed {{ background-color: {pressed}; }}
"""

def _ss(
    fg: str = _TEXT,
    hover: str = _WIN_HOVER,
    pressed: str = "rgba(255,255,255,0.18)",
    fs: int = 12,
    fw: str = "normal",
    w: int = 46,
    h: int = 32,
    r: int = 0,
) -> str:
    return _BTN_BASE.format(
        fg=fg, hover=hover, pressed=pressed,
        fs=fs, fw=fw, w=w, h=h, r=r,
    )

# ── About dialog ──────────────────────────────────────────────────────────
class AboutDialog(QDialog):
    """Modal 'About' window with project info, author, and features list."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("About Fatan")
        self.setMinimumWidth(460)
        self.setMaximumWidth(520)
        self.setStyleSheet("""
            QDialog {
                background-color: #f4f6ff;
            }
            QLabel {
                background: transparent;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(24, 20, 24, 20)
        body_lay.setSpacing(14)

        def _section(title: str) -> QLabel:
            lbl = QLabel(title)
            lbl.setStyleSheet(
                "color: #1a237e; font-weight: bold; font-size: 12px;"
                " border-bottom: 1px solid #c5cae9; padding-bottom: 4px;"
            )
            return lbl

        def _text(html: str) -> QLabel:
            lbl = QLabel(html)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #37474f; font-size: 11px; line-height: 1.5;")
            lbl.setOpenExternalLinks(True)
            return lbl

        body_lay.addWidget(_section("📌 About the project"))
        body_lay.addWidget(_text(
            "Fatan is an <b>Android Debugging Bridge Automation &amp; Management Tool</b> "
            "built with Python and PySide6. It allows you to manage multiple "
            "Android devices simultaneously — run ads automation, control "
            "screen state, inspect system services, manage packages and files, "
            "all from one unified desktop interface."
        ))

        body_lay.addWidget(_section("👤 Author"))
        body_lay.addWidget(_text(
            "GitHub: <a href='https://github.com/thuongtruong109'>"
            "thuongtruong109</a>"
        ))

        body_lay.addWidget(_section("✨ Features"))
        features = [
            ("🤖", "Simulator",  "Automate ads browsing across multiple devices"),
            ("🔗", "Proxy",      "Manage SOCKS5 proxies per device"),
            ("⚙️", "Settings",   "Configure preview size, ADB options"),
            ("ℹ️", "Dashboard",  "Live device info: battery, network, build"),
            ("⚡", "Actions",    "Send ADB input, keyevents, shell commands"),
            ("📦", "Packages",   "Install / uninstall / clear app data"),
            ("📁", "Files",      "Browse and manage device filesystem"),
            ("📊", "Activities", "Launch and inspect app activities"),
            ("🛠", "Toolbox",    "Setup keyboard, install apps in bulk"),
            ("⚙",  "Services",  "Inspect all running Android Binder services"),
        ]
        feat_html = "<table cellspacing='4' style='width:100%;'>"
        for icon, name, desc in features:
            feat_html += (
                f"<tr>"
                f"<td style='white-space:nowrap; color:#1a237e; font-weight:bold;"
                f" padding-right:8px;'>{icon} {name}</td>"
                f"<td style='color:#546e7a;'>{desc}</td>"
                f"</tr>"
            )
        feat_html += "</table>"
        feat_lbl = QLabel(feat_html)
        feat_lbl.setTextFormat(Qt.TextFormat.RichText)
        feat_lbl.setStyleSheet("font-size: 11px;")
        body_lay.addWidget(feat_lbl)

        b2 = QHBoxLayout()
        b2.addStretch()
        body_lay.addLayout(b2)

        root.addWidget(body)


# ── TitleBar ──────────────────────────────────────────────────────────────
class TitleBar(QWidget):
    """
    Custom Win11-style title bar.

    Signals
    -------
    menu_settings_clicked  – Settings button clicked
    menu_help_clicked      – Help button clicked
    menu_about_clicked     – About button clicked
    """

    menu_settings_clicked = Signal()
    menu_help_clicked      = Signal()
    menu_about_clicked     = Signal()

    def __init__(self, parent: QWidget, title: str = "App", icon_path: str = ""):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(34)
        self.setStyleSheet(_TITLEBAR_SS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._window = parent
        self._drag_pos: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(2)

        # ── App icon (16 × 16) ───────────────────────────────────────────
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(16, 16)
        self._icon_lbl.setScaledContents(True)
        self._icon_lbl.setStyleSheet("background: transparent;")
        if icon_path:
            pix = QPixmap(icon_path)
            if not pix.isNull():
                self._icon_lbl.setPixmap(pix)
        layout.addWidget(self._icon_lbl)
        layout.addSpacing(6)

        # ── Title label ──────────────────────────────────────────────────
        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: normal;"
            " background: transparent; letter-spacing: 0.2px;"
        )
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._title_lbl, 1)

        # ── ☰ Menu button (removed) ─────────────────────────────────────
        # Settings can be accessed via keyboard shortcut or other means

        # ── ❔ Help button ────────────────────────────────────────────────
        self._help_btn = QPushButton("❔")
        self._help_btn.setToolTip("Help")
        self._help_btn.setStyleSheet(_ss(hover=_MENU_HOVER, fs=13, w=36, h=34, r=4))
        self._help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._help_btn.clicked.connect(self.menu_help_clicked.emit)
        layout.addWidget(self._help_btn)

        # ── ℹ About button ───────────────────────────────────────────────
        self._about_btn = QPushButton("ℹ️")
        self._about_btn.setToolTip("About Fatan")
        self._about_btn.setStyleSheet(_ss(
           hover=_MENU_HOVER,
            fs=13, w=36, h=34, r=4,
        ))
        self._about_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._about_btn.clicked.connect(self._show_about)
        layout.addWidget(self._about_btn)

        layout.addStretch()

        # ── Win-control buttons (Win11: no border-radius, no bg at rest) ─
        # Minimize
        self._min_btn = QPushButton("➖")
        self._min_btn.setToolTip("Minimize")
        self._min_btn.setStyleSheet(_ss(fs=10, w=46, h=34))
        self._min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._min_btn.clicked.connect(self._on_minimize)
        layout.addWidget(self._min_btn)

        # Maximize / Restore
        self._max_btn = QPushButton("⬜")
        self._max_btn.setToolTip("Maximize")
        self._max_btn.setStyleSheet(_ss(fs=11, w=46, h=34))
        self._max_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._max_btn.clicked.connect(self._on_maximize)
        layout.addWidget(self._max_btn)

        # Close  — red hover like Win11
        self._close_btn = QPushButton("❌")
        self._close_btn.setToolTip("Close")
        self._close_btn.setStyleSheet(
            _ss(fs=11, w=46, h=34, hover=_WIN_CLOSE_HOV, pressed="#b52417")
        )
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._on_close)
        layout.addWidget(self._close_btn)

    def set_title(self, text: str):
        self._title_lbl.setText(text)

    def title(self) -> str:
        return self._title_lbl.text()

    def _on_minimize(self):
        self._window.showMinimized()

    def _on_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
            self._max_btn.setText("🟩")
            self._max_btn.setToolTip("Maximize")
        else:
            self._window.showMaximized()
            self._max_btn.setText("⬜")
            self._max_btn.setToolTip("Restore")

    def _on_close(self):
        self._window.close()

    def _show_about(self):
        dlg = AboutDialog(self._window)
        dlg.exec()
        self.menu_about_clicked.emit()

    # ── Drag-to-move ──────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint()
                - self._window.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
                self._max_btn.setText("🟩")
                self._max_btn.setToolTip("Maximize")
                self._drag_pos = QPoint(self._window.width() // 2, self.height() // 2)
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_maximize()
        super().mouseDoubleClickEvent(event)
