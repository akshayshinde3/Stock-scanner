"""
strategies.py — 44 MA Touch & Near Scanner + Symmetrical & Ascending Triangle Breakouts
======================================================================================
Strict Rules & Strategy Definitions:
1. 44 MA TOUCH & NEAR SCANNER (Daily & Weekly):
   - MA44: 44-period simple moving average of Close on that timeframe.
   - Distance %: (Close - MA44) / MA44 * 100
   - TOUCH: Low <= MA44 <= High
   - NEAR_BELOW: Close < MA44 AND Distance % >= -B (default B = 3%, adjustable)
   - ABOVE_ZONE: Close >= MA44 AND Distance % <= +A (default A = 2%, adjustable)
   - Status: 1. "Touching" (Blue), 2. "Above (0-2%)" (Green), 3. "Near Below" (Orange)
   - Rising MA: Today's MA44 > MA44 5 bars ago
   - Green Candle: Close > Open

2. ASCENDING TRIANGLE PATTERN:
   - Horizontal upper resistance with multiple touches (2-3+ touches around same level)
   - Rising lower support line connecting higher swing lows
   - Breakout Entry (direct on breakout close with volume)
   - Pullback / Retest Entry (on retest of broken resistance)
   - Stop-Loss: below breakout candle or last swing low (direct) / below retest low (pullback)
   - Target: Breakout level + Height of triangle (B - A)
   - Minimum Risk:Reward: 1:3

3. SYMMETRICAL TRIANGLE PATTERN:
   - Converging trendlines: upper descending (lower highs) and lower ascending (higher lows)
   - Volume dry-up during consolidation
   - Breakout confirmation with volume expansion
   - Stop-Loss: below breakout point / trendline
   - Target: Breakout level + Height of widest part of the triangle (base)
   - Minimum Risk:Reward: 1:2.5 to 1:3
"""

import math
import statistics
import datetime as dt
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════
# 1. 44 MA TOUCH & NEAR ENGINE (Discrete Named Functions)
# ═══════════════════════════════════════════════════════════════════════════

def calculate_ma44(closes: list) -> list:
    """Calculates 44-period Simple Moving Average of Close series."""
    if len(closes) < 44:
        return [None] * len(closes)
    
    # Use pandas rolling for speed and precision
    s = pd.Series(closes)
    ma = s.rolling(window=44).mean()
    return [None if pd.isna(v) else round(float(v), 2) for v in ma]


def is_touch(low: float, high: float, ma44: float) -> bool:
    """TOUCH = Low <= MA44 <= High"""
    if ma44 is None or low is None or high is None:
        return False
    return low <= ma44 <= high


def is_near_below(close: float, ma44: float, dist_pct: float, max_below_b: float = 3.0) -> bool:
    """NEAR_BELOW = Close < MA44 AND Distance % >= -B (e.g. -3.0%)"""
    if ma44 is None or close is None or dist_pct is None:
        return False
    return close < ma44 and dist_pct >= -abs(max_below_b)


def is_above_zone(close: float, ma44: float, dist_pct: float, max_above_a: float = 2.0) -> bool:
    """ABOVE_ZONE = Close >= MA44 AND Distance % <= +A (e.g. +2.0%)"""
    if ma44 is None or close is None or dist_pct is None:
        return False
    return close >= ma44 and dist_pct <= abs(max_above_a)


def get_status(touch: bool, above_zone: bool, near_below: bool, max_above_a: float = 2.0) -> str:
    """
    Status label, first match wins:
      1. 'Touching' (TOUCH)
      2. 'Above (0-A%)' (ABOVE_ZONE)
      3. 'Near Below' (NEAR_BELOW)
    """
    if touch:
        return "Touching"
    if above_zone:
        pct_str = f"0-{int(max_above_a)}%" if max_above_a == int(max_above_a) else f"0-{max_above_a:.1f}%"
        return f"Above ({pct_str})"
    if near_below:
        return "Near Below"
    return "Excluded"


def is_ma44_rising(ma44_series: list, bars_back: int = 5) -> bool:
    """MA44 rising only: today's MA44 > MA44 5 bars ago"""
    if len(ma44_series) <= bars_back:
        return False
    current_ma = ma44_series[-1]
    past_ma = ma44_series[-(bars_back + 1)]
    if current_ma is None or past_ma is None:
        return False
    return current_ma > past_ma


def is_green_candle(open_price: float, close_price: float) -> bool:
    """Green candle only: Close > Open"""
    if open_price is None or close_price is None:
        return False
    return close_price > open_price


def analyze_44ma_timeframe(candles: list, max_above_a: float = 2.0, max_below_b: float = 3.0) -> dict:
    """
    Analyzes a candle series for 44 MA Touch & Near conditions.
    Candles structure: [date, open, high, low, close, volume]
    """
    if not candles or len(candles) < 45:
        return None

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    opens = [c[1] for c in candles]
    volumes = [c[5] for c in candles]

    ma_series = calculate_ma44(closes)
    current_ma = ma_series[-1]
    if current_ma is None:
        return None

    cur_close = closes[-1]
    cur_open = opens[-1]
    cur_high = highs[-1]
    cur_low = lows[-1]
    cur_vol = volumes[-1]

    # Distance % = (Close - MA44) / MA44 * 100
    dist_pct = round(((cur_close - current_ma) / current_ma) * 100, 2)

    # Core Rule Evaluations
    touch = is_touch(cur_low, cur_high, current_ma)
    near_bel = is_near_below(cur_close, current_ma, dist_pct, max_below_b)
    above_z = is_above_zone(cur_close, current_ma, dist_pct, max_above_a)

    # Qualification check: TOUCH or NEAR_BELOW or ABOVE_ZONE is true
    # Stocks more than A% above the MA44 are strictly excluded.
    qualifies = (touch or near_bel or above_z) and (dist_pct <= abs(max_above_a))
    if not qualifies:
        return None

    status_label = get_status(touch, above_z, near_bel, max_above_a)
    ma_rising = is_ma44_rising(ma_series, bars_back=5)
    green_candle = is_green_candle(cur_open, cur_close)

    # Day change %
    prev_close = closes[-2] if len(closes) >= 2 else cur_open
    day_change_pct = round(((cur_close - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

    # Weekly volume: sum of last 5 daily volumes (or current weekly bar volume)
    recent_vol = sum(volumes[-5:]) if len(volumes) >= 5 else sum(volumes)

    # Sparkline prices (last 12 closes normalized for sparkline visualization)
    sparkline = [round(c, 2) for c in closes[-12:]]

    is_confirmed_signal = (touch or above_z)
    is_watch_signal = near_bel

    return {
        "cmp": round(cur_close, 2),
        "ma44": round(current_ma, 2),
        "distance_pct": dist_pct,
        "status": status_label,
        "is_confirmed": is_confirmed_signal,
        "is_watch": is_watch_signal,
        "touch_candle_date": candles[-1][0] if touch else None,
        "day_change_pct": day_change_pct,
        "volume": int(cur_vol),
        "weekly_volume": int(recent_vol),
        "ma44_rising": ma_rising,
        "green_candle": green_candle,
        "sparkline": sparkline,
    }


def evaluate_44ma_stock(
    symbol: str,
    company_name: str,
    daily_candles: list,
    weekly_candles: list,
    max_above_a: float = 2.0,
    max_below_b: float = 3.0,
    min_price: float = 0.0,
    min_weekly_vol: int = 100000,
    rising_only: bool = False,
    green_only: bool = False,
) -> dict:
    """
    Evaluates both Daily and Weekly for the 44 MA Touch & Near conditions.
    Returns qualification status for 'Daily', 'Weekly', or 'Both'.
    """
    d_res = analyze_44ma_timeframe(daily_candles, max_above_a, max_below_b) if daily_candles else None
    w_res = analyze_44ma_timeframe(weekly_candles, max_above_a, max_below_b) if weekly_candles else None

    # Filter checks (Min price & Min weekly volume)
    cmp_price = d_res["cmp"] if d_res else (w_res["cmp"] if w_res else 0)
    if min_price > 0 and cmp_price < min_price:
        return None

    vol_check = (d_res["weekly_volume"] if d_res else 0) or (w_res["volume"] if w_res else 0)
    if min_weekly_vol > 0 and vol_check < min_weekly_vol:
        return None

    # Filter checks (Rising MA & Green Candle)
    d_qualifies = d_res is not None
    if d_qualifies:
        if rising_only and not d_res["ma44_rising"]:
            d_qualifies = False
        if green_only and not d_res["green_candle"]:
            d_qualifies = False

    w_qualifies = w_res is not None
    if w_qualifies:
        if rising_only and not w_res["ma44_rising"]:
            w_qualifies = False
        if green_only and not w_res["green_candle"]:
            w_qualifies = False

    if not d_qualifies and not w_qualifies:
        return None

    timeframe_badge = "Both" if (d_qualifies and w_qualifies) else ("Daily" if d_qualifies else "Weekly")
    primary = d_res if d_qualifies else w_res

    return {
        "symbol": symbol,
        "company": company_name,
        "cmp": primary["cmp"],
        "ma44": primary["ma44"],
        "distance_pct": primary["distance_pct"],
        "status": primary["status"],
        "is_confirmed": primary.get("is_confirmed", False),
        "is_watch": primary.get("is_watch", False),
        "touch_candle_date": primary.get("touch_candle_date"),
        "day_change_pct": primary["day_change_pct"],
        "volume": primary["volume"],
        "timeframe": timeframe_badge,
        "sparkline": primary["sparkline"],
        "daily_data": d_res if d_qualifies else None,
        "weekly_data": w_res if w_qualifies else None,
        "abs_distance": abs(primary["distance_pct"]),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. ASCENDING & SYMMETRICAL TRIANGLE PATTERN ENGINES
# ═══════════════════════════════════════════════════════════════════════════

def find_swings(highs: list, lows: list, window: int = 2):
    """Finds swing highs and swing lows."""
    sh, sl = [], []
    n = len(highs)
    for i in range(window, n - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            sh.append((i, highs[i]))
        if lows[i] == min(lows[i - window : i + window + 1]):
            sl.append((i, lows[i]))
    return sh, sl


def linreg(points: list):
    """Linear regression over (index, price) points."""
    n = len(points)
    if n < 2:
        return 0.0, (points[0][1] if points else 0.0), 0.0
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
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, intercept, max(0.0, min(1.0, r2))


def detect_ascending_triangle(symbol: str, company: str, candles: list, timeframe: str = "daily") -> dict:
    """
    Ascending Triangle Pattern:
      1. Strong prior uptrend or base
      2. Flat horizontal upper resistance zone (multiple touches, e.g. 2-3 touches)
      3. Rising lower support trendline (higher lows)
      4. Breakout Entry (direct on breakout with volume) OR Retest Entry (on retest of broken resistance)
      5. Target = Breakout price + Height of triangle (B - A)
      6. Stop-Loss = Below breakout candle / last swing low (Direct) or below retest low (Pullback)
      7. Risk to Reward Ratio = Minimum 1:3
    """
    if len(candles) < 30:
        return None

    # Test lookbacks
    best_pattern = None
    for lb in [25, 35, 45, 60]:
        if len(candles) < lb:
            continue
        window = candles[-lb:]
        highs = [c[2] for c in window]
        lows = [c[3] for c in window]
        closes = [c[4] for c in window]
        volumes = [c[5] for c in window]
        n = len(window)

        sh, sl = find_swings(highs, lows, window=2)
        if len(sh) < 2 or len(sl) < 2:
            continue

        # Resistance line: Flat horizontal upper line
        # Peak prices should be clustered tightly (within 1.8% of each other)
        peak_prices = [p[1] for p in sh]
        res_level = sum(peak_prices) / len(peak_prices)
        res_dispersion = max(peak_prices) - min(peak_prices)
        if (res_dispersion / res_level) > 0.025:
            continue  # Peaks not flat enough for ascending triangle

        # Support line: Rising lower trendline (higher lows)
        sup_slope, sup_intercept, sup_r2 = linreg(sl)
        avg_price = sum(closes) / n
        sup_slope_norm = sup_slope / avg_price

        # Lower slope must be clearly rising (+0.0004 or more)
        if sup_slope_norm <= 0.0003 or sup_r2 < 0.35:
            continue

        # Touch count on resistance: within 1.5% of resistance level
        res_touches = sum(1 for h in highs if abs(h - res_level) / res_level <= 0.015)
        if res_touches < 2:
            continue

        # Triangle base height (earliest high B - earliest swing low A)
        triangle_height = res_level - sl[0][1]
        if triangle_height <= 0 or (triangle_height / res_level) < 0.03:
            continue

        cur_close = closes[-1]
        cur_vol = volumes[-1]
        v_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        vol_surge = (cur_vol >= 1.2 * v_avg) if v_avg > 0 else False

        # Status: Breakout vs Retest vs Forming (Watchlist)
        # Breakout Entry: Price has crossed resistance (+0.2% to +2.5%)
        # Retest Entry: Price broke out and is retesting the broken resistance (res_level - 0.5% to +0.8%)
        # Pre-breakout watch: Price is coiling right below resistance (within 2% below resistance)
        status = None
        entry_type = None
        buy_price = round(res_level * 1.002, 2)
        last_swing_low = sl[-1][1]

        if cur_close >= buy_price and cur_close <= buy_price * 1.025:
            status = "Confirmed Breakout"
            entry_type = "Direct Breakout Entry"
            stop_loss = round(min(last_swing_low, cur_close * 0.975), 2)
        elif abs(cur_close - res_level) / res_level <= 0.008 and min(lows[-3:]) <= res_level * 1.005:
            status = "Confirmed Retest"
            entry_type = "Pullback / Retest Entry"
            retest_low = min(lows[-3:])
            stop_loss = round(retest_low * 0.992, 2)
        elif cur_close >= res_level * 0.970 and cur_close < buy_price:
            status = "Pre-Breakout Watch"
            entry_type = "Anticipatory Setup"
            stop_loss = round(last_swing_low * 0.99, 2)
        else:
            continue

        # Risk & Target (Target = Buy Price + Triangle Height)
        # Ensure 1:3 R:R maintained as per educational specs
        risk = buy_price - stop_loss
        if risk <= 0:
            stop_loss = round(buy_price * 0.965, 2)
            risk = buy_price - stop_loss

        target = round(buy_price + max(triangle_height, 3.0 * risk), 2)
        rr = round((target - buy_price) / risk, 2) if risk > 0 else 3.0

        if rr < 2.5:
            continue  # Minimum strict R:R requirement

        pattern_score = 75
        if res_touches >= 3:
            pattern_score += 10
        if vol_surge:
            pattern_score += 10

        # Construct trendline points for chart overlay
        sup_start_val = sup_slope * 0 + sup_intercept
        sup_end_val = sup_slope * (n - 1) + sup_intercept
        res_line = [
            {"time": window[0][0], "value": round(res_level, 2)},
            {"time": window[-1][0], "value": round(res_level, 2)}
        ]
        sup_line = [
            {"time": window[0][0], "value": round(sup_start_val, 2)},
            {"time": window[-1][0], "value": round(sup_end_val, 2)}
        ]
        breakout_candle_date = window[-1][0] if ("Confirmed" in status) else None

        res_obj = {
            "symbol": symbol,
            "company": company,
            "pattern": "Ascending Triangle",
            "status": status,
            "entry_type": entry_type,
            "cmp": round(cur_close, 2),
            "resistance_level": round(res_level, 2),
            "support_level": round(last_swing_low, 2),
            "buy_price": buy_price,
            "stop_loss": stop_loss,
            "target": target,
            "risk_reward": f"1:{rr}",
            "touches": res_touches,
            "triangle_height": round(triangle_height, 2),
            "timeframe": timeframe.capitalize(),
            "confidence": min(98, pattern_score),
            "sparkline": [round(c, 2) for c in closes[-12:]],
            "abs_distance": abs(round(((cur_close - res_level) / res_level) * 100, 2)),
            "resistance_line": res_line,
            "support_line": sup_line,
            "breakout_candle_date": breakout_candle_date,
        }

        if not best_pattern or (res_obj["confidence"], res_touches) > (best_pattern["confidence"], best_pattern["touches"]):
            best_pattern = res_obj

    return best_pattern


def detect_symmetrical_triangle(symbol: str, company: str, candles: list, timeframe: str = "daily") -> dict:
    """
    Symmetrical Triangle Pattern (Coil):
      1. Two converging trendlines with opposite slopes:
         - Upper trendline: Downward sloping (lower highs)
         - Lower trendline: Upward sloping (higher lows)
      2. Decreasing trading volume during coil formation (indecision)
      3. Breakout above upper descending trendline confirms bullish continuation
      4. Target = Breakout price + Height of widest part of the triangle (base)
      5. Stop-Loss = Placed right below breakout point or rising support trendline
      6. Minimum Risk:Reward = 1:2.5 to 1:3
    """
    if len(candles) < 30:
        return None

    best_pattern = None
    for lb in [25, 35, 45, 55]:
        if len(candles) < lb:
            continue
        window = candles[-lb:]
        highs = [c[2] for c in window]
        lows = [c[3] for c in window]
        closes = [c[4] for c in window]
        volumes = [c[5] for c in window]
        n = len(window)

        sh, sl = find_swings(highs, lows, window=2)
        if len(sh) < 2 or len(sl) < 2:
            continue

        res_slope, res_intercept, res_r2 = linreg(sh)
        sup_slope, sup_intercept, sup_r2 = linreg(sl)

        avg_price = sum(closes) / n
        res_slope_norm = res_slope / avg_price
        sup_slope_norm = sup_slope / avg_price

        # Symmetrical triangle convergence check:
        # Upper line must be downward sloping (-0.0003 or lower)
        # Lower line must be upward sloping (+0.0003 or higher)
        if res_slope_norm >= -0.0003 or sup_slope_norm <= 0.0003:
            continue

        fit_quality = (res_r2 + sup_r2) / 2
        if fit_quality < 0.32:
            continue

        last_x = n - 1
        res_now = res_slope * last_x + res_intercept
        sup_now = sup_slope * last_x + sup_intercept
        if sup_now >= res_now:
            continue

        # Widest part of the triangle (height at start)
        base_height = (res_slope * 0 + res_intercept) - (sup_slope * 0 + sup_intercept)
        if base_height <= 0 or (base_height / res_now) < 0.03:
            continue

        cur_close = closes[-1]
        cur_vol = volumes[-1]
        v_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        vol_surge = (cur_vol >= 1.25 * v_avg) if v_avg > 0 else False

        buy_price = round(res_now * 1.002, 2)
        last_swing_low = sl[-1][1]

        # Breakout qualification:
        # Confirmed Breakout: Price crossed upper descending line (+0.2% to +2.5%)
        # Pre-breakout watch: Price is coiling inside triangle within 2% of resistance
        if cur_close >= buy_price and cur_close <= buy_price * 1.025:
            status = "Confirmed Breakout"
            stop_loss = round(min(res_now * 0.985, last_swing_low), 2)
        elif cur_close >= res_now * 0.970 and cur_close < buy_price:
            status = "Pre-Breakout Watch"
            stop_loss = round(sup_now * 0.985, 2)
        else:
            continue

        risk = buy_price - stop_loss
        if risk <= 0:
            stop_loss = round(buy_price * 0.965, 2)
            risk = buy_price - stop_loss

        target = round(buy_price + max(base_height, 2.5 * risk), 2)
        rr = round((target - buy_price) / risk, 2) if risk > 0 else 2.5

        if rr < 2.2:
            continue

        pattern_score = 72
        if fit_quality >= 0.50:
            pattern_score += 10
        if vol_surge:
            pattern_score += 10

        # Construct trendline points for chart overlay
        res_start_val = res_slope * 0 + res_intercept
        res_end_val = res_slope * (n - 1) + res_intercept
        sup_start_val = sup_slope * 0 + sup_intercept
        sup_end_val = sup_slope * (n - 1) + sup_intercept
        res_line = [
            {"time": window[0][0], "value": round(res_start_val, 2)},
            {"time": window[-1][0], "value": round(res_end_val, 2)}
        ]
        sup_line = [
            {"time": window[0][0], "value": round(sup_start_val, 2)},
            {"time": window[-1][0], "value": round(sup_end_val, 2)}
        ]
        breakout_candle_date = window[-1][0] if ("Confirmed" in status) else None

        res_obj = {
            "symbol": symbol,
            "company": company,
            "pattern": "Symmetrical Triangle",
            "status": status,
            "entry_type": "Coil Breakout",
            "cmp": round(cur_close, 2),
            "resistance_level": round(res_now, 2),
            "support_level": round(sup_now, 2),
            "buy_price": buy_price,
            "stop_loss": stop_loss,
            "target": target,
            "risk_reward": f"1:{rr}",
            "touches": len(sh) + len(sl),
            "triangle_height": round(base_height, 2),
            "timeframe": timeframe.capitalize(),
            "confidence": min(98, pattern_score),
            "sparkline": [round(c, 2) for c in closes[-12:]],
            "abs_distance": abs(round(((cur_close - res_now) / res_now) * 100, 2)),
            "resistance_line": res_line,
            "support_line": sup_line,
            "breakout_candle_date": breakout_candle_date,
        }

        if not best_pattern or (res_obj["confidence"] > best_pattern["confidence"]):
            best_pattern = res_obj

    return best_pattern
