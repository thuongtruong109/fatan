"""
Proxy configuration tab.
Lets users set HTTP proxy or SOCKS5 proxy per-device (or all devices at once)
via Android's global ADB proxy settings.
"""
from __future__ import annotations

import subprocess
import os
import time
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

    PROXY_TYPES = ["None", "HTTP / HTTPS", "SOCKS5"]

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
                border: 1px solid #ddd;
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
        proxy_type_label = QLabel("Proxy type:")
        proxy_type_label.setFixedWidth(60)
        type_row.addWidget(proxy_type_label)
        self._type_combo = QComboBox()
        self._type_combo.addItems(self.PROXY_TYPES)
        self._type_combo.setFixedWidth(160)
        self._type_combo.setStyleSheet(
            "QComboBox {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  min-height: 20px;"
            "  max-height: 24px;"
            "}"
            "QComboBox:focus {"
            "  border: 1px solid #1976d2;"
            "}"
            "QComboBox::drop-down {"
            "  border: none; width: 20px;"
            "}"
        )
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo)

        host_label = QLabel("Host / IP:")
        host_label.setFixedWidth(60)
        type_row.addWidget(host_label)
        self._host_input = QLineEdit()
        self._host_input.setPlaceholderText("e.g. 192.168.1.100  or  proxy.example.com")
        self._host_input.setFixedWidth(160)
        self._host_input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  min-height: 20px;"
            "  max-height: 24px;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #1976d2;"
            "}"
        )
        type_row.addWidget(self._host_input)

        port_label = QLabel("Port:")
        port_label.setFixedWidth(60)
        type_row.addWidget(port_label)
        self._port_input = QLineEdit()
        self._port_input.setPlaceholderText("e.g. 8080")
        self._port_input.setFixedWidth(160)
        self._port_input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  min-height: 20px;"
            "  max-height: 24px;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #1976d2;"
            "}"
        )
        type_row.addWidget(self._port_input)

        # Apply scope

        type_row.addStretch()
        cfg_layout.addLayout(type_row)

        # Host / Port
        host_port_row = QHBoxLayout()


        host_port_row.addStretch()
        cfg_layout.addLayout(host_port_row)

        # Auth (optional, HTTP only)
        auth_row = QHBoxLayout()
        apply_to_label = QLabel("Apply to:")
        apply_to_label.setFixedWidth(60)
        auth_row.addWidget(apply_to_label)
        self._scope_combo = QComboBox()
        self._scope_combo.addItems(["All devices", "Selected devices only"])
        self._scope_combo.setFixedWidth(160)
        self._scope_combo.setStyleSheet(
            "QComboBox {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  min-height: 20px;"
            "  max-height: 24px;"
            "}"
            "QComboBox:focus {"
            "  border: 1px solid #1976d2;"
            "}"
            "QComboBox::drop-down {"
            "  border: none; width: 20px;"
            "}"
        )
        auth_row.addWidget(self._scope_combo)

        username_label = QLabel("Username:")
        username_label.setFixedWidth(60)
        auth_row.addWidget(username_label)
        self._user_input = QLineEdit()
        self._user_input.setPlaceholderText("optional")
        self._user_input.setFixedWidth(160)
        self._user_input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  min-height: 20px;"
            "  max-height: 24px;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #1976d2;"
            "}"
        )
        auth_row.addWidget(self._user_input)

        password_label = QLabel("Password:")
        password_label.setFixedWidth(60)
        auth_row.addWidget(password_label)
        self._pass_input = QLineEdit()
        self._pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_input.setPlaceholderText("optional")
        self._pass_input.setFixedWidth(160)
        self._pass_input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "  background: #ffffff;"
            "  color: #212121;"
            "  font-size: 11px;"
            "  min-height: 20px;"
            "  max-height: 24px;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #1976d2;"
            "}"
        )
        auth_row.addWidget(self._pass_input)
        auth_row.addStretch()
        cfg_layout.addLayout(auth_row)

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
                    # ── HTTP / HTTPS proxy ──────────────────────────────────────────
                    # Android chỉ hỗ trợ format "host:port" cho http_proxy.
                    # KHÔNG được nhúng user:pass vào đây — Android không hiểu và sẽ
                    # parse sai toàn bộ setting → mất kết nối.
                    proxy_val = f"{host}:{port_int}"
                    user = self._user_input.text().strip()
                    passwd = self._pass_input.text().strip()

                    # Xóa sạch HTTP proxy cũ trước (dùng delete, không dùng ":0")
                    _adb(serial, "shell", "settings", "delete", "global", "http_proxy")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_host")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_port")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_exclusion_list")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_username")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_password")

                    # Set proxy mới — chỉ host:port (Android hiểu được)
                    _adb(serial, "shell", "settings", "put", "global", "http_proxy", proxy_val)
                    # Các key global_http_proxy_* cho Android 8+ (PAC / manual)
                    _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_host", host)
                    _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_port", str(port_int))
                    if user:
                        _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_username", user)
                        if passwd:
                            _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_password", passwd)

                elif ptype == 2:
                    # ── SOCKS5 proxy ────────────────────────────────────────────────
                    # Android KHÔNG có SOCKS5 system-wide proxy native.
                    # Giải pháp: dùng ADB port-forward để đưa SOCKS5 về localhost,
                    # sau đó KHÔNG set http_proxy (vì Android chỉ hiểu HTTP proxy).
                    # Chỉ forward port, để app tự cấu hình SOCKS5 nếu hỗ trợ.
                    #
                    # Nếu muốn toàn hệ thống: cần redsocks/tun2socks trên device
                    # (yêu cầu root). Ở đây chỉ làm ADB forward port để dùng được
                    # từ app có hỗ trợ SOCKS5 explicit.

                    # Xóa HTTP proxy cũ (tránh conflict)
                    _adb(serial, "shell", "settings", "delete", "global", "http_proxy")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_host")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_port")
                    _adb(serial, "shell", "settings", "delete", "global", "global_http_proxy_exclusion_list")

                    # Forward port SOCKS5 từ PC về localhost trên device
                    subprocess.run(
                        ["adb", "-s", serial, "forward", f"tcp:{port_int}", f"tcp:{port_int}"],
                        startupinfo=_si,
                        capture_output=True,
                        text=True,
                    )
                    # Lưu thông tin để hiển thị status
                    _adb(serial, "shell", "setprop", "net.socks5.host", host)
                    _adb(serial, "shell", "setprop", "net.socks5.port", str(port_int))

                ok_count += 1
            except Exception as e:
                self._set_status(f"❌ {serial}: {e}", ok=False)

        type_label = "HTTP / HTTPS" if ptype == 1 else "SOCKS5"
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
                # Xóa đúng cách bằng cách set thành empty string thay vì delete
                # (delete có thể không hoạt động ngay lập tức trên một số Android version)
                _adb(serial, "shell", "settings", "put", "global", "http_proxy", ":0")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_host", "")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_port", "0")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_exclusion_list", "")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_username", "")
                _adb(serial, "shell", "settings", "put", "global", "global_http_proxy_password", "")
                # Xóa SOCKS5 props + hủy port forward
                _adb(serial, "shell", "setprop", "net.socks5.host", "")
                _adb(serial, "shell", "setprop", "net.socks5.port", "")
                subprocess.run(
                    ["adb", "-s", serial, "forward", "--remove-all"],
                    startupinfo=_si,
                    capture_output=True,
                    text=True,
                )
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

            # HTTP proxy takes priority: if global_http_proxy_host is set, it's HTTP
            if proxy_host and proxy_host not in ("", "null"):
                proxy_data[serial] = {"type": "HTTP / HTTPS", "host_port": f"{proxy_host}:{proxy_port}"}
            elif socks_host:
                socks_port = self._read_setprop(serial, "net.socks5.port")
                proxy_data[serial] = {"type": "SOCKS5", "host_port": f"{socks_host}:{socks_port}"}
            else:
                proxy_data[serial] = {"type": "None", "host_port": "—"}

        self.proxy_status_updated.emit(proxy_data)

    def _read_prop(self, serial: str, key: str) -> str:
        try:
            r = _adb(serial, "shell", "settings", "get", "global", key)
            val = r.stdout.strip()
            # Android có thể trả về "null" hoặc empty string khi setting không tồn tại
            return "" if val in ("null", "Null", "NULL", "", "0") or not val else val
        except Exception:
            return ""

    def _read_setprop(self, serial: str, key: str) -> str:
        try:
            r = _adb(serial, "shell", "getprop", key)
            val = r.stdout.strip()
            return "" if val in ("", "0") else val
        except Exception:
            return ""
