import subprocess, zipfile, tempfile, os, json, shutil
import time
import threading
import logging
from typing import Optional

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


# ---------------------------------------------------------------------------
# Device I/O layer — migrated from utils/device_io.py
# ---------------------------------------------------------------------------

logger = logging.getLogger("adbflow.adb")

# ── Rate-limiter: minimum gap between ADB commands per serial ───────────
_MIN_ADB_INTERVAL = 0.02  # 20 ms
_last_cmd_time: dict[str, float] = {}
_rate_lock = threading.Lock()


def _rate_limit(serial: str):
    """Ensure at least _MIN_ADB_INTERVAL seconds between commands to the same device."""
    with _rate_lock:
        now = time.monotonic()
        last = _last_cmd_time.get(serial, 0.0)
        wait = _MIN_ADB_INTERVAL - (now - last)
        if wait > 0:
            time.sleep(wait)
        _last_cmd_time[serial] = time.monotonic()


def adb_run(
    serial: str,
    *args: str,
    timeout: float = 15.0,
    check: bool = False,
    retries: int = 1,
    silent: bool = False,
) -> subprocess.CompletedProcess:
    """
    Run an ADB command with timeout, error capture, and rate-limiting.

    Parameters
    ----------
    serial : str
        ADB device serial.
    *args : str
        Command tokens after ``adb -s <serial>``.
    timeout : float
        Max seconds before killing the subprocess (default 15).
    check : bool
        If True, raise RuntimeError on non-zero returncode.
    retries : int
        How many times to retry on transient failure (default 1 = no retry).
    silent : bool
        If True, suppress debug logging for this call.
    """
    cmd = ["adb", "-s", serial, *args]
    last_err: Optional[Exception] = None

    for attempt in range(max(1, retries)):
        _rate_limit(serial)
        try:
            result = subprocess.run(
                cmd,
                startupinfo=si,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if not silent:
                logger.debug(
                    "ADB[%s] rc=%d cmd=%s", serial, result.returncode, " ".join(args)
                )
            if result.returncode != 0:
                err_msg = (result.stderr or result.stdout or "").strip()
                if not silent:
                    logger.warning(
                        "ADB[%s] non-zero rc=%d: %s", serial, result.returncode, err_msg
                    )
                if check:
                    raise RuntimeError(f"ADB command failed (rc={result.returncode}): {err_msg}")
            return result

        except subprocess.TimeoutExpired:
            last_err = TimeoutError(f"ADB command timed out after {timeout}s: {' '.join(cmd)}")
            logger.warning("ADB[%s] timeout (attempt %d/%d): %s",
                           serial, attempt + 1, retries, " ".join(args))
        except FileNotFoundError:
            raise
        except Exception as exc:
            last_err = exc
            logger.warning("ADB[%s] error (attempt %d/%d): %s",
                           serial, attempt + 1, retries, exc)

        if attempt < retries - 1:
            time.sleep(0.3 * (attempt + 1))

    raise last_err  # type: ignore[misc]


def adb_swipe(serial: str, x0: int, y0: int, x1: int, y1: int, duration_ms: int):
    """ADB input swipe with timeout and error capture."""
    adb_run(
        serial, "shell", "input", "swipe",
        str(x0), str(y0), str(x1), str(y1), str(duration_ms),
        timeout=max(10.0, duration_ms / 1000.0 + 5.0),
        silent=True,
    )


def adb_tap(serial: str, x: int, y: int):
    """ADB input tap with timeout and error capture."""
    adb_run(serial, "shell", "input", "tap", str(x), str(y), timeout=10.0, silent=True)


def adb_back(serial: str):
    """Send KEYEVENT_BACK."""
    adb_run(serial, "shell", "input", "keyevent", "4", timeout=10.0)


def adb_keyevent(serial: str, keycode: int):
    """Send arbitrary key event."""
    adb_run(serial, "shell", "input", "keyevent", str(keycode), timeout=10.0)