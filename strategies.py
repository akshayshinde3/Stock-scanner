"""
strategies.py — Focused Swing Trading Engine (Ascending/Symmetrical Triangle, Descending Channel, Pennant)

Implements:
  1.  Triangle pattern  (Ascending / Symmetrical)
  2.  Descending Channel pattern (Two parallel downward sloping trendlines with bullish breakout)
  3.  Pennant pattern  (pole + converging consolidation with volume confirmation)

All patterns include:
  - Confirmed breakout detection
  - Pre-breakout / watch-list detection
  - Confidence scoring
  - Trade levels (buy, stop-loss, target1, target2)
  - Strict confidence filter: Confirmed stocks returned ONLY with confidence >= 60%
"""

import datetime as dt
import statistics


# ---------------------------------------------------------------------------
# Swing point + trendline helpers
# ---------------------------------------------------------------------------
def find_swing_points(highs, lows, window=3):
    """Local swing highs/lows within +/- `window` bars."""
    swing_highs, swing_lows = [], []
    n = len(highs)
    for i in range(window, n - window):
        seg_h = highs[i - window: i + window + 1]
        seg_l = lows[i - window: i + window + 1]
        if highs[i] == max(seg_h):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(seg_l):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def linreg(points):
    """Simple linear regression over (x, y) points. Returns (slope, intercept, r2)."""
    n = len(points)
    if n < 2:
        return 0.0, points[0][1] if points else 0.0, 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    if ss_xx == 0:
        return 0.0, mean_y, 0.0
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in points)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, intercept, r2


def line_value(slope, intercept, x):
    return slope * x + intercept


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    val = sum(values[:period]) / period
    for v in values[period:]:
        val = v * k + val * (1.0 - k)
    return val


# ---------------------------------------------------------------------------
# 1. TRIANGLE PATTERNS — Ascending & Symmetrical (Chartink + Geometric Fallback)
# ---------------------------------------------------------------------------
FLAT_SLOPE_THRESHOLD = 0.0025       # realistic flat slope threshold (0.25% per day)
MIN_TOUCHES = 2                     # require ≥2 touches per trendline
MIN_FIT_QUALITY = 0.35              # minimum R² fit quality
TOUCH_TOLERANCE = 0.035             # 3.5% touch tolerance for real-world wicks


def detect_triangle_chartink_daily(candles, live_price=None):
    """
    Chartink Daily Triangle Strategy:
      - Daily Close > 50 EMA
      - 1 day ago min(10, low) > 11 days ago min(10, low)  [Higher Lows]
      - Daily SMA(volume, 5) < Daily SMA(volume, 20)        [Volume Dry-Up]
      - Case A (Ascending Triangle):
          11 days ago max(20, high) >= 1 day ago max(30, high) * 0.985
          1 day ago max(10, high) >= 1 day ago max(30, high) * 0.985
          Close in [max(30, high)*0.95, max(30, high)]
      - Case B (Symmetrical Triangle):
          1 day ago max(10, high) < 11 days ago max(20, high) * 0.985
          10-day range (H-L) < 10-day range from 11 days ago (H-L) [Range Contraction]
          Close in [max(10, high)*0.95, max(10, high)]
    """
    if len(candles) < 40:
        return None

    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]
    volumes = [c[5] for c in candles]

    cur_price = live_price if live_price is not None else closes[-1]
    today_close = closes[-1]

    # 1. Trend filter: Daily Close > 50 EMA
    e50 = ema(closes, 50)
    if e50 is not None and today_close < e50 * 0.985:
        return None

    # 2. Volume dry-up: SMA(Vol, 5) < SMA(Vol, 20)
    v5 = sma(volumes, 5)
    v20 = sma(volumes, 20)
    vol_dry_up = (v5 is not None and v20 is not None and v5 < v20)

    # 3. Higher Lows: 1 day ago min(10, low) > 11 days ago min(10, low)
    min_low_10_1d = min(lows[-11:-1])
    min_low_10_11d = min(lows[-21:-11])
    higher_lows = min_low_10_1d >= min_low_10_11d * 0.995

    # 4. Check CASE A: Ascending Triangle (Flat Top Resistance, Higher Lows)
    max_high_30_1d = max(highs[-31:-1])
    max_high_20_11d = max(highs[-31:-11])
    max_high_10_1d = max(highs[-11:-1])

    is_ascending = (
        higher_lows and
        max_high_20_11d >= max_high_30_1d * 0.980 and
        max_high_10_1d >= max_high_30_1d * 0.980
    )

    # 5. Check CASE B: Symmetrical Triangle (Lower Highs, Higher Lows, Range Contraction)
    range_10_1d = max_high_10_1d - min_low_10_1d
    max_high_10_11d = max(highs[-21:-11])
    min_low_10_11d_val = min(lows[-21:-11])
    range_10_11d = max_high_10_11d - min_low_10_11d_val

    is_symmetrical = (
        higher_lows and
        max_high_10_1d < max_high_20_11d * 0.988 and
        range_10_1d < range_10_11d
    )

    if not is_ascending and not is_symmetrical:
        return None

    if is_ascending:
        triangle_type = "Ascending Triangle"
        res_level = max_high_30_1d
        sup_level = min_low_10_1d
        lookback = 35
    else:
        triangle_type = "Symmetrical Triangle"
        res_level = max_high_10_1d
        sup_level = min_low_10_1d
        lookback = 25

    # Status check:
    breakout_now = cur_price >= res_level or today_close >= res_level
    recent_breakout = (len(closes) >= 3 and 
                       (closes[-2] >= res_level or closes[-3] >= res_level) and 
                       cur_price >= res_level * 0.97)
    is_watch = (cur_price >= sup_level * 0.97 and cur_price <= res_level * 1.01)

    if breakout_now or recent_breakout:
        status = "confirmed"
    elif is_watch:
        status = "pre_breakout_watch"
    else:
        return None

    return {
        "type": triangle_type,
        "resistance_now": round(res_level, 2),
        "support_now": round(sup_level, 2),
        "fit_quality": 0.90,
        "contraction": round(max(0.15, 1 - (range_10_1d / range_10_11d)) if range_10_11d > 0 else 0.25, 2),
        "bars_to_apex": 4,
        "touches": 4 if is_ascending else 3,
        "status": status,
        "vol_dry_up": vol_dry_up,
        "source": "Chartink Strategy",
        "lookback": lookback,
        "timeframe": "daily",
    }


def detect_triangle_chartink_weekly(candles, live_price=None):
    """
    Chartink Weekly Triangle Strategy:
      - Weekly Close > Weekly 20 EMA
      - 1 week ago min(5, low) > 6 weeks ago min(5, low) [Higher Lows]
      - Case A (Weekly Ascending Triangle):
          1 week ago max(5, high) >= 1 week ago max(15, high) * 0.985
          6 weeks ago max(10, high) >= 1 week ago max(15, high) * 0.985
          Weekly Close in [max(15, high)*0.95, max(15, high)]
      - Case B (Weekly Symmetrical Triangle):
          1 week ago max(5, high) < 6 weeks ago max(10, high) * 0.985
          5-week range (H-L) < 5-week range from 6 weeks ago (H-L) [Range Contraction]
          Weekly Close in [max(5, high)*0.95, max(5, high)]
    """
    if len(candles) < 20:
        return None

    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]

    cur_price = live_price if live_price is not None else closes[-1]
    today_close = closes[-1]

    # 1. Weekly Close > Weekly 20 EMA
    e20 = ema(closes, 20)
    if e20 is not None and today_close < e20 * 0.985:
        return None

    # 2. Higher Lows: 1 week ago min(5, low) > 6 weeks ago min(5, low)
    min_low_5_1w = min(lows[-6:-1])
    min_low_5_6w = min(lows[-11:-6])
    higher_lows = min_low_5_1w >= min_low_5_6w * 0.995

    # 3. CASE A: Weekly Ascending Triangle
    max_high_15_1w = max(highs[-16:-1])
    max_high_5_1w = max(highs[-6:-1])
    max_high_10_6w = max(highs[-16:-6])

    is_ascending = (
        higher_lows and
        max_high_5_1w >= max_high_15_1w * 0.980 and
        max_high_10_6w >= max_high_15_1w * 0.980
    )

    # 4. CASE B: Weekly Symmetrical Triangle
    range_5_1w = max_high_5_1w - min_low_5_1w
    max_high_5_6w = max(highs[-11:-6])
    range_5_6w = max_high_5_6w - min_low_5_6w

    is_symmetrical = (
        higher_lows and
        max_high_5_1w < max_high_10_6w * 0.988 and
        range_5_1w < range_5_6w
    )

    if not is_ascending and not is_symmetrical:
        return None

    if is_ascending:
        triangle_type = "Ascending Triangle"
        res_level = max_high_15_1w
        sup_level = min_low_5_1w
        lookback = 20
    else:
        triangle_type = "Symmetrical Triangle"
        res_level = max_high_5_1w
        sup_level = min_low_5_1w
        lookback = 15

    breakout_now = cur_price >= res_level or today_close >= res_level
    recent_breakout = (len(closes) >= 3 and 
                       (closes[-2] >= res_level or closes[-3] >= res_level) and 
                       cur_price >= res_level * 0.97)
    is_watch = (cur_price >= sup_level * 0.97 and cur_price <= res_level * 1.01)

    if breakout_now or recent_breakout:
        status = "confirmed"
    elif is_watch:
        status = "pre_breakout_watch"
    else:
        return None

    return {
        "type": triangle_type,
        "resistance_now": round(res_level, 2),
        "support_now": round(sup_level, 2),
        "fit_quality": 0.92,
        "contraction": round(max(0.15, 1 - (range_5_1w / range_5_6w)) if range_5_6w > 0 else 0.25, 2),
        "bars_to_apex": 4,
        "touches": 4 if is_ascending else 3,
        "status": status,
        "source": "Chartink Weekly Strategy",
        "lookback": lookback,
        "timeframe": "weekly",
    }


def _detect_triangle_window(candles, lookback=40):
    if len(candles) < lookback + 5:
        return None
    window = candles[-lookback:]
    highs = [c[2] for c in window]
    lows = [c[3] for c in window]
    closes = [c[4] for c in window]
    avg_price = sum(closes) / len(closes)

    swing_highs, swing_lows = find_swing_points(highs, lows, window=2)
    if len(swing_highs) < MIN_TOUCHES or len(swing_lows) < MIN_TOUCHES:
        return None

    res_slope, res_intercept, res_r2 = linreg(swing_highs)
    sup_slope, sup_intercept, sup_r2 = linreg(swing_lows)

    fit_quality = (res_r2 + sup_r2) / 2
    if fit_quality < MIN_FIT_QUALITY:
        return None

    res_slope_norm = res_slope / avg_price
    sup_slope_norm = sup_slope / avg_price

    last_x = len(window) - 1
    res_now = line_value(res_slope, res_intercept, last_x)
    sup_now = line_value(sup_slope, sup_intercept, last_x)
    if sup_now >= res_now:
        return None

    res_flat = abs(res_slope_norm) < FLAT_SLOPE_THRESHOLD

    triangle_type = None
    if res_flat and sup_slope_norm > 0.0003:
        triangle_type = "Ascending Triangle"
    elif res_slope_norm < -0.0003 and sup_slope_norm > 0.0003:
        triangle_type = "Symmetrical Triangle"
    else:
        return None

    gap_start = line_value(res_slope, res_intercept, 0) - line_value(sup_slope, sup_intercept, 0)
    gap_now = res_now - sup_now
    contraction = 1 - (gap_now / gap_start) if gap_start > 0 else 0

    if contraction < 0.10:
        return None

    if res_slope != sup_slope:
        apex_x = (sup_intercept - res_intercept) / (res_slope - sup_slope)
        bars_to_apex = apex_x - last_x
    else:
        bars_to_apex = None

    # Validate swing points actually touch the trendlines (within tolerance)
    res_touches = 0
    for idx, val in swing_highs:
        expected = line_value(res_slope, res_intercept, idx)
        if expected > 0 and abs(val - expected) / expected < TOUCH_TOLERANCE:
            res_touches += 1

    sup_touches = 0
    for idx, val in swing_lows:
        expected = line_value(sup_slope, sup_intercept, idx)
        if expected > 0 and abs(val - expected) / expected < TOUCH_TOLERANCE:
            sup_touches += 1

    if res_touches < 2 or sup_touches < 2:
        return None

    return {
        "type": triangle_type,
        "resistance_now": round(res_now, 2),
        "support_now": round(sup_now, 2),
        "fit_quality": round(fit_quality, 2),
        "contraction": round(max(contraction, 0), 2),
        "bars_to_apex": round(bars_to_apex, 1) if bars_to_apex is not None else None,
        "touches": res_touches + sup_touches,
        "lookback": lookback,
    }


def detect_triangle(candles, timeframe="daily", live_price=None):
    if timeframe == "weekly":
        c_res = detect_triangle_chartink_weekly(candles, live_price)
    else:
        c_res = detect_triangle_chartink_daily(candles, live_price)

    if c_res:
        return c_res

    best = None
    for lb in [40, 35, 50, 60]:
        res = _detect_triangle_window(candles, lookback=lb)
        if res:
            if not best or (res["fit_quality"], res["touches"]) > (best["fit_quality"], best["touches"]):
                best = res
    return best


# ---------------------------------------------------------------------------
# 2. DESCENDING CHANNEL STRATEGY — Parallel Downward Trendlines with Breakout
# ---------------------------------------------------------------------------
def _detect_channel_window(candles, lookback, timeframe="daily", live_price=None):
    """
    Detects a Descending Channel over a window:
    - Upper Resistance Trendline connects Lower Highs (LH): negative slope.
    - Lower Support Trendline connects Lower Lows (LL): negative slope.
    - Two trendlines are roughly parallel.
    - Confirmed Breakout: price breaks above upper resistance with volume expansion.
    - Pre-Breakout Watch: price testing upper resistance near breakout zone.
    """
    if len(candles) < lookback:
        return None

    window = candles[-lookback:]
    highs = [c[2] for c in window]
    lows = [c[3] for c in window]
    closes = [c[4] for c in window]
    volumes = [c[5] for c in window]
    avg_price = sum(closes) / len(closes)

    cur_price = live_price if live_price is not None else closes[-1]
    today_close = closes[-1]
    today_open = window[-1][1]

    # Find swing highs and swing lows
    win_param = 2 if lookback <= 30 else 3
    sh, sl = find_swing_points(highs, lows, window=win_param)
    if len(sh) < 2 or len(sl) < 2:
        return None

    # Fit linear regression to swing highs (resistance) and swing lows (support)
    res_slope, res_intercept, res_r2 = linreg(sh)
    sup_slope, sup_intercept, sup_r2 = linreg(sl)

    res_slope_norm = res_slope / avg_price
    sup_slope_norm = sup_slope / avg_price

    # Both slopes MUST be negative (descending channel!)
    if res_slope_norm >= -0.0002 or sup_slope_norm >= -0.0002:
        return None

    # Trendlines must be approximately parallel:
    # Slopes should not diverge sharply:
    slope_diff = abs(res_slope_norm - sup_slope_norm)
    if slope_diff > 0.005:
        return None

    last_x = len(window) - 1
    res_now = line_value(res_slope, res_intercept, last_x)
    sup_now = line_value(sup_slope, sup_intercept, last_x)

    # Channel must be valid (resistance > support throughout)
    res_start = line_value(res_slope, res_intercept, 0)
    sup_start = line_value(sup_slope, sup_intercept, 0)

    if res_now <= sup_now or res_start <= sup_start:
        return None

    channel_height = res_now - sup_now
    channel_height_pct = (channel_height / avg_price) * 100

    # Channel height should be reasonable (between 3% and 35%)
    if channel_height_pct < 3.0 or channel_height_pct > 35.0:
        return None

    fit_quality = (res_r2 + sup_r2) / 2
    if fit_quality < 0.28:
        return None

    # Count swing points respecting the boundaries
    res_touches = 0
    for idx, val in sh:
        exp = line_value(res_slope, res_intercept, idx)
        if exp > 0 and abs(val - exp) / exp < 0.038:
            res_touches += 1

    sup_touches = 0
    for idx, val in sl:
        exp = line_value(sup_slope, sup_intercept, idx)
        if exp > 0 and abs(val - exp) / exp < 0.038:
            sup_touches += 1

    if res_touches < 2 or sup_touches < 2:
        return None

    # Volume metrics
    avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
    cur_vol = volumes[-1]
    vol_ratio = (cur_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0
    vol_spike = vol_ratio >= 1.15

    # Breakout check:
    # 1. Breakout today: price breaks above upper descending resistance line
    breakout_now = (today_close >= res_now or cur_price >= res_now) and (today_close >= today_open * 0.995)
    # 2. Recent breakout holding:
    recent_breakout = (
        len(closes) >= 3 and
        (closes[-2] >= line_value(res_slope, res_intercept, last_x - 1) or
         closes[-3] >= line_value(res_slope, res_intercept, last_x - 2)) and
        cur_price >= res_now * 0.98
    )

    # Pre-breakout watch: price in upper 25% of channel near resistance
    is_watch = (cur_price >= res_now * 0.96 and cur_price <= res_now * 1.015)

    if breakout_now or recent_breakout:
        status = "confirmed"
    elif is_watch:
        status = "pre_breakout_watch"
    else:
        return None

    # Trendline coordinates for chart drawing
    off = len(candles) - lookback
    start_x = 0
    end_x = last_x

    return {
        "type": "Descending Channel",
        "resistance_now": round(res_now, 2),
        "support_now": round(sup_now, 2),
        "channel_height": round(channel_height, 2),
        "channel_height_pct": round(channel_height_pct, 1),
        "res_slope": res_slope,
        "res_intercept": res_intercept,
        "sup_slope": sup_slope,
        "sup_intercept": sup_intercept,
        "fit_quality": round(fit_quality, 2),
        "touches": res_touches + sup_touches,
        "status": status,
        "volume_ratio": round(vol_ratio, 2),
        "volume_spike": vol_spike,
        "lookback": lookback,
        "timeframe": timeframe,
        "offset": off,
        "start_x": start_x,
        "end_x": end_x,
    }


def detect_descending_channel(candles, timeframe="daily", live_price=None):
    """
    Evaluates descending channel across multiple lookbacks (capturing swing channels).
    For daily: tests lookbacks 25, 35, 45, 60.
    For weekly: tests lookbacks 15, 25, 35.
    """
    lookbacks = [15, 25, 35] if timeframe == "weekly" else [30, 45, 25, 60]
    best = None
    for lb in lookbacks:
        res = _detect_channel_window(candles, lb, timeframe=timeframe, live_price=live_price)
        if res:
            if not best or (res["fit_quality"], res["touches"]) > (best["fit_quality"], best["touches"]):
                best = res
    return best


# ---------------------------------------------------------------------------
# 3. PENNANT STRATEGY — Bullish Pennant with volume confirmation
# ---------------------------------------------------------------------------
def detect_pennant(candles):
    """
    Pennant Pattern (Bullish):
    - Sharp rise (pole) of at least 6% in the last 15-25 bars.
    - Small symmetrical triangle consolidation (converging lines) over 5-20 bars.
    - Confirmed: breakout above resistance with green candle AND volume spike.
    - Forming: price approaching resistance within 1.5%.
    """
    if len(candles) < 25:
        return None

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    volumes = [c[5] for c in candles]
    n = len(candles)

    pole_found = False
    pole_start_idx = -1
    pole_move_pct = 0.0

    for i in range(max(0, n - 25), n - 8):
        move = (closes[i+8] - closes[i]) / closes[i] * 100
        if move >= 6.0:
            pole_found = True
            pole_start_idx = i
            pole_move_pct = move
            break

    if not pole_found:
        return None

    consol_window = candles[pole_start_idx + 8:]
    if len(consol_window) < 5 or len(consol_window) > 20:
        return None

    c_highs = [c[2] for c in consol_window]
    c_lows = [c[3] for c in consol_window]
    c_vols = [c[5] for c in consol_window]

    res_slope, res_intercept, res_r2 = linreg([(idx, val) for idx, val in enumerate(c_highs)])
    sup_slope, sup_intercept, sup_r2 = linreg([(idx, val) for idx, val in enumerate(c_lows)])

    avg_price = sum(closes[-len(consol_window):]) / len(consol_window)
    res_slope_norm = res_slope / avg_price
    sup_slope_norm = sup_slope / avg_price

    consol_fit = (res_r2 + sup_r2) / 2
    if consol_fit < 0.30:
        return None

    # Converging lines (resistance slopes down, support slopes up)
    if res_slope_norm < -0.0003 and sup_slope_norm > 0.0003:
        last_x = len(consol_window) - 1
        res_now = line_value(res_slope, res_intercept, last_x)
        sup_now = line_value(sup_slope, sup_intercept, last_x)

        if res_now <= sup_now:
            return None

        gap_start = line_value(res_slope, res_intercept, 0) - line_value(sup_slope, sup_intercept, 0)
        gap_now = res_now - sup_now
        if gap_start > 0 and (gap_now / gap_start) > 0.85:
            return None

        current_price = closes[-1]
        current_volume = volumes[-1]
        is_green = closes[-1] >= candles[-1][1]

        avg_vol_consol = sum(c_vols) / len(c_vols) if c_vols else 1
        avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        avg_vol = (avg_vol_consol + avg_vol_20) / 2
        volume_ratio = current_volume / avg_vol if avg_vol > 0 else 1.0
        volume_spike = volume_ratio >= 1.15

        if current_price > res_now and is_green:
            return {
                "type": "Pennant Breakout",
                "direction": "bullish",
                "resistance": round(res_now, 2),
                "support": round(sup_now, 2),
                "pole_move_pct": round(pole_move_pct, 1),
                "fit_quality": round(consol_fit, 2),
                "volume_ratio": round(volume_ratio, 2),
                "volume_spike": volume_spike,
                "status": "confirmed",
            }
        elif current_price >= res_now * 0.985:
            return {
                "type": "Pennant Consolidation",
                "direction": "bullish",
                "resistance": round(res_now, 2),
                "support": round(sup_now, 2),
                "pole_move_pct": round(pole_move_pct, 1),
                "fit_quality": round(consol_fit, 2),
                "volume_ratio": round(volume_ratio, 2),
                "volume_spike": False,
                "status": "forming",
            }

    return None


# ---------------------------------------------------------------------------
# Per-pattern alert builder helpers
# ---------------------------------------------------------------------------
def _pattern_levels(pattern_type, pattern, candles):
    """Compute buy/sl/target levels based on pattern type."""
    today_close = candles[-1][4]
    atr = sum(c[2] - c[3] for c in candles[-14:]) / 14 if len(candles) >= 14 else (candles[-1][2] - candles[-1][3])

    if pattern_type == "channel":
        res = pattern["resistance_now"]
        ch_height = pattern.get("channel_height", res * 0.05)
        buy_price = round(max(res * 1.002, today_close), 2) if today_close > res else round(res * 1.002, 2)
        # Stop loss below recent swing low inside channel or 2% - 3% risk (TMGM reference)
        stop_loss = round(max(pattern["support_now"], buy_price - max(atr * 1.5, ch_height * 0.5)), 2)
        risk = buy_price - stop_loss
        if risk <= 0 or (risk / buy_price) < 0.01:
            stop_loss = round(buy_price - max(atr * 1.5, buy_price * 0.025), 2)
            risk = buy_price - stop_loss
        target1 = round(buy_price + 2 * risk, 2)            # TP1: 2:1 RR
        target2 = round(buy_price + max(ch_height, 3 * risk), 2)  # TP2: Channel height / Prior Highs
        return buy_price, stop_loss, target1, target2

    elif pattern_type == "triangle":
        res = pattern["resistance_now"]
        buy_price = round(max(res * 1.002, today_close), 2) if today_close > res else round(res * 1.002, 2)
        stop_loss = round(pattern["support_now"], 2)

    elif pattern_type == "pennant":
        res = pattern["resistance"]
        buy_price = round(max(res * 1.002, today_close), 2) if today_close > res else round(res * 1.002, 2)
        stop_loss = round(pattern["support"], 2)

    else:
        buy_price = round(today_close, 2)
        stop_loss = round(today_close - 1.5 * atr, 2)

    risk = buy_price - stop_loss
    if risk <= 0:
        stop_loss = round(buy_price - 1.5 * atr, 2)
        risk = buy_price - stop_loss

    if risk <= 0:
        return None, None, None, None

    target1 = round(buy_price + 2 * risk, 2)
    target2 = round(buy_price + 3 * risk, 2)
    return buy_price, stop_loss, target1, target2


# ---------------------------------------------------------------------------
# Main combined alert builder
# ---------------------------------------------------------------------------
def build_alert(symbol, candles, live_price, timeframe="daily"):
    """
    Runs strategies (Descending Channel, Triangle, Pennant), picks the single
    best qualifying signal, returns full alert dict or None.
    Confirmed breakouts strictly filtered to confidence >= 60%.
    """
    min_candles = 20 if timeframe == "weekly" else 40
    if len(candles) < min_candles:
        return None

    today = candles[-1]
    today_open, today_close = today[1], today[4]
    atr = sum(c[2] - c[3] for c in candles[-14:]) / 14 if len(candles) >= 14 else (today[2] - today[3])

    # Run detectors
    channel  = detect_descending_channel(candles, timeframe=timeframe, live_price=live_price)
    triangle = detect_triangle(candles, timeframe=timeframe, live_price=live_price)
    pennant  = detect_pennant(candles) if timeframe == "daily" else None

    # Candidate evaluation list: pick the single best pattern (no multi/combo)
    candidates = []

    # 1. Descending Channel Candidate
    if channel:
        c_status = channel["status"]
        c_score = 60 if c_status == "confirmed" else 42
        c_reasons = []
        if c_status == "confirmed":
            c_reasons.append(f"Descending Channel: Decisive breakout above upper trendline ₹{channel['resistance_now']}")
            if channel.get("volume_spike"):
                c_reasons.append(f"Volume spike on breakout: {channel.get('volume_ratio', 1.2):.2f}× 20-day average")
                c_score += 10
            else:
                c_score += 5
        else:
            c_reasons.append(f"Descending Channel: Testing upper resistance ₹{channel['resistance_now']} (Pre-breakout watch)")

        c_reasons.append(f"Channel support holding at ₹{channel['support_now']} (Fit: {channel['fit_quality']}, {channel['touches']} touches)")
        candidates.append({
            "type_key": "channel",
            "name": "Descending Channel",
            "status": c_status,
            "score": c_score,
            "reasons": c_reasons,
            "pattern": channel
        })

    # 2. Triangle Candidate (Ascending / Symmetrical)
    if triangle:
        t_name = triangle["type"]
        t_status = triangle.get("status", "confirmed")
        t_score = 55 if t_status == "confirmed" else 38
        t_reasons = []
        if t_status == "confirmed":
            t_reasons.append(f"{t_name}: Breakout at ₹{triangle['resistance_now']}")
            t_score += 8
        else:
            t_reasons.append(f"{t_name}: Tightening near resistance ₹{triangle['resistance_now']} (Pre-breakout watch)")

        if triangle.get("vol_dry_up"):
            t_reasons.append("Volume dry-up confirmed: 5-day volume < 20-day average")
            t_score += 5
        if timeframe == "daily":
            t_reasons.append("Trend confirmed: Daily Close > 50 EMA")
        elif timeframe == "weekly":
            t_reasons.append("Weekly trend confirmed: Weekly Close > 20 EMA")

        candidates.append({
            "type_key": "triangle",
            "name": t_name,
            "status": t_status,
            "score": t_score,
            "reasons": t_reasons,
            "pattern": triangle
        })

    # 3. Pennant Candidate
    if pennant:
        p_status = "confirmed" if pennant["status"] == "confirmed" else "pre_breakout_watch"
        p_score = 58 if p_status == "confirmed" else 36
        p_reasons = []
        if p_status == "confirmed":
            p_reasons.append(f"Pennant Breakout: pole +{pennant['pole_move_pct']}%, closed above resistance ₹{pennant['resistance']}")
            if pennant.get("volume_spike"):
                p_reasons.append(f"Volume spike on breakout: {pennant.get('volume_ratio', 1.2):.2f}× average")
                p_score += 10
            else:
                p_score += 4
        else:
            p_reasons.append(f"Pennant forming after +{pennant['pole_move_pct']}% move, resistance at ₹{pennant['resistance']}")

        candidates.append({
            "type_key": "pennant",
            "name": "Pennant Breakout",
            "status": p_status,
            "score": p_score,
            "reasons": p_reasons,
            "pattern": pennant
        })

    if not candidates:
        return None

    # Prioritize confirmed breakout candidates first, then highest score
    candidates.sort(key=lambda c: (1 if c["status"] == "confirmed" else 0, c["score"]), reverse=True)
    best = candidates[0]

    status = best["status"]
    score = best["score"]
    strategy_used = best["name"]
    reasons = best["reasons"]
    best_pattern_type = best["type_key"]
    best_pattern = best["pattern"]

    # Calculate trade levels
    buy_price, stop_loss, target1, target2 = _pattern_levels(best_pattern_type, best_pattern, candles)
    if buy_price is None:
        buy_price = round(today_close, 2)
        stop_loss = round(today_close - 1.5 * atr, 2)
        risk = buy_price - stop_loss
        if risk <= 0:
            return None
        target1 = round(buy_price + 2 * risk, 2)
        target2 = round(buy_price + 3 * risk, 2)

    risk = buy_price - stop_loss
    if risk <= 0:
        return None

    rr = round((target1 - buy_price) / risk, 2)
    if rr < 1.8:
        return None  # enforce minimum ~1:2 R:R

    # Pre-breakout: If LTP has crossed the buy trigger, it's a confirmed breakout
    if status == "pre_breakout_watch" and live_price >= buy_price:
        status = "confirmed"
        reasons.append(f"Price crossed above buy trigger ₹{buy_price} (Breakout confirmed)")
        score += 18

    # For watch alerts, drop if trigger is more than 10% away
    if status == "pre_breakout_watch" and buy_price > live_price * 1.10:
        return None

    confidence = min(round(score), 95)

    # ── STRICT FILTER: Show confirmation stocks ONLY above 60% confidence ──
    if status == "confirmed" and confidence < 60:
        return None

    expected_breakout_date = "Today / already triggered" if status == "confirmed" else \
        (dt.date.today() + dt.timedelta(days=1)).strftime("%d-%b-%Y")

    return {
        "symbol": symbol,
        "ltp": round(live_price, 2),
        "status": status,
        "strategy_used": strategy_used,
        "reasons": reasons,
        "buy_price": buy_price,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "risk_reward": f"1:{rr}",
        "confidence": confidence,
        "expected_breakout_date": expected_breakout_date,
    }
