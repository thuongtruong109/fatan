## Điều khiển thiết bị từ PC

Ví dụ:

```bash
adb shell input keyevent 26
```

```bash
adb shell monkey -p com.example.app -c android.intent.category.LAUNCHER 1
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

# 🔐 9. Cấp quyền đặc biệt cho app

Một số app cần quyền hệ thống.

ADB có thể cấp:

```bash
adb shell pm grant com.example.app android.permission.WRITE_SECURE_SETTINGS
```

Rất nhiều app automation cần quyền này.

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

### Mirror + control Android

- **scrcpy**

### Automation Android

- **UIAutomator**

### Reverse engineering

- **Frida**

Bạn có thể: hook function, bypass login, debug API

<!-- ---------------------------------------- -->

Nếu bạn muốn các **ADB command cực nâng cao, ít người biết, dùng để can thiệp sâu vào hệ thống** trong **Android** thông qua **Android Debug Bridge**, thì dưới đây là những nhóm lệnh mà **pro developer / reverse engineer / system dev** thường dùng. Nhiều cái gần như không xuất hiện trong tutorial bình thường. 🧠⚙️

---

# 1️⃣ Binder call trực tiếp vào system service

ADB có thể gọi **Binder IPC** trực tiếp.

Liệt kê service:

```bash
adb shell service list
```

Gọi method:

```bash
adb shell service call activity 159
```

Ví dụ:

### lock device

```bash
adb shell service call power 12
```

### simulate keyguard unlock

```bash
adb shell service call window 18
```

# 2️⃣ Inject input ở mức kernel event

Thay vì `input tap`, dùng **event device**.

Xem input device:

```bash
adb shell getevent -lp
```

Inject event:

```bash
adb shell sendevent /dev/input/event2 3 57 14
```

Ứng dụng:

- fake multi-touch
- bypass anti automation
- simulate hardware button

---

# 3️⃣ Điều khiển ActivityManager trực tiếp

`am` có nhiều command cực mạnh.

### start activity với profiling

```bash
adb shell am start --start-profiler /sdcard/profile.trace com.example/.MainActivity
```

### force stop + restart task

```bash
adb shell am restart
```

### dump activity stack

```bash
adb shell dumpsys activity activities
```

# 4️⃣ Can thiệp package manager

`pm` có nhiều lệnh hiếm.

### suspend app

```bash
adb shell pm suspend com.example.app
```

### hide app khỏi launcher

```bash
adb shell pm hide com.example.app
```

### install as instant app

```bash
adb shell pm install --instant app.apk
```

# 5️⃣ Điều khiển SurfaceFlinger (graphics engine)

**SurfaceFlinger** là compositor của Android.

Dump layer:

```bash
adb shell dumpsys SurfaceFlinger
```

Screenshot raw:

```bash
adb shell service call SurfaceFlinger 1013
```

List layer:

```bash
adb shell dumpsys SurfaceFlinger --list
```

Ứng dụng:

- debug rendering
- analyze overlay
- detect hidden UI

---

# 6️⃣ Inject location ở framework level

ADB có thể inject location trực tiếp.

Enable provider:

```bash
adb shell cmd location providers add gps
```

Inject location:

```bash
adb shell cmd location set 10.8231 106.6297
```

Reset:

```bash
adb shell cmd location clear
```

---

# 7️⃣ Debug binder performance

Android có tool binder stats.

```bash
adb shell dumpsys binder_calls_stats
```

Hoặc:

```bash
adb shell dumpsys binder
```

Dùng để:

- debug IPC bottleneck
- optimize system service

---

# 8️⃣ Truy cập internal storage mount

Mount info:

```bash
adb shell cat /proc/mounts
```

Debug vold:

```bash
adb shell dumpsys mount
```

Force unmount:

```bash
adb shell sm unmount
```

# Manipulate network stack

ADB có thể điều khiển network service.

Disable network:

```bash
adb shell svc data disable
```

Fake network latency:

```bash
adb shell cmd network delay 200
```

Fake packet loss:

```bash
adb shell cmd network loss 10
```

---

# 🔟 Debug input latency pipeline

Dump input pipeline:

```bash
adb shell dumpsys input
```

Hoặc:

```bash
adb shell dumpsys inputflinger
```

Xem:

- event latency
- dispatch queue
- dropped events

---

# 11️⃣ Force system UI state

Bạn có thể ép trạng thái system UI.

Ví dụ immersive mode:

```bash
adb shell settings put global policy_control immersive.full=*
```

Disable status bar:

```bash
adb shell service call statusbar 1
```

---

# 12️⃣ Trigger bugreport system

Android có **bugreport subsystem**. Dùng trong CI testing.

```bash
adb shell bugreport bug.zip
```

Hoặc streaming:

```bash
adb bugreport
```

# Trace system performance

```bash
adb shell atrace gfx view sched freq idle am wm
```

```bash
adb shell perfetto
```

Perfetto là tool tracing của Android.

---

# 14️⃣ Low-level memory inspection

Inspect process memory:

```bash
adb shell dumpsys meminfo com.example.app
```

Hoặc:

```bash
adb shell procrank
```

# 1 Override system config runtime

Android có **device_config**.

```bash
adb shell device_config list
```

Override:

```bash
adb shell device_config put activity_manager max_cached_processes 64
```

Có thể thay đổi behavior runtime.

---

# Enable binder transaction log:

```bash
adb shell setprop debug.binder.calls 1
```

```bash
adb shell dumpsys binder_calls_stats
```

Xem route: adb shell ip route
Xem IP: adb shell ip addr show
Xem netstat: adb shell netstat
Ping server: adb shell ping google.com

ROM modding

Remount system

adb remount

Mount system RW

adb shell mount -o rw,remount /system
