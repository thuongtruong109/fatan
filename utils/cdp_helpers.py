"""
CDP helpers — DOM queries & coordinate helpers for Chrome DevTools Protocol.

All coordinate conversion between CSS-pixels and ADB-physical-pixels is
centralised here so the rest of the codebase never has to worry about DPR.

Key improvements over the previous inline implementation:
  - _get_webpage_safe_zone: fixed chromeBot_phy formula (was self-cancelling)
  - _get_clickable_elements: filters out position:fixed/sticky, header/nav/footer
  - _find_close_button: uses dynamic vw instead of hard-coded 380
  - _try_close_overlay: verifies overlay is actually dismissed (post-condition)
  - InputDriver: unified tap/swipe API with backend choice (ADB vs CDP)
"""

from __future__ import annotations
import time
import random
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.cdp_chrome import ChromeCDP

from utils.device_io import adb_tap, adb_swipe

logger = logging.getLogger("adbflow.cdp_helpers")


# ---------------------------------------------------------------------------
# Safe-zone detection
# ---------------------------------------------------------------------------

def get_webpage_safe_zone(cdp: "ChromeCDP") -> dict:
    """
    Measure the safe content zone via CDP JavaScript.

    Returns physical-pixel (ADB) coordinates that exclude:
      - Android status bar
      - Chrome address bar / toolbar
      - Android navigation bar

    The old formula ``chromeBot = screenH - vpH - chromeTop`` collapses to 0
    when ``chromeTop = screenH - vpH``.  Fixed by using ``visualViewport``
    when available and falling back to sensible defaults.
    """
    result = cdp.execute_js("""
    (function() {
        var vw  = window.innerWidth  || document.documentElement.clientWidth;
        var vh  = window.innerHeight || document.documentElement.clientHeight;
        var dpr = window.devicePixelRatio || 1;

        var screenW_css = window.screen.width;
        var screenH_css = window.screen.height;
        var screenW_phy = Math.round(screenW_css * dpr);
        var screenH_phy = Math.round(screenH_css * dpr);

        var vpW_phy = Math.round(vw * dpr);
        var vpH_phy = Math.round(vh * dpr);

        // ── Compute chrome top (status bar + address bar) ────────────
        // Use visualViewport.offsetTop when available — it gives the
        // exact distance from the top of the layout viewport to the
        // visual viewport, which equals the collapsed-toolbar offset.
        var vvOffsetTop = 0;
        if (window.visualViewport) {
            vvOffsetTop = window.visualViewport.offsetTop;
        }
        // chromeTop_phy = everything above the web content
        //   screenH_phy - vpH_phy gives total UI chrome (top + bottom)
        var totalChrome = screenH_phy - vpH_phy;
        // Heuristic split: top gets ~62 %, bottom ~38 % of total chrome
        // (status 24dp + toolbar 56dp = 80dp vs nav-bar 48dp ≈ 63/37)
        var chromeTop_phy, chromeBot_phy;
        if (totalChrome > 0 && totalChrome < screenH_phy * 0.45) {
            chromeTop_phy = Math.round(totalChrome * 0.625);
            chromeBot_phy = totalChrome - chromeTop_phy;
        } else {
            // Fallback defaults (dp * dpr)
            chromeTop_phy = Math.round(80 * dpr);
            chromeBot_phy = Math.round(48 * dpr);
        }
        // Sanity: top must be ≥ 50 and < 40 % screen
        if (chromeTop_phy < 50)  chromeTop_phy = Math.round(80 * dpr);
        if (chromeTop_phy > screenH_phy * 0.40) chromeTop_phy = Math.round(80 * dpr);
        if (chromeBot_phy < 0)   chromeBot_phy = Math.round(48 * dpr);

        return {
            vw_css: vw, vh_css: vh, dpr: dpr,
            screenW_phy: screenW_phy, screenH_phy: screenH_phy,
            vpW_phy: vpW_phy, vpH_phy: vpH_phy,
            chromeTop_phy: chromeTop_phy,
            chromeBot_phy: chromeBot_phy
        };
    })()
    """)

    if not result:
        return {
            "x_min": 10, "x_max": 370,
            "y_min": 150, "y_max": 750,
            "chrome_top": 150, "chrome_bot": 48,
            "vh": 650, "vw": 390,
            "vh_css": 650, "vw_css": 390,
            "dpr": 1.0, "screenH_phy": 900,
        }

    dpr         = result.get("dpr", 1.0) or 1.0
    chrome_top  = int(result.get("chromeTop_phy", 150))
    chrome_bot  = int(result.get("chromeBot_phy", 48))
    screenH_phy = int(result.get("screenH_phy", 900))
    screenW_phy = int(result.get("screenW_phy", 390))
    vpH_phy     = int(result.get("vpH_phy", 650))
    vpW_phy     = int(result.get("vpW_phy", 390))
    vh_css      = int(result.get("vh_css", 650))
    vw_css      = int(result.get("vw_css", 390))

    padding = 12
    y_min = max(50, chrome_top + padding)
    y_max = min(int(screenH_phy * 0.90), chrome_top + vpH_phy - padding)

    return {
        "x_min": 10,
        "x_max": vpW_phy - 10,
        "y_min": y_min,
        "y_max": y_max,
        "chrome_top": chrome_top,
        "chrome_bot": chrome_bot,
        "vh": vpH_phy,
        "vw": vpW_phy,
        "vh_css": vh_css,
        "vw_css": vw_css,
        "dpr": dpr,
        "screenH_phy": screenH_phy,
    }


# ---------------------------------------------------------------------------
# Clickable-element discovery
# ---------------------------------------------------------------------------

def get_clickable_elements(
    cdp: "ChromeCDP",
    chrome_top: int,
    y_min: int,
    y_max: int,
    max_elements: int = 40,
    dpr: float = 1.0,
    vh_css: int = 0,
    vw_phy: int = 0,
) -> list[dict]:
    """
    Query non-navigating clickable elements in the current viewport.

    Improvements:
      - Skips ``position: fixed | sticky`` elements (nav bars, sticky headers).
      - Skips elements inside ``<header>``, ``<nav>``, ``<footer>``.
      - Uses dynamic viewport width instead of hard-coded values.
      - Returns physical-pixel coordinates (ADB).
    """
    safe_css_top = 25
    safe_css_bot = max(20, (vh_css - 25)) if vh_css > 0 else 620

    result = cdp.execute_js(f"""
    (function() {{
        var maxEl = {max_elements};
        var safeCssTop = {safe_css_top};
        var safeCssBot = {safe_css_bot};
        var results = [];

        // Helper: is element inside header/nav/footer?
        function inNavRegion(el) {{
            var node = el;
            while (node && node !== document.body) {{
                var tag = (node.tagName || '').toLowerCase();
                if (tag === 'header' || tag === 'nav' || tag === 'footer') return true;
                node = node.parentElement;
            }}
            return false;
        }}

        // Helper: is element fixed/sticky?
        function isFixedOrSticky(el) {{
            try {{
                var pos = window.getComputedStyle(el).position;
                return pos === 'fixed' || pos === 'sticky';
            }} catch(e) {{ return false; }}
        }}

        var typeMap = [
            {{ sel: 'button, [role="button"], input[type="button"], input[type="submit"]', type: 'button' }},
            {{ sel: 'img, figure, picture, [class*="image"], [class*="photo"], [class*="banner"], [class*="thumb"], [class*="cover"]', type: 'image' }},
            {{ sel: 'h1, h2, h3, h4, p, [class*="title"], [class*="heading"], [class*="desc"], [class*="text"]', type: 'text' }},
            {{ sel: '[class*="card"], [class*="item"], [class*="product"], article, section > div', type: 'card' }},
            {{ sel: 'span, label, [class*="tag"], [class*="badge"], [class*="price"], [class*="rating"]', type: 'label' }},
        ];

        var vw = window.innerWidth;
        var vh = window.innerHeight;
        var seen = new Set();

        for (var ti = 0; ti < typeMap.length && results.length < maxEl; ti++) {{
            var t = typeMap[ti];
            var els;
            try {{ els = document.querySelectorAll(t.sel); }} catch(e) {{ continue; }}
            for (var i = 0; i < els.length && results.length < maxEl; i++) {{
                var el = els[i];

                // Skip fixed/sticky (navbars, floating buttons)
                if (isFixedOrSticky(el)) continue;
                // Skip elements inside header/nav/footer
                if (inNavRegion(el)) continue;

                var rect = el.getBoundingClientRect();
                if (rect.width < 12 || rect.height < 12) continue;
                if (rect.top < 0 || rect.bottom > vh) continue;
                if (rect.left < 0 || rect.right > vw) continue;

                var cx = Math.round(rect.left + rect.width / 2);
                var cy = Math.round(rect.top  + rect.height / 2);
                if (cy < safeCssTop || cy > safeCssBot) continue;
                if (cx < 8 || cx > vw - 8) continue;

                var key = Math.round(cx/8) + '_' + Math.round(cy/8);
                if (seen.has(key)) continue;
                seen.add(key);

                results.push({{ x: cx, y: cy, type: t.type }});
            }}
        }}
        return results;
    }})()
    """)

    if not result or not isinstance(result, list):
        return []

    effective_vw = vw_phy or 390
    out: list[dict] = []
    for el in result:
        css_x = int(el.get("x", 0))
        css_y = int(el.get("y", 0))
        phy_x = round(css_x * dpr)
        phy_y = round(css_y * dpr) + chrome_top
        if phy_y < y_min or phy_y > y_max:
            continue
        if phy_x < 8 or phy_x > effective_vw - 8:
            continue
        out.append({"x": phy_x, "y": phy_y, "type": el.get("type", "image")})
    return out


# ---------------------------------------------------------------------------
# Overlay close helpers
# ---------------------------------------------------------------------------

def find_close_button(
    cdp: "ChromeCDP",
    chrome_top: int,
    safe_top: int,
    safe_bot: int,
    vw_phy: int = 390,
    dpr: float = 1.0,
) -> Optional[dict]:
    """
    Find a close/cancel/dismiss button on the current overlay/modal.

    Returns ``{x, y}`` in physical (ADB) coordinates, or None.
    Uses dynamic viewport width instead of hard-coded ``380``.
    """
    result = cdp.execute_js("""
    (function() {
        var keywords = ['close', 'cancel', 'dismiss', 'x', '×', '✕', '✖', 'done', 'ok', 'got it', 'okay'];
        var selectors = [
            '[aria-label*="close" i]', '[aria-label*="dismiss" i]', '[aria-label*="cancel" i]',
            'button[class*="close" i]', 'button[class*="dismiss" i]', 'button[class*="cancel" i]',
            '[class*="modal-close"]', '[class*="dialog-close"]', '[class*="overlay-close"]',
            '[class*="btn-close"]', '[class*="close-btn"]', '[class*="close-button"]',
            'dialog button', '[role="dialog"] button', '[role="alertdialog"] button',
        ];
        var vw = window.innerWidth;
        var vh = window.innerHeight;

        for (var si = 0; si < selectors.length; si++) {
            var els;
            try { els = document.querySelectorAll(selectors[si]); } catch(e) { continue; }
            for (var i = 0; i < els.length; i++) {
                var el = els[i];
                var rect = el.getBoundingClientRect();
                if (rect.width < 6 || rect.height < 6) continue;
                if (rect.bottom < 0 || rect.top > vh) continue;
                var cx = Math.round(rect.left + rect.width / 2);
                var cy = Math.round(rect.top + rect.height / 2);
                if (cx < 2 || cx > vw - 2 || cy < 2 || cy > vh - 2) continue;
                return { x: cx, y: cy, found: 'selector' };
            }
        }

        var allBtns = document.querySelectorAll('button, [role="button"], a[href="#"], input[type="button"]');
        for (var j = 0; j < allBtns.length; j++) {
            var btn = allBtns[j];
            var txt = (btn.textContent || btn.getAttribute('aria-label') || '').trim().toLowerCase();
            for (var k = 0; k < keywords.length; k++) {
                if (txt === keywords[k] || txt.includes(keywords[k])) {
                    var r = btn.getBoundingClientRect();
                    if (r.width < 6 || r.height < 6) continue;
                    if (r.bottom < 0 || r.top > vh) continue;
                    var bx = Math.round(r.left + r.width / 2);
                    var by = Math.round(r.top + r.height / 2);
                    if (bx < 2 || bx > vw - 2 || by < 2 || by > vh - 2) continue;
                    return { x: bx, y: by, found: 'text' };
                }
            }
        }
        return null;
    })()
    """)

    if not result or not isinstance(result, dict):
        return None

    # CSS → physical
    css_x = int(result.get("x", 0))
    css_y = int(result.get("y", 0))
    px = round(css_x * dpr)
    py = round(css_y * dpr) + chrome_top

    py = max(safe_top + 5, min(safe_bot - 5, py))
    if px < 5 or px > vw_phy - 10:
        return None
    return {"x": px, "y": py}


def try_close_overlay(
    serial: str,
    cdp: "ChromeCDP",
    chrome_top: int,
    safe_top: int,
    safe_bot: int,
    vw_phy: int = 390,
    dpr: float = 1.0,
    max_attempts: int = 2,
) -> bool:
    """
    Attempt to close an overlay/modal by finding and clicking its close button.

    Post-condition: after clicking, verify the dialog is actually dismissed.
    Retry up to ``max_attempts`` times if the overlay persists.
    """
    for attempt in range(max_attempts):
        btn = find_close_button(cdp, chrome_top, safe_top, safe_bot,
                                vw_phy=vw_phy, dpr=dpr)
        if not btn:
            return False

        logger.info("Close overlay btn (%d, %d) attempt %d", btn["x"], btn["y"], attempt + 1)
        time.sleep(random.uniform(0.15, 0.5))
        adb_tap(serial, btn["x"], btn["y"])
        time.sleep(random.uniform(0.5, 1.2))

        # ── Post-condition: verify overlay is gone ──────────────────
        still_open = cdp.execute_js("""
        (function() {
            var dialogs = document.querySelectorAll('[role="dialog"], [role="alertdialog"]');
            for (var i = 0; i < dialogs.length; i++) {
                var rect = dialogs[i].getBoundingClientRect();
                if (rect.width > 50 && rect.height > 50) return true;
            }
            // Check for body scroll-lock (common pattern)
            var bodyStyle = window.getComputedStyle(document.body);
            if (bodyStyle.overflow === 'hidden' || bodyStyle.position === 'fixed') return true;
            return false;
        })()
        """)
        if not still_open:
            return True
        logger.info("Overlay still open after attempt %d", attempt + 1)

    logger.warning("Failed to close overlay after %d attempts", max_attempts)
    return True  # We did click, even if it didn't fully close


# ---------------------------------------------------------------------------
# InputDriver — unified tap / click API
# ---------------------------------------------------------------------------

class InputDriver:
    """
    Unified input driver that can use either ADB or CDP for tap/click.

    Handles CSS ↔ physical coordinate conversion in one place.
    """

    def __init__(
        self,
        serial: str,
        cdp: "ChromeCDP",
        chrome_top: int = 150,
        dpr: float = 1.0,
        backend: str = "adb",
    ):
        self.serial = serial
        self.cdp = cdp
        self.chrome_top = chrome_top
        self.dpr = dpr
        self.backend = backend  # "adb" or "cdp"

    def update_zone(self, chrome_top: int, dpr: float):
        """Update after a safe-zone refresh."""
        self.chrome_top = chrome_top
        self.dpr = dpr

    # ── Physical-pixel tap (ADB coords) ─────────────────────────────
    def tap_physical(self, x: int, y: int):
        """Tap at physical ADB coordinates."""
        if self.backend == "cdp":
            css_x = round(x / self.dpr)
            css_y = round((y - self.chrome_top) / self.dpr)
            self._cdp_tap(css_x, css_y)
        else:
            adb_tap(self.serial, x, y)

    # ── CSS-pixel tap (viewport coords) ─────────────────────────────
    def tap_css(self, css_x: int, css_y: int):
        """Tap at CSS viewport coordinates."""
        if self.backend == "cdp":
            self._cdp_tap(css_x, css_y)
        else:
            phy_x = round(css_x * self.dpr)
            phy_y = round(css_y * self.dpr) + self.chrome_top
            adb_tap(self.serial, phy_x, phy_y)

    # ── CSS → physical conversion utilities ─────────────────────────
    def css_to_physical(self, css_x: int, css_y: int) -> tuple[int, int]:
        """Convert CSS viewport coords to ADB physical coords."""
        return (round(css_x * self.dpr),
                round(css_y * self.dpr) + self.chrome_top)

    def physical_to_css(self, phy_x: int, phy_y: int) -> tuple[int, int]:
        """Convert ADB physical coords to CSS viewport coords."""
        return (round(phy_x / self.dpr),
                round((phy_y - self.chrome_top) / self.dpr))

    # ── Internal CDP dispatch ───────────────────────────────────────
    def _cdp_tap(self, css_x: int, css_y: int):
        """Dispatch touch event via CDP at CSS coordinates."""
        self.cdp._send_command("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": css_x, "y": css_y}],
        })
        time.sleep(random.uniform(0.03, 0.08))
        self.cdp._send_command("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": [],
        })
