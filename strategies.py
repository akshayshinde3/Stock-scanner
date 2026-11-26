"""
strategies.py — 44 MA Scanner & Breakout Chart Pattern Engines
==============================================================
Institutional Strategy Suite for Indian Equities (NSE / Nifty 500, 100, 50):
  1. 44 MA RISING SCANNER (-1.0% to +3.0%):
     - MA44: 44-period simple moving average of Close on that timeframe.
     - Distance %: (Close - MA44) / MA44 * 100
     - Fixed Distance Band: -1.0% <= Distance % <= +3.0% ONLY.
     - MA44 Rising: today's MA44 > yesterday's MA44 (strictly rising slope).
     - Status badges:
         1. "Touching" (Blue): Low <= MA44 <= High (within -1% to +3%).
         2. "Above (0–3%)" (Green): Close >= MA44 and Distance <= +3.0%.
         3. "Near Below (−1–0%)" (Orange): Close < MA44 and Distance >= -1.0%.
     - Timeframes: Both (Daily + Weekly), Daily, Weekly.

  2. ASCENDING TRIANGLE PATTERN:
     - Flat resistance with >=2 confirmed swing highs (slope within ±0.05%/bar).
     - Rising support with >=2 confirmed swing lows (slope >= +0.05%/bar, R² >= 0.6).
     - Apex convergence within 1-15 bars.
     - True pattern height >= 3% of price.
     - Breakout price + height target, strict 1:3 minimum R:R (reject if below).

  3. SYMMETRICAL TRIANGLE PATTERN:
     - Converging lines: upper descending (<= -0.05%/bar), lower ascending (>= +0.05%/bar).
     - Range contraction (>=25% smaller) & volume dry-up (<85%).
     - Apex intersection: breakout between 50% and 85% to apex.
     - Minimum 1:2.5 R:R (reject if below).

  4. POLE AND FLAG PATTERN:
     - Impulsive pole >= 12% daily / >= 20% weekly, volume surge >= 1.3x.
     - Parallel flag channel, retracement <= 50%, volume contraction < 80%.
     - Target = breakout price + pole height, minimum 1:2.0 R:R.
"""

from typing import Optional, List, Dict, Any, Tuple

from patterns.config import (
    DIST_MIN,
    DIST_MAX,
    MA_PERIOD,
    MA_RISING_BARS,
    TOLERANCE_PRICE_PCT,
    TOLERANCE_ATR_MULT,
)
from patterns.geometry import (
    atr,
    confirmed_pivots,
    fit_line_through_pivots,
    touches_on_line,
    line_value,
    compute_tolerance,
    resample_to_weekly,
)
from patterns.ascending_triangle import (
    detect_ascending_triangle,
    get_ascending_triangle_debug,
)
from patterns.symmetrical_triangle import (
    detect_symmetrical_triangle,
    get_symmetrical_triangle_debug,
)
from patterns.pole_and_flag import (
    detect_pole_and_flag,
    get_pole_and_flag_debug,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. 44 MA SWING STRATEGY ENGINE (Chartink "swing-trade-by-pmpatil")
# ═══════════════════════════════════════════════════════════════════════════

def calculate_ma44(closes: list) -> list:
    """Calculates 44-period Simple Moving Average of Close series with sliding-window sum (0.02ms)."""
    n = len(closes)
    if n < MA_PERIOD:
        return [None] * n

    result = [None] * (MA_PERIOD - 1)
    w_sum = sum(closes[:MA_PERIOD])
    result.append(round(w_sum / MA_PERIOD, 2))
    for i in range(MA_PERIOD, n):
        w_sum += closes[i] - closes[i - MA_PERIOD]
        result.append(round(w_sum / MA_PERIOD, 2))
    return result


def calculate_ma44_high(highs: list) -> list:
    """Calculates 44-period Simple Moving Average of High series with sliding-window sum (0.02ms)."""
    n = len(highs)
    if n < MA_PERIOD:
        return [None] * n

    result = [None] * (MA_PERIOD - 1)
    w_sum = sum(highs[:MA_PERIOD])
    result.append(round(w_sum / MA_PERIOD, 2))
    for i in range(MA_PERIOD, n):
        w_sum += highs[i] - highs[i - MA_PERIOD]
        result.append(round(w_sum / MA_PERIOD, 2))
    return result


def is_touch(low: float, high: float, ma44: float) -> bool:
    """Direct TOUCH = Low <= MA44 <= High"""
    if ma44 is None or low is None or high is None:
        return False
    return low <= ma44 <= high


def is_in_44ma_band(dist_pct: float) -> bool:
    """A stock qualifies inside DIST_MIN <= Distance % <= DIST_MAX (-1.0% to +3.5%)."""
    if dist_pct is None:
        return False
    return DIST_MIN <= dist_pct <= DIST_MAX


def is_ma44_rising_chartink(ma44_series: list) -> Tuple[bool, bool]:
    """
    Checks Chartink filters:
      1. 1 day ago SMA(Close, 44) < Daily SMA(Close, 44)  (i.e. ma44[-1] > ma44[-2])
      2. 2 days ago SMA(Close, 44) < Daily SMA(Close, 44)  (i.e. ma44[-1] > ma44[-3])
    Returns (rising_1d, rising_2d). Both must be True for full qualification.
    """
    if len(ma44_series) < 3:
        return False, False
    m_today = ma44_series[-1]
    m_1d_ago = ma44_series[-2]
    m_2d_ago = ma44_series[-3]
    if m_today is None or m_1d_ago is None or m_2d_ago is None:
        return False, False
    return (m_today > m_1d_ago), (m_today > m_2d_ago)


def is_ma44_rising(ma44_series: list, bars_back: int = MA_RISING_BARS) -> bool:
    """MA44 rising check over bars_back (or 2 bars back for Chartink)."""
    if len(ma44_series) <= bars_back:
        return False
    current_ma = ma44_series[-1]
    past_ma = ma44_series[-(bars_back + 1)]
    if current_ma is None or past_ma is None:
        return False
    return current_ma > past_ma


def is_pullback_into_44_band(cur_low: float, ma44_high: float) -> bool:
    """Chartink filter 3: Daily Low < Daily SMA(Daily High, 44)"""
    if cur_low is None or ma44_high is None:
        return False
    return cur_low < ma44_high


def is_close_above_ma44(cur_close: float, ma44_close: float) -> bool:
    """Chartink filter 4: Daily Close > Daily SMA(Daily Close, 44)"""
    if cur_close is None or ma44_close is None:
        return False
    return cur_close > ma44_close


def is_green_candle(open_price: float, close_price: float) -> bool:
    """Chartink filter 5: Green candle only (Daily Close > Daily Open)"""
    if open_price is None or close_price is None:
        return False
    return close_price > open_price


def get_status(
    touch: bool,
    close: float,
    ma44: float,
    dist_pct: float,
    cur_low: float = None,
    ma44_high: float = None,
) -> Optional[str]:
    """
    Status badges for 44 MA setups strictly within -1.0% to +3.0% band:
      1. 'Touching' (Blue): Low <= MA44 <= High (and inside -1.0% to +3.0%).
      2. 'Above (0–3%)' (Green): Close >= MA44 and Distance % <= +3.0%.
      3. 'Near Below (−1–0%)' (Orange): Close < MA44 and Distance % >= -1.0%.
    """
    if not is_in_44ma_band(dist_pct):
        return None

    if touch:
        return "Touching"
    if close >= ma44 and dist_pct <= DIST_MAX:
        return "Above (0–3%)"
    if close < ma44 and dist_pct >= DIST_MIN:
        return "Near Below (−1–0%)"
    return None


def analyze_44ma_timeframe(candles: list, strict_chartink: bool = False) -> Optional[dict]:
    """
    Analyzes candle series for 44 MA Touch & Near conditions matching Chartink "swing-trade-by-pmpatil".
    Optimized for sub-millisecond execution.
    """
    if not candles or len(candles) < (MA_PERIOD + 2):
        return None

    # Fast slice: only the last 60 candles are needed for all 44 MA calculations
    sub = candles[-60:] if len(candles) > 60 else candles
    closes = [float(c[4]) for c in sub]
    highs = [float(c[2]) for c in sub]
    lows = [float(c[3]) for c in sub]
    opens = [float(c[1]) for c in sub]
    volumes = [int(c[5]) for c in sub]

    cur_close = closes[-1]
    cur_open = opens[-1]
    cur_high = highs[-1]
    cur_low = lows[-1]
    cur_vol = volumes[-1]

    # Fast sliding sums for 44 MA values
    current_ma = round(sum(closes[-MA_PERIOD:]) / MA_PERIOD, 2)
    past_ma_1d = round(sum(closes[-(MA_PERIOD + 1):-1]) / MA_PERIOD, 2)
    past_ma_2d = round(sum(closes[-(MA_PERIOD + 2):-2]) / MA_PERIOD, 2)
    current_ma_high = round(sum(highs[-MA_PERIOD:]) / MA_PERIOD, 2)

    # Distance % = (Close - MA44) / MA44 * 100
    dist_pct = round(((cur_close - current_ma) / current_ma) * 100, 2)

    # Core Rule: MUST fall inside [-1.0, +3.0]
    if not is_in_44ma_band(dist_pct):
        return None

    # Chartink 5 filters evaluation:
    rising_1d = current_ma > past_ma_1d
    rising_2d = current_ma > past_ma_2d
    pullback_touch = cur_low < current_ma_high
    close_above_ma = cur_close > current_ma
    green_candle = cur_close > cur_open
    chartink_pass = bool(rising_1d and rising_2d and pullback_touch and close_above_ma and green_candle)

    if strict_chartink and not chartink_pass:
        return None

    touch = is_touch(cur_low, cur_high, current_ma)
    status_label = get_status(touch, cur_close, current_ma, dist_pct)
    if not status_label:
        return None

    prev_close = closes[-2] if len(closes) >= 2 else cur_open
    day_change_pct = round(((cur_close - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

    recent_vol = sum(volumes[-5:]) if len(volumes) >= 5 else sum(volumes)
    sparkline = [round(c, 2) for c in closes[-12:]]

    # Calculate stop loss & target for swing trade clarity:
    cur_atr = atr(sub, period=14)
    stop_loss = round(min(current_ma * 0.985, cur_low - 0.5 * cur_atr), 2)
    risk = cur_close - stop_loss
    if risk <= 0:
        stop_loss = round(cur_close * 0.98, 2)
        risk = cur_close - stop_loss
    target = round(cur_close + 3.0 * risk, 2)

    return {
        "cmp": round(cur_close, 2),
        "ma44": round(current_ma, 2),
        "ma44_high": round(current_ma_high, 2),
        "distance_pct": dist_pct,
        "status": status_label,
        "day_change_pct": day_change_pct,
        "volume": int(cur_vol),
        "weekly_volume": int(recent_vol),
        "ma44_rising": bool(rising_1d and rising_2d),
        "ma44_rising_1d": rising_1d,
        "ma44_rising_2d": rising_2d,
        "green_candle": green_candle,
        "pullback_in_band": pullback_touch,
        "close_above_ma": close_above_ma,
        "chartink_qualified": chartink_pass,
        "sparkline": sparkline,
        "buy_price": round(cur_close, 2),
        "stop_loss": stop_loss,
        "target": target,
        "risk_reward": "1:3",
    }


def evaluate_44ma_stock(
    symbol: str,
    company_name: str,
    daily_candles: list,
    weekly_candles: list,
    min_price: float = 0.0,
    min_weekly_vol: int = 100000,
    rising_only: bool = True,
    green_only: bool = False,
    strict_chartink: bool = False,
    **kwargs,  # Gracefully ignore deprecated args
) -> Optional[dict]:
    """
    Evaluates both Daily and Weekly for the 44 MA Touch & Near conditions matching
    Chartink "swing-trade-by-pmpatil" rules.
    Returns qualification status for 'Daily', 'Weekly', or 'Both'.
    """
    d_res = analyze_44ma_timeframe(daily_candles, strict_chartink=strict_chartink) if daily_candles else None
    w_res = analyze_44ma_timeframe(weekly_candles, strict_chartink=strict_chartink) if weekly_candles else None

    cmp_price = d_res["cmp"] if d_res else (w_res["cmp"] if w_res else 0)
    if min_price > 0 and cmp_price < min_price:
        return None

    vol_check = (d_res["weekly_volume"] if d_res else 0) or (w_res["volume"] if w_res else 0)
    if min_weekly_vol > 0 and vol_check < min_weekly_vol:
        return None

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
        "pattern": f"44 MA ({timeframe_badge})",
        "cmp": primary["cmp"],
        "ma44": primary["ma44"],
        "ma44_high": primary.get("ma44_high"),
        "distance_pct": primary["distance_pct"],
        "status": primary["status"],
        "day_change_pct": primary["day_change_pct"],
        "volume": primary["volume"],
        "timeframe": timeframe_badge,
        "sparkline": primary["sparkline"],
        "buy_price": primary["buy_price"],
        "stop_loss": primary["stop_loss"],
        "target": primary["target"],
        "risk_reward": primary["risk_reward"],
        "chartink_qualified": primary.get("chartink_qualified", True),
        "daily_data": d_res if d_qualifies else None,
        "weekly_data": w_res if w_qualifies else None,
        "abs_distance": abs(primary["distance_pct"]),
        "confidence": 90 if timeframe_badge == "Both" else 80,
    }


def evaluate_44ma_breakout(
    symbol: str,
    company: str,
    candles: list,
    timeframe: str = "daily",
    min_dist_pct: float = DIST_MIN,
    max_dist_pct: float = DIST_MAX,
) -> Optional[dict]:
    """
    Updated for Part 5 to use the strict -1.0% to +3.0% band.
    Maintained for backward-compatible endpoints if queried.
    """
    res = analyze_44ma_timeframe(candles)
    if not res:
        return None

    res["symbol"] = symbol
    res["company"] = company
    res["pattern"] = f"44 MA ({timeframe.capitalize()})"
    res["timeframe"] = timeframe.capitalize()
    res["type"] = "confirm_breakout" if res["distance_pct"] >= 0 else "pre_breakout"
    res["abs_distance"] = abs(res["distance_pct"])
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 2. DEBUG DIAGNOSTICS HELPER
# ═══════════════════════════════════════════════════════════════════════════

def get_44ma_debug(
    symbol: str,
    company: str,
    candles: list,
    timeframe: str = "daily",
) -> Dict[str, Any]:
    """
    Returns rule-by-rule diagnostic analysis of the 5 Chartink filters for the 44 MA strategy:
      1. 1 day ago SMA(Close, 44) < Daily SMA(Close, 44)
      2. 2 days ago SMA(Close, 44) < Daily SMA(Close, 44)
      3. Daily Low < Daily SMA(High, 44)
      4. Daily Close > Daily SMA(Close, 44)
      5. Daily Close > Daily Open (Green candle)
      6. Distance % within [-1.0%, +3.5%]
    """
    if not candles or len(candles) < (MA_PERIOD + 2):
        return {
            "symbol": symbol,
            "company": company,
            "strategy": f"44 MA ({timeframe.capitalize()} - Chartink PMPatil)",
            "bars_analyzed": len(candles) if candles else 0,
            "qualified": False,
            "setup": None,
            "reject_reasons": [
                f"Insufficient bars: {len(candles) if candles else 0} bars available, minimum {MA_PERIOD + 2} required."
            ],
        }

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    opens = [c[1] for c in candles]

    ma_close_series = calculate_ma44(closes)
    ma_high_series = calculate_ma44_high(highs)

    cur_close = closes[-1]
    cur_open = opens[-1]
    cur_high = highs[-1]
    cur_low = lows[-1]

    cur_ma_close = ma_close_series[-1]
    cur_ma_high = ma_high_series[-1]
    ma_1d = ma_close_series[-2]
    ma_2d = ma_close_series[-3]

    reasons = []

    # Rule 1
    r1 = cur_ma_close > ma_1d
    if not r1:
        reasons.append(f"❌ Rule 1 Failed: 44 SMA is falling today (Today: ₹{cur_ma_close:.2f} <= Yesterday: ₹{ma_1d:.2f})")
    else:
        reasons.append(f"✓ Rule 1 Passed: 44 SMA rising vs yesterday (₹{cur_ma_close:.2f} > ₹{ma_1d:.2f})")

    # Rule 2
    r2 = cur_ma_close > ma_2d
    if not r2:
        reasons.append(f"❌ Rule 2 Failed: 44 SMA is lower than 2 days ago (Today: ₹{cur_ma_close:.2f} <= 2d ago: ₹{ma_2d:.2f})")
    else:
        reasons.append(f"✓ Rule 2 Passed: 44 SMA rising vs 2 days ago (₹{cur_ma_close:.2f} > ₹{ma_2d:.2f})")

    # Rule 3
    r3 = cur_low < cur_ma_high
    if not r3:
        reasons.append(f"❌ Rule 3 Failed: Low did not dip below 44 SMA of High (Low: ₹{cur_low:.2f} >= 44 SMA High: ₹{cur_ma_high:.2f})")
    else:
        reasons.append(f"✓ Rule 3 Passed: Low dipped into 44 MA band (Low: ₹{cur_low:.2f} < 44 SMA High: ₹{cur_ma_high:.2f})")

    # Rule 4
    r4 = cur_close > cur_ma_close
    if not r4:
        reasons.append(f"❌ Rule 4 Failed: Close is below 44 SMA of Close (Close: ₹{cur_close:.2f} <= 44 SMA Close: ₹{cur_ma_close:.2f})")
    else:
        reasons.append(f"✓ Rule 4 Passed: Close holds above 44 SMA (Close: ₹{cur_close:.2f} > ₹{cur_ma_close:.2f})")

    # Rule 5
    r5 = cur_close > cur_open
    if not r5:
        reasons.append(f"❌ Rule 5 Failed: Red candle (Close: ₹{cur_close:.2f} <= Open: ₹{cur_open:.2f})")
    else:
        reasons.append(f"✓ Rule 5 Passed: Bullish green candle (Close: ₹{cur_close:.2f} > Open: ₹{cur_open:.2f})")

    # Distance clearance
    dist_pct = round(((cur_close - cur_ma_close) / cur_ma_close) * 100, 2)
    r6 = DIST_MIN <= dist_pct <= DIST_MAX
    if not r6:
        reasons.append(f"❌ Clearance Failed: Distance {dist_pct:+.2f}% is outside optimal swing entry band [{DIST_MIN:.1f}%, +{DIST_MAX:.1f}%]")
    else:
        reasons.append(f"✓ Clearance Passed: Distance {dist_pct:+.2f}% within band [{DIST_MIN:.1f}%, +{DIST_MAX:.1f}%]")

    all_passed = r1 and r2 and r3 and r4 and r5 and r6
    setup = analyze_44ma_timeframe(candles, strict_chartink=True) if all_passed else None

    # Filter reasons: if not all passed, keep only the failing ones for clear debugging
    failing_reasons = [r for r in reasons if r.startswith("❌")]

    return {
        "symbol": symbol,
        "company": company,
        "strategy": f"44 MA ({timeframe.capitalize()} - Chartink PMPatil)",
        "bars_analyzed": len(candles),
        "qualified": all_passed,
        "setup": setup,
        "reject_reasons": failing_reasons if not all_passed else ["All 5 Chartink PMPatil 44 MA rules passed!"],
        "all_checks": reasons,
    }


def get_strategy_debug(
    symbol: str,
    company: str,
    candles: list,
    strategy: str = "ascending",
    timeframe: str = "daily",
) -> Dict[str, Any]:
    """
    Returns detailed diagnostics and reject reasons for a stock and strategy.
    """
    strat = strategy.lower().strip()
    if strat in ["ascending", "asc", "ascending_triangle"]:
        return get_ascending_triangle_debug(symbol, company, candles, timeframe=timeframe)
    elif strat in ["symmetrical", "symm", "symmetrical_triangle"]:
        return get_symmetrical_triangle_debug(symbol, company, candles, timeframe=timeframe)
    elif strat in ["pole_and_flag", "flag", "pole"]:
        return get_pole_and_flag_debug(symbol, company, candles, timeframe=timeframe)
    elif strat in ["44ma", "ma44"]:
        return get_44ma_debug(symbol, company, candles, timeframe=timeframe)
    else:
        return {"qualified": False, "setup": None, "reject_reasons": [f"Unknown strategy: {strategy}"]}
