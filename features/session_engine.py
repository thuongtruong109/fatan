"""
Session engine — human-like browsing behaviour on a mobile device.

Key improvements over the monolithic ``ads.py``:
  - Seeded RNG per session for reproducible replay / debugging.
  - Structured JSON action log (session_id, action type, coords, state).
  - Coordinate clamping on BOTH top & bottom (was only bottom).
  - Dynamic viewport width in zigzag (was hard-coded 350).
  - Motion variants (flash / zigzag / stutter) use safe-zone from zone dict.
  - All ADB calls go through ``device_io`` (timeout + rate-limit).
"""

from __future__ import annotations

import json
import math
import time
import uuid
import random as _random_module
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.cdp_chrome import ChromeCDP

from utils.device_io import adb_swipe, adb_tap, adb_back
from utils.cdp_helpers import (
    get_webpage_safe_zone,
    get_clickable_elements,
    try_close_overlay,
    InputDriver,
)

logger = logging.getLogger("adbflow.session")

# ---------------------------------------------------------------------------
# Behaviour profiles
# ---------------------------------------------------------------------------

PROFILES = {
    "fast_scroller": {
        "swipe_speed_ms": (180, 450),
        "pause_after_swipe": (0.15, 0.6),
        "read_pause": (0.8, 2.5),
        "read_prob": 0.20,
        "scroll_up_prob": 0.22,
        "overshoot_prob": 0.14,
        "misclick_prob": 0.08,
        "idle_prob": 0.04,
        "bored_exit_prob": 0.05,
        "fatigue_start_min": 3.0,
    },
    "careful_reader": {
        "swipe_speed_ms": (450, 850),
        "pause_after_swipe": (0.5, 1.5),
        "read_pause": (3.0, 8.0),
        "read_prob": 0.55,
        "scroll_up_prob": 0.38,
        "overshoot_prob": 0.12,
        "misclick_prob": 0.05,
        "idle_prob": 0.08,
        "bored_exit_prob": 0.02,
        "fatigue_start_min": 6.0,
    },
    "distracted": {
        "swipe_speed_ms": (280, 700),
        "pause_after_swipe": (0.3, 2.0),
        "read_pause": (1.5, 5.0),
        "read_prob": 0.35,
        "scroll_up_prob": 0.30,
        "overshoot_prob": 0.25,
        "misclick_prob": 0.15,
        "idle_prob": 0.18,
        "bored_exit_prob": 0.08,
        "fatigue_start_min": 2.0,
    },
}


# ---------------------------------------------------------------------------
# Motion primitives — Bezier + easing + jitter
# ---------------------------------------------------------------------------

def _bezier_point(t: float, p0: tuple, p1: tuple, p2: tuple, p3: tuple) -> tuple:
    mt = 1 - t
    x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
    y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
    return (x, y)


def _ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


def _jitter(rng: _random_module.Random, val: float, magnitude: int = 2) -> int:
    if rng.random() < 0.35:
        return round(val + rng.uniform(-magnitude, magnitude))
    return round(val)


def human_swipe(
    serial: str,
    start_x: int, start_y: int,
    end_x: int, end_y: int,
    duration_ms: int | None = None,
    safe_top: int = 60,
    safe_bot: int = 2000,
    rng: _random_module.Random | None = None,
):
    """
    Bezier-curved swipe with micro-jitter + easing.

    **Fix**: clamps Y on BOTH top and bottom (was only clamping bottom before).
    """
    if rng is None:
        rng = _random_module.Random()
    if duration_ms is None:
        duration_ms = rng.randint(350, 800)

    steps = rng.randint(6, 10)

    dx = end_x - start_x
    dy = end_y - start_y
    perp_len = math.sqrt(dx**2 + dy**2) or 1
    perp_x = -dy / perp_len
    perp_y = dx / perp_len

    curve_dist = rng.uniform(0.05, 0.14) * perp_len
    side = rng.choice([-1, 1])
    cp1 = (start_x + dx*0.30 + perp_x*curve_dist*side,
           start_y + dy*0.30 + perp_y*curve_dist*side)
    cp2 = (start_x + dx*0.70 + perp_x*curve_dist*rng.choice([-1, 1]),
           start_y + dy*0.70 + perp_y*curve_dist*rng.choice([-1, 1]))

    p0, p3 = (start_x, start_y), (end_x, end_y)

    points = []
    for i in range(steps + 1):
        t = _ease_in_out(i / steps)
        px, py = _bezier_point(t, p0, cp1, cp2, p3)
        jx = _jitter(rng, px, 2)
        # FIX: clamp BOTH top and bottom
        jy = max(safe_top, min(safe_bot, _jitter(rng, py, 2)))
        points.append((jx, jy))

    seg_ms = max(30, duration_ms // steps)
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        adb_swipe(serial, x0, y0, x1, y1, seg_ms)


# ---------------------------------------------------------------------------
# Extended motion variants
# ---------------------------------------------------------------------------

def _swipe_flash(
    serial: str, x: int, y_start: int, y_end: int,
    safe_top: int, safe_bot: int,
    rng: _random_module.Random | None = None,
):
    """Ultra-fast flick — 80-140 ms, straight vertical."""
    if rng is None:
        rng = _random_module.Random()
    dur = rng.randint(80, 140)
    y_start = max(safe_top + 10, min(safe_bot - 10, y_start))
    y_end   = max(safe_top + 10, min(safe_bot - 10, y_end))
    adb_swipe(serial, x, y_start, x, y_end, dur)


def _swipe_slow_zigzag(
    serial: str, x_center: int, y_start: int, y_end: int,
    safe_top: int, safe_bot: int,
    vw_phy: int = 390,
    rng: _random_module.Random | None = None,
):
    """
    Slow zigzag scroll — 4-7 small segments with X drift.

    **Fix**: uses dynamic ``vw_phy`` instead of hard-coded 350.
    """
    if rng is None:
        rng = _random_module.Random()
    segments = rng.randint(4, 7)
    total_dy = y_end - y_start
    dy_per = total_dy / segments
    cx = x_center
    cy = float(y_start)
    x_margin = 20
    x_limit = max(x_margin + 1, vw_phy - x_margin)
    for _ in range(segments):
        nx = max(x_margin, min(x_limit, cx + rng.randint(-30, 30)))
        ny = cy + dy_per + rng.uniform(-20, 20)
        ny = max(safe_top + 10, min(safe_bot - 10, ny))
        seg_dur = rng.randint(180, 350)
        adb_swipe(serial, round(cx), round(cy), round(nx), round(ny), seg_dur)
        time.sleep(rng.uniform(0.04, 0.15))
        cx, cy = nx, ny


def _swipe_stutter(
    serial: str, x: int, y_start: int, y_end: int,
    safe_top: int, safe_bot: int,
    rng: _random_module.Random | None = None,
):
    """Start-stop stuttering scroll — mimics hesitant finger."""
    if rng is None:
        rng = _random_module.Random()
    total_dist = abs(y_end - y_start)
    direction = 1 if y_end > y_start else -1
    cy = y_start
    taps = rng.randint(3, 6)
    chunk = total_dist / taps
    for _ in range(taps):
        ny = cy + direction * (chunk + rng.uniform(-40, 40))
        ny = max(safe_top + 10, min(safe_bot - 10, ny))
        dur = rng.randint(120, 280)
        adb_swipe(serial, x, round(cy), x, round(ny), dur)
        cy = ny
        time.sleep(rng.uniform(0.08, 0.55))


# ---------------------------------------------------------------------------
# Markov state machine
# ---------------------------------------------------------------------------

_MARKOV = {
    "FAST_BROWSE": {"FAST_BROWSE": 0.45, "FOCUS": 0.30, "BORED": 0.18, "IDLE": 0.07},
    "FOCUS":       {"FAST_BROWSE": 0.25, "FOCUS": 0.45, "BORED": 0.20, "IDLE": 0.10},
    "BORED":       {"FAST_BROWSE": 0.30, "FOCUS": 0.15, "BORED": 0.35, "IDLE": 0.20},
    "IDLE":        {"FAST_BROWSE": 0.40, "FOCUS": 0.20, "BORED": 0.20, "IDLE": 0.20},
}


def _next_state(current: str, rng: _random_module.Random) -> str:
    transitions = _MARKOV[current]
    states = list(transitions.keys())
    weights = list(transitions.values())
    return rng.choices(states, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Action logger
# ---------------------------------------------------------------------------

class _ActionLog:
    """Structured in-memory log of every action in a session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._entries: list[dict] = []

    def record(self, **kwargs):
        kwargs["session_id"] = self.session_id
        kwargs["ts"] = time.time()
        self._entries.append(kwargs)
        # Also emit a human-readable line
        action = kwargs.get("action", "?")
        extra = {k: v for k, v in kwargs.items()
                 if k not in ("session_id", "ts", "action")}
        extra_str = " ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
        logger.info("  [%s] %s %s", self.session_id[:8], action, extra_str)

    def to_json_lines(self) -> str:
        return "\n".join(json.dumps(e) for e in self._entries)


# ---------------------------------------------------------------------------
# browse_session — the main engine
# ---------------------------------------------------------------------------

def browse_session(
    serial: str,
    cdp: "ChromeCDP",
    *,
    min_duration: float = 60.0,
    max_duration: float = 90.0,
    original_url: str = "",
    click_prob: float = 0.30,
    burst_prob: float = 0.30,
    scroll_dist_min: int = 500,
    scroll_dist_max: int = 1400,
    read_pause_min: float | None = None,
    read_pause_max: float | None = None,
    seed: int | None = None,
    # ── NEW scroll-tuning params ─────────────────────────────────────
    scroll_focus: float = 1.0,
    swipe_speed_min_ms: int | None = None,
    swipe_speed_max_ms: int | None = None,
    overshoot_prob: float | None = None,
    scroll_style_weights: dict | None = None,
    profile: str | None = None,
) -> dict:
    """
    Human-like browsing session — scrolling is the dominant action (~75 % of time).

    Parameters
    ----------
    scroll_focus : float
        Multiplier on scroll action weights (0.5 = less scroll, 2.0 = heavy scroll).
        Default 1.0 = balanced. Values above 1.5 make scrolling very dominant.
    swipe_speed_min_ms / swipe_speed_max_ms : int | None
        Override the profile's swipe speed range (ms per swipe).
        Smaller = faster swipes, larger = slower, more deliberate swipes.
    overshoot_prob : float | None
        Override profile overshoot probability (0–1).
        Controls how often a swipe overshoots then corrects back.
    scroll_style_weights : dict | None
        Override the style distribution for ``pick_style()``.
        Keys: "normal", "flash", "zigzag", "stutter" with integer weights.
        Example: {"normal": 50, "flash": 30, "zigzag": 10, "stutter": 10}
    profile : str | None
        Force a specific PROFILES key ("fast_scroller", "careful_reader",
        "distracted") instead of picking randomly.

    Returns
    -------
    dict
        ``{"swipe_count": int, "click_count": int, "duration": float,
           "profile": str, "session_id": str}``
    """
    # ── Seeded RNG for reproducibility ──────────────────────────────
    session_id = uuid.uuid4().hex[:12]
    if seed is None:
        seed = int.from_bytes(bytes.fromhex(session_id), "big") % (2**31)
    rng = _random_module.Random(seed)
    alog = _ActionLog(session_id)

    # ── Profile selection ───────────────────────────────────────────
    if profile and profile in PROFILES:
        profile_name = profile
    else:
        profile_name = rng.choice(list(PROFILES.keys()))
    p = dict(PROFILES[profile_name])  # copy so we can mutate
    if read_pause_min is not None and read_pause_max is not None:
        p["read_pause"] = (read_pause_min, read_pause_max)
    if swipe_speed_min_ms is not None and swipe_speed_max_ms is not None:
        p["swipe_speed_ms"] = (swipe_speed_min_ms, swipe_speed_max_ms)
    elif swipe_speed_min_ms is not None:
        p["swipe_speed_ms"] = (swipe_speed_min_ms, p["swipe_speed_ms"][1])
    elif swipe_speed_max_ms is not None:
        p["swipe_speed_ms"] = (p["swipe_speed_ms"][0], swipe_speed_max_ms)
    if overshoot_prob is not None:
        p["overshoot_prob"] = max(0.0, min(1.0, overshoot_prob))

    target_duration = rng.uniform(min_duration, max_duration)
    session_start = time.time()
    swipe_count = 0
    click_count = 0
    state = "FAST_BROWSE"

    # ── Safe zone ───────────────────────────────────────────────────
    zone = get_webpage_safe_zone(cdp)
    y_min      = zone["y_min"]
    y_max      = zone["y_max"]
    chrome_top = zone.get("chrome_top", 150)
    vw         = zone.get("vw", 390)
    dpr        = zone.get("dpr", 1.0)
    vh_css     = zone.get("vh_css", 650)
    vh_physical = y_max - y_min

    SAFE_TOP = y_min + 25
    SAFE_BOT = y_max - 25

    # InputDriver (unified backend)
    inp = InputDriver(serial, cdp, chrome_top=chrome_top, dpr=dpr)

    alog.record(action="session_start", profile=profile_name,
                target_s=round(target_duration), seed=seed,
                safe_top=SAFE_TOP, safe_bot=SAFE_BOT, vw=vw, dpr=dpr)

    elements: list = []
    elem_age: int = 0
    virtual_y: float = 0.0
    consec_dn: int = 0
    action_no: int = 0

    # ── Helpers ─────────────────────────────────────────────────────
    def rand_x() -> int:
        return rng.randint(int(vw * 0.15), int(vw * 0.85))

    def safe_swipe(ys: int, ye: int, ms: int, style: str = "normal"):
        ys = max(SAFE_TOP + 8, min(SAFE_BOT - 8, ys))
        ye = max(SAFE_TOP + 8, min(SAFE_BOT - 8, ye))
        sx = rand_x()
        if style == "flash":
            _swipe_flash(serial, sx, ys, ye, SAFE_TOP, SAFE_BOT, rng=rng)
        elif style == "zigzag":
            _swipe_slow_zigzag(serial, sx, ys, ye, SAFE_TOP, SAFE_BOT,
                               vw_phy=vw, rng=rng)
        elif style == "stutter":
            _swipe_stutter(serial, sx, ys, ye, SAFE_TOP, SAFE_BOT, rng=rng)
        else:
            if rng.random() < p["overshoot_prob"]:
                going_up = ye > ys
                over = rng.randint(20, 70)
                ov_y = min(SAFE_BOT - 5, ye + over) if going_up else max(SAFE_TOP + 5, ye - over)
                human_swipe(serial, sx, ys, sx, ov_y, duration_ms=ms,
                            safe_top=SAFE_TOP, safe_bot=SAFE_BOT, rng=rng)
                time.sleep(rng.uniform(0.03, 0.10))
                back_y = max(SAFE_TOP + 5, min(SAFE_BOT - 5,
                    ov_y - rng.randint(10, 40) if going_up
                    else ov_y + rng.randint(10, 40)
                ))
                human_swipe(serial, sx, ov_y, sx, back_y,
                            duration_ms=rng.randint(70, 180),
                            safe_top=SAFE_TOP, safe_bot=SAFE_BOT, rng=rng)
            else:
                human_swipe(serial, sx, ys, sx, ye, duration_ms=ms,
                            safe_top=SAFE_TOP, safe_bot=SAFE_BOT, rng=rng)

    def scroll_pause(style: str = "normal"):
        nonlocal remaining
        if style == "flash":
            time.sleep(rng.uniform(0.01, 0.08))
        elif state == "FOCUS" and rng.random() < p["read_prob"] * 0.5:
            plo, phi = p["read_pause"]
            pause = min(rng.uniform(plo, phi), remaining * 0.10)
            if pause > 0.5:
                alog.record(action="read_pause", duration=round(pause, 1))
                time.sleep(pause)
        elif state == "FAST_BROWSE":
            time.sleep(rng.uniform(0.02, 0.18))
        else:
            time.sleep(rng.uniform(0.05, 0.30))

    def pick_style() -> str:
        if scroll_style_weights:
            styles = list(scroll_style_weights.keys())
            weights = list(scroll_style_weights.values())
            return rng.choices(styles, weights=weights, k=1)[0]
        r = rng.random()
        if r < 0.18:   return "flash"
        elif r < 0.35: return "zigzag"
        elif r < 0.48: return "stutter"
        else:           return "normal"

    def pick_dist() -> int:
        if state == "FAST_BROWSE":
            return rng.randint(scroll_dist_min + 100, scroll_dist_max)
        elif state == "FOCUS":
            # FIX: don't cut to 1/3 — use 60-90% of min range (deliberate, not tiny)
            lo = max(150, int(scroll_dist_min * 0.60))
            hi = max(lo + 50, int(scroll_dist_min * 0.90))
            return rng.randint(lo, hi)
        elif state == "BORED":
            return rng.randint(scroll_dist_min, scroll_dist_max - 50)
        return rng.randint(scroll_dist_min, scroll_dist_max)

    def refresh_zone():
        nonlocal y_min, y_max, chrome_top, SAFE_TOP, SAFE_BOT, vh_physical, dpr, vh_css, vw
        z = get_webpage_safe_zone(cdp)
        y_min = z["y_min"];  y_max = z["y_max"]
        chrome_top = z.get("chrome_top", chrome_top)
        dpr = z.get("dpr", dpr);  vh_css = z.get("vh_css", vh_css)
        vw = z.get("vw", vw)
        SAFE_TOP = y_min + 25;  SAFE_BOT = y_max - 25
        vh_physical = SAFE_BOT - SAFE_TOP
        inp.update_zone(chrome_top, dpr)

    def refresh_elems():
        nonlocal elements, elem_age
        elements = get_clickable_elements(
            cdp, chrome_top, SAFE_TOP, SAFE_BOT,
            dpr=dpr, vh_css=vh_css, vw_phy=vw,
        )
        elem_age = 0

    def return_origin(lo: float = 0.7, hi: float = 1.5):
        if original_url:
            cdp.navigate(original_url)
            time.sleep(rng.uniform(lo, hi))
            refresh_zone()
            refresh_elems()
        else:
            adb_back(serial)
            time.sleep(rng.uniform(0.5, 1.0))

    # ════════════════════════════════════════════════════════════════
    # MAIN LOOP
    # ════════════════════════════════════════════════════════════════
    while True:
        elapsed = time.time() - session_start
        remaining = target_duration - elapsed
        if remaining <= 0:
            break

        fatigue = min(elapsed / 60.0 / p["fatigue_start_min"], 1.0)
        speed_lo, speed_hi = p["swipe_speed_ms"]
        state = _next_state(state, rng)
        action_no += 1

        # ── IDLE ─────────────────────────────────────────────────────
        if state == "IDLE" and action_no % 8 == 0:
            idle_t = min(rng.uniform(0.8, 3.5), remaining * 0.12)
            if idle_t > 0.5:
                alog.record(action="idle", duration=round(idle_t, 1))
                time.sleep(idle_t)
            continue
        if state == "IDLE":
            state = "FAST_BROWSE"

        # ── Refresh elements every 5 actions ─────────────────────────
        elem_age += 1
        if elem_age >= 5 or not elements:
            refresh_elems()

        # ── URL drift guard (every 6 actions) ────────────────────────
        if original_url and action_no % 6 == 0:
            try:
                cur = cdp.get_current_url() or ""
                if cur and cur.rstrip("/") != original_url.rstrip("/"):
                    alog.record(action="url_drift_return")
                    cdp.navigate(original_url)
                    time.sleep(rng.uniform(1.0, 1.8))
                    refresh_zone(); refresh_elems()
                    consec_dn = 0
                    continue
            except Exception:
                pass

        # ── Action weights ───────────────────────────────────────────
        up_w = max(18, min(60, 12 + consec_dn * 7))
        sf = max(0.1, scroll_focus)  # scroll_focus multiplier
        W = {
            "scroll_dn":   round(65 * sf),
            "scroll_up":   round(up_w * sf),
            "burst_dn":    round(int(burst_prob * 50) * sf),
            "burst_up":    round(max(10, up_w // 2) * sf),
            "mini_series": round(28 * sf),
            "deep_scroll": round(20 * sf),
            "swipe_back":  14,
            "check_top":   10 if virtual_y > 500 else 2,
            "click_elem":  int(click_prob * 20) if elements else 0,
            "double_tap":  3 if elements else 0,
            "long_press":  2 if elements else 0,
            "mis_tap":     int(p["misclick_prob"] * 22) if elements else 0,
        }

        act = rng.choices(list(W.keys()), weights=list(W.values()), k=1)[0]
        ms  = round(rng.randint(speed_lo, speed_hi) * (1 + 0.20 * fatigue))
        sty = pick_style()
        dist = pick_dist()

        # ════════════════════════════════════════════════════════════
        if act == "scroll_dn":
            ys = rng.randint(SAFE_TOP + int(vh_physical * 0.30), SAFE_BOT - 15)
            ye = max(SAFE_TOP + 12, ys - dist)
            alog.record(action="scroll_dn", dist=ys-ye, style=sty, state=state)
            safe_swipe(ys, ye, ms, sty)
            swipe_count += 1; virtual_y += (ys - ye); consec_dn += 1
            scroll_pause(sty)

        elif act == "scroll_up":
            ys = rng.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.55))
            ye = min(SAFE_BOT - 12, ys + dist)
            alog.record(action="scroll_up", dist=ye-ys, style=sty, state=state)
            safe_swipe(ys, ye, ms, sty)
            swipe_count += 1
            virtual_y = max(0.0, virtual_y - (ye - ys))
            consec_dn = max(0, consec_dn - 2)
            scroll_pause(sty)

        elif act == "burst_dn":
            n = rng.randint(4, 10)
            bx = rand_x()
            alog.record(action="burst_dn", count=n, state=state)
            for _ in range(n):
                d = rng.randint(scroll_dist_min, scroll_dist_max)
                ys = rng.randint(SAFE_TOP + int(vh_physical * 0.22), SAFE_BOT - 20)
                ye = max(SAFE_TOP + 12, ys - d)
                _swipe_flash(serial, bx, ys, ye, SAFE_TOP, SAFE_BOT, rng=rng)
                virtual_y += (ys - ye); consec_dn += 1; swipe_count += 1
                time.sleep(rng.uniform(0.02, 0.10))
            time.sleep(rng.uniform(0.25, 1.2))

        elif act == "burst_up":
            n = rng.randint(3, 7)
            bx = rand_x()
            alog.record(action="burst_up", count=n, state=state)
            for _ in range(n):
                d = rng.randint(max(150, scroll_dist_min // 2), scroll_dist_min + 200)
                ys = rng.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.52))
                ye = min(SAFE_BOT - 12, ys + d)
                _swipe_flash(serial, bx, ys, ye, SAFE_TOP, SAFE_BOT, rng=rng)
                virtual_y = max(0.0, virtual_y - (ye - ys))
                consec_dn = max(0, consec_dn - 1)
                swipe_count += 1
                time.sleep(rng.uniform(0.02, 0.11))
            time.sleep(rng.uniform(0.15, 0.80))

        elif act == "mini_series":
            n = rng.randint(4, 9)
            alog.record(action="mini_series", count=n, state=state)
            for _ in range(n):
                up = rng.random() < 0.42
                # mini_series uses medium-short distances — still feels like a real nudge
                d = rng.randint(
                    max(120, scroll_dist_min // 4),
                    max(300, scroll_dist_min // 2),
                )
                if up:
                    ys = rng.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.48))
                    ye = min(SAFE_BOT - 12, ys + d)
                    virtual_y = max(0.0, virtual_y - (ye - ys))
                    consec_dn = max(0, consec_dn - 1)
                else:
                    ys = rng.randint(SAFE_TOP + int(vh_physical * 0.32), SAFE_BOT - 18)
                    ye = max(SAFE_TOP + 12, ys - d)
                    virtual_y += (ys - ye); consec_dn += 1
                human_swipe(serial, rand_x(), ys, rand_x(), ye,
                            duration_ms=rng.randint(180, 500),
                            safe_top=SAFE_TOP, safe_bot=SAFE_BOT, rng=rng)
                swipe_count += 1
                time.sleep(rng.uniform(0.05, 0.40))
            time.sleep(rng.uniform(0.08, 0.45))

        elif act == "deep_scroll":
            # Continuous multi-swipe covering 2-4 screen heights without pause
            n = rng.randint(4, 8)
            seg_dist = rng.randint(
                max(200, scroll_dist_min),
                max(scroll_dist_min + 200, scroll_dist_max),
            )
            bx = rand_x()
            alog.record(action="deep_scroll", swipes=n, dist_each=seg_dist, state=state)
            for i in range(n):
                ys = rng.randint(SAFE_TOP + int(vh_physical * 0.25), SAFE_BOT - 20)
                ye = max(SAFE_TOP + 15, ys - seg_dist)
                seg_ms = rng.randint(
                    max(80, p["swipe_speed_ms"][0] - 60),
                    p["swipe_speed_ms"][0] + 80,
                )
                if rng.random() < 0.60:
                    _swipe_flash(serial, bx, ys, ye, SAFE_TOP, SAFE_BOT, rng=rng)
                else:
                    human_swipe(serial, bx, ys, bx, ye,
                                duration_ms=seg_ms,
                                safe_top=SAFE_TOP, safe_bot=SAFE_BOT, rng=rng)
                virtual_y += (ys - ye); consec_dn += 1; swipe_count += 1
                # Very short gap between deep-scroll segments
                gap = rng.uniform(0.01, 0.08) if i < n - 2 else rng.uniform(0.08, 0.30)
                time.sleep(gap)
            # Brief reading pause after deep scroll
            if state == "FOCUS" and rng.random() < 0.55:
                plo, phi = p["read_pause"]
                time.sleep(min(rng.uniform(plo, phi), remaining * 0.08))
            else:
                time.sleep(rng.uniform(0.15, 0.60))

        elif act == "swipe_back":
            d_up = rng.randint(scroll_dist_min, scroll_dist_max)
            d_dn = rng.randint(scroll_dist_min // 2, scroll_dist_min + 100)
            alog.record(action="swipe_back", up=d_up, dn=d_dn)
            ys_u = rng.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.48))
            ye_u = min(SAFE_BOT - 12, ys_u + d_up)
            _swipe_flash(serial, rand_x(), ys_u, ye_u, SAFE_TOP, SAFE_BOT, rng=rng)
            virtual_y = max(0.0, virtual_y - (ye_u - ys_u))
            consec_dn = max(0, consec_dn - 2)
            swipe_count += 1
            time.sleep(rng.uniform(0.20, 0.75))
            ys_d = rng.randint(SAFE_TOP + int(vh_physical * 0.30), SAFE_BOT - 18)
            ye_d = max(SAFE_TOP + 12, ys_d - d_dn)
            human_swipe(serial, rand_x(), ys_d, rand_x(), ye_d,
                        duration_ms=rng.randint(speed_hi, speed_hi + 250),
                        safe_top=SAFE_TOP, safe_bot=SAFE_BOT, rng=rng)
            virtual_y += (ys_d - ye_d); consec_dn += 1; swipe_count += 1
            scroll_pause("normal")

        elif act == "check_top":
            up_px = min(virtual_y, rng.randint(350, 800))
            alog.record(action="check_top", up_px=round(up_px))
            left = up_px; bx2 = rand_x()
            while left > 60:
                chunk = min(left, rng.randint(200, 500))
                ys = rng.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.48))
                ye = min(SAFE_BOT - 12, ys + chunk)
                _swipe_flash(serial, bx2, ys, ye, SAFE_TOP, SAFE_BOT, rng=rng)
                virtual_y = max(0.0, virtual_y - (ye - ys))
                left -= (ye - ys)
                swipe_count += 1
                time.sleep(rng.uniform(0.02, 0.09))
            consec_dn = 0
            time.sleep(rng.uniform(0.3, 1.2))

        elif act == "click_elem" and elements:
            priority = {"image": 0, "button": 1, "label": 2, "text": 3, "card": 4}
            pool = sorted(elements, key=lambda e: priority.get(e["type"], 5))
            pool = pool[:max(1, int(len(pool) * 0.85))]
            seq = rng.randint(2, 3) if rng.random() < 0.28 else 1
            for _ci in range(seq):
                if not pool: break
                tgt = rng.choice(pool)
                tx, ty = tgt["x"], tgt["y"]
                alog.record(action="click", type=tgt["type"], x=tx, y=ty)
                time.sleep(rng.uniform(0.05, 0.18))
                adb_tap(serial, tx, ty)
                click_count += 1
                time.sleep(rng.uniform(0.8, 2.0))
                if tgt["type"] in ("image", "card", "button"):
                    if try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT,
                                         vw_phy=vw, dpr=dpr):
                        time.sleep(rng.uniform(0.2, 0.5))
                if _ci < seq - 1:
                    time.sleep(rng.uniform(0.12, 0.40))
            return_origin(0.6, 1.4)

        elif act == "double_tap" and elements:
            tgt = rng.choice(elements)
            tx, ty = tgt["x"], tgt["y"]
            alog.record(action="double_tap", type=tgt["type"], x=tx, y=ty)
            adb_tap(serial, tx, ty)
            time.sleep(rng.uniform(0.07, 0.15))
            adb_tap(serial, tx + rng.randint(-3, 3), ty + rng.randint(-3, 3))
            time.sleep(rng.uniform(0.5, 1.5))
            try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT,
                              vw_phy=vw, dpr=dpr)
            return_origin(0.5, 1.2)

        elif act == "long_press" and elements:
            tgt = rng.choice(elements)
            tx, ty = tgt["x"], tgt["y"]
            hold = rng.randint(500, 1200)
            alog.record(action="long_press", type=tgt["type"], x=tx, y=ty, hold_ms=hold)
            adb_swipe(serial, tx, ty, tx, ty, hold)
            time.sleep(rng.uniform(0.4, 1.0))
            try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT,
                              vw_phy=vw, dpr=dpr)
            return_origin(0.5, 1.1)

        elif act == "mis_tap" and elements:
            tgt = rng.choice(elements)
            tx = max(8, min(vw - 8, tgt["x"] + rng.randint(-15, 15)))
            ty = max(SAFE_TOP + 5, min(SAFE_BOT - 5, tgt["y"] + rng.randint(-10, 10)))
            alog.record(action="mis_tap", type=tgt["type"], x=tx, y=ty)
            time.sleep(rng.uniform(0.04, 0.15))
            adb_tap(serial, tx, ty)
            time.sleep(rng.uniform(0.4, 1.0))
            try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT,
                              vw_phy=vw, dpr=dpr)
            return_origin(0.5, 1.0)

        # ── Bored exit ───────────────────────────────────────────────
        if elapsed > 20 and rng.random() < p["bored_exit_prob"] * 0.4:
            alog.record(action="bored_exit", elapsed=round(elapsed))
            break

    total = time.time() - session_start
    alog.record(action="session_end", swipes=swipe_count, clicks=click_count,
                duration=round(total, 1))

    return {
        "swipe_count": swipe_count,
        "click_count": click_count,
        "duration": round(total, 1),
        "profile": profile_name,
        "session_id": session_id,
    }
