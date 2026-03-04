"""
Backward-compatibility shim.
All device I/O code has been merged into utils/adb.py.
Import from utils.adb directly for new code.
"""
from utils.adb import (  # noqa: F401
    adb_run,
    adb_swipe,
    adb_tap,
    adb_back,
    adb_keyevent,
    _rate_limit,
)
