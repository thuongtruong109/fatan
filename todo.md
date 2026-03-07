## Mở shell điều khiển Android

Chạy lệnh Linux trực tiếp trên máy:

```bash
adb shell
```

Ví dụ:

- xem danh sách app
- xem process
- chỉnh system settings
- thao tác file

## Ghi log hệ thống (debug)

```bash
adb logcat
```

Dùng để:

- debug app crash
- xem lỗi hệ thống
- ## theo dõi hoạt động app

## Chụp màn hình / quay màn hình

- Chụp màn hình

```bash
adb shell screencap /sdcard/screen.png
```

- Quay video màn hình

```bash
adb shell screenrecord /sdcard/video.mp4
```

## Điều khiển thiết bị từ PC

Có thể giả lập thao tác:

- mở app
- gửi phím
- click màn hình

Ví dụ:

```bash
adb shell input tap 500 1000
adb shell input text hello
adb shell input keyevent 26
```

## Backup & restore dữ liệu

```bash
adb backup -apk -shared -all
adb restore backup.ab
```

## Gỡ app hệ thống (không cần root)

Xóa app rác khỏi user hiện tại:

```bash
adb shell pm uninstall -k --user 0 <package_name>
```

Ví dụ:

```bash
adb shell pm uninstall -k --user 0 com.facebook.appmanager
```

✔ Không cần root
✔ Có thể cài lại nếu reset máy

# Chụp screenshot nhanh

```bash
adb exec-out screencap -p > screen.png
```

✔ Chụp trực tiếp về PC.

# Quay màn hình

```bash
adb shell screenrecord /sdcard/demo.mp4
```

# Mở app bằng ADB

```bash
adb shell monkey -p com.example.app -c android.intent.category.LAUNCHER 1
```

# Fake thao tác chạm

Tap:

```bash
adb shell input tap 500 1000
```

Swipe:

```bash
adb shell input swipe 300 1000 300 300
```

👉 Có thể **auto click bot**.

# Gõ text từ PC vào điện thoại

```bash
adb shell input text hello
```

# 🤖 2. Automation Android (bot)

Kết hợp:

- `adb shell input`
- `adb screencap`
- script Python / bash

Bạn có thể tạo:

- bot game
- auto test app
- auto click app

Ví dụ swipe:

```bash
adb shell input swipe 500 1500 500 500 200
```

# 📦 4. Dump toàn bộ thông tin hệ thống

ADB có thể lấy **report cực chi tiết**:

```bash
adb bugreport
```

File này chứa:

- log hệ thống
- lỗi app
- trạng thái kernel
- network info

Dev Android dùng để debug.

# 🔍 5. Phân tích activity đang chạy

Xem app nào đang mở:

```bash
adb shell dumpsys activity activities
```

Hoặc:

```bash
adb shell dumpsys activity top
```

Có thể biết:

- activity hiện tại
- task stack
- process

# 📊 6. Phân tích pin cực chi tiết

```bash
adb shell dumpsys batterystats
```

Biết được:

- app nào hao pin
- wakelock
- CPU usage
- network usage

# 🔐 9. Cấp quyền đặc biệt cho app

Một số app cần quyền hệ thống.

ADB có thể cấp:

```bash
adb shell pm grant com.example.app android.permission.WRITE_SECURE_SETTINGS
```

Rất nhiều app automation cần quyền này.

# 🧪 11. Test crash app

ADB có thể **ép crash app**:

```bash
adb shell am crash com.example.app
```

Dev dùng để test error handling.

# 📂 12. Truy cập database app

Nếu có quyền:

```bash
adb shell
run-as com.example.app
```

Sau đó:

```bash
cd /data/data/com.example.app/databases
```

# 🌐 13. Port forwarding

ADB có thể forward port:

```bash
adb forward tcp:8080 tcp:8080
```

Dùng cho:

- debug web server
- dev backend

# 🧬 14. Reverse port (ít người biết)

Ngược lại:

```bash
adb reverse tcp:3000 tcp:3000
```

👉 Android truy cập server từ PC.

# 🧨 15. Truy cập log kernel

```bash
adb shell dmesg
```

Xem:

- lỗi driver
- lỗi hardware
- lỗi kernel

# 💡 Một số thứ **cực nâng cao có thể làm với ADB**

- flash ROM
- unlock bootloader
- remote debugging

* 🧹 **debloat toàn bộ app rác**

- **gỡ app hệ thống không cần root**
- **ghi log kernel**
- **port ROM / mod hệ thống**

💡 Ví dụ phổ biến:
gỡ app rác hệ thống:

```bash
adb shell pm uninstall -k --user 0 com.facebook.appmanager
```

# 🔎 2. Xem activity của app

ADB có thể biết **activity nào đang chạy**:

```bash
adb shell dumpsys window | grep mCurrentFocus
```

Kết quả ví dụ:

```
com.example.app/.MainActivity
```

👉 Rất hữu ích khi:

- automation
- reverse app

# 🤖 3. Mở activity trực tiếp

Không cần mở app bình thường.

```bash
adb shell am start -n com.example.app/.MainActivity
```

👉 Có thể mở **menu ẩn trong app**.

# 📦 4. Gửi intent vào app

ADB có thể **giả lập Android intent**.

Ví dụ:

```bash
adb shell am start -a android.intent.action.VIEW -d https://google.com
```

👉 Android sẽ mở trình duyệt.

# 🧪 5. Broadcast intent (kỹ thuật pentest)

Gửi broadcast:

```bash
adb shell am broadcast -a com.example.TEST
```

Dùng để:

- test security
- trigger chức năng ẩn

# 📊 7. Xem toàn bộ service Android

```bash
adb shell service list
```

Có thể thấy:

- audio
- wifi
- activity
- package

👉 Đây là **API nội bộ Android**.

# ⚡ 8. Restart System UI

Nếu UI bị lỗi:

```bash
adb shell pkill com.android.systemui
```

Android sẽ tự reload.

# 📱 9. Giả lập cuộc gọi

```bash
adb shell am start -a android.intent.action.CALL -d tel:123456
```

# 📡 10. Giả lập nhận SMS

```bash
adb shell am broadcast -a android.provider.Telephony.SMS_RECEIVED
```

Dev dùng để test app SMS.

# 🧬 11. Theo dõi network app

```bash
adb shell dumpsys netstats
```

Biết:

- app dùng bao nhiêu data
- wifi vs mobile

# 🧨 13. Dump UI layout

ADB có thể **lấy layout UI của app**:

```bash
adb shell uiautomator dump
```

Sau đó:

```bash
adb pull /sdcard/window_dump.xml
```

# 🌐 14. Điều khiển Android qua network

ADB có thể chạy qua WiFi:

```bash
adb tcpip 5555
adb connect 192.168.1.10
```

👉 Điều khiển điện thoại **không cần cắm dây**.

# 🧬 15. Ghi log app riêng

Chỉ log app cụ thể:

```bash
adb logcat | grep com.example.app
```

# 🚀 Tool cực mạnh dùng ADB

### Mirror + control Android

- **scrcpy**

### Automation Android

- **UIAutomator**

### Reverse engineering

- **Frida**

5. Dynamic analysis app

Dùng ADB +

Frida

Bạn có thể:

hook function

bypass login

debug API

Đây là kỹ thuật pentester Android hay dùng.

📊 6. Monitor hiệu năng điện thoại

ADB có thể lấy metrics:

adb shell dumpsys meminfo
adb shell dumpsys cpuinfo

Dev dùng để:

test memory leak

test performance

8️⃣ Giả lập xoay màn hình
adb shell settings put system user_rotation 1

Values:

0 portrait

1 landscape

🔟 Chụp screenshot không lưu file
adb exec-out screencap -p > screenshot.png

👉 screenshot thẳng về PC.

11️⃣ Xem tiến trình đang chạy
adb shell ps -A
12️⃣ Kiểm tra RAM
adb shell free -m
13️⃣ Kiểm tra CPU usage
adb shell top
14️⃣ Kiểm tra dung lượng storage
adb shell df -h
