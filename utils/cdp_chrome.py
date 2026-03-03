"""
Chrome DevTools Protocol (CDP) automation for Android Chrome.

Không cần Appium, chỉ dùng ADB + WebSocket để điều khiển Chrome mobile.

Cách dùng:
    from utils.cdp_chrome import ChromeCDP

    with ChromeCDP(serial="XXXX") as cdp:
        cdp.navigate("https://example.com")
        cdp.click("#login-button")
        cdp.input_text("#email", "test@example.com")
"""

import json
import time
import subprocess
import requests
import websocket
from typing import Optional, Dict, Any


class ChromeCDP:
    """
    Chrome DevTools Protocol automation cho Android Chrome.

    Cách dùng:
        with ChromeCDP(serial="XXXX") as cdp:
            cdp.navigate("https://example.com")
            cdp.click("#login-button")
    """

    def __init__(self, serial: str, debug_port: int = 9222, initial_url: str = None):
        self.serial = serial
        self.debug_port = debug_port
        self.ws: Optional[websocket.WebSocket] = None
        self.msg_id = 1
        self.tabs = []
        self._initial_url: Optional[str] = initial_url

    def __enter__(self):
        self._setup_chrome_debugging()
        self._connect_websocket()
        return self

    def __exit__(self, *_):
        if self.ws:
            try:
                self.ws.close()
            except:
                pass

    def _adb(self, cmd: str) -> str:
        """Chạy ADB command."""
        result = subprocess.run(
            f"adb -s {self.serial} {cmd}",
            shell=True, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"ADB failed: {result.stderr}")
        return result.stdout.strip()

    def _setup_chrome_debugging(self):
        """Setup Chrome remote debugging."""
        # Kill Chrome hiện tại
        self._adb("shell am force-stop com.android.chrome")
        time.sleep(2)

        # Mở Chrome, vào thẳng URL nếu có để tránh vào 2 lần
        if self._initial_url:
            self._adb(f'shell am start -a android.intent.action.VIEW -n com.android.chrome/com.google.android.apps.chrome.Main -d "{self._initial_url}"')
        else:
            self._adb("shell am start -n com.android.chrome/com.google.android.apps.chrome.Main")

        # Forward port
        subprocess.run(
            f"adb -s {self.serial} forward tcp:{self.debug_port} localabstract:chrome_devtools_remote",
            shell=True, check=True
        )

        # Đợi Chrome khởi động, retry nhiều lần
        for attempt in range(10):
            time.sleep(2)
            try:
                response = requests.get(f"http://localhost:{self.debug_port}/json", timeout=3)
                self.tabs = response.json()
                if self.tabs:
                    return
            except requests.RequestException:
                pass

        raise RuntimeError("Cannot connect to Chrome debugging after 20s. Make sure Chrome is running.")

    def _connect_websocket(self):
        """Connect WebSocket tới tab đầu tiên."""
        if not self.tabs:
            raise RuntimeError("No tabs available")

        ws_url = self.tabs[0]["webSocketDebuggerUrl"]
        # timeout=None → không bị ngắt kết nối khi pause lâu giữa các command
        self.ws = websocket.create_connection(ws_url, timeout=None)
        self._ws_url = ws_url  # lưu lại để reconnect khi cần

    def _reconnect_websocket(self):
        """Reconnect lại WebSocket khi bị ngắt kết nối."""
        print(f"🔄 WebSocket disconnected, reconnecting on {self.serial}...")
        try:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
            # Lấy ws_url mới nhất từ /json (tab có thể đã đổi)
            try:
                response = requests.get(f"http://localhost:{self.debug_port}/json", timeout=5)
                tabs = response.json()
                page_tabs = [t for t in tabs if t.get("type") == "page"]
                ws_url = page_tabs[0]["webSocketDebuggerUrl"] if page_tabs else self._ws_url
            except Exception:
                ws_url = self._ws_url
            self.ws = websocket.create_connection(ws_url, timeout=None)
            self._ws_url = ws_url
            print(f"✅ WebSocket reconnected on {self.serial}")
        except Exception as e:
            raise RuntimeError(f"Failed to reconnect WebSocket on {self.serial}: {e}")

    def _send_command(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Gửi CDP command và nhận response. Tự reconnect nếu kết nối bị đứt."""
        if not self.ws:
            raise RuntimeError("WebSocket not connected")

        cmd = {
            "id": self.msg_id,
            "method": method,
            "params": params or {}
        }

        for attempt in range(3):
            try:
                self.ws.send(json.dumps(cmd))
                self.msg_id += 1

                # Nhận response
                while True:
                    response = json.loads(self.ws.recv())
                    if "id" in response and response["id"] == cmd["id"]:
                        if "error" in response:
                            raise RuntimeError(f"CDP error: {response['error']}")
                        return response.get("result", {})
            except RuntimeError:
                raise  # CDP error thật, không retry
            except Exception as e:
                if attempt < 2:
                    print(f"⚠️  WebSocket error ({e}), attempt {attempt + 1}/3, reconnecting...")
                    self._reconnect_websocket()
                    # Reset msg_id về lại trước khi retry
                    self.msg_id -= 1
                else:
                    raise RuntimeError(f"Connection timed out after 3 attempts: {e}")

    def navigate(self, url: str):
        """Navigate tới URL."""
        self._send_command("Page.navigate", {"url": url})
        time.sleep(2)  # Đợi trang load

    def click(self, selector: str):
        """Click element bằng CSS selector."""
        js = f"""
        const el = document.querySelector('{selector}');
        if (el) {{
            el.click();
            true;
        }} else {{
            false;
        }}
        """
        result = self._send_command("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True
        })
        if not result.get("result", {}).get("value", False):
            raise RuntimeError(f"Element not found: {selector}")

    def input_text(self, selector: str, text: str):
        """Input text vào element."""
        # Focus element
        focus_js = f"document.querySelector('{selector}')?.focus();"
        self._send_command("Runtime.evaluate", {"expression": focus_js})

        # Send keys
        for char in text:
            self._send_command("Input.dispatchKeyEvent", {
                "type": "keyDown",
                "text": char
            })
            self._send_command("Input.dispatchKeyEvent", {
                "type": "keyUp",
                "text": char
            })

    def get_page_title(self) -> str:
        """Lấy title của trang, đọc từ /json endpoint để có giá trị mới nhất sau navigation."""
        try:
            response = requests.get(f"http://localhost:{self.debug_port}/json", timeout=5)
            tabs = response.json()
            page_tabs = [t for t in tabs if t.get("type") == "page"]
            if page_tabs:
                return page_tabs[0].get("title", "")
        except Exception:
            pass
        result = self._send_command("Runtime.evaluate", {
            "expression": "document.title",
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def get_current_url(self) -> str:
        """Lấy URL hiện tại của tab, đọc từ /json endpoint."""
        try:
            response = requests.get(f"http://localhost:{self.debug_port}/json", timeout=5)
            tabs = response.json()
            page_tabs = [t for t in tabs if t.get("type") == "page"]
            if page_tabs:
                return page_tabs[0].get("url", "")
        except Exception:
            pass
        result = self._send_command("Runtime.evaluate", {
            "expression": "window.location.href",
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def execute_js(self, js: str) -> Any:
        """Execute JavaScript và trả về kết quả."""
        result = self._send_command("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True
        })
        return result.get("result", {}).get("value")

    def switch_to_new_tab(self) -> bool:
        """Switch WebSocket sang tab mới nhất (được mở sau tab hiện tại)."""
        try:
            response = requests.get(f"http://localhost:{self.debug_port}/json", timeout=5)
            tabs = response.json()
            # Lọc chỉ lấy page tabs (không lấy extension/devtools)
            page_tabs = [t for t in tabs if t.get("type") == "page"]
            if len(page_tabs) <= 1:
                return False
            # Tab mới nhất là tab cuối cùng
            new_tab = page_tabs[-1]
            if self.ws:
                self.ws.close()
            self.ws = websocket.create_connection(new_tab["webSocketDebuggerUrl"], timeout=10)
            self.tabs = tabs
            return True
        except Exception:
            return False