import time
import random
import math
import subprocess
from urllib.parse import urlparse
from utils.cdp_chrome import ChromeCDP

# ===========================================================================
# ██╗  ██╗██╗   ██╗███╗   ███╗ █████╗ ███╗   ██╗    ███████╗███╗   ██╗ ██████╗
# ██║  ██║██║   ██║████╗ ████║██╔══██╗████╗  ██║    ██╔════╝████╗  ██║██╔════╝
# ███████║██║   ██║██╔████╔██║███████║██╔██╗ ██║    █████╗  ██╔██╗ ██║██║  ███╗
# ██╔══██║██║   ██║██║╚██╔╝██║██╔══██║██║╚██╗██║    ██╔══╝  ██║╚██╗██║██║   ██║
# ██║  ██║╚██████╔╝██║ ╚═╝ ██║██║  ██║██║ ╚████║    ███████╗██║ ╚████║╚██████╔╝
# Human Behavior Engine — Motion + Timing + Imperfection + Personality
# ===========================================================================

# ---------------------------------------------------------------------------
# Personality Profiles — mỗi device được gán 1 profile ngẫu nhiên
# ---------------------------------------------------------------------------

PROFILES = {
    "fast_scroller": {
        # Lướt nhanh, ít đọc, hay back
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
        # Đọc kỹ, delay lâu, hay scroll lên
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
        # Idle nhiều, scroll thất thường, click rồi bỏ
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
# Motion Layer — Bezier + Easing + Micro-jitter
# ---------------------------------------------------------------------------

def _bezier_point(t: float, p0: tuple, p1: tuple, p2: tuple, p3: tuple) -> tuple:
    mt = 1 - t
    x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
    y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
    return (x, y)


def _ease_in_out(t: float) -> float:
    """Cubic ease-in-out: 0–20% chậm, 20–70% nhanh, 70–100% giảm tốc."""
    return t * t * (3 - 2 * t)


def _jitter(val: float, magnitude: int = 2) -> int:
    """Micro-jitter ±magnitude px, chỉ 35% frame có jitter."""
    if random.random() < 0.35:
        return round(val + random.uniform(-magnitude, magnitude))
    return round(val)


def _adb_swipe(serial: str, x0: int, y0: int, x1: int, y1: int, duration_ms: int):
    subprocess.run(
        ["adb", "-s", serial, "shell", "input", "swipe",
         str(x0), str(y0), str(x1), str(y1), str(duration_ms)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _adb_tap(serial: str, x: int, y: int):
    subprocess.run(
        ["adb", "-s", serial, "shell", "input", "tap", str(x), str(y)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _adb_back(serial: str):
    subprocess.run(
        ["adb", "-s", serial, "shell", "input", "keyevent", "4"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


# ---------------------------------------------------------------------------
# Extended Motion Variants — Flash / Slow Zigzag / Stutter
# ---------------------------------------------------------------------------

def _swipe_flash(serial: str, x: int, y_start: int, y_end: int, safe_top: int):
    """Lướt cực nhanh như quẹt — 80–140ms, thẳng đứng không cong."""
    dur = random.randint(80, 140)
    y_start = max(safe_top + 10, y_start)
    y_end   = max(safe_top + 10, y_end)
    _adb_swipe(serial, x, y_start, x, y_end, dur)


def _swipe_slow_zigzag(serial: str, x_center: int, y_start: int, y_end: int,
                       safe_top: int, safe_bot: int):
    """
    Lướt chậm zic-zac: chia thành 4–7 đoạn nhỏ, mỗi đoạn lệch X ±30px,
    mỗi đoạn 180–350ms. Giống người vừa lướt vừa đọc lung tung.
    """
    segments = random.randint(4, 7)
    total_dy = y_end - y_start
    dy_per   = total_dy / segments
    cx = x_center
    cy = float(y_start)
    for _ in range(segments):
        nx = max(20, min(350, cx + random.randint(-30, 30)))
        ny = cy + dy_per + random.uniform(-20, 20)
        ny = max(safe_top + 10, min(safe_bot - 10, ny))
        seg_dur = random.randint(180, 350)
        _adb_swipe(serial, round(cx), round(cy), round(nx), round(ny), seg_dur)
        time.sleep(random.uniform(0.04, 0.15))
        cx, cy = nx, ny


def _swipe_stutter(serial: str, x: int, y_start: int, y_end: int,
                   safe_top: int, safe_bot: int):
    """
    Lướt nhấp nhả: lướt 1 đoạn → dừng ngắn → lướt tiếp → dừng → ...
    Giống người ngón tay bị giật hoặc đang xem gì đó vừa lướt vừa dừng.
    """
    total_dist = abs(y_end - y_start)
    direction  = 1 if y_end > y_start else -1
    cy = y_start
    taps = random.randint(3, 6)
    chunk = total_dist / taps
    for i in range(taps):
        ny = cy + direction * (chunk + random.uniform(-40, 40))
        ny = max(safe_top + 10, min(safe_bot - 10, ny))
        dur = random.randint(120, 280)
        _adb_swipe(serial, x, round(cy), x, round(ny), dur)
        cy = ny
        # Dừng giữa chừng — đây là nét đặc trưng "stutter"
        pause = random.uniform(0.08, 0.55)
        time.sleep(pause)


# ---------------------------------------------------------------------------
# Close/Cancel Overlay Helper
# ---------------------------------------------------------------------------

def _find_close_button(cdp, chrome_top: int, safe_top: int, safe_bot: int) -> dict | None:
    """
    Tìm button close/cancel/dismiss/X trên overlay/modal hiện tại.
    Trả về {x, y} tọa độ vật lý, hoặc None nếu không tìm thấy.
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

        // Thử selector trực tiếp trước
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

        // Fallback: tìm button có text gần với keywords
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
    px = int(result.get("x", 0))
    py = int(result.get("y", 0)) + chrome_top
    py = max(safe_top + 5, min(safe_bot - 5, py))
    if px < 5 or px > 380:
        return None
    return {"x": px, "y": py}


def _try_close_overlay(serial: str, cdp, chrome_top: int,
                       safe_top: int, safe_bot: int) -> bool:
    """
    Thử tìm và click nút close/cancel overlay.
    Trả về True nếu đã click, False nếu không tìm thấy.
    """
    btn = _find_close_button(cdp, chrome_top, safe_top, safe_bot)
    if btn:
        print(f"  ❌  Close overlay btn ({btn['x']}, {btn['y']})")
        time.sleep(random.uniform(0.15, 0.5))
        _adb_tap(serial, btn["x"], btn["y"])
        time.sleep(random.uniform(0.5, 1.2))
        return True
    return False


def human_swipe(serial: str, start_x: int, start_y: int, end_x: int, end_y: int,
                duration_ms: int = None, safe_margin: int = 60):
    """
    Vuốt Bezier cong + micro-jitter + easing qua ADB.
    safe_margin: giới hạn tọa độ Y để không chạm mép trên/dưới màn hình
                 (tránh kéo notification bar / nav bar).
    """
    if duration_ms is None:
        duration_ms = random.randint(350, 800)

    steps = random.randint(6, 10)

    dx = end_x - start_x
    dy = end_y - start_y
    perp_len = math.sqrt(dx**2 + dy**2) or 1
    perp_x = -dy / perp_len
    perp_y = dx / perp_len

    curve_dist = random.uniform(0.05, 0.14) * perp_len
    side = random.choice([-1, 1])
    cp1 = (start_x + dx*0.30 + perp_x*curve_dist*side,
           start_y + dy*0.30 + perp_y*curve_dist*side)
    cp2 = (start_x + dx*0.70 + perp_x*curve_dist*random.choice([-1, 1]),
           start_y + dy*0.70 + perp_y*curve_dist*random.choice([-1, 1]))

    p0, p3 = (start_x, start_y), (end_x, end_y)

    points = []
    for i in range(steps + 1):
        t = _ease_in_out(i / steps)
        px, py = _bezier_point(t, p0, cp1, cp2, p3)
        # Micro-jitter + clamp tránh mép trên/dưới
        jx = _jitter(px, 2)
        jy = max(safe_margin, _jitter(py, 2))
        points.append((jx, jy))

    seg_ms = max(30, duration_ms // steps)
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        _adb_swipe(serial, x0, y0, x1, y1, seg_ms)


# ---------------------------------------------------------------------------
# Behavior State Machine
# States: FAST_BROWSE → FOCUS → BORED → IDLE
# ---------------------------------------------------------------------------

_STATES = ["FAST_BROWSE", "FOCUS", "BORED", "IDLE"]

# Markov transition matrix: từ state hiện tại → xác suất chuyển sang state khác
_MARKOV = {
    "FAST_BROWSE": {"FAST_BROWSE": 0.45, "FOCUS": 0.30, "BORED": 0.18, "IDLE": 0.07},
    "FOCUS":       {"FAST_BROWSE": 0.25, "FOCUS": 0.45, "BORED": 0.20, "IDLE": 0.10},
    "BORED":       {"FAST_BROWSE": 0.30, "FOCUS": 0.15, "BORED": 0.35, "IDLE": 0.20},
    "IDLE":        {"FAST_BROWSE": 0.40, "FOCUS": 0.20, "BORED": 0.20, "IDLE": 0.20},
}


def _next_state(current: str) -> str:
    """Chuyển state theo Markov Chain."""
    transitions = _MARKOV[current]
    states = list(transitions.keys())
    weights = list(transitions.values())
    return random.choices(states, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Human Scroll Session — engine chính
# ---------------------------------------------------------------------------

def _get_webpage_safe_zone(cdp) -> dict:
    """
    Dùng CDP JS để lấy vùng an toàn của webpage content.
    Trả về toạ độ màn hình vật lý, loại bỏ Chrome UI + phone status/nav bars.

    Cách tính đúng:
      - window.innerHeight  = chiều cao viewport thật (CSS px, đã trừ Chrome UI)
      - Dùng CDP Input.dispatchTouchEvent để xác định chrome_top chính xác hơn
      - Fallback: ước tính chrome_top = screenH * devicePixelRatio - innerHeight * devicePixelRatio
    """
    result = cdp.execute_js("""
    (function() {
        var vw = window.innerWidth  || document.documentElement.clientWidth;
        var vh = window.innerHeight || document.documentElement.clientHeight;
        var dpr = window.devicePixelRatio || 1;
        // screen.width/height là LOGICAL pixels (CSS px), nhân dpr = physical px
        var screenW_css = window.screen.width;
        var screenH_css = window.screen.height;
        var screenH_phy = Math.round(screenH_css * dpr);
        var screenW_phy = Math.round(screenW_css * dpr);
        // innerHeight / innerWidth là CSS px
        // viewport physical = innerHeight * dpr
        var vpH_phy = Math.round(vh * dpr);
        var vpW_phy = Math.round(vw * dpr);
        // chrome_top_phy = khoảng trống phía trên viewport (status bar + address bar)
        var chromeTop_phy = screenH_phy - vpH_phy;
        // Nếu bị âm hoặc bất hợp lý (< 50px hoặc > 40% screen) → dùng giá trị mặc định an toàn
        if (chromeTop_phy < 50 || chromeTop_phy > screenH_phy * 0.40) {
            // Ước tính thực tế: status bar ~24dp, Chrome address bar ~56dp, bottom bar ~48dp
            // → top UI ~ 80dp * dpr, bottom UI ~ 48dp * dpr
            chromeTop_phy = Math.round(80 * dpr);
        }
        // chromeBot_phy = nav bar + bottom Chrome bar
        var chromeBot_phy = screenH_phy - vpH_phy - chromeTop_phy;
        if (chromeBot_phy < 0) chromeBot_phy = Math.round(48 * dpr);
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
        return {"x_min": 10, "x_max": 370, "y_min": 150, "y_max": 750,
                "chrome_top": 150, "vh": 650, "vw": 390, "dpr": 1.0}

    dpr         = result.get("dpr", 1.0) or 1.0
    chrome_top  = int(result.get("chromeTop_phy", 150))
    chrome_bot  = int(result.get("chromeBot_phy", 48))
    screenH_phy = int(result.get("screenH_phy", 900))
    screenW_phy = int(result.get("screenW_phy", 390))
    vpH_phy     = int(result.get("vpH_phy", 650))
    vpW_phy     = int(result.get("vpW_phy", 390))
    vh_css      = int(result.get("vh_css", 650))
    vw_css      = int(result.get("vw_css", 390))

    # y_min/y_max là toạ độ màn hình vật lý (pixel ADB)
    y_min = chrome_top + 12   # 12px padding tránh sát Chrome address bar
    y_max = chrome_top + vpH_phy - 12  # 12px padding tránh sát bottom bar

    # Sanity check — y_max không được vượt quá 90% screenH
    y_max = min(y_max, int(screenH_phy * 0.90))
    y_min = max(y_min, 50)

    return {
        "x_min": 10,
        "x_max": vpW_phy - 10,
        "y_min": y_min,
        "y_max": y_max,
        "chrome_top": chrome_top,
        "chrome_bot": chrome_bot,
        "vh": vpH_phy,       # physical px height của viewport
        "vw": vpW_phy,       # physical px width của viewport
        "vh_css": vh_css,    # CSS px (dùng để quy đổi element Y)
        "vw_css": vw_css,
        "dpr": dpr,
        "screenH_phy": screenH_phy,
    }


def _get_clickable_elements(cdp, chrome_top: int, y_min: int, y_max: int,
                            max_elements: int = 40, dpr: float = 1.0,
                            vh_css: int = 0) -> list:
    """
    Lấy các element NON-NAVIGATING trong viewport hiện tại.

    - Tọa độ trả về là physical pixel (ADB coordinates).
    - Element phải nằm HOÀN TOÀN trong viewport CSS (không partial ở top/bottom).
    - Sau khi quy đổi sang physical px phải nằm trong [y_min, y_max].
    - Loại bỏ mọi element có tọa độ CSS Y < 20px hoặc > vh-20px
      (tránh click vào vùng Chrome UI bị render chồng lên page).

    dpr: devicePixelRatio để quy đổi CSS px → physical px
    vh_css: innerHeight CSS px (để filter element ngoài viewport)
    """
    safe_css_top = 25     # CSS px — loại element quá gần mép trên viewport
    safe_css_bot = max(20, (vh_css - 25)) if vh_css > 0 else 620  # CSS px mép dưới

    result = cdp.execute_js(f"""
    (function() {{
        var maxEl = {max_elements};
        var safeCssTop = {safe_css_top};
        var safeCssBot = {safe_css_bot};
        var results = [];

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
                var rect = el.getBoundingClientRect();

                // Bỏ qua element quá nhỏ (không thể click được)
                if (rect.width < 12 || rect.height < 12) continue;

                // Phải nằm TRONG viewport (không nằm ngoài viewport)
                if (rect.top < 0 || rect.bottom > vh) continue;
                if (rect.left < 0 || rect.right > vw) continue;

                // Center phải nằm trong vùng an toàn CSS [safeCssTop, safeCssBot]
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

    out = []
    for el in result:
        # CSS px center
        css_x = int(el.get("x", 0))
        css_y = int(el.get("y", 0))

        # Quy đổi sang physical px: nhân dpr, rồi cộng chrome_top
        phy_x = round(css_x * dpr)
        phy_y = round(css_y * dpr) + chrome_top

        # Guard cuối: phải nằm TRONG [y_min, y_max] và [8, vw-8]
        if phy_y < y_min or phy_y > y_max:
            continue
        if phy_x < 8:
            continue

        out.append({"x": phy_x, "y": phy_y, "type": el.get("type", "image")})
    return out



def human_scroll_session(serial: str, cdp, viewport_width: int = 390,
                          viewport_height: int = 844,
                          min_duration: float = 60.0, max_duration: float = 90.0,
                          original_url: str = "",
                          click_prob: float = 0.30,
                          burst_prob: float = 0.30,
                          scroll_dist_min: int = 300,
                          scroll_dist_max: int = 700,
                          read_pause_min: float = None,
                          read_pause_max: float = None):
    """
    Phiên lướt như người thật — SCROLL là hành vi chủ lực (~75% thời gian).
    Click chỉ là hành vi phụ xen kẽ.

    Nguyên tắc tọa độ (TUYỆT ĐỐI):
      - Mọi swipe/tap đều nằm trong vùng [SAFE_TOP, SAFE_BOT] (physical px).
      - SAFE_TOP/SAFE_BOT đã loại bỏ Chrome address bar + phone nav bar.
      - Element từ _get_clickable_elements đã là physical px — dùng trực tiếp,
        KHÔNG cộng/trừ gì thêm.
      - Tap tọa độ ngẫu nhiên (mis-tap) luôn dùng tgt["y"] từ element list,
        KHÔNG dùng randint trực tiếp cho Y.
    """
    profile_name = random.choice(list(PROFILES.keys()))
    p = PROFILES[profile_name]

    if read_pause_min is not None and read_pause_max is not None:
        p = dict(p)
        p["read_pause"] = (read_pause_min, read_pause_max)

    target_duration = random.uniform(min_duration, max_duration)
    session_start   = time.time()
    swipe_count     = 0
    click_count     = 0
    state           = "FAST_BROWSE"

    zone        = _get_webpage_safe_zone(cdp)
    y_min       = zone["y_min"]
    y_max       = zone["y_max"]
    chrome_top  = zone.get("chrome_top", 150)
    vw          = zone.get("vw", viewport_width)
    dpr         = zone.get("dpr", 1.0)
    vh_css      = zone.get("vh_css", 650)
    vh_physical = y_max - y_min

    # Vùng an toàn vật lý — TẤT CẢ tap/swipe phải nằm trong đây
    SAFE_TOP = y_min + 25
    SAFE_BOT = y_max - 25

    print(f"🤖 Human session | profile={profile_name} | target={target_duration:.0f}s")
    print(f"   SAFE y=[{SAFE_TOP}..{SAFE_BOT}] ph={vh_physical}px chrome_top={chrome_top}px dpr={dpr}")
    print(f"   scroll={scroll_dist_min}-{scroll_dist_max}px | click={click_prob:.0%} | burst={burst_prob:.0%}")

    elements:    list  = []
    elem_age:    int   = 0
    virtual_y:   float = 0.0   # px đã cuộn xuống từ đầu trang (ảo)
    consec_dn:   int   = 0     # số lần scroll xuống liên tiếp
    action_no:   int   = 0

    # ── Helper: X ngẫu nhiên trong viewport ──────────────────────────────
    def rand_x() -> int:
        return random.randint(int(vw * 0.15), int(vw * 0.85))

    # ── Helper: swipe an toàn (clamp ys/ye trong safe zone) ──────────────
    def safe_swipe(ys: int, ye: int, ms: int, style: str = "normal"):
        ys = max(SAFE_TOP + 8, min(SAFE_BOT - 8, ys))
        ye = max(SAFE_TOP + 8, min(SAFE_BOT - 8, ye))
        sx = rand_x()
        if style == "flash":
            _swipe_flash(serial, sx, ys, ye, SAFE_TOP)
        elif style == "zigzag":
            _swipe_slow_zigzag(serial, sx, ys, ye, SAFE_TOP, SAFE_BOT)
        elif style == "stutter":
            _swipe_stutter(serial, sx, ys, ye, SAFE_TOP, SAFE_BOT)
        else:
            if random.random() < p["overshoot_prob"]:
                going_up = ye > ys
                over     = random.randint(20, 70)
                ov_y     = min(SAFE_BOT - 5, ye + over) if going_up else max(SAFE_TOP + 5, ye - over)
                human_swipe(serial, sx, ys, sx, ov_y, duration_ms=ms, safe_margin=SAFE_TOP)
                time.sleep(random.uniform(0.03, 0.10))
                back_y = max(SAFE_TOP + 5, min(SAFE_BOT - 5,
                    ov_y - random.randint(10, 40) if going_up
                    else ov_y + random.randint(10, 40)
                ))
                human_swipe(serial, sx, ov_y, sx, back_y,
                            duration_ms=random.randint(70, 180), safe_margin=SAFE_TOP)
            else:
                human_swipe(serial, sx, ys, sx, ye, duration_ms=ms, safe_margin=SAFE_TOP)

    # ── Helper: pause sau scroll (ngắn — ưu tiên scroll nhiều hơn đứng im) ─
    def scroll_pause(style: str = "normal"):
        if style == "flash":
            time.sleep(random.uniform(0.02, 0.12))
        elif state == "FOCUS" and random.random() < p["read_prob"] * 0.5:
            plo, phi = p["read_pause"]
            pause = min(random.uniform(plo, phi), remaining * 0.10)
            if pause > 0.5:
                print(f"  👁️  Read {pause:.1f}s")
                time.sleep(pause)
        elif state == "FAST_BROWSE":
            time.sleep(random.uniform(0.04, 0.25))
        else:
            time.sleep(random.uniform(0.08, 0.45))

    # ── Helper: chọn style scroll ─────────────────────────────────────────
    def pick_style() -> str:
        r = random.random()
        if r < 0.18:   return "flash"
        elif r < 0.35: return "zigzag"
        elif r < 0.48: return "stutter"
        else:           return "normal"

    # ── Helper: chọn dist scroll theo state ──────────────────────────────
    def pick_dist() -> int:
        if state == "FAST_BROWSE":
            return random.randint(scroll_dist_min + 80, scroll_dist_max)
        elif state == "FOCUS":
            return random.randint(max(80, scroll_dist_min // 3), scroll_dist_min + 80)
        elif state == "BORED":
            return random.randint(scroll_dist_min, scroll_dist_max - 50)
        return random.randint(scroll_dist_min, scroll_dist_max)

    # ── Helper: refresh safe zone ─────────────────────────────────────────
    def refresh_zone():
        nonlocal y_min, y_max, chrome_top, SAFE_TOP, SAFE_BOT, vh_physical, dpr, vh_css, vw
        z       = _get_webpage_safe_zone(cdp)
        y_min   = z["y_min"];    y_max  = z["y_max"]
        chrome_top = z.get("chrome_top", chrome_top)
        dpr        = z.get("dpr", dpr);  vh_css = z.get("vh_css", vh_css)
        vw         = z.get("vw", vw)
        SAFE_TOP   = y_min + 25; SAFE_BOT  = y_max - 25
        vh_physical = SAFE_BOT - SAFE_TOP

    # ── Helper: refresh elements ──────────────────────────────────────────
    def refresh_elems():
        nonlocal elements, elem_age
        elements = _get_clickable_elements(cdp, chrome_top, SAFE_TOP, SAFE_BOT,
                                           dpr=dpr, vh_css=vh_css)
        elem_age = 0

    # ── Helper: về link gốc sau click ────────────────────────────────────
    def return_origin(lo: float = 0.7, hi: float = 1.5):
        if original_url:
            cdp.navigate(original_url)
            time.sleep(random.uniform(lo, hi))
            refresh_zone()
            refresh_elems()
        else:
            _adb_back(serial)
            time.sleep(random.uniform(0.5, 1.0))

    # ════════════════════════════════════════════════════════════════════
    # MAIN LOOP
    # ════════════════════════════════════════════════════════════════════
    while True:
        elapsed   = time.time() - session_start
        remaining = target_duration - elapsed
        if remaining <= 0:
            break

        fatigue      = min(elapsed / 60.0 / p["fatigue_start_min"], 1.0)
        speed_lo, speed_hi = p["swipe_speed_ms"]
        state        = _next_state(state)
        action_no   += 1

        # ── IDLE ─────────────────────────────────────────────────────────
        # Chỉ idle mỗi ~8 action, và thời gian ngắn hơn nhiều
        if state == "IDLE" and action_no % 8 == 0:
            idle_t = min(random.uniform(0.8, 3.5), remaining * 0.12)
            if idle_t > 0.5:
                print(f"  💤  IDLE {idle_t:.1f}s")
                time.sleep(idle_t)
            continue
        if state == "IDLE":
            state = "FAST_BROWSE"   # skip idle nếu không đủ điều kiện trên

        # ── Refresh elements mỗi 5 action ────────────────────────────────
        elem_age += 1
        if elem_age >= 5 or not elements:
            refresh_elems()

        # ── URL drift guard (mỗi 6 action) ────────────────────────────────
        if original_url and action_no % 6 == 0:
            try:
                cur = cdp.get_current_url() or ""
                if cur and cur.rstrip("/") != original_url.rstrip("/"):
                    print(f"  ⚠️  URL drift → returning")
                    cdp.navigate(original_url)
                    time.sleep(random.uniform(1.0, 1.8))
                    refresh_zone(); refresh_elems()
                    consec_dn = 0
                    continue
            except Exception:
                pass

        # ════════════════════════════════════════════════════════════════
        # ACTION WEIGHTS
        # Scroll-family chiếm ~80% weight tổng.
        # Click-family ~20%. Pause giữa scroll ngắn → nhiều scroll hơn / giây.
        # ════════════════════════════════════════════════════════════════

        # up_boost: càng cuộn xuống nhiều → scroll lên được ưu tiên hơn
        up_w = max(18, min(60, 12 + consec_dn * 7))

        W = {
            # ── Scroll — chủ lực ─────────────────────────────────────────
            "scroll_dn":   50,
            "scroll_up":   up_w,
            "burst_dn":    int(burst_prob * 40),
            "burst_up":    max(10, up_w // 2),
            "mini_series": 22,    # 3–8 swipe nhỏ lên/xuống xen kẽ
            "swipe_back":  14,    # lên nhanh rồi xuống chậm đọc
            "check_top":   10 if virtual_y > 500 else 2,
            # ── Click — phụ ──────────────────────────────────────────────
            "click_elem":  int(click_prob * 25) if elements else 0,
            "double_tap":  4 if elements else 0,
            "long_press":  3 if elements else 0,
            "mis_tap":     int(p["misclick_prob"] * 28) if elements else 0,
        }

        act  = random.choices(list(W.keys()), weights=list(W.values()), k=1)[0]
        ms   = round(random.randint(speed_lo, speed_hi) * (1 + 0.20 * fatigue))
        sty  = pick_style()
        dist = pick_dist()

        # ════════════════════════════════════════════════════════════════
        if act == "scroll_dn":
            ys = random.randint(SAFE_TOP + int(vh_physical * 0.30), SAFE_BOT - 15)
            ye = max(SAFE_TOP + 12, ys - dist)
            print(f"  🔽  DN {ys-ye}px [{sty}] #{swipe_count+1} [{state}]")
            safe_swipe(ys, ye, ms, sty)
            swipe_count += 1;  virtual_y += (ys - ye);  consec_dn += 1
            scroll_pause(sty)

        # ════════════════════════════════════════════════════════════════
        elif act == "scroll_up":
            ys = random.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.55))
            ye = min(SAFE_BOT - 12, ys + dist)
            print(f"  🔼  UP {ye-ys}px [{sty}] #{swipe_count+1} [{state}]")
            safe_swipe(ys, ye, ms, sty)
            swipe_count += 1
            virtual_y   = max(0.0, virtual_y - (ye - ys))
            consec_dn   = max(0, consec_dn - 2)
            scroll_pause(sty)

        # ════════════════════════════════════════════════════════════════
        elif act == "burst_dn":
            n  = random.randint(4, 10)
            bx = rand_x()
            print(f"  ⚡↓  BURST-DN x{n} [{state}]")
            for _ in range(n):
                d  = random.randint(scroll_dist_min, scroll_dist_max)
                ys = random.randint(SAFE_TOP + int(vh_physical * 0.22), SAFE_BOT - 20)
                ye = max(SAFE_TOP + 12, ys - d)
                _swipe_flash(serial, bx, ys, ye, SAFE_TOP)
                virtual_y += (ys - ye);  consec_dn += 1;  swipe_count += 1
                time.sleep(random.uniform(0.02, 0.10))
            time.sleep(random.uniform(0.25, 1.2))

        # ════════════════════════════════════════════════════════════════
        elif act == "burst_up":
            n  = random.randint(3, 7)
            bx = rand_x()
            print(f"  ⚡↑  BURST-UP x{n} [{state}]")
            for _ in range(n):
                d  = random.randint(max(100, scroll_dist_min // 2), scroll_dist_min + 150)
                ys = random.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.52))
                ye = min(SAFE_BOT - 12, ys + d)
                _swipe_flash(serial, bx, ys, ye, SAFE_TOP)
                virtual_y   = max(0.0, virtual_y - (ye - ys))
                consec_dn   = max(0, consec_dn - 1)
                swipe_count += 1
                time.sleep(random.uniform(0.02, 0.11))
            time.sleep(random.uniform(0.15, 0.80))

        # ════════════════════════════════════════════════════════════════
        elif act == "mini_series":
            n = random.randint(4, 9)
            print(f"  〰️  MINI x{n} [{state}]")
            for _ in range(n):
                up  = random.random() < 0.42
                d   = random.randint(60, 280)
                if up:
                    ys = random.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.48))
                    ye = min(SAFE_BOT - 12, ys + d)
                    virtual_y = max(0.0, virtual_y - (ye - ys))
                    consec_dn = max(0, consec_dn - 1)
                else:
                    ys = random.randint(SAFE_TOP + int(vh_physical * 0.32), SAFE_BOT - 18)
                    ye = max(SAFE_TOP + 12, ys - d)
                    virtual_y += (ys - ye);  consec_dn += 1
                human_swipe(serial, rand_x(), ys, rand_x(), ye,
                            duration_ms=random.randint(180, 500), safe_margin=SAFE_TOP)
                swipe_count += 1
                time.sleep(random.uniform(0.08, 0.50))
            time.sleep(random.uniform(0.10, 0.55))

        # ════════════════════════════════════════════════════════════════
        elif act == "swipe_back":
            # Lên nhanh → dừng nhìn → xuống chậm đọc
            d_up = random.randint(scroll_dist_min, scroll_dist_max)
            d_dn = random.randint(scroll_dist_min // 2, scroll_dist_min + 100)
            print(f"  ↩️  SwipeBack ↑{d_up} ↓{d_dn}")
            ys_u = random.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.48))
            ye_u = min(SAFE_BOT - 12, ys_u + d_up)
            _swipe_flash(serial, rand_x(), ys_u, ye_u, SAFE_TOP)
            virtual_y   = max(0.0, virtual_y - (ye_u - ys_u))
            consec_dn   = max(0, consec_dn - 2)
            swipe_count += 1
            time.sleep(random.uniform(0.20, 0.75))
            ys_d = random.randint(SAFE_TOP + int(vh_physical * 0.30), SAFE_BOT - 18)
            ye_d = max(SAFE_TOP + 12, ys_d - d_dn)
            human_swipe(serial, rand_x(), ys_d, rand_x(), ye_d,
                        duration_ms=random.randint(speed_hi, speed_hi + 250), safe_margin=SAFE_TOP)
            virtual_y   += (ys_d - ye_d);  consec_dn += 1;  swipe_count += 1
            scroll_pause("normal")

        # ════════════════════════════════════════════════════════════════
        elif act == "check_top":
            up_px = min(virtual_y, random.randint(350, 800))
            print(f"  ⬆️  CheckTop ~{up_px:.0f}px")
            left  = up_px;  bx2 = rand_x()
            while left > 60:
                chunk = min(left, random.randint(200, 500))
                ys    = random.randint(SAFE_TOP + 12, SAFE_TOP + int(vh_physical * 0.48))
                ye    = min(SAFE_BOT - 12, ys + chunk)
                _swipe_flash(serial, bx2, ys, ye, SAFE_TOP)
                virtual_y   = max(0.0, virtual_y - (ye - ys))
                left       -= (ye - ys)
                swipe_count += 1
                time.sleep(random.uniform(0.02, 0.09))
            consec_dn = 0
            time.sleep(random.uniform(0.3, 1.2))

        # ════════════════════════════════════════════════════════════════
        elif act == "click_elem" and elements:
            priority = {"image": 0, "button": 1, "label": 2, "text": 3, "card": 4}
            pool = sorted(elements, key=lambda e: priority.get(e["type"], 5))
            pool = pool[:max(1, int(len(pool) * 0.85))]
            seq  = random.randint(2, 3) if random.random() < 0.28 else 1
            for _ci in range(seq):
                if not pool: break
                tgt = random.choice(pool)
                # Tọa độ ĐÃ là physical px từ _get_clickable_elements, dùng trực tiếp
                tx, ty = tgt["x"], tgt["y"]
                print(f"  👆  Click [{tgt['type']}] ({tx},{ty}) #{click_count+1}")
                time.sleep(random.uniform(0.05, 0.18))
                _adb_tap(serial, tx, ty)
                click_count += 1
                time.sleep(random.uniform(0.8, 2.0))
                if tgt["type"] in ("image", "card", "button"):
                    if _try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT):
                        time.sleep(random.uniform(0.2, 0.5))
                if _ci < seq - 1:
                    time.sleep(random.uniform(0.12, 0.40))
            return_origin(0.6, 1.4)

        # ════════════════════════════════════════════════════════════════
        elif act == "double_tap" and elements:
            tgt   = random.choice(elements)
            tx, ty = tgt["x"], tgt["y"]
            print(f"  👆👆 DblTap [{tgt['type']}] ({tx},{ty})")
            _adb_tap(serial, tx, ty)
            time.sleep(random.uniform(0.07, 0.15))
            _adb_tap(serial, tx + random.randint(-3, 3), ty + random.randint(-3, 3))
            time.sleep(random.uniform(0.5, 1.5))
            _try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT)
            return_origin(0.5, 1.2)

        # ════════════════════════════════════════════════════════════════
        elif act == "long_press" and elements:
            tgt      = random.choice(elements)
            tx, ty   = tgt["x"], tgt["y"]
            hold     = random.randint(500, 1200)
            print(f"  🖐️  LongPress [{tgt['type']}] ({tx},{ty}) {hold}ms")
            _adb_swipe(serial, tx, ty, tx, ty, hold)
            time.sleep(random.uniform(0.4, 1.0))
            _try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT)
            return_origin(0.5, 1.1)

        # ════════════════════════════════════════════════════════════════
        elif act == "mis_tap" and elements:
            # Lệch ±15px so với element thật — Y vẫn từ element list
            tgt = random.choice(elements)
            tx  = max(8, min(vw - 8, tgt["x"] + random.randint(-15, 15)))
            ty  = max(SAFE_TOP + 5, min(SAFE_BOT - 5, tgt["y"] + random.randint(-10, 10)))
            print(f"  🖱️  MisTap [{tgt['type']}] ({tx},{ty})")
            time.sleep(random.uniform(0.04, 0.15))
            _adb_tap(serial, tx, ty)
            time.sleep(random.uniform(0.4, 1.0))
            _try_close_overlay(serial, cdp, chrome_top, SAFE_TOP, SAFE_BOT)
            return_origin(0.5, 1.0)

        # ── Bored exit ────────────────────────────────────────────────────
        if elapsed > 20 and random.random() < p["bored_exit_prob"] * 0.4:
            print(f"  😴  Bored exit at {elapsed:.0f}s")
            break

    total = time.time() - session_start
    print(f"✅ Done — {swipe_count} scrolls + {click_count} clicks | {total:.1f}s | [{profile_name}]")






def run_ads_automation(
    serial: str,
    url: str,
    human_settings: dict = None,
):
    """
    Flow:
      1. Mở link ads ban đầu (url ở ô Ads Link).
      2. Đợi modal "Link to ad" xuất hiện, cuộn xuống tìm nút "Learn more".
      3. Click "Learn more" → vào trang đích thật.
      4. Thu thập ads info (title + domain).
      5. Thực hiện hành vi lướt ngẫu nhiên như người thật (≥ 60s).

    Args:
        serial: ADB serial của device
        url: link ads ban đầu (ô Ads Link)

    Raises:
        RuntimeError: nếu Chrome không chạy hoặc lỗi kết nối
    """

    with ChromeCDP(serial=serial, initial_url=url) as cdp:

        # ── Bước 1: Đợi trang ads load ──────────────────────────────────
        print(f"⏳ Waiting for ads page to load on {serial}...")
        time.sleep(5)

        # ── Bước 2: Đợi modal "Link to ad" xuất hiện ────────────────────
        print(f"⏳ Waiting for 'Link to ad' modal on {serial}...")
        modal_appeared = False
        for _ in range(15):  # Đợi tối đa 15 giây
            time.sleep(1)
            check_modal = cdp.execute_js("""
            (function() {
                const dialogs = document.querySelectorAll('[role="dialog"]');
                for (const dialog of dialogs) {
                    if (dialog.textContent && dialog.textContent.toLowerCase().includes('link to ad')) {
                        return true;
                    }
                }
                return false;
            })()
            """)
            if check_modal:
                modal_appeared = True
                print(f"✅ 'Link to ad' modal appeared on {serial}")
                break

        if not modal_appeared:
            print(f"⚠️  'Link to ad' modal not found on {serial}, collecting current page info...")
            page_title = cdp.get_page_title()
            page_url = cdp.get_current_url()
            domain = urlparse(page_url).netloc if page_url else ""
            return {"title": page_title, "domain": domain, "url": page_url}

        # ── Bước 3: Cuộn trong modal để nút "Learn more" hiện ra ─────────
        print(f"� Scrolling modal to reveal 'Learn more' button on {serial}...")
        cdp.execute_js("""
        (function() {
            const dialogs = document.querySelectorAll('[role="dialog"]');
            for (const dialog of dialogs) {
                if (dialog.textContent && dialog.textContent.toLowerCase().includes('link to ad')) {
                    dialog.scrollTop = dialog.scrollHeight;
                    return;
                }
            }
            window.scrollTo(0, document.body.scrollHeight);
        })()
        """)
        time.sleep(1)

        # ── Bước 4: Tìm và click nút "Learn more" ───────────────────────
        page_title = ""
        page_url = ""
        try:
            js_rect = """
            (function() {
                const dialogs = document.querySelectorAll('[role="dialog"]');
                let targetDialog = null;
                for (const dialog of dialogs) {
                    if (dialog.textContent && dialog.textContent.toLowerCase().includes('link to ad')) {
                        targetDialog = dialog;
                        break;
                    }
                }
                if (!targetDialog) return null;

                const btn = Array.from(targetDialog.querySelectorAll('a, button, [role="button"]')).find(el =>
                    el.textContent && el.textContent.trim().toLowerCase().includes('learn more')
                );
                if (!btn) return null;

                btn.scrollIntoView({block: 'center'});
                const rect = btn.getBoundingClientRect();
                return {
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2)
                };
            })()
            """
            rect = cdp.execute_js(js_rect)
            if rect and rect.get('x') and rect.get('y'):
                x, y = rect['x'], rect['y']
                print(f"🎯 'Learn more' button found at ({x}, {y}) on {serial}")
                cdp._send_command("Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": x, "y": y,
                    "button": "left", "clickCount": 1
                })
                time.sleep(0.1)
                cdp._send_command("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": x, "y": y,
                    "button": "left", "clickCount": 1
                })
                print(f"✅ Clicked 'Learn more' on {serial}, waiting for destination page...")

                # ── Bước 5: Đợi trang đích load ─────────────────────────
                time.sleep(5)
                page_title = cdp.get_page_title()
                page_url = cdp.get_current_url()
                domain = urlparse(page_url).netloc if page_url else ""
                print(f"📄 Landed on: {page_title} | {domain} ({page_url})")

                # ── Bước 6: Hành vi lướt như người thật (≥ 60s) ─────────
                print(f"🤖 Starting human browsing behavior on {serial}...")
                hs = human_settings or {}
                human_scroll_session(serial, cdp,
                                     viewport_width=390, viewport_height=844,
                                     original_url=page_url,
                                     min_duration=hs.get("min_duration", 60.0),
                                     max_duration=hs.get("max_duration", 90.0),
                                     click_prob=hs.get("click_prob", 0.40),
                                     burst_prob=hs.get("burst_prob", 0.35),
                                     scroll_dist_min=hs.get("scroll_dist_min", 350),
                                     scroll_dist_max=hs.get("scroll_dist_max", 750),
                                     read_pause_min=hs.get("read_pause_min", None),
                                     read_pause_max=hs.get("read_pause_max", None))

                # Nghỉ cuối phiên
                time.sleep(random.uniform(2.0, 4.0))

            else:
                print(f"⚠️  'Learn more' button not found in modal on {serial}")
                page_title = cdp.get_page_title()
                page_url = cdp.get_current_url()
                domain = urlparse(page_url).netloc if page_url else ""

        except Exception as e:
            print(f"⚠️  Error clicking 'Learn more' on {serial}: {e}")
            page_title = cdp.get_page_title()
            page_url = cdp.get_current_url()
            domain = urlparse(page_url).netloc if page_url else ""

        return {"title": page_title, "domain": domain, "url": page_url}



# GUI Components for Ads Management
import sys, os, subprocess, shutil, json
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QTableWidget, QTableWidgetItem, QHBoxLayout, QDialog, QLineEdit, QLabel, QDialogButtonBox, QFormLayout, QStyledItemDelegate, QTextEdit, QSizePolicy, QGroupBox, QDoubleSpinBox, QSpinBox, QSlider, QFrame
from PySide6.QtCore import QTimer, QThread, Signal, Qt, QRect
from PySide6.QtGui import QIcon

_ANDROID_TOOLS_PATHS = [
    r"C:\android-tools\platform-tools",
    r"C:\android-tools\scrcpy-win64-v3.3.4",
]
for _p in _ANDROID_TOOLS_PATHS:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

_si = subprocess.STARTUPINFO()
_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

from helpers.csv import CSVHelper
from utils.adb import setup_adb_keyboard
from features.chrome import install_chrome, open_url_in_chrome

class SerialDelegate(QStyledItemDelegate):
    """Delegate giới hạn editor của cột Serial đúng bằng width của ô."""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        return editor

    def updateEditorGeometry(self, editor, option, index):
        # Đặt geometry của editor khớp đúng với rect của ô, không tràn ra ngoài
        editor.setGeometry(option.rect)


class AdsLinkWidget(QWidget):
    """Custom widget for ads link column with truncated text and copy button."""

    link_changed = Signal(str)  # Signal emitted when link is changed

    def __init__(self, link_text="", parent=None):
        super().__init__(parent)
        self.full_link = link_text
        self.initUI()

    def initUI(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Truncated link label
        self.link_label = QLabel(self.truncate_link(self.full_link))
        self.link_label.setStyleSheet("""
            QLabel {
                color: blue;
                text-decoration: underline;
            }
            QLabel:hover {
                color: blue;
            }
        """)
        layout.addWidget(self.link_label)

        # Inline edit input (hidden by default)
        self.link_input = QLineEdit()
        self.link_input.setVisible(False)
        self.link_input.returnPressed.connect(self.finish_inline_edit)
        self.link_input.editingFinished.connect(self.finish_inline_edit)
        layout.addWidget(self.link_input)

        # Copy button
        self.copy_button = QPushButton("📋")
        self.copy_button.setFixedSize(24, 24)
        self.copy_button.setToolTip("Copy link to clipboard")
        self.copy_button.clicked.connect(self.copy_link)
        layout.addWidget(self.copy_button)

        layout.addStretch()

    def truncate_link(self, link, max_length=30):
        """Truncate link to max_length characters with ellipsis."""
        if len(link) <= max_length:
            return link
        return link[:max_length-3] + "..."

    def copy_link(self):
        """Copy the full link to clipboard."""
        if self.full_link:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.full_link)
            # Show temporary feedback
            original_text = self.copy_button.text()
            self.copy_button.setText("✅")
            QTimer.singleShot(1000, lambda: self.copy_button.setText(original_text))

    def start_inline_edit(self):
        """Start inline editing of the link."""
        self.link_input.setText(self.full_link)
        self.link_label.setVisible(False)
        self.copy_button.setVisible(False)  # Ẩn nút copy để input chiếm full width
        self.link_input.setVisible(True)
        self.link_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.link_input.setFocus()
        self.link_input.selectAll()

    def finish_inline_edit(self):
        """Finish inline editing and update the link."""
        if not self.link_input.isVisible():
            return
        new_link = self.link_input.text().strip()
        self.set_link(new_link)
        self.link_label.setVisible(True)
        self.link_input.setVisible(False)
        self.copy_button.setVisible(True)  # Hiện lại nút copy
        self.link_changed.emit(new_link)

    def edit_link(self, event=None):
        """Open dialog to edit the link."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Ads Link")
        dialog.setModal(True)

        layout = QVBoxLayout()

        link_input = QLineEdit(self.full_link)
        layout.addWidget(link_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_link = link_input.text().strip()
            self.set_link(new_link)
            self.link_changed.emit(new_link)

    def set_link(self, link_text):
        self.full_link = link_text
        self.link_label.setText(self.truncate_link(link_text))

    def get_link(self):
        return self.full_link

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to start inline editing."""
        self.start_inline_edit()
        event.accept()

class AdsTableWidget(QWidget):
    """Widget containing the ads table with device management functionality."""

    status_update = Signal(str)
    ads_link_changed = Signal(int, str)  # Signal for ads link changes (row_idx, new_link)

    def __init__(self, data_csv="data.csv", parent=None):
        super().__init__(parent)
        self.data_csv = data_csv
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Model', 'Serial', 'Ads Link', 'Ads Info'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.on_table_item_changed)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.mousePressEvent = self.table_mouse_press_event
        self.table.focusOutEvent = self.table_focus_out_event
        self.table.mouseDoubleClickEvent = self.table_mouse_double_click_event

        # Dùng delegate riêng cho cột Serial để editor không bị tràn ra ngoài ô
        self._serial_delegate = SerialDelegate(self.table)
        self.table.setItemDelegateForColumn(1, self._serial_delegate)

        # Remove cell hover effect but keep row selection, make header text bolder
        self.table.setStyleSheet("""
            QTableWidget::item:hover {
                background-color: transparent;
                border: none;
                outline: none;
                color: inherit;
            }
            QTableWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
            QTableWidget::item:selected:hover {
                background-color: #e3f2fd;
                border: none;
                outline: none;
                color: black;
            }
            QTableWidget::item:focus {
                border: 1px solid transparent;
                outline: none;
                background-color: inherit;
            }
            QTableWidget::item:selected:focus {
                background-color: #e3f2fd;
                border: 1px solid transparent;
                outline: none;
                color: black;
            }
            QTableWidget {
                selection-background-color: #e3f2fd;
                gridline-color: #ddd;
            }
            QHeaderView::section {
                font-weight: bold;
                background-color: #f0f0f0;
            }
        """)

        layout.addWidget(self.table)

        # ── Like Human Settings Section ──────────────────────────────────
        self._build_human_settings_section(layout)

        self.refresh_table()

    def _build_human_settings_section(self, parent_layout: QVBoxLayout):
        """Tạo section 'Like Human Behavior' bên dưới table."""
        group = QGroupBox("🤖 Like Human Behavior")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #ccc;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 4px;
                background-color: #fafafa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #333;
            }
        """)

        grid = QHBoxLayout()
        grid.setSpacing(16)
        grid.setContentsMargins(10, 6, 10, 8)

        # ── Cột 1: Duration ──────────────────────────────────────────────
        col1 = QVBoxLayout()
        col1.setSpacing(4)
        col1_title = QLabel("⏱ Duration (s)")
        col1_title.setStyleSheet("font-weight: bold; color: #555;")
        col1.addWidget(col1_title)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Min:"))
        self._hs_min_dur = QSpinBox()
        self._hs_min_dur.setRange(10, 600)
        self._hs_min_dur.setValue(60)
        self._hs_min_dur.setSuffix("s")
        self._hs_min_dur.setToolTip("Thời gian tối thiểu mỗi phiên lướt")
        dur_row.addWidget(self._hs_min_dur)
        dur_row.addWidget(QLabel("Max:"))
        self._hs_max_dur = QSpinBox()
        self._hs_max_dur.setRange(10, 600)
        self._hs_max_dur.setValue(90)
        self._hs_max_dur.setSuffix("s")
        self._hs_max_dur.setToolTip("Thời gian tối đa mỗi phiên lướt")
        dur_row.addWidget(self._hs_max_dur)
        col1.addLayout(dur_row)

        read_row = QHBoxLayout()
        read_row.addWidget(QLabel("Read min:"))
        self._hs_read_min = QDoubleSpinBox()
        self._hs_read_min.setRange(0.5, 30.0)
        self._hs_read_min.setValue(1.5)
        self._hs_read_min.setSuffix("s")
        self._hs_read_min.setSingleStep(0.5)
        self._hs_read_min.setToolTip("Thời gian dừng đọc tối thiểu")
        read_row.addWidget(self._hs_read_min)
        read_row.addWidget(QLabel("max:"))
        self._hs_read_max = QDoubleSpinBox()
        self._hs_read_max.setRange(0.5, 60.0)
        self._hs_read_max.setValue(6.0)
        self._hs_read_max.setSuffix("s")
        self._hs_read_max.setSingleStep(0.5)
        self._hs_read_max.setToolTip("Thời gian dừng đọc tối đa")
        read_row.addWidget(self._hs_read_max)
        col1.addLayout(read_row)
        grid.addLayout(col1)

        # ── Separator ────────────────────────────────────────────────────
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #ddd;")
        grid.addWidget(sep1)

        # ── Cột 2: Click & Burst ─────────────────────────────────────────
        col2 = QVBoxLayout()
        col2.setSpacing(4)
        col2_title = QLabel("👆 Click & Burst")
        col2_title.setStyleSheet("font-weight: bold; color: #555;")
        col2.addWidget(col2_title)

        click_row = QHBoxLayout()
        click_row.addWidget(QLabel("Click %:"))
        self._hs_click_prob = QSlider(Qt.Orientation.Horizontal)
        self._hs_click_prob.setRange(5, 80)
        self._hs_click_prob.setValue(55)
        self._hs_click_prob.setFixedWidth(100)
        self._hs_click_prob.setToolTip("Xác suất click vào element mỗi lượt (cao = click nhiều hơn)")
        self._hs_click_label = QLabel("55%")
        self._hs_click_label.setFixedWidth(36)
        self._hs_click_prob.valueChanged.connect(lambda v: self._hs_click_label.setText(f"{v}%"))
        click_row.addWidget(self._hs_click_prob)
        click_row.addWidget(self._hs_click_label)
        col2.addLayout(click_row)

        burst_row = QHBoxLayout()
        burst_row.addWidget(QLabel("Burst %:"))
        self._hs_burst_prob = QSlider(Qt.Orientation.Horizontal)
        self._hs_burst_prob.setRange(5, 80)
        self._hs_burst_prob.setValue(35)
        self._hs_burst_prob.setFixedWidth(100)
        self._hs_burst_prob.setToolTip("Xác suất burst scroll (cao = scroll nhiều liên tiếp hơn)")
        self._hs_burst_label = QLabel("35%")
        self._hs_burst_label.setFixedWidth(36)
        self._hs_burst_prob.valueChanged.connect(lambda v: self._hs_burst_label.setText(f"{v}%"))
        burst_row.addWidget(self._hs_burst_prob)
        burst_row.addWidget(self._hs_burst_label)
        col2.addLayout(burst_row)
        grid.addLayout(col2)

        # ── Separator ────────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #ddd;")
        grid.addWidget(sep2)

        # ── Cột 3: Scroll Distance ───────────────────────────────────────
        col3 = QVBoxLayout()
        col3.setSpacing(4)
        col3_title = QLabel("📜 Scroll Distance (px)")
        col3_title.setStyleSheet("font-weight: bold; color: #555;")
        col3.addWidget(col3_title)

        sdist_row = QHBoxLayout()
        sdist_row.addWidget(QLabel("Min:"))
        self._hs_scroll_min = QSpinBox()
        self._hs_scroll_min.setRange(50, 1500)
        self._hs_scroll_min.setValue(350)
        self._hs_scroll_min.setSuffix("px")
        self._hs_scroll_min.setSingleStep(50)
        self._hs_scroll_min.setToolTip("Khoảng cách scroll tối thiểu mỗi lần")
        sdist_row.addWidget(self._hs_scroll_min)
        sdist_row.addWidget(QLabel("Max:"))
        self._hs_scroll_max = QSpinBox()
        self._hs_scroll_max.setRange(100, 2000)
        self._hs_scroll_max.setValue(750)
        self._hs_scroll_max.setSuffix("px")
        self._hs_scroll_max.setSingleStep(50)
        self._hs_scroll_max.setToolTip("Khoảng cách scroll tối đa mỗi lần (cao = scroll xa hơn, giống người hơn)")
        sdist_row.addWidget(self._hs_scroll_max)
        col3.addLayout(sdist_row)
        grid.addLayout(col3)

        group.setLayout(grid)
        parent_layout.addWidget(group)

    def get_human_settings(self) -> dict:
        """Trả về dict settings 'like human' từ UI controls."""
        return {
            "min_duration": float(self._hs_min_dur.value()),
            "max_duration": float(self._hs_max_dur.value()),
            "click_prob": self._hs_click_prob.value() / 100.0,
            "burst_prob": self._hs_burst_prob.value() / 100.0,
            "scroll_dist_min": self._hs_scroll_min.value(),
            "scroll_dist_max": self._hs_scroll_max.value(),
            "read_pause_min": self._hs_read_min.value(),
            "read_pause_max": self._hs_read_max.value(),
        }

    def get_devices_with_model(self):
        try:
            out = subprocess.check_output(
                ["adb", "devices", "-l"],
                text=True, startupinfo=_si, stderr=subprocess.DEVNULL
            )
            lines = out.strip().splitlines()[1:]

            devices = []
            for line in lines:
                if "device" not in line:
                    continue

                parts = line.split()
                serial = parts[0]

                model = "UNKNOWN"
                for p in parts:
                    if p.startswith("model:"):
                        model = p.split("model:")[1]
                        break

                devices.append({
                    "serial": serial,
                    "model": model,
                    "raw": line
                })

            return devices
        except Exception as e:
            print(f"Error getting devices: {e}")
            return []

    def refresh_table(self):
        try:
            try:
                rows = CSVHelper.read_csv(self.data_csv)
            except FileNotFoundError:
                rows = []

            num_rows = len(rows)
            if num_rows == 0:
                self.table.setRowCount(0)
                self.status_update.emit('No data in CSV found')
                return

            self.table.blockSignals(True)
            self.table.setRowCount(num_rows)
            self.table.setColumnCount(4)

            for row_idx in range(num_rows):
                model = rows[row_idx][0] if len(rows[row_idx]) > 0 else ""
                serial = rows[row_idx][1] if len(rows[row_idx]) > 1 else ""
                ads_link = rows[row_idx][2] if len(rows[row_idx]) > 2 else ""
                ads_info = rows[row_idx][3] if len(rows[row_idx]) > 3 else ""

                model_item = QTableWidgetItem(model)
                serial_item = QTableWidgetItem(serial)
                ads_link_widget = AdsLinkWidget(ads_link)
                ads_info_item = QTableWidgetItem(ads_info)

                # Model và Ads Info không cho edit trực tiếp, Serial cho phép edit
                non_editable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                model_item.setFlags(non_editable)
                # Serial column is now editable
                serial_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
                ads_info_item.setFlags(non_editable)

                self.table.setItem(row_idx, 0, model_item)
                self.table.setItem(row_idx, 1, serial_item)
                self.table.setCellWidget(row_idx, 2, ads_link_widget)  # Use setCellWidget for custom widget
                ads_link_widget.link_changed.connect(lambda new_link, row=row_idx: self.on_ads_link_changed(row, new_link))
                self.table.setItem(row_idx, 3, ads_info_item)

            self.table.resizeColumnsToContents()
            # Set minimum width for ads link column to accommodate the buttons
            if self.table.columnCount() > 2:
                min_width = 200  # Minimum width to show truncated text + buttons
                current_width = self.table.columnWidth(2)
                if current_width < min_width:
                    self.table.setColumnWidth(2, min_width)
            self.table.blockSignals(False)

            self.status_update.emit(f'Loaded {len(rows)} rows from CSV')

        except Exception as e:
            self.status_update.emit(f'Error refreshing table: {str(e)}')
            print(f"Error details: {e}")

    def refresh_devices_and_csv(self):
        try:
            devices = self.get_devices_with_model()

            # Đọc ads_link cũ từ CSV (nếu có) để giữ lại khi refresh
            try:
                existing = CSVHelper.read_csv(self.data_csv)
                existing_links = {row[1]: row[2] for row in existing if len(row) > 2}
                existing_info = {row[1]: row[3] for row in existing if len(row) > 3}
            except Exception:
                existing_links = {}
                existing_info = {}

            rows = []
            for device in devices:
                serial = device["serial"]
                ads_link = existing_links.get(serial, "")
                ads_info = existing_info.get(serial, "")
                rows.append([device["model"], serial, ads_link, ads_info])

            CSVHelper.write_csv(self.data_csv, rows)

            self.refresh_table()
            self.status_update.emit(f'Updated with {len(devices)} devices')

        except Exception as e:
            self.status_update.emit(f'Error refreshing devices: {str(e)}')
            print(f"Error details: {e}")

    def on_ads_link_changed(self, row_idx, new_link):
        """Handle ads link changes from custom widget."""
        self.ads_link_changed.emit(row_idx, new_link)
        self.save_csv_changes()

    def on_selection_changed(self):
        """Clear focus when selection changes."""
        self.table.clearFocus()

    def table_mouse_press_event(self, event):
        """Handle mouse press to clear focus before normal processing."""
        # Clear focus first
        self.table.clearFocus()
        self.table.setCurrentItem(None)
        # Then call the original mouse press event
        QTableWidget.mousePressEvent(self.table, event)

    def table_focus_out_event(self, event):
        """Handle focus out to clear cell focus."""
        # Clear focus when table loses focus
        self.table.clearFocus()
        self.table.setCurrentItem(None)
        # Call original focus out event
        QTableWidget.focusOutEvent(self.table, event)

    def table_mouse_double_click_event(self, event):
        """Handle double-click on table cells for inline editing."""
        # Get the index at the double-click position
        index = self.table.indexAt(event.pos())
        if index.isValid():
            row = index.row()
            col = index.column()

            if col == 1:  # Serial column
                item = self.table.item(row, col)
                if item:
                    self.table.editItem(item)
            elif col == 2:  # Ads link column
                # Get the AdsLinkWidget and trigger inline editing
                widget = self.table.cellWidget(row, col)
                if isinstance(widget, AdsLinkWidget):
                    widget.start_inline_edit()
            elif col == 3:  # Ads Info column — mở modal xem full text
                item = self.table.item(row, col)
                full_text = item.text() if item else ""
                self.show_ads_info_modal(full_text)

        # Call parent event
        QTableWidget.mouseDoubleClickEvent(self.table, event)

    def show_ads_info_modal(self, text: str):
        """Mở dialog hiển thị đầy đủ nội dung Ads Info."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Ads Info")
        dialog.setModal(True)
        dialog.resize(520, 320)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text if text else "(Chưa có thông tin)")
        text_edit.setStyleSheet("""
            QTextEdit {
                font-size: 13px;
                padding: 6px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #fafafa;
            }
        """)
        layout.addWidget(text_edit)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        dialog.exec()

    def on_table_item_changed(self, item):
        """Lưu CSV mỗi khi user chỉnh sửa ô Ads Link."""
        if item.column() != 2:
            return
        self.save_csv_changes()

    def save_csv_changes(self):
        """Save current table data to CSV."""
        try:
            rows = []
            for row_idx in range(self.table.rowCount()):
                model = self.table.item(row_idx, 0)
                serial = self.table.item(row_idx, 1)
                # For ads link, get from custom widget
                ads_widget = self.table.cellWidget(row_idx, 2)
                ads_link = ads_widget.get_link() if ads_widget else ""
                ads_info = self.table.item(row_idx, 3)
                rows.append([
                    model.text() if model else "",
                    serial.text() if serial else "",
                    ads_link,
                    ads_info.text() if ads_info else "",
                ])
            CSVHelper.write_csv(self.data_csv, rows)
        except Exception as e:
            print(f"Error saving CSV: {e}")

    def on_row_result(self, row_idx: int, ads_info: str):
        """Cập nhật cột Ads Info khi một device chạy xong."""
        self.table.blockSignals(True)
        item = QTableWidgetItem(ads_info)
        non_editable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        item.setFlags(non_editable)
        self.table.setItem(row_idx, 3, item)
        self.table.resizeColumnToContents(3)
        self.table.blockSignals(False)
        # Lưu CSV ngay
        try:
            rows = []
            for r in range(self.table.rowCount()):
                model = self.table.item(r, 0)
                serial = self.table.item(r, 1)
                # For ads link, get from custom widget
                ads_widget = self.table.cellWidget(r, 2)
                ads_link = ads_widget.get_link() if ads_widget else ""
                ads_info = self.table.item(r, 3)
                rows.append([
                    model.text() if model else "",
                    serial.text() if serial else "",
                    ads_link,
                    ads_info.text() if ads_info else "",
                ])
            CSVHelper.write_csv(self.data_csv, rows)
        except Exception as e:
            print(f"Error saving ads info: {e}")

    def get_table_data(self):
        """Get table data for worker operations."""
        table_data = []
        row_count = self.table.rowCount()
        for row in range(row_count):
            serial_item = self.table.item(row, 1)
            # Get ads link from custom widget
            ads_widget = self.table.cellWidget(row, 2)
            ads_link = ads_widget.get_link() if ads_widget else ""
            serial = serial_item.text() if serial_item else ""
            table_data.append({'serial': serial, 'ads_link': ads_link, 'row_index': row})
        return table_data
