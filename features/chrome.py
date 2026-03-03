import os
from utils.adb import adb, install_xapk

def install_chrome(serial: str, apk_path: str = "chrome.apkm"):
    ext = os.path.splitext(apk_path)[1].lower()
    if ext in (".xapk", ".apkm"):
        install_xapk(serial, apk_path)
    else:
        adb(serial, "install", "-r", apk_path)

def open_url_in_chrome(serial: str, url: str):
    if not url:
        raise ValueError("URL is empty")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    adb(serial, "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-n", "com.android.chrome/com.google.android.apps.chrome.Main",
        "-d", url)
