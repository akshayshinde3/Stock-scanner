"""
patterns/geometry.py — Shared Pivot and Geometry Engine
========================================================
Reusable mathematical and geometric utilities for chart pattern analysis:
  - ATR (Average True Range)
  - Confirmed Pivots (Swing Highs and Swing Lows with separation)
  - Ordinary Least Squares Line Fitting with Close Violation Checks
  - Pivot Touches on Lines
  - Line Value helper
  - Pandas Weekly Resampling ('W-FRI')
"""

from typing import List, Tuple, Optional, Union, Dict, Any
import numpy as np
import pandas as pd
from patterns.config import (
    DEFAULT_PIVOT_WINDOW,
    DEFAULT_MIN_SEPARATION,
    ATR_PERIOD,
    TOLERANCE_PRICE_PCT,
    TOLERANCE_ATR_MULT,
)


def atr(candles: Union[pd.DataFrame, list], period: int = ATR_PERIOD) -> float:
    """
    Computes the 14-period Average True Range (ATR) on the candle series.
    Returns the latest ATR value (float). If not enough data, returns 1.0% of latest close.
    """
    if candles is None or len(candles) < 2:
        return 1.0

    if isinstance(candles, pd.DataFrame):
        highs = candles["high"].values.astype(float)
        lows = candles["low"].values.astype(float)
        closes = candles["close"].values.astype(float)
    else:
        # Assumed format: [date, open, high, low, close, volume]
        highs = np.array([float(c[2]) for c in candles], dtype=float)
        lows = np.array([float(c[3]) for c in candles], dtype=float)
        closes = np.array([float(c[4]) for c in candles], dtype=float)

    n = len(closes)
    if n < 2:
        return float(closes[-1] * 0.01) if n == 1 else 1.0

    # True Range calculation
    tr = np.zeros(n, dtype=float)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    if n < period:
        return float(np.mean(tr))

    # Wilder's smoothing or simple rolling mean for ATR
    atr_vals = np.zeros(n, dtype=float)
    atr_vals[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period

    return float(atr_vals[-1])


def atr_series(candles: Union[pd.DataFrame, list], period: int = ATR_PERIOD) -> List[float]:
    """Returns the full ATR series as a list of floats matching candle indices."""
    if candles is None or len(candles) < 2:
        return [1.0] * (len(candles) if candles else 0)

    if isinstance(candles, pd.DataFrame):
        highs = candles["high"].values.astype(float)
        lows = candles["low"].values.astype(float)
        closes = candles["close"].values.astype(float)
    else:
        highs = np.array([float(c[2]) for c in candles], dtype=float)
        lows = np.array([float(c[3]) for c in candles], dtype=float)
        closes = np.array([float(c[4]) for c in candles], dtype=float)

    n = len(closes)
    tr = np.zeros(n, dtype=float)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    atr_vals = np.zeros(n, dtype=float)
    if n <= period:
        rolling = np.cumsum(tr) / (np.arange(n) + 1)
        return rolling.tolist()

    atr_vals[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period
    for i in range(period - 1):
        atr_vals[i] = atr_vals[period - 1]

    return atr_vals.tolist()


def confirmed_pivots(
    high: List[float],
    low: List[float],
    window: int = DEFAULT_PIVOT_WINDOW,
    min_separation: int = DEFAULT_MIN_SEPARATION,
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """
    Finds confirmed swing highs and swing lows with index and price.
    A pivot is confirmed only if it is the extreme over window bars on each side:
      high[i] == max(high[i - window : i + window + 1])
      low[i]  == min(low[i - window : i + window + 1])

    Enforces min_separation between same-type pivots: if two same-type pivots
    occur closer than min_separation, the more extreme price is retained.
    """
    n = len(high)
    raw_sh: List[Tuple[int, float]] = []
    raw_sl: List[Tuple[int, float]] = []

    if n < (2 * window + 1):
        return raw_sh, raw_sl

    for i in range(window, n - window):
        # Swing High
        window_highs = high[i - window : i + window + 1]
        if high[i] == max(window_highs):
            # Check strict local dominance to avoid flat ties across bars
            if high[i] > high[i - 1] or high[i] > high[i + 1] or (i == window):
                raw_sh.append((i, float(high[i])))

        # Swing Low
        window_lows = low[i - window : i + window + 1]
        if low[i] == min(window_lows):
            if low[i] < low[i - 1] or low[i] < low[i + 1] or (i == window):
                raw_sl.append((i, float(low[i])))

    # Enforce min_separation between same-type pivots
    def filter_separation(pivots: List[Tuple[int, float]], is_high: bool) -> List[Tuple[int, float]]:
        if not pivots:
            return []
        filtered: List[Tuple[int, float]] = [pivots[0]]
        for p in pivots[1:]:
            last_idx, last_price = filtered[-1]
            curr_idx, curr_price = p
            if (curr_idx - last_idx) < min_separation:
                # Keep the more extreme one
                if is_high:
                    if curr_price > last_price:
                        filtered[-1] = p
                else:
                    if curr_price < last_price:
                        filtered[-1] = p
            else:
                filtered.append(p)
        return filtered

    filtered_sh = filter_separation(raw_sh, is_high=True)
    filtered_sl = filter_separation(raw_sl, is_high=False)

    return filtered_sh, filtered_sl


def line_value(slope: float, intercept: float, i: Union[int, float]) -> float:
    """Helper returning line value at bar index i."""
    return float(slope * i + intercept)


def fit_line_through_pivots(
    points: List[Tuple[int, float]],
    window_closes: Optional[List[float]] = None,
    tolerance: Optional[float] = None,
    line_type: Optional[str] = None,  # 'upper', 'lower', or None
) -> Tuple[float, float, float, bool]:
    """
    Fits a linear regression line through the given pivot points (index, price).
    Returns (slope, intercept, R², is_valid).

    If window_closes and tolerance are provided:
      - For 'upper': no close in window can exceed (line_value + tolerance)
      - For 'lower': no close in window can fall below (line_value - tolerance)
      A violation marks is_valid = False.
    """
    n = len(points)
    if n < 2:
        val = points[0][1] if points else 0.0
        return 0.0, float(val), 0.0, False

    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)

    mean_x = np.mean(xs)
    mean_y = np.mean(ys)

    ss_xx = np.sum((xs - mean_x) ** 2)
    ss_xy = np.sum((xs - mean_x) * (ys - mean_y))

    if ss_xx == 0:
        slope = 0.0
        intercept = float(mean_y)
        r2 = 0.0
    else:
        slope = float(ss_xy / ss_xx)
        intercept = float(mean_y - slope * mean_x)

        ss_tot = np.sum((ys - mean_y) ** 2)
        fitted_ys = slope * xs + intercept
        ss_res = np.sum((ys - fitted_ys) ** 2)

        if ss_tot > 0:
            r2 = float(max(0.0, min(1.0, 1.0 - (ss_res / ss_tot))))
        else:
            r2 = 1.0

    # Check price bar violations across the window
    is_valid = True
    if window_closes is not None and tolerance is not None:
        tol = float(tolerance)
        for i, c in enumerate(window_closes):
            lvl = slope * i + intercept
            if line_type == "upper":
                if c > (lvl + tol):
                    is_valid = False
                    break
            elif line_type == "lower":
                if c < (lvl - tol):
                    is_valid = False
                    break

    return slope, intercept, r2, is_valid


def touches_on_line(
    pivots: List[Tuple[int, float]],
    slope: float,
    intercept: float,
    tolerance: float,
) -> List[Tuple[int, float]]:
    """
    Returns the list of pivots (index, price) that lie within tolerance of the fitted line.
    """
    touches: List[Tuple[int, float]] = []
    tol = float(tolerance)
    for p in pivots:
        idx, price = p
        expected = slope * idx + intercept
        if abs(price - expected) <= tol:
            touches.append(p)
    return touches


def compute_tolerance(price: float, atr_val: float) -> float:
    """
    Calculates tolerance:
      tolerance = max(0.4% of price, 0.35 * ATR)
    """
    pct_based = float(price) * TOLERANCE_PRICE_PCT
    atr_based = float(atr_val) * TOLERANCE_ATR_MULT
    return max(pct_based, atr_based)


def resample_to_weekly(daily_candles: list) -> list:
    """
    Resamples daily OHLCV candles to weekly candles using pandas resample('W-FRI').
    Aggregates:
      open: 'first'
      high: 'max'
      low: 'min'
      close: 'last'
      volume: 'sum'

    Returns list of weekly candles: [[date_str, open, high, low, close, volume], ...]
    """
    if not daily_candles or len(daily_candles) < 5:
        return []

    # Format check: each row is [date, open, high, low, close, volume]
    records = []
    for c in daily_candles:
        records.append({
            "date": str(c[0])[:10],
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": int(c[5]),
        })

    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["date"])
    df = df.set_index("datetime").sort_index()

    weekly_df = df.resample("W-FRI").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "date": "last"
    }).dropna(subset=["close"])

    weekly_candles = []
    for dt_idx, row in weekly_df.iterrows():
        # Use Friday or latest date in that week
        d_str = str(row["date"]) if pd.notna(row["date"]) else dt_idx.strftime("%Y-%m-%d")
        weekly_candles.append([
            d_str,
            round(float(row["open"]), 2),
            round(float(row["high"]), 2),
            round(float(row["low"]), 2),
            round(float(row["close"]), 2),
            int(row["volume"])
        ])

    return weekly_candles
