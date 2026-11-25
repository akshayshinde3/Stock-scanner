"""
strategies.py — 44 MA Scanner & Breakout Chart Pattern Engines
==============================================================
Institutional Strategy Suite for Indian Equities (NSE / Nifty 500, 100, 50):
  1. 44 MA TOUCH & NEAR SCANNER (Daily & Weekly):
     - MA44: 44-period simple moving average of Close on that timeframe.
     - Distance %: (Close - MA44) / MA44 * 100
     - Fixed Distance Band: -1.0% <= Distance % <= +3.0% ONLY.
     - TOUCH: Low <= MA44 <= High (must also close within -1% to +3% band).
     - Status badges (first match wins):
         1. "Touching" (Blue): TOUCH true.
         2. "Above (0–3%)" (Green): Close >= MA44 and Distance <= +3.0%.
         3. "Near Below (−1–0%)" (Orange): Close < MA44 and Distance >= -1.0%.
     - MA44 Rising Only: today's MA44 > MA44 5 bars ago.
     - Green Candle Only: Close > Open.
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
import pandas as pd
import numpy as np

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
# 1. 44 MA TOUCH & NEAR ENGINE (Discrete Named Functions)
# ═══════════════════════════════════════════════════════════════════════════

def calculate_ma44(closes: list) -> list:
    """Calculates 44-period Simple Moving Average of Close series."""
    if len(closes) < MA_PERIOD:
        return [None] * len(closes)

    s = pd.Series(closes)
    ma = s.rolling(window=MA_PERIOD).mean()
    return [None if pd.isna(v) else round(float(v), 2) for v in ma]


def is_touch(low: float, high: float, ma44: float) -> bool:
    """TOUCH = Low <= MA44 <= High"""
    if ma44 is None or low is None or high is None:
        return False
    return low <= ma44 <= high


def is_in_44ma_band(dist_pct: float) -> bool:
    """A stock qualifies ONLY if -1.0 <= Distance % <= +3.0."""
    if dist_pct is None:
        return False
    return DIST_MIN <= dist_pct <= DIST_MAX


def get_status(touch: bool, close: float, ma44: float, dist_pct: float) -> Optional[str]:
    """
    Status badges (first match wins, strictly within -1.0% to +3.0% band):
      1. 'Touching' (Blue): TOUCH true (and -1.0 <= Distance % <= +3.0).
      2. 'Above (0–3%)' (Green): Close >= MA44 and Distance % <= +3.0.
      3. 'Near Below (−1–0%)' (Orange): Close < MA44 and Distance % >= -1.0.
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


def is_ma44_rising(ma44_series: list, bars_back: int = MA_RISING_BARS) -> bool:
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


def analyze_44ma_timeframe(candles: list) -> Optional[dict]:
    """
    Analyzes a candle series for 44 MA Touch & Near conditions strictly within -1% to +3%.
    Candles structure: [date, open, high, low, close, volume]
    """
    if not candles or len(candles) < MA_PERIOD:
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

    # Core Rule: MUST fall strictly in [-1.0, +3.0]
    if not is_in_44ma_band(dist_pct):
        return None

    touch = is_touch(cur_low, cur_high, current_ma)
    status_label = get_status(touch, cur_close, current_ma, dist_pct)
    if not status_label:
        return None

    ma_rising = is_ma44_rising(ma_series, bars_back=MA_RISING_BARS)
    green_candle = is_green_candle(cur_open, cur_close)

    prev_close = closes[-2] if len(closes) >= 2 else cur_open
    day_change_pct = round(((cur_close - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

    recent_vol = sum(volumes[-5:]) if len(volumes) >= 5 else sum(volumes)
    sparkline = [round(c, 2) for c in closes[-12:]]

    # Calculate stop loss & target for swing trade clarity:
    # Stop below 44 MA or low of recent support minus buffer
    cur_atr = atr(candles, period=14)
    stop_loss = round(min(current_ma * 0.985, cur_low - 0.5 * cur_atr), 2)
    risk = cur_close - stop_loss
    if risk <= 0:
        stop_loss = round(cur_close * 0.98, 2)
        risk = cur_close - stop_loss
    target = round(cur_close + 3.0 * risk, 2)

    return {
        "cmp": round(cur_close, 2),
        "ma44": round(current_ma, 2),
        "distance_pct": dist_pct,
        "status": status_label,
        "day_change_pct": day_change_pct,
        "volume": int(cur_vol),
        "weekly_volume": int(recent_vol),
        "ma44_rising": ma_rising,
        "green_candle": green_candle,
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
    rising_only: bool = False,
    green_only: bool = False,
    **kwargs,  # Gracefully ignore deprecated max_above / max_below args
) -> Optional[dict]:
    """
    Evaluates both Daily and Weekly for the 44 MA Touch & Near conditions (-1.0% to +3.0%).
    Returns qualification status for 'Daily', 'Weekly', or 'Both'.
    """
    d_res = analyze_44ma_timeframe(daily_candles) if daily_candles else None
    w_res = analyze_44ma_timeframe(weekly_candles) if weekly_candles else None

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
        "daily_data": d_res if d_qualifies else None,
        "weekly_data": w_res if w_qualifies else None,
        "abs_distance": abs(primary["distance_pct"]),
        "confidence": 85 if timeframe_badge == "Both" else 75,
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
        d_res = analyze_44ma_timeframe(candles)
        if d_res:
            return {"qualified": True, "setup": d_res, "reject_reasons": []}
        closes = [c[4] for c in candles] if candles else []
        ma44 = calculate_ma44(closes) if len(closes) >= MA_PERIOD else []
        cur_ma = ma44[-1] if ma44 else None
        cur_close = closes[-1] if closes else None
        dist = round(((cur_close - cur_ma) / cur_ma) * 100, 2) if (cur_close and cur_ma) else None
        reasons = [
            f"Distance {dist}% outside required band [-1.0%, +3.0%]" if dist is not None else "Insufficient candle data for MA44"
        ]
        return {"qualified": False, "setup": None, "reject_reasons": reasons}
    else:
        return {"qualified": False, "setup": None, "reject_reasons": [f"Unknown strategy: {strategy}"]}
