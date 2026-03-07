# Fatan — Android Device Manager & Ads Automation

A multi-device Android management GUI and ads automation tool built with PySide6. Connect Android phones via ADB (USB or WiFi), control device settings in bulk, and run Chrome-based ads automation via Chrome DevTools Protocol (CDP).

## Features

- **Multi-device Management**: Detect and manage multiple Android devices simultaneously
- **Ads Automation**: Automate ad interactions in Chrome using CDP — navigates to the ad, clicks "Learn more", and performs human-like browsing behaviour
- **Human-like Behaviour Engine**: Configurable scroll speed, burst probability, click probability, read pauses, and predefined profiles (e.g. light, normal, deep)
- **Device Controls** (bulk, over ADB):
  - Screen lock mode, brightness, media volume, Bluetooth
  - WiFi / Mobile Data / Airplane mode toggles
  - Dark mode, animation speed, stay-on-while-charging
  - Reboot, Disable/Enable Play Store
- **Proxy Management**: Assign HTTP proxies per device and verify connectivity
- **Device Info**: Battery, storage, CPU, RAM, IP, uptime at a glance
- **App Management**: List, install, and uninstall APKs on selected devices
- **Screen Remote**: Live screen preview & control via embedded scrcpy window
- **CSV Persistence**: Device names and serials stored in `data/data.csv`
- **Build Tools**: PyInstaller build scripts for creating a standalone Windows executable

## Project Structure

```
gui.py                  # Main PySide6 application entry-point
features/
  ads.py                # AdsTableWidget + human behaviour config UI
  actions.py            # Per-device quick-action panel
  apps.py               # App management panel
  chrome.py             # Chrome APK installer helper
  info.py               # Device info panel
  proxy.py              # Proxy assignment & verification panel
  session_engine.py     # Human-like browsing session engine
  settings.py           # Settings tab (device controls, save/load JSON)
helpers/
  csv.py                # CSV read/write utilities
utils/
  adb.py                # ADB helper functions
  appium_chrome.py      # Appium Chrome driver utilities
  cdp_chrome.py         # ChromeCDP context manager (port forwarding + WS)
  cdp_helpers.py        # InputDriver, safe-zone helpers
data/
  data.csv              # Persisted device list (model, serial, device name)
  settings.json         # Saved UI settings (preview dimensions, etc.)
  chrome.apkm           # Chrome APK bundle for installation
build.bat               # PyInstaller build script
installer.bat           # ADB + scrcpy installer for Windows
requirements.txt        # Python dependencies
```

## Installation

### Prerequisites

- Python 3.8+
- Windows 10/11
- Android device(s) with **USB debugging** enabled
- ADB — installed automatically by `installer.bat`

### Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/sonic-media/auto-mobile.git
   cd auto-mobile
   ```

2. **Install Python dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Install ADB and scrcpy (Windows):**

   ```bash
   installer.bat
   ```

   This downloads and installs ADB and scrcpy to `C:\android-tools\`.

4. **Restart your terminal** to refresh the `PATH` environment variable.

## Usage

### Launch the GUI

```bash
python gui.py
```

### Workflow

1. **Connect your device(s)** via USB or `adb connect <ip>:5555`
2. Click **🔃 Load devices** to detect devices and populate the table
3. Navigate tabs from the left sidebar:
   - **🤖 Simulator** — set an ads URL, configure human behaviour, and click **Run Ads**
   - **🔗 Proxy** — assign HTTP proxies to individual devices
   - **⚙️ Settings** — bulk device controls (brightness, volume, Bluetooth, WiFi, etc.)
   - **ℹ️ Info** — hardware and software info for the selected device
   - **⚡ Actions** — quick per-device actions (open URL, input text, scroll, etc.)
   - **📦 Apps** — list, install, and uninstall APKs

### Connecting devices via WiFi

```bash
# Enable TCP/IP mode (with USB connected)
adb tcpip 5555

# Connect wirelessly
adb connect 192.168.1.100:5555
```

## Ads Automation Flow

For each device the automation:

1. Opens the ads URL in Chrome via ADB
2. Waits for the "Link to ad" modal to appear
3. Scrolls the modal and clicks **Learn more**
4. Lands on the destination page and collects title + domain
5. Runs a configurable human-like browsing session (scroll, read pauses, random clicks)

```
Python app ─── ADB port-forward ──► Chrome mobile (port 9222)
                                         │
                                    CDP WebSocket
```

### Available CDP helpers (`utils/cdp_chrome.py`)

| Method                  | Description                      |
| ----------------------- | -------------------------------- |
| `cdp.navigate(url)`     | Navigate to URL                  |
| `cdp.execute_js(js)`    | Run JavaScript and return result |
| `cdp.get_page_title()`  | Get current page title           |
| `cdp.get_current_url()` | Get current URL                  |

## Building a Standalone Executable

```bash
build.bat
```

Output: `dist/gui.exe`

## Requirements

- Python 3.8+
- PySide6 ≥ 6.0
- websocket-client
- PyInstaller ≥ 6.0 (build only)
- Android device with Chrome installed
- USB debugging enabled

## Troubleshooting

| Problem                       | Solution                                                            |
| ----------------------------- | ------------------------------------------------------------------- |
| `adb` not found               | Run `installer.bat` and restart your terminal                       |
| Device not detected           | Enable USB debugging, accept the RSA fingerprint prompt on device   |
| Chrome remote debugging fails | Install Chrome via **🌐 Install Chrome** button in the Settings tab |
| `QLayout` warnings in console | Already fixed — update to latest version                            |

```bash
# Check connected devices
adb devices

# Restart ADB server if devices disappear
adb kill-server && adb start-server
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Submit a pull request

## License

This project is licensed under the MIT License.
