"""
Settings tab content widget.
Replaces the old modal dialog — lives as a tab page in the right panel.
"""
from __future__ import annotations

import json
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QSpacerItem, QSizePolicy,
)
from PySide6.QtCore import Signal


class SettingsWidget(QWidget):
    """Settings form rendered as an inline tab content (no modal)."""

    settings_saved = Signal(dict)   # emitted after user saves

    DEFAULTS = {
        "preview_width": 400,
        "preview_height": 800,
    }

    def __init__(self, settings_file: str = "settings.json", parent=None):
        super().__init__(parent)
        self.settings_file = settings_file
        self._data: dict = dict(self.DEFAULTS)
        self._load()
        self._build_ui()

    # ── persistence ─────────────────────────────────────────────────────
    def _load(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r") as f:
                    saved = json.load(f)
                self._data.update({k: saved[k] for k in self.DEFAULTS if k in saved})
        except Exception as e:
            print(f"[Settings] load error: {e}")

    def _save(self):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            print(f"[Settings] save error: {e}")

    # ── public accessors ─────────────────────────────────────────────────
    def get(self, key: str, default=None):
        return self._data.get(key, default)

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # ── Scrcpy Preview ───────────────────────────────────────────────
        preview_group = QGroupBox("📱 Scrcpy Preview")
        preview_group.setStyleSheet("""
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
        form = QFormLayout()
        form.setContentsMargins(10, 8, 10, 10)
        form.setSpacing(8)

        self._width_input = QLineEdit(str(self._data["preview_width"]))
        self._width_input.setPlaceholderText("e.g. 400")
        self._width_input.setMaximumWidth(120)
        form.addRow(QLabel("Preview Width (px):"), self._width_input)

        self._height_input = QLineEdit(str(self._data["preview_height"]))
        self._height_input.setPlaceholderText("e.g. 800")
        self._height_input.setMaximumWidth(120)
        form.addRow(QLabel("Preview Height (px):"), self._height_input)

        preview_group.setLayout(form)
        root.addWidget(preview_group)

        # ── Save button row ──────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch()

        save_btn = QPushButton("💾 Save settings")
        save_btn.setFixedWidth(140)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        root.addLayout(btn_row)
        root.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

    def _on_save(self):
        try:
            w = int(self._width_input.text())
            h = int(self._height_input.text())
        except ValueError:
            self._status_label.setStyleSheet("color: #c62828; font-size: 12px;")
            self._status_label.setText("⚠️ Invalid values — enter integers only.")
            return

        self._data["preview_width"] = w
        self._data["preview_height"] = h
        self._save()
        self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")
        self._status_label.setText("✅ Settings saved.")
        self.settings_saved.emit(dict(self._data))
