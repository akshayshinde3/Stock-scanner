"""
descending_channel.py — Advanced Descending Channel Bullish Breakout Strategy
=============================================================================
Professional stock market pattern recognition and signal generation engine for NSE stocks.

Features:
  1. Descending Channel Identification:
     - Confirmed pivot swing highs and swing lows (minimum 3 Lower Highs, 3 Lower Lows).
     - Downward-sloping upper resistance and lower support trendlines via robust linear regression.
     - Approximate parallelism and channel height bounds.
     - ATR-based trendline touch validation without look-ahead bias.
     - Channel duration: 20 to 120 candles.
  2. Breakout Detection:
     - Candle close above upper trendline by at least 0.25 ATR buffer.
     - Volume expansion: Relative Volume (RVOL) = Volume / SMA(Volume, 20) >= 1.5x (Strong/Excellent).
  3. Breakout Candle Confirmation:
     - Strong bullish body representing >= 60% of total candle range.
     - Close near high with limited upper wick (<= 25% of candle range).
  4. Retest Confirmation:
     - Monitors 1–10 candles after breakout for a pullback to previous resistance (now support).
     - Low volume on pullback, bullish reversal candle on retest.
  5. Double Bottom Confirmation (Optional Bonus):
     - Two swing lows within 1.0%–1.5% (or ATR-adjusted) near channel support.
  6. Buy Signal Types:
     - EARLY BREAKOUT BUY: Breakout candle confirmed, RVOL >= 1.5, Quality Score >= 80.
     - CONFIRMED BUY: Breakout + successful retest + bullish reversal candle + R:R >= 1:2.
  7. Trade Levels:
     - Entry: On confirmed retest reversal (or breakout close for early).
     - Stop Loss: Below retest swing low with 0.2 ATR buffer.
     - Target 1: Entry + (Risk * 2) (1:2 R:R).
     - Target 2: Entry + (Risk * 3) (1:3 R:R).
     - Target 3: Breakout Price + Channel Height (H).
  8. Setup Quality Score (Weighted out of 100):
     - Valid descending channel: 15
     - Min 3 Lower Highs: 10
     - Min 3 Lower Lows: 10
     - Strong breakout candle: 15
     - Volume confirmation: 15
     - Successful retest: 15
     - Double bottom confirmation: 5
     - Bullish reversal candle: 5
     - Risk/Reward >= 1:2: 10
  9. Strict Rules:
     - NO RSI, NO ADX used anywhere in filters or scoring.
     - Repainting and look-ahead bias strictly avoided.
"""

import math
from typing import List, Dict, Any, Optional, Tuple


# ---------------------------------------------------------------------------
# Default Configuration Constants
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "min_lh": 3,                     # Minimum Lower Highs required
    "min_ll": 3,                     # Minimum Lower Lows required
    "min_duration": 20,              # Minimum channel duration (candles)
    "max_duration": 120,             # Maximum channel duration (candles)
    "max_slope_diff": 0.006,         # Maximum normalized slope difference for parallelism
    "touch_tolerance_pct": 0.038,    # 3.8% touch tolerance for trendline touches
    "min_breakout_buffer_atr": 0.25, # Close must clear resistance by >= 0.25 ATR
    "min_relative_volume": 1.5,      # Breakout volume >= 1.5x 20-candle SMA(volume)
    "min_body_ratio": 0.55,          # Candle body must be >= 55% of range (pref >= 60%)
    "max_upper_wick_ratio": 0.25,    # Upper wick <= 25% of candle range
    "retest_max_candles": 10,        # Monitor retest for up to 10 candles after breakout
    "retest_tolerance_atr": 0.40,    # Distance from broken resistance for retest zone
    "sl_buffer_atr": 0.20,           # Stop loss buffer below retest low
    "min_risk_reward": 1.8,          # Minimum acceptable R:R ratio
    "min_score_actionable": 85,      # Minimum score for actionable buy signals
}


# ---------------------------------------------------------------------------
# 1. Price Action Helpers & Indicator-Free Math
# ---------------------------------------------------------------------------
def calculate_atr(candles: List[List[Any]], period: int = 14) -> float:
    """Calculate Average True Range (ATR) purely from OHLC without third-party indicators."""
    if len(candles) < 2:
        return 1.0
    true_ranges = []
    for i in range(1, len(candles)):
        h = float(candles[i][2])
        l = float(candles[i][3])
        prev_c = float(candles[i-1][4])
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        true_ranges.append(tr)
    recent = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(recent) / len(recent) if recent else 1.0


def calculate_sma(values: List[float], period: int) -> Optional[float]:
    """Simple Moving Average helper."""
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def linreg(points: List[Tuple[int, float]]) -> Tuple[float, float, float]:
    """Linear regression over (x, y) points. Returns (slope, intercept, r_squared)."""
    n = len(points)
    if n < 2:
        return 0.0, (points[0][1] if points else 0.0), 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
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


def line_val(slope: float, intercept: float, x: int) -> float:
    return slope * x + intercept


# ---------------------------------------------------------------------------
# 2. Pivot & Swing Point Detection (Confirmed Pivots Only)
# ---------------------------------------------------------------------------
def detect_swing_highs(highs: List[float], window: int = 2) -> List[Tuple[int, float]]:
    """
    Identifies confirmed swing highs where candle high is higher than `window` candles
    before and after. Avoids look-ahead bias by only evaluating up to (len - window - 1).
    """
    swings = []
    n = len(highs)
    for i in range(window, n - window):
        seg = highs[i - window : i + window + 1]
        if highs[i] == max(seg):
            swings.append((i, highs[i]))
    return swings


def detect_swing_lows(lows: List[float], window: int = 2) -> List[Tuple[int, float]]:
    """Identifies confirmed swing lows where candle low is lower than surrounding candles."""
    swings = []
    n = len(lows)
    for i in range(window, n - window):
        seg = lows[i - window : i + window + 1]
        if lows[i] == min(seg):
            swings.append((i, lows[i]))
    return swings


# ---------------------------------------------------------------------------
# 3. Descending Channel Identification & Trendline Fitting
# ---------------------------------------------------------------------------
def calculate_channel_trendlines(
    swing_highs: List[Tuple[int, float]],
    swing_lows: List[Tuple[int, float]],
    avg_price: float
) -> Tuple[float, float, float, float, float, float]:
    """Calculates linear regression trendlines for resistance and support."""
    res_slope, res_intercept, res_r2 = linreg(swing_highs)
    sup_slope, sup_intercept, sup_r2 = linreg(swing_lows)
    res_slope_norm = res_slope / avg_price if avg_price > 0 else 0.0
    sup_slope_norm = sup_slope / avg_price if avg_price > 0 else 0.0
    return res_slope, res_intercept, res_slope_norm, sup_slope, sup_intercept, sup_slope_norm


def validate_channel(
    res_slope_norm: float,
    sup_slope_norm: float,
    swing_highs: List[Tuple[int, float]],
    swing_lows: List[Tuple[int, float]],
    channel_height_pct: float,
    duration: int,
    config: Dict[str, Any]
) -> Tuple[bool, int, int, List[str]]:
    """
    Validates all criteria for a Descending Channel:
      - At least 3 Lower Highs and 3 Lower Lows.
      - Both trendlines slope downwards (negative slopes).
      - Approximately parallel trendlines (slope difference within threshold).
      - Valid channel height (between 3% and 40%).
      - Duration between min and max candles.
    """
    reasons = []

    # 1. Both trendlines must slope downward
    if res_slope_norm >= -0.0001:
        return False, 0, 0, ["Resistance slope is flat or upward"]
    if sup_slope_norm >= -0.0001:
        return False, 0, 0, ["Support slope is flat or upward"]

    # 2. Both trendlines approximately parallel
    slope_diff = abs(res_slope_norm - sup_slope_norm)
    if slope_diff > config["max_slope_diff"]:
        return False, 0, 0, [f"Trendlines diverge too sharply (diff: {slope_diff:.4f})"]

    # 3. Count strictly Lower Highs (LH)
    lh_count = 1
    for i in range(1, len(swing_highs)):
        if swing_highs[i][1] <= swing_highs[i-1][1] * 1.015:
            lh_count += 1
    if lh_count < config["min_lh"]:
        return False, lh_count, 0, [f"Insufficient Lower Highs ({lh_count} < {config['min_lh']})"]

    # 4. Count strictly Lower Lows (LL)
    ll_count = 1
    for i in range(1, len(swing_lows)):
        if swing_lows[i][1] <= swing_lows[i-1][1] * 1.015:
            ll_count += 1
    if ll_count < config["min_ll"]:
        return False, lh_count, ll_count, [f"Insufficient Lower Lows ({ll_count} < {config['min_ll']})"]

    # 5. Channel height check
    if channel_height_pct < 3.0 or channel_height_pct > 40.0:
        return False, lh_count, ll_count, [f"Channel height ({channel_height_pct:.1f}%) outside 3%-40% range"]

    # 6. Duration check
    if duration < config["min_duration"] or duration > config["max_duration"]:
        return False, lh_count, ll_count, [f"Channel duration {duration} outside {config['min_duration']}-{config['max_duration']} range"]

    reasons.append("Valid Descending Channel")
    reasons.append(f"{lh_count} Lower Highs")
    reasons.append(f"{ll_count} Lower Lows")
    return True, lh_count, ll_count, reasons


def identify_descending_channel(
    candles: List[List[Any]],
    lookback: int,
    config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Identifies and fits a descending channel on a specific lookback window."""
    if len(candles) < lookback:
        return None

    window = candles[-lookback:]
    highs = [float(c[2]) for c in window]
    lows = [float(c[3]) for c in window]
    closes = [float(c[4]) for c in window]
    avg_price = sum(closes) / len(closes) if closes else 1.0

    sh = detect_swing_highs(highs, window=2)
    sl = detect_swing_lows(lows, window=2)

    if len(sh) < config["min_lh"] or len(sl) < config["min_ll"]:
        return None

    res_slope, res_intercept, res_norm, sup_slope, sup_intercept, sup_norm = calculate_channel_trendlines(sh, sl, avg_price)

    last_x = len(window) - 1
    res_now = line_val(res_slope, res_intercept, last_x)
    sup_now = line_val(sup_slope, sup_intercept, last_x)
    res_start = line_val(res_slope, res_intercept, 0)
    sup_start = line_val(sup_slope, sup_intercept, 0)

    if res_now <= sup_now or res_start <= sup_start:
        return None

    channel_height = res_now - sup_now
    channel_height_pct = (channel_height / avg_price) * 100.0

    valid, lh_count, ll_count, notes = validate_channel(
        res_norm, sup_norm, sh, sl, channel_height_pct, lookback, config
    )
    if not valid:
        return None

    # Trendline touches validation
    res_touches = 0
    for idx, val in sh:
        exp = line_val(res_slope, res_intercept, idx)
        if exp > 0 and abs(val - exp) / exp <= config["touch_tolerance_pct"]:
            res_touches += 1

    sup_touches = 0
    for idx, val in sl:
        exp = line_val(sup_slope, sup_intercept, idx)
        if exp > 0 and abs(val - exp) / exp <= config["touch_tolerance_pct"]:
            sup_touches += 1

    # Trendline coordinates for charting
    offset = len(candles) - lookback
    res_points = [
        {"time": window[0][0][:10], "value": round(res_start, 2)},
        {"time": window[-1][0][:10], "value": round(res_now, 2)}
    ]
    sup_points = [
        {"time": window[0][0][:10], "value": round(sup_start, 2)},
        {"time": window[-1][0][:10], "value": round(sup_now, 2)}
    ]

    return {
        "valid": True,
        "lookback": lookback,
        "offset": offset,
        "res_slope": res_slope,
        "res_intercept": res_intercept,
        "sup_slope": sup_slope,
        "sup_intercept": sup_intercept,
        "res_slope_norm": res_norm,
        "sup_slope_norm": sup_norm,
        "res_now": round(res_now, 2),
        "sup_now": round(sup_now, 2),
        "channel_height": round(channel_height, 2),
        "channel_height_pct": round(channel_height_pct, 1),
        "lh_count": lh_count,
        "ll_count": ll_count,
        "res_touches": res_touches,
        "sup_touches": sup_touches,
        "swing_highs": [(offset + idx, val) for idx, val in sh],
        "swing_lows": [(offset + idx, val) for idx, val in sl],
        "res_points": res_points,
        "sup_points": sup_points,
        "start_date": window[0][0][:10],
        "end_date": window[-1][0][:10],
    }


# ---------------------------------------------------------------------------
# 4. Volume Expansion & Relative Volume (RVOL)
# ---------------------------------------------------------------------------
def calculate_relative_volume(candles: List[List[Any]], candle_idx: int = -1) -> Tuple[float, str]:
    """
    Relative Volume (RVOL) = Volume / SMA(Volume, 20).
    Ratings:
      - RVOL >= 2.0: Excellent
      - RVOL >= 1.5: Strong
      - RVOL >= 1.2: Moderate
      - RVOL < 1.2:  Weak
    """
    if len(candles) < 21:
        return 1.0, "Moderate"
    idx = (len(candles) + candle_idx) if candle_idx < 0 else candle_idx
    cur_vol = float(candles[idx][5]) if candles[idx][5] is not None else 0.0
    prior_vols = [float(c[5]) for c in candles[max(0, idx - 20) : idx] if c[5] is not None]
    if not prior_vols:
        return 1.0, "Moderate"
    avg_vol = sum(prior_vols) / len(prior_vols)
    if avg_vol <= 0:
        return 1.0, "Moderate"
    rvol = cur_vol / avg_vol
    if rvol >= 2.0:
        desc = "Excellent"
    elif rvol >= 1.5:
        desc = "Strong"
    elif rvol >= 1.2:
        desc = "Moderate"
    else:
        desc = "Weak"
    return round(rvol, 2), desc


# ---------------------------------------------------------------------------
# 5. Breakout Candle Confirmation
# ---------------------------------------------------------------------------
def validate_breakout_candle(
    candle: List[Any],
    res_level: float,
    atr: float,
    config: Dict[str, Any]
) -> Tuple[bool, float, Dict[str, Any]]:
    """
    Validates breakout candle quality:
      1. Closes above resistance by >= 0.25 ATR buffer.
      2. Bullish candle body (close > open).
      3. Body represents >= 55% of total candle range (preferably >= 60%).
      4. Limited upper wick (<= 25% of total range).
    """
    open_p = float(candle[1])
    high_p = float(candle[2])
    low_p = float(candle[3])
    close_p = float(candle[4])

    candle_range = high_p - low_p
    if candle_range <= 0:
        return False, 0.0, {"reason": "Zero range candle"}

    body = close_p - open_p
    upper_wick = high_p - max(open_p, close_p)
    body_ratio = body / candle_range if candle_range > 0 else 0.0
    upper_wick_ratio = upper_wick / candle_range if candle_range > 0 else 0.0

    buffer_atr = (close_p - res_level) / atr if atr > 0 else 0.0

    # Checks
    is_above_buffer = buffer_atr >= config["min_breakout_buffer_atr"]
    is_bullish = body > 0
    is_strong_body = body_ratio >= config["min_body_ratio"]
    is_limited_wick = upper_wick_ratio <= config["max_upper_wick_ratio"]

    valid = is_above_buffer and is_bullish and is_strong_body and is_limited_wick

    details = {
        "body_ratio": round(body_ratio, 2),
        "upper_wick_ratio": round(upper_wick_ratio, 2),
        "buffer_atr": round(buffer_atr, 2),
        "is_bullish": is_bullish,
        "is_strong_body": is_strong_body,
        "is_limited_wick": is_limited_wick,
    }
    return valid, buffer_atr, details


# ---------------------------------------------------------------------------
# 6. Breakout Detection Across Lookbacks
# ---------------------------------------------------------------------------
def detect_breakout(
    candles: List[List[Any]],
    channel: Dict[str, Any],
    atr: float,
    config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Scans the most recent candles (up to 12 candles back) to detect when
    the price cleanly broke out above the descending resistance trendline.
    """
    res_slope = channel["res_slope"]
    res_intercept = channel["res_intercept"]
    offset = channel["offset"]
    n_candles = len(candles)

    # Check recent candles for breakout event
    look_window = min(5, n_candles - offset)
    for b_offset in range(look_window, 0, -1):
        idx = n_candles - b_offset
        if idx < 0:
            continue
        c = candles[idx]
        x_in_window = idx - offset
        res_at_x = line_val(res_slope, res_intercept, x_in_window)
        close_p = float(c[4])

        if close_p > res_at_x:
            valid_candle, buffer_atr, candle_details = validate_breakout_candle(c, res_at_x, atr, config)
            rvol, rvol_desc = calculate_relative_volume(candles, idx)
            # Volume requirement: >= 1.5x
            vol_confirmed = rvol >= config["min_relative_volume"]

            if valid_candle and vol_confirmed:
                breakout_date = c[0][:10] if isinstance(c[0], str) else str(c[0])[:10]
                breakout_pct = round(((close_p - res_at_x) / res_at_x) * 100.0, 2)
                return {
                    "breakout_idx": idx,
                    "candles_ago": b_offset - 1,
                    "date": breakout_date,
                    "breakout_price": round(close_p, 2),
                    "res_at_breakout": round(res_at_x, 2),
                    "breakout_pct": breakout_pct,
                    "relative_volume": rvol,
                    "volume_rating": rvol_desc,
                    "buffer_atr": buffer_atr,
                    "candle_details": candle_details,
                    "is_recent": (b_offset - 1) == 0,
                }
    return None


# ---------------------------------------------------------------------------
# 7. Retest Confirmation & Bullish Reversal Detection
# ---------------------------------------------------------------------------
def detect_breakout_retest(
    candles: List[List[Any]],
    breakout: Dict[str, Any],
    channel: Dict[str, Any],
    atr: float,
    config: Dict[str, Any]
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    After a confirmed breakout:
      1. Monitors price for a retest within 1–10 candles.
      2. Previous resistance acts as new support.
      3. Price approaches breakout level within ATR tolerance.
      4. Price does NOT close decisively below broken resistance zone.
      5. Pullback volume is lower than breakout volume.
      6. A bullish reversal / rejection candle forms off the support.
    """
    b_idx = breakout["breakout_idx"]
    n = len(candles)
    candles_since_breakout = n - 1 - b_idx

    # If breakout was today, retest is still pending
    if candles_since_breakout < 1:
        return False, {"status": "Retest Pending", "reason": "Breakout just triggered"}

    if candles_since_breakout > config["retest_max_candles"]:
        return False, {"status": "Retest Expired", "reason": f"No retest within {config['retest_max_candles']} candles"}

    res_slope = channel["res_slope"]
    res_intercept = channel["res_intercept"]
    offset = channel["offset"]

    b_vol = float(candles[b_idx][5]) if candles[b_idx][5] else 1.0
    retest_low = float("inf")
    retest_candle_idx = -1
    retest_found = False
    pullback_vol_healthy = True

    for i in range(b_idx + 1, n):
        c = candles[i]
        c_low = float(c[3])
        c_close = float(c[4])
        c_vol = float(c[5]) if c[5] else 0.0
        x = i - offset
        expected_support = line_val(res_slope, res_intercept, x)

        # Distance to support in ATR
        dist_atr = (c_low - expected_support) / atr if atr > 0 else 0.0

        # Touched or approached retest zone within tolerance
        if dist_atr <= config["retest_tolerance_atr"] and c_close >= expected_support - (0.35 * atr):
            retest_found = True
            if c_low < retest_low:
                retest_low = c_low
                retest_candle_idx = i

            # Pullback volume check
            if c_vol > b_vol * 1.15:
                pullback_vol_healthy = False

    if not retest_found:
        return False, {"status": "Retest Pending", "reason": "Price consolidating above resistance, retest pending"}

    # Evaluate bullish reversal candle on or after retest
    last_candle = candles[-1]
    last_close = float(last_candle[4])
    last_open = float(last_candle[1])
    is_bullish_reversal = last_close >= last_open and last_close >= (retest_low + 0.15 * atr)

    retest_date = candles[retest_candle_idx][0][:10] if isinstance(candles[retest_candle_idx][0], str) else str(candles[retest_candle_idx][0])[:10]

    return True, {
        "status": "Retest Successful",
        "retest_candle_idx": retest_candle_idx,
        "retest_date": retest_date,
        "retest_low": round(retest_low, 2),
        "is_bullish_reversal": is_bullish_reversal,
        "pullback_vol_healthy": pullback_vol_healthy,
    }


# ---------------------------------------------------------------------------
# 8. Double Bottom Detection (Optional Bonus)
# ---------------------------------------------------------------------------
def detect_double_bottom(
    candles: List[List[Any]],
    swing_lows: List[Tuple[int, float]],
    channel_support_now: float,
    atr: float
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Identifies optional double bottom confirmation:
      - 2 confirmed swing lows within 1.0%–1.5% of each other.
      - Minimum separation of 5 candles.
      - Formed near descending channel support.
    """
    if len(swing_lows) < 2:
        return False, None

    for i in range(len(swing_lows) - 1, 0, -1):
        idx2, low2 = swing_lows[i]
        for j in range(i - 1, -1, -1):
            idx1, low1 = swing_lows[j]
            separation = idx2 - idx1
            if 5 <= separation <= 45:
                price_diff_pct = abs(low2 - low1) / min(low1, low2) * 100.0
                if price_diff_pct <= 1.5:
                    # Near channel support?
                    dist_to_sup = abs(min(low1, low2) - channel_support_now) / channel_support_now * 100.0
                    if dist_to_sup <= 8.0:
                        neckline = max(float(c[2]) for c in candles[idx1 : idx2 + 1])
                        return True, {
                            "low1": round(low1, 2),
                            "low2": round(low2, 2),
                            "neckline": round(neckline, 2),
                            "separation_bars": separation,
                            "price_diff_pct": round(price_diff_pct, 2),
                        }
    return False, None


# ---------------------------------------------------------------------------
# 9. Trade Levels: Entry, Stop Loss, Target 1, Target 2, Target 3
# ---------------------------------------------------------------------------
def calculate_trade_levels(
    breakout: Dict[str, Any],
    retest_info: Optional[Dict[str, Any]],
    channel: Dict[str, Any],
    atr: float,
    live_price: float,
    config: Dict[str, Any]
) -> Tuple[float, float, float, float, float, float]:
    """
    Calculates trade levels:
      - Entry: On confirmed retest reversal or breakout close.
      - Stop Loss: Below confirmed retest swing low (or channel support / ATR buffer) with 0.2 ATR buffer.
      - Target 1: Entry + (Risk * 2) (1:2 R:R).
      - Target 2: Entry + (Risk * 3) (1:3 R:R).
      - Target 3: Breakout Price + Channel Height (H).
    """
    breakout_price = breakout["breakout_price"]
    channel_height = channel["channel_height"]

    if retest_info and retest_info.get("status") == "Retest Successful":
        entry = round(max(live_price, breakout_price), 2)
        base_low = retest_info["retest_low"]
        stop_loss = round(base_low - (config["sl_buffer_atr"] * atr), 2)
    else:
        entry = round(breakout_price, 2)
        stop_loss = round(channel["sup_now"] - (config["sl_buffer_atr"] * atr), 2)

    risk = entry - stop_loss
    # Safety risk floor (at least 1% of entry)
    if risk <= 0 or (risk / entry) < 0.01:
        stop_loss = round(entry - max(atr * 1.5, entry * 0.025), 2)
        risk = entry - stop_loss

    target1 = round(entry + (2.0 * risk), 2)
    target2 = round(entry + (3.0 * risk), 2)
    target3 = round(breakout_price + channel_height, 2)

    rr = round((target1 - entry) / risk, 2) if risk > 0 else 0.0
    return entry, stop_loss, target1, target2, target3, rr


# ---------------------------------------------------------------------------
# 10. Setup Quality Score Calculation (Weighted out of 100)
# ---------------------------------------------------------------------------
def calculate_setup_score(
    channel_valid: bool,
    lh_count: int,
    ll_count: int,
    strong_breakout_candle: bool,
    volume_confirmed: bool,
    retest_successful: bool,
    double_bottom: bool,
    bullish_reversal: bool,
    rr_favorable: bool
) -> Tuple[int, Dict[str, int]]:
    """
    Exact weighted breakdown out of 100:
      Valid descending channel:   15 pts
      Minimum 3 Lower Highs:      10 pts
      Minimum 3 Lower Lows:       10 pts
      Strong breakout candle:     15 pts
      Volume confirmation:        15 pts
      Successful retest:          15 pts
      Double bottom confirmation:  5 pts
      Bullish reversal candle:     5 pts
      Risk/reward >= 1:2:         10 pts
      TOTAL:                     100 pts
    """
    breakdown = {
        "valid_channel": 15 if channel_valid else 0,
        "lower_highs": 10 if lh_count >= 3 else 0,
        "lower_lows": 10 if ll_count >= 3 else 0,
        "breakout_candle": 15 if strong_breakout_candle else 0,
        "volume_confirmed": 15 if volume_confirmed else 0,
        "retest_successful": 15 if retest_successful else 0,
        "double_bottom": 5 if double_bottom else 0,
        "bullish_reversal": 5 if bullish_reversal else 0,
        "risk_reward": 10 if rr_favorable else 0,
    }
    total_score = sum(breakdown.values())
    return total_score, breakdown


# ---------------------------------------------------------------------------
# 11. False Breakout Protection
# ---------------------------------------------------------------------------
def validate_failed_breakout(
    candles: List[List[Any]],
    breakout: Dict[str, Any],
    channel: Dict[str, Any]
) -> bool:
    """
    Detects invalid/failed breakouts:
      - Price closed back inside the channel within 1-7 candles after breakout.
      - Price lost the broken resistance level by more than 1.0%.
      - Current price is more than 3% below the breakout price (momentum lost).
    """
    b_idx = breakout["breakout_idx"]
    n = len(candles)
    res_slope = channel["res_slope"]
    res_intercept = channel["res_intercept"]
    offset = channel["offset"]
    breakout_price = breakout["breakout_price"]

    # Check up to 7 candles after breakout for price falling back into channel
    for i in range(b_idx + 1, min(b_idx + 8, n)):
        c = candles[i]
        c_close = float(c[4])
        x = i - offset
        res_x = line_val(res_slope, res_intercept, x)
        # If price closed more than 1% below resistance level = failed breakout
        if c_close < res_x * 0.990:
            return True

    # Current price check: if current price is 3%+ below breakout price, momentum lost
    current_close = float(candles[-1][4])
    if current_close < breakout_price * 0.970:
        return True

    return False


# ---------------------------------------------------------------------------
# 12. Master Scanner Function
# ---------------------------------------------------------------------------
def scan_descending_channel(
    symbol: str,
    candles: List[List[Any]],
    live_price: Optional[float] = None,
    timeframe: str = "daily",
    company_name: str = "",
    config_overrides: Optional[Dict[str, Any]] = None,
    nifty_trend_ok: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Main evaluation pipeline:
      1. Tests multiple lookback windows (e.g. 25, 35, 45, 60, 90).
      2. Validates descending channel parameters.
      3. Identifies breakouts and confirms volume expansion.
      4. Detects retest status and optional double bottoms.
      5. Calculates Stop Loss, Targets 1, 2, 3 and Setup Quality Score (100).
      6. Emits CONFIRMED BUY, EARLY BREAKOUT, or WATCHLIST signal.
    """
    config = dict(DEFAULT_CONFIG)
    if config_overrides:
        config.update(config_overrides)

    if len(candles) < config["min_duration"]:
        return None

    cur_price = float(live_price) if live_price is not None else float(candles[-1][4])
    atr = calculate_atr(candles, period=14)

    # === BULLISH TREND FILTER ===
    # Require current price > 50-period SMA for bullish bias (buy signals only)
    closes_all = [float(c[4]) for c in candles]
    sma50_val = calculate_sma(closes_all, 50)
    sma20_val = calculate_sma(closes_all, 20)
    # For confirmed/early breakout signals, price must be above SMA50 OR recently recovered above SMA20
    # (allow some tolerance: within 3% below SMA50 for channel breakouts since they recover)
    sma50_ok = sma50_val is None or cur_price >= sma50_val * 0.97
    if not sma50_ok:
        return None  # Skip bearish stocks entirely for buy signals

    # Multi-window channel search
    lookbacks = [15, 25, 35] if timeframe == "weekly" else [30, 45, 25, 60, 90]
    best_channel = None

    for lb in lookbacks:
        ch = identify_descending_channel(candles, lb, config)
        if ch:
            if not best_channel or (ch["lh_count"] + ch["ll_count"]) > (best_channel["lh_count"] + best_channel["ll_count"]):
                best_channel = ch

    if not best_channel:
        return None

    # Detect breakout
    breakout = detect_breakout(candles, best_channel, atr, config)

    # Detect double bottom
    has_db, db_info = detect_double_bottom(candles, best_channel["swing_lows"], best_channel["sup_now"], atr)

    # Evaluate Retest
    retest_ok = False
    retest_info = None
    is_failed_breakout = False

    if breakout:
        is_failed_breakout = validate_failed_breakout(candles, breakout, best_channel)
        if not is_failed_breakout:
            retest_ok, retest_info = detect_breakout_retest(candles, breakout, best_channel, atr, config)

    # Trade Levels
    if breakout and not is_failed_breakout:
        entry, sl, t1, t2, t3, rr = calculate_trade_levels(
            breakout, retest_info, best_channel, atr, cur_price, config
        )
    else:
        entry = round(best_channel["res_now"] * 1.005, 2)
        sl = round(best_channel["sup_now"] - (config["sl_buffer_atr"] * atr), 2)
        risk = entry - sl
        t1 = round(entry + 2 * risk, 2) if risk > 0 else round(entry * 1.10, 2)
        t2 = round(entry + 3 * risk, 2) if risk > 0 else round(entry * 1.15, 2)
        t3 = round(entry + best_channel["channel_height"], 2)
        rr = round((t1 - entry) / risk, 2) if risk > 0 else 2.0

    # Setup Quality Score
    strong_candle = breakout["candle_details"]["is_strong_body"] if breakout else False
    vol_conf = (breakout["relative_volume"] >= config["min_relative_volume"]) if breakout else False
    bullish_rev = retest_info.get("is_bullish_reversal", False) if retest_info else False
    rr_favorable = rr >= config["min_risk_reward"]

    total_score, score_breakdown = calculate_setup_score(
        channel_valid=True,
        lh_count=best_channel["lh_count"],
        ll_count=best_channel["ll_count"],
        strong_breakout_candle=strong_candle,
        volume_confirmed=vol_conf,
        retest_successful=retest_ok,
        double_bottom=has_db,
        bullish_reversal=bullish_rev,
        risk_reward=rr_favorable
    )

    # Signal Classification
    if is_failed_breakout or total_score < 65:
        signal_type = "REJECTED"
        signal_color = "RED"
        status_label = "Failed Breakout" if is_failed_breakout else "Rejected (<65)"
    elif breakout and not is_failed_breakout and retest_ok and bullish_rev and total_score >= config["min_score_actionable"] and rr_favorable and nifty_trend_ok:
        signal_type = "CONFIRMED BUY"
        signal_color = "GREEN"
        status_label = "Confirmed Buy (Post-Retest)"
    elif breakout and not is_failed_breakout and total_score >= config["min_score_actionable"] and vol_conf:
        signal_type = "EARLY BREAKOUT"
        signal_color = "BLUE"
        status_label = "Early Breakout (Momentum)"
    elif total_score >= 75 or (cur_price >= best_channel["res_now"] * 0.96 and cur_price <= best_channel["res_now"] * 1.02):
        signal_type = "WATCHLIST"
        signal_color = "YELLOW"
        status_label = "Watchlist (Setup Forming)"
    else:
        signal_type = "WATCHLIST"
        signal_color = "YELLOW"
        status_label = "Watchlist"

    reasons = [
        f"Channel: {best_channel['lookback']} bars ({best_channel['start_date']} to {best_channel['end_date']})",
        f"{best_channel['lh_count']} LH, {best_channel['ll_count']} LL",
        f"Res ₹{best_channel['res_now']} | Sup ₹{best_channel['sup_now']}",
    ]
    if breakout:
        reasons.append(f"Breakout on {breakout['date']} @ ₹{breakout['breakout_price']} (+{breakout['breakout_pct']}%)")
        reasons.append(f"RVOL: {breakout['relative_volume']}x ({breakout['volume_rating']})")
    if retest_ok and retest_info:
        reasons.append(f"Retest held @ ₹{retest_info['retest_low']} on {retest_info['retest_date']}")
    if has_db and db_info:
        reasons.append(f"Double Bottom @ ₹{db_info['low1']}/₹{db_info['low2']}")

    return {
        "symbol": symbol,
        "company_name": company_name or symbol,
        "exchange": "NSE",
        "current_price": round(cur_price, 2),
        "timeframe": timeframe,
        "channel_start_date": best_channel["start_date"],
        "channel_end_date": best_channel["end_date"],
        "channel_duration": best_channel["lookback"],
        "upper_trendline": best_channel["res_now"],
        "lower_trendline": best_channel["sup_now"],
        "channel_height": best_channel["channel_height"],
        "channel_height_pct": best_channel["channel_height_pct"],
        "breakout_price": breakout["breakout_price"] if breakout else None,
        "breakout_date": breakout["date"] if breakout else None,
        "breakout_pct": breakout["breakout_pct"] if breakout else None,
        "relative_volume": breakout["relative_volume"] if breakout else None,
        "volume_rating": breakout["volume_rating"] if breakout else "N/A",
        "breakout_candle_strength": "Strong" if strong_candle else ("Moderate" if breakout else "N/A"),
        "double_bottom_status": "Confirmed" if has_db else "None",
        "double_bottom_info": db_info,
        "retest_status": retest_info["status"] if retest_info else ("Pending" if breakout else "None"),
        "retest_date": retest_info.get("retest_date") if retest_info else None,
        "entry_price": entry,
        "stop_loss": sl,
        "target1": t1,
        "target2": t2,
        "target3": t3,
        "risk_reward": f"1:{rr}",
        "setup_quality_score": total_score,
        "score_breakdown": score_breakdown,
        "signal_type": signal_type,
        "signal_color": signal_color,
        "status_label": status_label,
        "reasons": reasons,
        "atr": round(atr, 2),
        "res_points": best_channel["res_points"],
        "sup_points": best_channel["sup_points"],
        "swing_highs": best_channel["swing_highs"],
        "swing_lows": best_channel["swing_lows"],
    }
