"""
Device I/O layer — ADB subprocess wrapper with:
  - Configurable timeout per command
  - Error capture & structured logging
  - Rate-limiting (minimum interval between ADB calls)
  - Retry on transient failures
"""

import time
import random
import subprocess
import logging
import threading
from typing import Optional

logger = logging.getLogger("adbflow.device_io")

# ── Startup-info for Windows (hide console window) ──────────────────────
_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

# ── Rate-limiter: minimum gap between ADB commands per serial ───────────
_MIN_ADB_INTERVAL = 0.02  # 20 ms — avoid flooding ADB server
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


# ---------------------------------------------------------------------------
# Core ADB wrapper
# ---------------------------------------------------------------------------

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

    Returns
    -------
    subprocess.CompletedProcess
    """
    cmd = ["adb", "-s", serial, *args]
    last_err: Optional[Exception] = None

    for attempt in range(max(1, retries)):
        _rate_limit(serial)
        try:
            result = subprocess.run(
                cmd,
                startupinfo=_si,
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
            raise  # adb binary not found — no point retrying
        except Exception as exc:
            last_err = exc
            logger.warning("ADB[%s] error (attempt %d/%d): %s",
                           serial, attempt + 1, retries, exc)

        if attempt < retries - 1:
            time.sleep(0.3 * (attempt + 1))

    raise last_err  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Convenience wrappers — drop-in replacements for the old bare subprocess calls
# ---------------------------------------------------------------------------

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
