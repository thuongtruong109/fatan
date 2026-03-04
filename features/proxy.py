"""
Proxy configuration tab.
Lets users set HTTP proxy or SOCKS5 proxy per-device (or all devices at once)
via Android's global ADB proxy settings.
"""
from __future__ import annotations

import subprocess
import os
from typing import List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QComboBox, QSpacerItem, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt

# ── ADB startup-info (Windows) ──────────────────────────────────────────
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW


def _adb(serial: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        startupinfo=_si,
        capture_output=True,
        text=True,
    )


class ProxyWidget(QWidget):
    """Proxy / SOCKS5 configuration panel rendered as a tab page."""

    status_update = Signal(str)
    proxy_status_updated = Signal(dict)  # { serial: {"type": str, "host_port": str} }

    PROXY_TYPES = ["None (clear)", "HTTP / HTTPS", "SOCKS5"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # ── Global proxy config form ─────────────────────────────────────
        cfg_group = QGroupBox("🌐 Proxy Configuration")
        cfg_group.setStyleSheet("""
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
        cfg_layout = QVBoxLayout()
        cfg_layout.setContentsMargins(10, 10, 10, 10)
        cfg_layout.setSpacing(10)

        # Proxy type selector
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Proxy type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(self.PROXY_TYPES)
        self._type_combo.setFixedWidth(160)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        cfg_layout.addLayout(type_row)

        # Host / Port
        form = QFormLayout()
        form.setSpacing(8)
        self._host_input = QLineEdit()
        self._host_input.setPlaceholderText("e.g. 192.168.1.100  or  proxy.example.com")
        self._host_input.setMaximumWidth(280)
        form.addRow(QLabel("Host / IP:"), self._host_input)

        self._port_input = QLineEdit()
        self._port_input.setPlaceholderText("e.g. 8080")
        self._port_input.setMaximumWidth(100)
        form.addRow(QLabel("Port:"), self._port_input)

        # Auth (optional, HTTP only)
        self._user_input = QLineEdit()
        self._user_input.setPlaceholderText("optional")
        self._user_input.setMaximumWidth(180)
        form.addRow(QLabel("Username:"), self._user_input)

        self._pass_input = QLineEdit()
        self._pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_input.setPlaceholderText("optional")
        self._pass_input.setMaximumWidth(180)
        form.addRow(QLabel("Password:"), self._pass_input)

        cfg_layout.addLayout(form)

        # Apply scope
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Apply to:"))
        self._scope_combo = QComboBox()
        self._scope_combo.addItems(["All devices", "Selected devices only"])
        self._scope_combo.setFixedWidth(180)
        scope_row.addWidget(self._scope_combo)
        scope_row.addStretch()
        cfg_layout.addLayout(scope_row)

        # Buttons
        btn_row = QHBoxLayout()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch()

        refresh_btn = QPushButton("🔄 Refresh status")
        refresh_btn.setFixedWidth(140)
        refresh_btn.setToolTip("Refresh proxy status columns in the device table")
        refresh_btn.clicked.connect(self.refresh_device_status)
        btn_row.addWidget(refresh_btn)

        apply_btn = QPushButton("✅ Apply proxy")
        apply_btn.setFixedWidth(130)
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)

        clear_btn = QPushButton("🚫 Clear proxy")
        clear_btn.setFixedWidth(130)
        clear_btn.setToolTip("Remove proxy settings from all / selected devices")
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(clear_btn)

        cfg_layout.addLayout(btn_row)
        cfg_group.setLayout(cfg_layout)
        root.addWidget(cfg_group)

        root.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Initial UI state
        self._on_type_changed(0)

    # ── helpers ──────────────────────────────────────────────────────────
    def _on_type_changed(self, idx: int):
        is_none = idx == 0
        is_socks = idx == 2
        self._host_input.setEnabled(not is_none)
        self._port_input.setEnabled(not is_none)
        # Auth only for HTTP
        self._user_input.setEnabled(not is_none and not is_socks)
        self._pass_input.setEnabled(not is_none and not is_socks)

    def _set_status(self, msg: str, ok: bool = True):
        color = "#2e7d32" if ok else "#c62828"
        self._status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._status_label.setText(msg)
        self.status_update.emit(msg)

    def _connected_serials(self) -> List[str]:
        try:
            out = subprocess.check_output(
                ["adb", "devices"], startupinfo=_si, text=True, stderr=subprocess.DEVNULL
            )
            serials = []
            for line in out.splitlines()[1:]:
                line = line.strip()
                if line and "\t" in line:
                    serial, state = line.split("\t", 1)
                    if state.strip() == "device":
                        serials.append(serial.strip())
            return serials
        except Exception:
            return []

    def _target_serials(self) -> List[str]:
        all_serials = self._connected_serials()
        if self._scope_combo.currentIndex() == 0:
            return all_serials
        # "Selected devices only" — return all (no internal table selection anymore)
        return all_serials

    # ── proxy application ────────────────────────────────────────────────
    def _on_apply(self):
        ptype = self._type_combo.currentIndex()
        if ptype == 0:
            self._on_clear()
            return

        host = self._host_input.text().strip()
        port = self._port_input.text().strip()
        if not host or not port:
            self._set_status("⚠️  Host and port are required.", ok=False)
            return
        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                raise ValueError
        except ValueError:
            self._set_status("⚠️  Port must be a number between 1–65535.", ok=False)
            return

        serials = self._target_serials()
        if not serials:
            self._set_status("⚠️  No connected devices found.", ok=False)
            return

        ok_count = 0
        for serial in serials:
            try:
                if ptype == 1:
                    # HTTP proxy — use Android global_http_proxy setting
                    proxy_val = f"{host}:{port_int}"
                    user = self._user_input.text().strip()
                    passwd = self._pass_input.text().strip()
                    if user:
                        proxy_val = f"{user}:{passwd}@{host}:{port_int}" if passwd else f"{user}@{host}:{port_int}"
                    _adb(serial, "shell", "settings", "put", "global", "http_proxy", proxy_val)
                    # Also set via global settings for Android 8+
                    _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_host", host)
                    _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_port", str(port_int))
                    if user:
                        _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_username", user)
                        if passwd:
                            _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_password", passwd)

                elif ptype == 2:
                    # SOCKS5 — set via Android system properties
                    _adb(serial, "shell", "settings", "put", "global", "http_proxy", "")
                    _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_host", "")
                    _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_port", "0")
                    _adb(serial, "shell", "setprop", "net.socks5.host", host)
                    _adb(serial, "shell", "setprop", "net.socks5.port", str(port_int))

                ok_count += 1
            except Exception as e:
                self._set_status(f"❌ {serial}: {e}", ok=False)

        type_label = "HTTP" if ptype == 1 else "SOCKS5"
        self._set_status(f"✅ {type_label} proxy applied to {ok_count}/{len(serials)} device(s).")
        self.refresh_device_status()

    def _on_clear(self):
        serials = self._target_serials()
        if not serials:
            self._set_status("⚠️  No connected devices found.", ok=False)
            return

        ok_count = 0
        for serial in serials:
            try:
                # Clear HTTP proxy
                _adb(serial, "shell", "settings", "put", "global", "http_proxy", ":0")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_host", "")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_port", "0")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_username", "")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_password", "")
                # Clear SOCKS5 props
                _adb(serial, "shell", "setprop", "net.socks5.host", "")
                _adb(serial, "shell", "setprop", "net.socks5.port", "0")
                ok_count += 1
            except Exception as e:
                self._set_status(f"❌ {serial}: {e}", ok=False)

        self._set_status(f"🚫 Proxy cleared on {ok_count}/{len(serials)} device(s).")
        self.refresh_device_status()

    # ── status ─────────────────────────────────────────────────────────────
    def refresh_device_status(self):
        """Read proxy settings from all connected devices and emit proxy_status_updated."""
        serials = self._connected_serials()
        proxy_data: dict = {}

        for serial in serials:
            proxy_host = self._read_prop(serial, "global_http_proxy_host")
            proxy_port = self._read_prop(serial, "global_http_proxy_port")
            socks_host = self._read_setprop(serial, "net.socks5.host")

            if socks_host:
                socks_port = self._read_setprop(serial, "net.socks5.port")
                proxy_data[serial] = {"type": "SOCKS5", "host_port": f"{socks_host}:{socks_port}"}
            elif proxy_host and proxy_host not in ("", "null"):
                proxy_data[serial] = {"type": "HTTP", "host_port": f"{proxy_host}:{proxy_port}"}
            else:
                proxy_data[serial] = {"type": "None", "host_port": "—"}

        self.proxy_status_updated.emit(proxy_data)

    def _read_prop(self, serial: str, key: str) -> str:
        try:
            r = _adb(serial, "shell", "settings", "get", "global", key)
            val = r.stdout.strip()
            return "" if val in ("null", "0", "") else val
        except Exception:
            return ""

    def _read_setprop(self, serial: str, key: str) -> str:
        try:
            r = _adb(serial, "shell", "getprop", key)
            val = r.stdout.strip()
            return "" if val in ("", "0") else val
        except Exception:
            return ""
