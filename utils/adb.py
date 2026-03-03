import subprocess, zipfile, tempfile, os, json, shutil

# Đảm bảo adb luôn tìm được dù PATH của session chưa được update
_ANDROID_TOOLS_PATHS = [
    r"C:\android-tools\platform-tools",
    r"C:\android-tools\scrcpy-win64-v3.3.4",
]
for _p in _ANDROID_TOOLS_PATHS:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

si = subprocess.STARTUPINFO()
si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

def adb(serial, *args, check=True):
    result = subprocess.run(
        ["adb", "-s", serial, *args],
        startupinfo=si,
        check=False,
        capture_output=True,
        text=True
    )
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        raise RuntimeError(err)
    return result

def adb_output(serial, *args):
    result = subprocess.run(
        ["adb", "-s", serial, *args],
        startupinfo=si,
        check=True,
        capture_output=True,
        text=True
    )
    return result.stdout.strip()

def install_xapk(serial: str, xapk_path: str):
    """
    Install a .xapk or .apkm file to a device.
    - XAPK (APKPure): manifest.json with "split_apks" list
    - APKM (APKMirror): info.json with "pname", all split_*.apk + base.apk files
    """
    tmp_dir = tempfile.mkdtemp(prefix="xapk_")
    try:
        # --- Extract archive ---
        with zipfile.ZipFile(xapk_path, "r") as z:
            z.extractall(tmp_dir)

        package_name = None
        split_apk_files = []
        ext = os.path.splitext(xapk_path)[1].lower()

        if ext == ".apkm":
            # --- APKM format (APKMirror): info.json, all .apk files are splits ---
            info_path = os.path.join(tmp_dir, "info.json")
            if os.path.isfile(info_path):
                with open(info_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                package_name = data.get("pname") or data.get("package_name")
            # Collect all .apk files (base.apk + split_*.apk)
            for fname in os.listdir(tmp_dir):
                if fname.lower().endswith(".apk"):
                    split_apk_files.append(os.path.join(tmp_dir, fname))

        else:
            # --- XAPK format (APKPure): manifest.json with explicit split_apks list ---
            manifest_path = os.path.join(tmp_dir, "manifest.json")
            if os.path.isfile(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                package_name = data.get("package_name")
                for entry in data.get("split_apks", []):
                    fpath = os.path.join(tmp_dir, entry["file"])
                    if os.path.isfile(fpath):
                        split_apk_files.append(fpath)

        # Fallback: scan all .apk if still empty
        if not split_apk_files:
            for root, _, files in os.walk(tmp_dir):
                for fname in files:
                    if fname.lower().endswith(".apk"):
                        split_apk_files.append(os.path.join(root, fname))

        if not split_apk_files:
            raise FileNotFoundError(f"No APK files found inside {xapk_path}")

        # --- Install split APKs ---
        adb(serial, "install-multiple", "-r", *split_apk_files)

        # --- Push OBB files if any ---
        for root, _, files in os.walk(tmp_dir):
            for fname in files:
                if fname.lower().endswith(".obb"):
                    src = os.path.join(root, fname)
                    remote_dir = f"/sdcard/Android/obb/{package_name}" if package_name else "/sdcard"
                    adb(serial, "shell", "mkdir", "-p", remote_dir, check=False)
                    adb(serial, "push", src, f"{remote_dir}/{fname}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def setup_adb_keyboard(
    serial: str,
    apk_path: str = "keyboard.apk",
    ime: str = "com.android.adbkeyboard/.AdbIME"
):
    adb(serial, "install", "-r", apk_path)
    adb(serial, "shell", "ime", "enable", ime)
    adb(serial, "shell", "ime", "set", ime)