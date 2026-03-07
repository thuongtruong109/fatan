## List devices

```bash
adb devices -l
```

output: List of devices attached
2285d50b40047ece device product:starlteks model:SM_G960N device:starlteks transport_id:1

👉 First column (2285d50b40047ece) is serial/ID.

## Send request for special device

```bash
adb -s <serial_id> shell monkey -p org.mozilla.firefox -c android.intent.category.LAUNCHER 1
```

## Connect wireless

##### Android < 11 or not use Wireless debugging

```bash
adb tcpip 5555
# Unplugin cable to connect via wifi
adb connect 192.168.1.43:5555
```

##### Android > 11

1. On Android: Settings → Developer options → Wireless debugging → ON

- Pair device with pairing code

  - Click will see pairing code
  - IP:PAIR_PORT (ví dụ 192.168.1.50:47123)

- IP address & port
  - At Wireless debugging has line:
  - IP address & port (ví dụ 192.168.1.50:37099)

2. On PC:

- Pair (use PAIR_PORT)

```bash
adb pair 192.168.1.50:47123 # Replace with pairing code from android
```

- Connect (use IP address & port)

```bash
adb connect 192.168.1.50:37099 # Replace with IP address & port from android
adb devices
```

- If right, will have:

```bash
192.168.1.50:37099 device
scrcpy -s 192.168.1.50:37099
```

## Push data to device

```bash
adb -s <serial_id> push <file_path> /sdcard/Download/<file_name>
```

## ADB Keyboard

Install Keyboard APK

```bash
adb -s <serial_id> install -r keyboard.apk
```

Get available

```bash
adb -s <serial_id> shell ime list -s
```

Enable keyboard to IME

```bash
adb -s <serial_id> shell ime enable com.android.adbkeyboard/.AdbIME
adb -s <serial_id> shell ime set com.android.adbkeyboard/.AdbIME
```

Send text

```bash
adb -s 2285d50b40047ece shell am broadcast -a ADB_INPUT_B64 --es msg "<base64_text>"
```
