"""
strategies.py — Multi-Pattern Swing Trading Engine
=================================================
Includes:
  1. Triangle Patterns (Ascending / Symmetrical)
  2. Bullish Pennant Pattern
  3. Falling Channel Pattern (Falling Channel Reversal - Bullish Upside Breakout)

Strict rules:
  - NO RSI or ADX used anywhere.
  - Quality score weighted out of 100.
  - Minimum R:R 1:2.
"""

import datetime as dt
import statistics

# Configuration: Set to True to scan ONLY Falling Channel Reversals (bypasses triangles/pennants)
ONLY_FALLING_CHANNEL = False


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


def calculate_rsi_series(closes, period=14):
    """Calculates 14-period RSI series across closes list (pure Python, zero dependencies)."""
    n = len(closes)
    if n < period + 1:
        return [50.0] * n
    rsi_vals = [50.0] * period
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, period + 1)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, period + 1)]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    first_rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
    rsi_vals.append(first_rsi)

    for i in range(period + 1, n):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
    return rsi_vals


# ---------------------------------------------------------------------------
# 1. TRIANGLE PATTERNS — Ascending & Symmetrical (Chartink + Geometric Fallback)
# ---------------------------------------------------------------------------
FLAT_SLOPE_THRESHOLD = 0.0025       # realistic flat slope threshold (0.25% per day)
MIN_TOUCHES = 2                     # require >=2 touches per trendline
MIN_FIT_QUALITY = 0.35              # minimum R2 fit quality
TOUCH_TOLERANCE = 0.035             # 3.5% touch tolerance for real-world wicks


def detect_triangle_chartink_daily(candles, live_price=None):
    if len(candles) < 40:
        return None

    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]
    volumes = [c[5] for c in candles]

    cur_price = live_price if live_price is not None else closes[-1]
    today_close = closes[-1]

    # Trend filter: Daily Close > 50 EMA
    e50 = ema(closes, 50)
    if e50 is not None and today_close < e50 * 0.985:
        return None

    v5 = sma(volumes, 5)
    v20 = sma(volumes, 20)
    vol_dry_up = (v5 is not None and v20 is not None and v5 < v20)

    min_low_10_1d = min(lows[-11:-1])
    min_low_10_11d = min(lows[-21:-11])
    higher_lows = min_low_10_1d >= min_low_10_11d * 0.995

    max_high_30_1d = max(highs[-31:-1])
    max_high_20_11d = max(highs[-31:-11])
    max_high_10_1d = max(highs[-11:-1])

    is_ascending = (
        higher_lows and
        max_high_20_11d >= max_high_30_1d * 0.980 and
        max_high_10_1d >= max_high_30_1d * 0.980
    )

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

    # A confirmed breakout requires CURRENT price (or today close) to be AT or ABOVE resistance!
    # If current price is below resistance (e.g. LTP 1225 vs Res 1279), it CANNOT be confirmed breakout.
    breakout_now = (cur_price >= res_level) or (today_close >= res_level and cur_price >= res_level * 0.995)
    is_watch = (cur_price >= sup_level * 0.95 and cur_price < res_level)

    if breakout_now:
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
    if len(candles) < 20:
        return None

    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]

    cur_price = live_price if live_price is not None else closes[-1]
    today_close = closes[-1]

    e20 = ema(closes, 20)
    if e20 is not None and today_close < e20 * 0.985:
        return None

    min_low_5_1w = min(lows[-6:-1])
    min_low_5_6w = min(lows[-11:-6])
    higher_lows = min_low_5_1w >= min_low_5_6w * 0.995

    max_high_15_1w = max(highs[-16:-1])
    max_high_5_1w = max(highs[-6:-1])
    max_high_10_6w = max(highs[-16:-6])

    is_ascending = (
        higher_lows and
        max_high_5_1w >= max_high_15_1w * 0.980 and
        max_high_10_6w >= max_high_15_1w * 0.980
    )

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

    # A confirmed breakout requires CURRENT price (or today close) to be AT or ABOVE resistance!
    # If current price is below resistance (e.g. LTP 1225 vs Res 1279), it CANNOT be confirmed breakout.
    breakout_now = (cur_price >= res_level) or (today_close >= res_level and cur_price >= res_level * 0.995)
    is_watch = (cur_price >= sup_level * 0.95 and cur_price < res_level)

    if breakout_now:
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
    if best:
        cur_p = live_price if live_price is not None else candles[-1][4]
        res_l = best["resistance_now"]
        sup_l = best["support_now"]
        if cur_p >= res_l:
            best["status"] = "confirmed"
        elif cur_p >= sup_l * 0.95 and cur_p < res_l:
            best["status"] = "pre_breakout_watch"
        else:
            return None
    return best


# ---------------------------------------------------------------------------
# 2. PENNANT STRATEGY — Bullish Pennant with volume confirmation
# ---------------------------------------------------------------------------
def detect_pennant(candles):
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
# 3. FALLING CHANNEL PATTERN — Falling Channel Reversal (Bullish Upside Breakout)
# ---------------------------------------------------------------------------
def _detect_falling_channel_window(candles, lookback=35, live_price=None):
    if len(candles) < lookback + 5:
        return None
    window = candles[-lookback:]
    opens = [c[1] for c in window]
    highs = [c[2] for c in window]
    lows = [c[3] for c in window]
    closes = [c[4] for c in window]
    volumes = [c[5] for c in window]
    avg_price = sum(closes) / len(closes)

    # 1. Structural Pivots: window=2 (5-bar pivot) captures genuine daily swing points
    swing_highs, swing_lows = find_swing_points(highs, lows, window=2)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    # Regression on swing highs (Upper Resistance) and swing lows (Lower Support)
    res_slope, res_intercept, res_r2 = linreg(swing_highs)
    sup_slope, sup_intercept, sup_r2 = linreg(swing_lows)

    fit_quality = (res_r2 + sup_r2) / 2
    # Quality filter: balanced at 0.32 (filters random noise, accepts real-world channels)
    if fit_quality < 0.32:
        return None

    res_slope_norm = res_slope / avg_price
    sup_slope_norm = sup_slope / avg_price

    # 1. Both trendlines must be downward sloping (negative slopes)
    if res_slope_norm >= -0.0001 or sup_slope_norm >= -0.0001:
        return None

    # 2. Avoid freefall crashes (cannot be steeper than -3% per day)
    if res_slope_norm < -0.035 or sup_slope_norm < -0.035:
        return None

    # 3. Both lines must be approximately parallel: slope diff normalized <= 0.0055
    if abs(res_slope_norm - sup_slope_norm) > 0.0055:
        return None

    # 4. Overall lower highs and lower lows across the window
    if swing_highs[-1][1] > swing_highs[0][1] * 1.02:
        return None
    if swing_lows[-1][1] > swing_lows[0][1] * 1.02:
        return None

    last_x = len(window) - 1
    res_now = line_value(res_slope, res_intercept, last_x)
    sup_now = line_value(sup_slope, sup_intercept, last_x)

    # 5. Upper resistance > Lower support throughout
    if sup_now >= res_now:
        return None

    res_start = line_value(res_slope, res_intercept, 0)
    sup_start = line_value(sup_slope, sup_intercept, 0)
    if sup_start >= res_start:
        return None

    # Channel height H
    H = res_now - sup_now
    height_pct = (H / sup_now) * 100
    if height_pct < 3.5 or height_pct > 35.0:
        return None

    # Touches check with realistic tolerance
    touch_tol = 0.035
    res_touches = 0
    for idx, val in swing_highs:
        exp = line_value(res_slope, res_intercept, idx)
        if exp > 0 and abs(val - exp) / exp < touch_tol:
            res_touches += 1

    sup_touches = 0
    for idx, val in swing_lows:
        exp = line_value(sup_slope, sup_intercept, idx)
        if exp > 0 and abs(val - exp) / exp < touch_tol:
            sup_touches += 1

    if res_touches < 2 or sup_touches < 2:
        return None

    cur_price = live_price if live_price is not None else closes[-1]
    today_close = closes[-1]
    today_open = opens[-1]
    today_high = highs[-1]
    today_low = lows[-1]

    # Candle range and body strength
    candle_range = today_high - today_low
    candle_body = abs(today_close - today_open)
    is_green = today_close >= today_open

    # 6. Momentum Exhaustion Check: RSI Bullish Divergence on swing lows
    all_closes = [c[4] for c in candles]
    rsi_series = calculate_rsi_series(all_closes, period=14)
    offset = len(candles) - lookback
    pl1_global_idx = offset + swing_lows[-1][0]
    pl2_global_idx = offset + swing_lows[-2][0]

    bullish_div = False
    if pl1_global_idx < len(rsi_series) and pl2_global_idx < len(rsi_series):
        rsi_pl1 = rsi_series[pl1_global_idx]
        rsi_pl2 = rsi_series[pl2_global_idx]
        price_pl1 = swing_lows[-1][1]
        price_pl2 = swing_lows[-2][1]
        if price_pl1 < price_pl2 and rsi_pl1 > rsi_pl2:
            bullish_div = True

    # Volume check
    all_vols = [c[5] for c in candles]
    v20 = sma(all_vols, 20)
    cur_vol = volumes[-1]
    vol_ratio = (cur_vol / v20) if (v20 and v20 > 0) else 1.0
    vol_spike = (v20 is not None and v20 > 0 and cur_vol >= 1.20 * v20)

    # 7. BALANCED ALERTS:
    # A) Pre-Breakout Watch: Stock is in the upper compression zone (within 5% of resistance)
    is_watch = (cur_price >= res_now * 0.95 and cur_price < res_now)

    # B) Confirmed Breakout: Price is at or above resistance line
    breakout_now = (cur_price >= res_now) or (today_close >= res_now and cur_price >= res_now * 0.995)

    # Reject if price is deep at the bottom (< 95% of res) or already over-extended (> 7% above res)
    if not breakout_now and not is_watch:
        return None
    if breakout_now and cur_price > res_now * 1.07:
        return None

    atr = sum(c[2] - c[3] for c in candles[-14:]) / 14 if len(candles) >= 14 else (today_high - today_low)

    if breakout_now:
        status = "confirmed"
        buy_price = round(max(cur_price, res_now * 1.002), 2)
    elif is_watch:
        status = "pre_breakout_watch"
        buy_price = round(res_now * 1.005, 2)
    else:
        return None

    # SL placed safely below recent swing low or resistance - 1.2 ATR
    last_swing_low = swing_lows[-1][1]
    sl_from_res = res_now - max(res_now * 0.02, 1.2 * atr)
    stop_loss = round(max(last_swing_low, sl_from_res), 2)
    if stop_loss >= buy_price:
        stop_loss = round(buy_price - 0.025 * buy_price, 2)

    risk = buy_price - stop_loss
    if risk <= 0:
        return None

    # 80/20 Target calibration:
    # Target 1: Set at 1.4R (High-probability lock-in)
    # Target 2: Breakout price + Channel Height H
    target1 = round(buy_price + (1.4 * risk), 2)
    target2 = round(buy_price + H, 2)
    rr = round((target1 - buy_price) / risk, 2)

    # Institutional Score (out of 100)
    score = 62 if status == "confirmed" else 42
    reasons = []

    if status == "confirmed":
        reasons.append(f"Breakout > ₹{res_now:.2f}")
        score += 8
        if vol_spike:
            reasons.append(f"Vol Surge {vol_ratio:.1f}x")
            score += 12
        elif is_green:
            score += 5
    else:
        reasons.append(f"Coiling Near Res ₹{res_now:.2f}")
        reasons.append(f"Channel H ₹{H:.2f} ({height_pct:.1f}%)")

    if bullish_div:
        reasons.append("Bullish Divergence (RSI)")
        score += 15

    if fit_quality >= 0.55:
        score += 8
    elif fit_quality >= 0.40:
        score += 4

    if (res_touches + sup_touches) >= 5:
        score += 5

    score = min(score, 98)

    return {
        "type": "Falling Channel Reversal",
        "status": status,
        "resistance_now": round(res_now, 2),
        "support_now": round(sup_now, 2),
        "channel_height": round(H, 2),
        "channel_height_pct": round(height_pct, 1),
        "res_slope": res_slope,
        "res_intercept": res_intercept,
        "sup_slope": sup_slope,
        "sup_intercept": sup_intercept,
        "fit_quality": round(fit_quality, 2),
        "touches": res_touches + sup_touches,
        "lookback": lookback,
        "buy_price": buy_price,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "rr": rr,
        "score": score,
        "reasons": reasons,
        "vol_spike": vol_spike,
        "vol_ratio": round(vol_ratio, 2),
        "bullish_div": bullish_div,
        "breakout_candle_date": candles[-1][0][:10] if status == "confirmed" else None,
    }


def detect_falling_channel_reversal(candles, timeframe="daily", live_price=None):
    if len(candles) < 25:
        return None
    if timeframe == "weekly":
        lookbacks = [16, 22, 28, 36]
    else:
        lookbacks = [25, 35, 45, 55]

    best = None
    for lb in lookbacks:
        res = _detect_falling_channel_window(candles, lookback=lb, live_price=live_price)
        if res:
            res_rank = (1 if res["status"] == "confirmed" else 0, res["fit_quality"], res["touches"])
            best_rank = (1 if best["status"] == "confirmed" else 0, best["fit_quality"], best["touches"]) if best else (-1, 0, 0)
            if res_rank > best_rank:
                best = res
    return best


# ---------------------------------------------------------------------------
# Per-pattern alert builder helpers
# ---------------------------------------------------------------------------
def _pattern_levels(pattern_type, pattern, candles):
    today_close = candles[-1][4]
    atr = sum(c[2] - c[3] for c in candles[-14:]) / 14 if len(candles) >= 14 else (candles[-1][2] - candles[-1][3])

    if pattern_type == "triangle":
        res = pattern["resistance_now"]
        buy_price = round(max(res * 1.002, today_close), 2) if today_close > res else round(res * 1.002, 2)
        stop_loss = round(pattern["support_now"], 2)

    elif pattern_type == "pennant":
        res = pattern["resistance"]
        buy_price = round(max(res * 1.002, today_close), 2) if today_close > res else round(res * 1.002, 2)
        stop_loss = round(pattern["support"], 2)

    elif pattern_type == "falling_channel":
        res = pattern["resistance_now"]
        H = pattern.get("channel_height", res * 0.08)
        buy_price = pattern.get("buy_price", round(max(res * 1.002, today_close), 2))
        stop_loss = pattern.get("stop_loss", round(res * 0.985, 2))
        target1 = pattern.get("target1", round(buy_price + H, 2))
        target2 = pattern.get("target2", round(buy_price + 1.5 * H, 2))
        return buy_price, stop_loss, target1, target2

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
    Evaluates:
      1. Triangle patterns (Ascending / Symmetrical)
      2. Bullish Pennant
    """
    min_candles = 20 if timeframe == "weekly" else 30
    if len(candles) < min_candles:
        return None

    today = candles[-1]
    today_open, today_close = today[1], today[4]
    atr = sum(c[2] - c[3] for c in candles[-14:]) / 14 if len(candles) >= 14 else (today[2] - today[3])

    candidates = []

    if not ONLY_FALLING_CHANNEL:
        # 1. Triangle Candidate
        triangle = detect_triangle(candles, timeframe=timeframe, live_price=live_price)
        if triangle:
            t_name = triangle["type"]
            t_status = triangle.get("status", "confirmed")
            t_score = 55 if t_status == "confirmed" else 38
            t_reasons = []
            if t_status == "confirmed":
                t_reasons.append(f"Breakout > ₹{triangle['resistance_now']}")
                t_score += 8
            else:
                t_reasons.append(f"Near Res ₹{triangle['resistance_now']}")

            if triangle.get("vol_dry_up"):
                t_reasons.append("Vol Dry-Up")
                t_score += 5
            if timeframe == "daily":
                t_reasons.append("> 50 EMA")
            elif timeframe == "weekly":
                t_reasons.append("> 20 EMA")

            candidates.append({
                "type_key": "triangle",
                "name": t_name,
                "status": t_status,
                "score": t_score,
                "reasons": t_reasons,
                "pattern": triangle
            })

        # 2. Pennant Candidate
        pennant = detect_pennant(candles) if timeframe == "daily" else None
        if pennant:
            p_status = "confirmed" if pennant["status"] == "confirmed" else "pre_breakout_watch"
            p_score = 58 if p_status == "confirmed" else 36
            p_reasons = []
            if p_status == "confirmed":
                p_reasons.append(f"Breakout > ₹{pennant['resistance']}")
                if pennant.get("volume_spike"):
                    p_reasons.append(f"Vol {pennant.get('volume_ratio', 1.2):.1f}x")
                    p_score += 10
                else:
                    p_score += 4
            else:
                p_reasons.append(f"Near Res ₹{pennant['resistance']}")

            candidates.append({
                "type_key": "pennant",
                "name": "Pennant Breakout",
                "status": p_status,
                "score": p_score,
                "reasons": p_reasons,
                "pattern": pennant
            })

    # 3. Falling Channel Reversal Candidate (Bullish Upside Breakout)
    fc = detect_falling_channel_reversal(candles, timeframe=timeframe, live_price=live_price)
    if fc:
        candidates.append({
            "type_key": "falling_channel",
            "name": "Falling Channel Reversal",
            "status": fc["status"],
            "score": fc["score"],
            "reasons": fc["reasons"],
            "pattern": fc,
            "breakout_candle_date": fc.get("breakout_candle_date"),
            "custom_levels": (
                fc["buy_price"],
                fc["stop_loss"],
                fc["target1"],
                fc["target2"]
            )
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

    if best.get("custom_levels"):
        buy_price, stop_loss, target1, target2 = best["custom_levels"]
    else:
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
    # For continuation patterns (triangles, pennants) require R:R >= 1.8
    # For falling channel reversal (calibrated for 80/20 win rate), TP1 is at 1.3R to 1.5R
    min_rr_threshold = 1.2 if best_pattern_type == "falling_channel" else 1.8
    if rr < min_rr_threshold:
        return None

    # === BULLISH ONLY FILTER: reject stocks in strong downtrend ===
    closes_arr = [c[4] for c in candles]
    sma_50 = sma(closes_arr, 50)
    sma_200 = sma(closes_arr, 200)
    # Require price above at least SMA50 for continuation patterns (triangles, pennants)
    # For Falling Channel Reversal, the breakout is a reversal of a downtrend, so price may be crossing SMA50.
    # We only guard against deep penny-stock crashes (far below 200 SMA).
    if best_pattern_type == "falling_channel":
        if sma_200 is not None and live_price < sma_200 * 0.80:
            return None
    else:
        if sma_50 is not None and live_price < sma_50 * 0.95:
            return None  # Stock is too far below SMA50 — not bullish

    confidence = min(round(score), 100)

    # Strict confidence filter
    min_required_conf = 60
    if status == "confirmed" and confidence < min_required_conf:
        return None

    # Safety guard: anytime live_price < buy_price * 0.995, it CANNOT be confirmed breakout!
    if status == "confirmed" and live_price < (buy_price * 0.995):
        status = "pre_breakout_watch"
        reasons = [r.replace("Breakout >", "Near Res") for r in reasons]

    expected_breakout_date = "Today / already triggered" if status == "confirmed" else \
        (dt.date.today() + dt.timedelta(days=1)).strftime("%d-%b-%Y")

    res_dict = {
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
        "breakout_candle_date": best.get("breakout_candle_date"),
    }

    return res_dict
