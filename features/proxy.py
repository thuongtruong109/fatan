"""
Proxy configuration tab.
Lets users set HTTP proxy or SOCKS5 proxy per-device (or all devices at once)
via Android's global ADB proxy settings.
"""
from __future__ import annotations

import subprocess
import os
import asyncio
import time
from typing import List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QComboBox, QSpacerItem, QSizePolicy, QTextEdit, QSpinBox,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Signal, Qt, QThread

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

class _PingWorker(QThread):
    """Test connectivity / response time for a list of proxies."""
    progress = Signal(str)
    finished = Signal(str)

    PROXY_TYPES = ("TCP", "SOCKS4", "SOCKS5", "HTTP")

    def __init__(self, proxies: list, proxy_type: str = "TCP",
                 timeout: int = 3, concurrency: int = 200):
        super().__init__()
        self.proxies = proxies
        self.proxy_type = proxy_type
        self.timeout = timeout
        self.concurrency = concurrency
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        ptype = self.proxy_type
        timeout = self.timeout
        stop_ref = self

        async def _test_one(sem, proxy):
            if stop_ref._stop_flag:
                return None, None
            proxy = proxy.strip()
            if not proxy:
                return None, None
            parts = proxy.split(":")
            if len(parts) != 2:
                stop_ref.progress.emit(f"[SKIP] {proxy} — invalid format (use host:port)")
                return None, None
            ip, port_str = parts
            try:
                port = int(port_str)
            except ValueError:
                stop_ref.progress.emit(f"[SKIP] {proxy} — invalid port")
                return None, None

            async with sem:
                if stop_ref._stop_flag:
                    return None, None
                try:
                    t0 = time.perf_counter()
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(ip, port),
                        timeout=timeout,
                    )
                    ok = True

                    if ptype == "SOCKS5":
                        writer.write(b"\x05\x01\x00")
                        await writer.drain()
                        resp = await asyncio.wait_for(reader.read(2), timeout=timeout)
                        ok = (resp == b"\x05\x00")

                    elif ptype == "SOCKS4":
                        # SOCKS4 CONNECT to 0.0.0.0:80 (probe only)
                        writer.write(b"\x04\x01\x00\x50\x00\x00\x00\x01\x00")
                        await writer.drain()
                        resp = await asyncio.wait_for(reader.read(8), timeout=timeout)
                        ok = (len(resp) >= 2 and resp[1] == 0x5A)

                    elif ptype == "HTTP":
                        writer.write(b"HEAD / HTTP/1.0\r\nHost: " + ip.encode() + b"\r\n\r\n")
                        await writer.drain()
                        resp = await asyncio.wait_for(reader.read(64), timeout=timeout)
                        ok = len(resp) > 0

                    elapsed_ms = round((time.perf_counter() - t0) * 1000)
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

                    if ok:
                        stop_ref.progress.emit(f"[OK] {proxy} — {elapsed_ms} ms")
                        return proxy, elapsed_ms
                    else:
                        stop_ref.progress.emit(f"[FAIL] {proxy} — protocol mismatch")
                        return None, None

                except asyncio.TimeoutError:
                    stop_ref.progress.emit(f"[TIMEOUT] {proxy}")
                    return None, None
                except Exception as e:
                    stop_ref.progress.emit(f"[FAIL] {proxy}")
                    return None, None

        async def _run_all():
            sem = asyncio.Semaphore(self.concurrency)
            t_start = time.time()
            tasks = [_test_one(sem, p) for p in self.proxies if p.strip()]
            results = await asyncio.gather(*tasks)
            live = [r for r in results if r[0] is not None]
            total = len([p for p in self.proxies if p.strip()])
            elapsed = round(time.time() - t_start, 2)
            stop_ref.finished.emit(
                f"✅ Done — Live: {len(live)}/{total} | Time: {elapsed}s"
            )

        asyncio.run(_run_all())


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
        cfg_group = QGroupBox("🌐 Configuration")
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

        # ── Port Forward / Reverse ────────────────────────────────────────
        _PORT_GROUP_SS = """
            QGroupBox {
                font-weight: bold; font-size: 12px;
                border: 1px solid #ddd; border-radius: 6px;
                margin-top: 6px; padding-top: 4px;
                background-color: #f8f9ff;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 4px; color: #1565c0;
            }
        """
        _PORT_INPUT_SS = (
            "QLineEdit { border: 1px solid #ddd; border-radius: 4px;"
            " padding: 2px 6px; background: #fff; color: #212121;"
            " font-size: 11px; min-height: 20px; max-height: 24px; }"
            "QLineEdit:focus { border: 1px solid #1976d2; }"
        )
        _PORT_BTN_SS = (
            "QPushButton { background-color: #1976d2; color: white; font-weight: bold;"
            " padding: 4px 12px; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1565c0; }"
            "QPushButton:disabled { background-color: #90caf9; }"
        )
        _PORT_BTN_RM_SS = (
            "QPushButton { background-color: #e53935; color: white; font-weight: bold;"
            " padding: 4px 12px; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #c62828; }"
            "QPushButton:disabled { background-color: #ef9a9a; }"
        )
        _PORT_LBL_SS = "font-size: 11px; font-weight: bold; color: #555;"

        port_group = QGroupBox("🔀 Port Forward / Reverse")
        port_group.setStyleSheet(_PORT_GROUP_SS)
        port_vl = QVBoxLayout()
        port_vl.setContentsMargins(10, 10, 10, 10)
        port_vl.setSpacing(10)

        # ── Forward section ───────────────────────────────────────────────
        fwd_lbl = QLabel("➡ Forward")
        fwd_lbl.setStyleSheet(_PORT_LBL_SS)
        port_vl.addWidget(fwd_lbl)

        fwd_row = QHBoxLayout()
        fwd_row.setSpacing(6)

        fwd_host_lbl = QLabel("Host port:")
        fwd_host_lbl.setStyleSheet("font-size: 11px; color: #555;")
        fwd_row.addWidget(fwd_host_lbl)
        self._fwd_host_port = QLineEdit()
        self._fwd_host_port.setPlaceholderText("e.g. 8080")
        self._fwd_host_port.setFixedWidth(90)
        self._fwd_host_port.setStyleSheet(_PORT_INPUT_SS)
        fwd_row.addWidget(self._fwd_host_port)

        fwd_dev_lbl = QLabel("Device port:")
        fwd_dev_lbl.setStyleSheet("font-size: 11px; color: #555;")
        fwd_row.addWidget(fwd_dev_lbl)
        self._fwd_dev_port = QLineEdit()
        self._fwd_dev_port.setPlaceholderText("e.g. 8080")
        self._fwd_dev_port.setFixedWidth(90)
        self._fwd_dev_port.setStyleSheet(_PORT_INPUT_SS)
        fwd_row.addWidget(self._fwd_dev_port)

        fwd_row.addStretch()

        fwd_apply_btn = QPushButton("▶ Forward")
        fwd_apply_btn.setStyleSheet(_PORT_BTN_SS)
        fwd_apply_btn.clicked.connect(self._on_forward_apply)
        fwd_row.addWidget(fwd_apply_btn)

        fwd_rm_btn = QPushButton("✖ Remove All")
        fwd_rm_btn.setStyleSheet(_PORT_BTN_RM_SS)
        fwd_rm_btn.setToolTip("Remove all forward port forwards")
        fwd_rm_btn.clicked.connect(self._on_forward_remove_all)
        fwd_row.addWidget(fwd_rm_btn)

        port_vl.addLayout(fwd_row)

        # ── Reverse section ───────────────────────────────────────────────
        rev_lbl = QLabel("⬅ Reverse")
        rev_lbl.setStyleSheet(_PORT_LBL_SS)
        port_vl.addWidget(rev_lbl)

        rev_row = QHBoxLayout()
        rev_row.setSpacing(6)

        rev_dev_lbl = QLabel("Device port:")
        rev_dev_lbl.setStyleSheet("font-size: 11px; color: #555;")
        rev_row.addWidget(rev_dev_lbl)
        self._rev_dev_port = QLineEdit()
        self._rev_dev_port.setPlaceholderText("e.g. 3000")
        self._rev_dev_port.setFixedWidth(90)
        self._rev_dev_port.setStyleSheet(_PORT_INPUT_SS)
        rev_row.addWidget(self._rev_dev_port)

        rev_host_lbl = QLabel("Host port:")
        rev_host_lbl.setStyleSheet("font-size: 11px; color: #555;")
        rev_row.addWidget(rev_host_lbl)
        self._rev_host_port = QLineEdit()
        self._rev_host_port.setPlaceholderText("e.g. 3000")
        self._rev_host_port.setFixedWidth(90)
        self._rev_host_port.setStyleSheet(_PORT_INPUT_SS)
        rev_row.addWidget(self._rev_host_port)

        rev_row.addStretch()

        rev_apply_btn = QPushButton("▶ Reverse")
        rev_apply_btn.setStyleSheet(_PORT_BTN_SS)
        rev_apply_btn.clicked.connect(self._on_reverse_apply)
        rev_row.addWidget(rev_apply_btn)

        rev_rm_btn = QPushButton("✖ Remove All")
        rev_rm_btn.setStyleSheet(_PORT_BTN_RM_SS)
        rev_rm_btn.setToolTip("Remove all reverse port forwards")
        rev_rm_btn.clicked.connect(self._on_reverse_remove_all)
        rev_row.addWidget(rev_rm_btn)

        port_vl.addLayout(rev_row)

        # ── Status label ──────────────────────────────────────────────────
        self._port_status_lbl = QLabel("")
        self._port_status_lbl.setStyleSheet("font-size: 11px; color: #2e7d32;")
        port_vl.addWidget(self._port_status_lbl)

        port_group.setLayout(port_vl)
        root.addWidget(port_group)

        # ── Ping / Proxy Test ─────────────────────────────────────────────
        _GROUP_SS = """
            QGroupBox {
                font-weight: bold; font-size: 12px;
                border: 1px solid #ddd; border-radius: 6px;
                margin-top: 6px; padding-top: 4px;
                background-color: #f8fff8;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 4px; color: #2e7d32;
            }
        """
        _INPUT_SS = (
            "QLineEdit { border: 1px solid #ddd; border-radius: 4px;"
            " padding: 2px 6px; background: #fff; color: #212121;"
            " font-size: 11px; min-height: 20px; max-height: 24px; }"
            "QLineEdit:focus { border: 1px solid #1976d2; }"
        )
        _BTN_TEST_SS = (
            "QPushButton { background-color: #388e3c; color: white; font-weight: bold;"
            " padding: 5px 14px; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #2e7d32; }"
            "QPushButton:disabled { background-color: #a5d6a7; }"
        )
        _BTN_STOP_SS = (
            "QPushButton { background-color: #e53935; color: white; font-weight: bold;"
            " padding: 5px 14px; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #c62828; }"
            "QPushButton:disabled { background-color: #ef9a9a; }"
        )

        ping_group = QGroupBox("🏓 Ping Test")
        ping_group.setStyleSheet(_GROUP_SS)
        ping_vl = QVBoxLayout()
        ping_vl.setContentsMargins(10, 10, 10, 10)
        ping_vl.setSpacing(8)

        # Row 1: proxy type + timeout + concurrency + buttons
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        lbl_ptype = QLabel("Type:")
        lbl_ptype.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        ctrl_row.addWidget(lbl_ptype)
        self._ping_type_combo = QComboBox()
        self._ping_type_combo.addItems(["TCP (any)", "SOCKS5", "SOCKS4", "HTTP"])
        self._ping_type_combo.setFixedWidth(110)
        self._ping_type_combo.setStyleSheet(
            "QComboBox { border: 1px solid #ddd; border-radius: 4px; padding: 2px 6px;"
            " background: #fff; font-size: 11px; min-height: 20px; max-height: 24px; }"
            "QComboBox:focus { border: 1px solid #1976d2; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
        )
        ctrl_row.addWidget(self._ping_type_combo)

        lbl_timeout = QLabel("Timeout (s):")
        lbl_timeout.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        ctrl_row.addWidget(lbl_timeout)
        self._ping_timeout = QSpinBox()
        self._ping_timeout.setRange(1, 30)
        self._ping_timeout.setValue(3)
        self._ping_timeout.setFixedWidth(55)
        self._ping_timeout.setStyleSheet(
            "QSpinBox { border: 1px solid #ddd; border-radius: 4px; padding: 2px 6px;"
            " background: #fff; font-size: 11px; min-height: 20px; max-height: 24px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; }"
        )
        ctrl_row.addWidget(self._ping_timeout)

        lbl_conc = QLabel("Concurrency:")
        lbl_conc.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        ctrl_row.addWidget(lbl_conc)
        self._ping_concurrency = QSpinBox()
        self._ping_concurrency.setRange(1, 1000)
        self._ping_concurrency.setValue(200)
        self._ping_concurrency.setFixedWidth(65)
        self._ping_concurrency.setStyleSheet(
            "QSpinBox { border: 1px solid #ddd; border-radius: 4px; padding: 2px 6px;"
            " background: #fff; font-size: 11px; min-height: 20px; max-height: 24px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; }"
        )
        ctrl_row.addWidget(self._ping_concurrency)

        ctrl_row.addStretch()

        self._ping_test_btn = QPushButton("▶ Test")
        self._ping_test_btn.setStyleSheet(_BTN_TEST_SS)
        self._ping_test_btn.clicked.connect(self._on_ping_test)
        ctrl_row.addWidget(self._ping_test_btn)

        self._ping_stop_btn = QPushButton("■ Stop")
        self._ping_stop_btn.setStyleSheet(_BTN_STOP_SS)
        self._ping_stop_btn.setEnabled(False)
        self._ping_stop_btn.clicked.connect(self._on_ping_stop)
        ctrl_row.addWidget(self._ping_stop_btn)

        ping_vl.addLayout(ctrl_row)

        # Row 2: Use from config button
        use_config_row = QHBoxLayout()
        use_config_row.setSpacing(6)
        lbl_proxies = QLabel("Proxies (host:port, one per line):")
        lbl_proxies.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        use_config_row.addWidget(lbl_proxies)
        use_config_row.addStretch()
        use_config_btn = QPushButton("📋 Use Config")
        use_config_btn.setToolTip("Fill from the proxy config form above")
        use_config_btn.setStyleSheet(
            "QPushButton { border: 1px solid #ccc; border-radius: 4px;"
            " padding: 3px 10px; background: #f0f0f0; font-size: 11px; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        use_config_btn.clicked.connect(self._ping_use_config)
        use_config_row.addWidget(use_config_btn)
        ping_vl.addLayout(use_config_row)

        # Proxies input
        self._ping_proxies_input = QTextEdit()
        self._ping_proxies_input.setPlaceholderText(
            "192.168.1.1:1080\n192.168.1.2:1080\n..."
        )
        self._ping_proxies_input.setFixedHeight(80)
        self._ping_proxies_input.setStyleSheet(
            "QTextEdit { border: 1px solid #ddd; border-radius: 4px;"
            " padding: 4px 6px; background: #fff; font-size: 11px;"
            " font-family: Consolas, monospace; }"
            "QTextEdit:focus { border: 1px solid #1976d2; }"
        )
        ping_vl.addWidget(self._ping_proxies_input)

        # Results label
        lbl_results = QLabel("Results:")
        lbl_results.setStyleSheet("font-size: 11px; font-weight: bold; color: #555;")
        ping_vl.addWidget(lbl_results)

        self._ping_result_log = QTextEdit()
        self._ping_result_log.setReadOnly(True)
        self._ping_result_log.setFixedHeight(130)
        self._ping_result_log.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4;"
            " font-family: Consolas, monospace; font-size: 11px;"
            " border: 1px solid #333; border-radius: 4px; padding: 4px 6px; }"
        )
        ping_vl.addWidget(self._ping_result_log)

        # Summary label
        self._ping_summary_lbl = QLabel("")
        self._ping_summary_lbl.setStyleSheet("font-size: 11px; color: #2e7d32;")
        ping_vl.addWidget(self._ping_summary_lbl)

        ping_group.setLayout(ping_vl)
        root.addWidget(ping_group)

        self._ping_worker: "_PingWorker | None" = None

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

    # ── Ping handlers ─────────────────────────────────────────────────────
    def _ping_use_config(self):
        host = self._host_input.text().strip()
        port = self._port_input.text().strip()
        if host and port:
            self._ping_proxies_input.setPlainText(f"{host}:{port}")
        else:
            self._set_status("⚠️ Enter host and port in the config form first.", ok=False)

    def _on_ping_test(self):
        raw = self._ping_proxies_input.toPlainText()
        proxies = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not proxies:
            self._ping_summary_lbl.setStyleSheet("color: #c62828; font-size: 11px;")
            self._ping_summary_lbl.setText("⚠ Enter at least one proxy (host:port).")
            return

        ptype_map = {"TCP (any)": "TCP", "SOCKS5": "SOCKS5", "SOCKS4": "SOCKS4", "HTTP": "HTTP"}
        ptype = ptype_map.get(self._ping_type_combo.currentText(), "TCP")
        timeout = self._ping_timeout.value()
        concurrency = self._ping_concurrency.value()

        self._ping_result_log.clear()
        self._ping_summary_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self._ping_summary_lbl.setText("⏳ Testing…")
        self._ping_test_btn.setEnabled(False)
        self._ping_stop_btn.setEnabled(True)

        self._ping_worker = _PingWorker(proxies, ptype, timeout, concurrency)
        self._ping_worker.progress.connect(self._on_ping_progress)
        self._ping_worker.finished.connect(self._on_ping_finished)
        self._ping_worker.start()

    def _on_ping_stop(self):
        if self._ping_worker and self._ping_worker.isRunning():
            self._ping_worker.stop()
            self._ping_summary_lbl.setStyleSheet("color: #e65100; font-size: 11px;")
            self._ping_summary_lbl.setText("⏹ Stopping…")
            self._ping_stop_btn.setEnabled(False)

    def _on_ping_progress(self, msg: str):
        self._ping_result_log.append(msg)
        sb = self._ping_result_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_ping_finished(self, summary: str):
        self._ping_test_btn.setEnabled(True)
        self._ping_stop_btn.setEnabled(False)
        color = "#2e7d32" if "Done" in summary else "#c62828"
        self._ping_summary_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._ping_summary_lbl.setText(summary)
        self._ping_worker = None

    # ── Port Forward / Reverse handlers ──────────────────────────────────
    def _set_port_status(self, msg: str, ok: bool = True):
        color = "#2e7d32" if ok else "#c62828"
        self._port_status_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._port_status_lbl.setText(msg)

    def _on_forward_apply(self):
        host_port = self._fwd_host_port.text().strip()
        dev_port  = self._fwd_dev_port.text().strip()
        if not host_port or not dev_port:
            self._set_port_status("⚠️ Enter both host port and device port.", ok=False)
            return
        try:
            int(host_port); int(dev_port)
        except ValueError:
            self._set_port_status("⚠️ Ports must be numbers.", ok=False)
            return

        serials = self._connected_serials()
        if not serials:
            self._set_port_status("⚠️ No connected devices found.", ok=False)
            return

        ok_count = 0
        for serial in serials:
            try:
                r = subprocess.run(
                    ["adb", "-s", serial, "forward", f"tcp:{host_port}", f"tcp:{dev_port}"],
                    startupinfo=_si, capture_output=True, text=True,
                )
                if r.returncode == 0:
                    ok_count += 1
                else:
                    self._set_port_status(f"❌ {serial}: {r.stderr.strip()}", ok=False)
            except Exception as e:
                self._set_port_status(f"❌ {serial}: {e}", ok=False)

        if ok_count:
            self._set_port_status(
                f"✅ Forwarded tcp:{host_port} → tcp:{dev_port} on {ok_count}/{len(serials)} device(s)."
            )

    def _on_forward_remove_all(self):
        serials = self._connected_serials()
        if not serials:
            self._set_port_status("⚠️ No connected devices found.", ok=False)
            return
        ok_count = 0
        for serial in serials:
            try:
                r = subprocess.run(
                    ["adb", "-s", serial, "forward", "--remove-all"],
                    startupinfo=_si, capture_output=True, text=True,
                )
                if r.returncode == 0:
                    ok_count += 1
            except Exception:
                pass
        self._set_port_status(f"🚫 Removed all forwards on {ok_count}/{len(serials)} device(s).")

    def _on_reverse_apply(self):
        dev_port  = self._rev_dev_port.text().strip()
        host_port = self._rev_host_port.text().strip()
        if not dev_port or not host_port:
            self._set_port_status("⚠️ Enter both device port and host port.", ok=False)
            return
        try:
            int(dev_port); int(host_port)
        except ValueError:
            self._set_port_status("⚠️ Ports must be numbers.", ok=False)
            return

        serials = self._connected_serials()
        if not serials:
            self._set_port_status("⚠️ No connected devices found.", ok=False)
            return

        ok_count = 0
        for serial in serials:
            try:
                r = subprocess.run(
                    ["adb", "-s", serial, "reverse", f"tcp:{dev_port}", f"tcp:{host_port}"],
                    startupinfo=_si, capture_output=True, text=True,
                )
                if r.returncode == 0:
                    ok_count += 1
                else:
                    self._set_port_status(f"❌ {serial}: {r.stderr.strip()}", ok=False)
            except Exception as e:
                self._set_port_status(f"❌ {serial}: {e}", ok=False)

        if ok_count:
            self._set_port_status(
                f"✅ Reversed tcp:{dev_port} → tcp:{host_port} on {ok_count}/{len(serials)} device(s)."
            )

    def _on_reverse_remove_all(self):
        serials = self._connected_serials()
        if not serials:
            self._set_port_status("⚠️ No connected devices found.", ok=False)
            return
        ok_count = 0
        for serial in serials:
            try:
                r = subprocess.run(
                    ["adb", "-s", serial, "reverse", "--remove-all"],
                    startupinfo=_si, capture_output=True, text=True,
                )
                if r.returncode == 0:
                    ok_count += 1
            except Exception:
                pass
        self._set_port_status(f"🚫 Removed all reverses on {ok_count}/{len(serials)} device(s).")
