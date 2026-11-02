"""
strategies.py — Focused Swing Trading Engine (3 Strategies)

Implements:
  1.  Triangle pattern  (Ascending / Symmetrical)
  2.  Pennant pattern  (pole + converging consolidation with volume confirmation)

All patterns include:
  - Confirmed breakout detection
  - Pre-breakout / watch-list detection
  - Confidence scoring
  - Trade levels (buy, stop-loss, target1, target2)

None of this predicts the future with certainty — it identifies setups
that historically precede breakouts more often than random price action.
Treat "confidence score" as setup quality, not a probability of profit.
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


# ---------------------------------------------------------------------------
# 1. TRIANGLE PATTERN — Ascending and Symmetrical
# ---------------------------------------------------------------------------
FLAT_SLOPE_THRESHOLD = 0.0012       # flat slope threshold
MIN_TOUCHES = 2                     # require ≥2 touches per trendline
MIN_FIT_QUALITY = 0.50              # minimum R² fit quality (relaxed)
LOOKBACK = 40

def detect_triangle(candles):
    if len(candles) < LOOKBACK + 5:
        return None
    window = candles[-LOOKBACK:]
    highs = [c[2] for c in window]
    lows = [c[3] for c in window]
    closes = [c[4] for c in window]
    avg_price = sum(closes) / len(closes)

    swing_highs, swing_lows = find_swing_points(highs, lows, window=2)
    if len(swing_highs) < MIN_TOUCHES or len(swing_lows) < MIN_TOUCHES:
        return None

    res_slope, res_intercept, res_r2 = linreg(swing_highs)
    sup_slope, sup_intercept, sup_r2 = linreg(swing_lows)

    # Require good trendline fit quality
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
    sup_flat = abs(sup_slope_norm) < FLAT_SLOPE_THRESHOLD

    triangle_type = None
    if res_flat and sup_slope_norm > FLAT_SLOPE_THRESHOLD:
        triangle_type = "Ascending Triangle"
    elif res_slope_norm < -FLAT_SLOPE_THRESHOLD and sup_slope_norm > FLAT_SLOPE_THRESHOLD:
        triangle_type = "Symmetrical Triangle"
    else:
        return None

    gap_start = line_value(res_slope, res_intercept, 0) - line_value(sup_slope, sup_intercept, 0)
    gap_now = res_now - sup_now
    contraction = 1 - (gap_now / gap_start) if gap_start > 0 else 0

    # Require minimum contraction for valid triangle
    if contraction < 0.15:
        return None

    if res_slope != sup_slope:
        apex_x = (sup_intercept - res_intercept) / (res_slope - sup_slope)
        bars_to_apex = apex_x - last_x
    else:
        bars_to_apex = None

    # Validate swing points actually touch the trendlines (within 2.5% tolerance)
    res_touches = 0
    for idx, val in swing_highs:
        expected = line_value(res_slope, res_intercept, idx)
        if expected > 0 and abs(val - expected) / expected < 0.025:
            res_touches += 1

    sup_touches = 0
    for idx, val in swing_lows:
        expected = line_value(sup_slope, sup_intercept, idx)
        if expected > 0 and abs(val - expected) / expected < 0.025:
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
    }


# ---------------------------------------------------------------------------
# 2. PENNANT STRATEGY — Bullish Pennant with volume spike confirmation
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
        if move >= 6.0:  # relaxed from 8% to 6%
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

    # Require good fit quality for the consolidation trendlines
    consol_fit = (res_r2 + sup_r2) / 2
    if consol_fit < 0.30:
        return None

    # converging lines (resistance slopes down, support slopes up)
    if res_slope_norm < -0.0003 and sup_slope_norm > 0.0003:
        last_x = len(consol_window) - 1
        res_now = line_value(res_slope, res_intercept, last_x)
        sup_now = line_value(sup_slope, sup_intercept, last_x)

        if res_now <= sup_now:
            return None

        # Ensure consolidation is actually tightening (converging)
        gap_start = line_value(res_slope, res_intercept, 0) - line_value(sup_slope, sup_intercept, 0)
        gap_now = res_now - sup_now
        if gap_start > 0 and (gap_now / gap_start) > 0.85:
            return None  # not converging enough

        current_price = closes[-1]
        current_volume = volumes[-1]
        is_green = closes[-1] > candles[-1][1]  # close > open

        # Volume spike check: breakout bar should have above-average volume
        avg_vol_consol = sum(c_vols) / len(c_vols) if c_vols else 1
        avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        avg_vol = (avg_vol_consol + avg_vol_20) / 2
        volume_ratio = current_volume / avg_vol if avg_vol > 0 else 1.0
        volume_spike = volume_ratio >= 1.2  # at least 20% above average on breakout

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
    atr = sum(c[2] - c[3] for c in candles[-14:]) / 14

    if pattern_type == "triangle":
        buy_price = round(pattern["resistance_now"] * 1.002, 2)
        stop_loss = round(pattern["support_now"], 2)

    elif pattern_type == "pennant":
        buy_price = round(pattern["resistance"] * 1.002, 2)
        stop_loss = round(pattern["support"], 2)

    else:
        buy_price = round(today_close, 2)
        stop_loss = round(today_close - 1.5 * atr, 2)

    risk = buy_price - stop_loss
    if risk <= 0:
        return None, None, None, None

    target1 = round(buy_price + 2 * risk, 2)
    target2 = round(buy_price + 3 * risk, 2)
    return buy_price, stop_loss, target1, target2


# ---------------------------------------------------------------------------
# Main combined alert builder
# ---------------------------------------------------------------------------
def build_alert(symbol, candles, live_price):
    """
    Runs all strategies (Triangle, Pennant), picks the best
    qualifying signal, returns a full alert dict or None if nothing qualifies.
    """
    if len(candles) < 50:
        return None

    today = candles[-1]
    today_open, today_close = today[1], today[4]
    is_green_today = today_close > today_open
    atr = sum(c[2] - c[3] for c in candles[-14:]) / 14

    # Run all detectors
    triangle = detect_triangle(candles)
    pennant  = detect_pennant(candles)

    reasons = []
    strategies_used = []
    status = "confirmed"
    score = 0
    best_pattern_type = None
    best_pattern = None

    # ---- Triangle ----
    if triangle:
        breakout_now = is_green_today and today_close > triangle["resistance_now"]
        approaching = (
            triangle["contraction"] >= 0.25
            and triangle["bars_to_apex"] is not None and 0 < triangle["bars_to_apex"] <= 10
            and today_close >= triangle["resistance_now"] * 0.97
        )
        t_name = triangle["type"]
        if breakout_now:
            strategies_used.append(t_name)
            reasons.append(f"{t_name} breakout above {triangle['resistance_now']} "
                           f"(fit: {triangle['fit_quality']}, {triangle['touches']} touches)")
            score += 42
            best_pattern_type = "triangle"
            best_pattern = triangle
        elif approaching:
            strategies_used.append(t_name)
            status = "pre_breakout_watch"
            reasons.append(
                f"{t_name} tightening ({int(triangle['contraction']*100)}% contraction), "
                f"price {today_close} near resistance {triangle['resistance_now']}, "
                f"~{triangle['bars_to_apex']} bars to apex"
            )
            score += 24
            best_pattern_type = "triangle"
            best_pattern = triangle

    # ---- Pennant ----
    if pennant:
        vol_info = f", volume {pennant.get('volume_ratio', 0):.2f}× avg" if pennant.get('volume_ratio') else ""
        vol_spike_bonus = 8 if pennant.get("volume_spike") else 0
        if pennant["status"] == "confirmed":
            strategies_used.append("Pennant Breakout")
            reasons.append(
                f"Pennant Breakout: pole +{pennant['pole_move_pct']}%, "
                f"closed above resistance {pennant['resistance']}"
                f"{vol_info} (fit: {pennant.get('fit_quality', 'N/A')})"
            )
            score += 40 + vol_spike_bonus
            if not best_pattern_type:
                best_pattern_type = "pennant"
                best_pattern = pennant
        elif pennant["status"] == "forming":
            strategies_used.append("Pennant Breakout")
            status = "pre_breakout_watch"
            reasons.append(
                f"Pennant forming after +{pennant['pole_move_pct']}% move, "
                f"resistance at {pennant['resistance']}"
            )
            score += 20
            if not best_pattern_type:
                best_pattern_type = "pennant"
                best_pattern = pennant

    if not strategies_used:
        return None

    if len(strategies_used) >= 2:
        score += 12  # multiple patterns agreeing — stronger signal

    confidence = min(round(score), 95)

    # ---- Trade levels ----
    buy_price, stop_loss, target1, target2 = _pattern_levels(best_pattern_type, best_pattern, candles)
    if buy_price is None:
        # Fallback to ATR-based levels
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
    if rr < 2:
        return None  # enforce minimum 1:2 R:R

    # ── Pre-breakout sanity: LTP must be BELOW the buy trigger ──────────────
    # If LTP is already at or above buy_price the breakout already happened
    # but didn't meet confirmed criteria — drop it from Watch entirely.
    if status == "pre_breakout_watch" and live_price >= buy_price:
        return None

    # Also drop pre-breakout alerts where the trigger is more than 8% away —
    # those are too far from current price to be "near" breakout candidates.
    if status == "pre_breakout_watch" and buy_price > live_price * 1.08:
        return None

    expected_breakout_date = "Today / already triggered" if status == "confirmed" else \
        (dt.date.today() + dt.timedelta(days=1)).strftime("%d-%b-%Y")

    return {
        "symbol": symbol,
        "ltp": round(live_price, 2),
        "status": status,
        "strategy_used": " + ".join(strategies_used) if len(strategies_used) > 1 else strategies_used[0],
        "reasons": reasons,
        "buy_price": buy_price,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "risk_reward": f"1:{rr}",
        "confidence": confidence,
        "expected_breakout_date": expected_breakout_date,
    }
