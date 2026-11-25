"""
test_patterns.py — Pytest Unit Tests for Chart Patterns & 44 MA Geometry
========================================================================
Tests:
  1. Clean Ascending Triangle (Breakout & Retest, R:R >= 3.0)
  2. Clean Symmetrical Triangle (Coil Contraction, Volume Dry-up, Apex check)
  3. Clean Bull Pole & Flag (Daily & Weekly)
  4. Random Walk Data (Must produce ZERO false signals)
  5. 44 MA Distance Band (-1.0% to +3.0% strictly enforced)
"""

import datetime as dt
import numpy as np
import pytest
from patterns.geometry import (
    atr,
    confirmed_pivots,
    fit_line_through_pivots,
    touches_on_line,
    line_value,
    compute_tolerance,
)
from patterns.ascending_triangle import detect_ascending_triangle
from patterns.symmetrical_triangle import detect_symmetrical_triangle
from patterns.pole_and_flag import detect_pole_and_flag
from strategies import (
    is_in_44ma_band,
    get_status,
    calculate_ma44,
    evaluate_44ma_stock,
)


def _generate_synthetic_candle(date_str, o, h, l, c, v):
    return [date_str, round(float(o), 2), round(float(h), 2), round(float(l), 2), round(float(c), 2), int(v)]


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLEAN ASCENDING TRIANGLE TEST
# ═══════════════════════════════════════════════════════════════════════════
def test_clean_ascending_triangle():
    """
    Constructs a textbook ascending triangle:
      - 50 prior bars establishing an uptrend
      - Resistance flat at 100.0 (touches at 100.0, 99.9, 100.1)
      - Rising support from 90.0 -> 94.0 -> 97.0
      - Triangle height = 100.0 - 90.0 = 10.0 (10% of price)
      - Breakout candle closing at 100.4 (> 100.2) with 2x volume
      - Apex converges within 1-15 bars
    """
    candles = []
    start_date = dt.date(2023, 1, 1)

    # 1. Prior trend (50 bars rising from 70 to 95)
    price = 70.0
    for i in range(50):
        d_str = (start_date + dt.timedelta(days=i)).isoformat()
        price += 0.5
        candles.append(_generate_synthetic_candle(d_str, price - 0.2, price + 0.4, price - 0.5, price, 100000))

    # 2. Ascending Triangle Consolidation (45 bars)
    # Target shape:
    # Highs peak near 100.0 at bar 5, 20, 35
    # Lows rise: bar 0 at 90.0, bar 15 at 93.5, bar 30 at 96.5, bar 40 at 98.0
    # Resistance = 100.0, Support slope approx +0.20/bar
    pat_start = 50
    for i in range(45):
        d_str = (start_date + dt.timedelta(days=50 + i)).isoformat()
        day_in_pat = i

        # Calculate rising support and flat resistance bounds
        sup_lvl = 90.0 + (day_in_pat * 0.20)
        res_lvl = 100.0

        if day_in_pat in [5, 20, 35]:
            # Swing High touch near 100.0
            h = 100.0
            c = 99.6
            l = sup_lvl + 2.0
            o = 98.5
            v = 110000
        elif day_in_pat in [0, 14, 28, 38]:
            # Swing Low touch near rising support
            l = sup_lvl
            o = sup_lvl + 1.0
            c = sup_lvl + 1.5
            h = sup_lvl + 3.0
            v = 80000
        else:
            mid = (sup_lvl + res_lvl) / 2
            o = mid - 0.5
            c = mid + 0.5
            h = mid + 1.5
            l = mid - 1.5
            v = 90000

        candles.append(_generate_synthetic_candle(d_str, o, h, l, c, v))

    # 3. Breakout bar on final day (day 45)
    d_breakout = (start_date + dt.timedelta(days=95)).isoformat()
    candles.append(_generate_synthetic_candle(d_breakout, 99.8, 101.2, 99.5, 100.5, 250000))

    setup = detect_ascending_triangle("TEST_ASC", "Test Ascending Corp", candles, timeframe="daily")

    assert setup is not None, "Failed to detect clean ascending triangle"
    assert setup["pattern"] == "Ascending Triangle"
    assert setup["status"] in ["Confirmed Breakout", "Retest Entry"]
    assert setup["resistance_level"] == pytest.approx(100.0, rel=0.015)
    assert setup["triangle_height"] >= 3.0
    assert setup["rr_ratio"] >= 3.0, f"R:R {setup['rr_ratio']} must be >= 3.0"
    assert len(setup["upper_touches"]) >= 2
    assert len(setup["lower_touches"]) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# 2. CLEAN SYMMETRICAL TRIANGLE TEST
# ═══════════════════════════════════════════════════════════════════════════
def test_clean_symmetrical_triangle():
    """
    Constructs a clean symmetrical triangle:
      - 45 bars consolidation starting at x=0
      - Upper line descending from 110.0 to 102.0
      - Lower line ascending from 90.0 to 98.0
      - Base height = 20.0 (wide)
      - Contraction in last 1/3 range (>= 25% smaller)
      - Volume dry-up in last 1/3 (< 85% of first 1/3)
      - Apex around bar 55; Breakout at bar 42 (between 50% and 85% to apex)
      - Breakout bar with volume expansion
    """
    candles = []
    start_date = dt.date(2023, 1, 1)

    # 40 baseline bars
    p = 95.0
    for i in range(40):
        d_str = (start_date + dt.timedelta(days=i)).isoformat()
        candles.append(_generate_synthetic_candle(d_str, p, p + 1.5, p - 1.5, p + 0.2, 120000))

    # 45 triangle bars
    # res(x) = 110.0 - 0.18 * x
    # sup(x) = 90.0 + 0.18 * x
    # Apex intersection: 110 - 0.18x = 90 + 0.18x => 0.36x = 20 => x_apex = 55.5
    # Progress at bar 42: 42 / 55.5 = 75.6% (within 50% to 85%)
    for i in range(42):
        d_str = (start_date + dt.timedelta(days=40 + i)).isoformat()
        upper = 110.0 - (0.18 * i)
        lower = 90.0 + (0.18 * i)

        # Volume drying up from 150k down to 70k
        vol = int(150000 - (i * 2000))

        if i in [2, 16, 28]:
            # Swing High touch
            h = upper
            l = lower + 3.0
            o = upper - 1.0
            c = upper - 0.4
        elif i in [6, 20, 32]:
            # Swing Low touch
            l = lower
            h = upper - 3.0
            o = lower + 0.5
            c = lower + 1.0
        else:
            mid = (upper + lower) / 2
            half_rng = max(1.0, (upper - lower) * 0.25)
            h = mid + half_rng
            l = mid - half_rng
            o = mid - 0.2
            c = mid + 0.2

        candles.append(_generate_synthetic_candle(d_str, o, h, l, c, vol))

    # Breakout bar on bar 42
    upper_at_bo = 110.0 - (0.18 * 42) # ~102.44
    d_bo = (start_date + dt.timedelta(days=82)).isoformat()
    candles.append(_generate_synthetic_candle(d_bo, upper_at_bo - 0.2, upper_at_bo + 1.5, upper_at_bo - 0.5, upper_at_bo + 0.8, 250000))

    setup = detect_symmetrical_triangle("TEST_SYM", "Test Symmetrical Corp", candles, timeframe="daily")

    assert setup is not None, "Failed to detect clean symmetrical triangle"
    assert setup["pattern"] == "Symmetrical Triangle"
    assert setup["status"] == "Confirmed Breakout"
    assert setup["rr_ratio"] >= 2.5, f"R:R {setup['rr_ratio']} must be >= 2.5"
    assert len(setup["upper_touches"]) >= 2
    assert len(setup["lower_touches"]) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# 3. CLEAN BULL POLE & FLAG TEST
# ═══════════════════════════════════════════════════════════════════════════
def test_clean_pole_and_flag():
    """
    Constructs a clean bull pole and flag:
      - 25 base bars around 100.0 with 80k avg volume
      - Pole: 8 bars surging from 100.0 to 118.0 (+18% > 12%), all green, 180k volume (> 1.3x)
      - Flag: 8 bars consolidating between 114.0 and 117.0 (retrace ~22% < 50%)
      - Flag volume: 60k (< 80% of pole volume)
      - Breakout bar above upper flag line with volume surge
    """
    candles = []
    start_date = dt.date(2023, 1, 1)

    # 25 base bars
    for i in range(25):
        d_str = (start_date + dt.timedelta(days=i)).isoformat()
        candles.append(_generate_synthetic_candle(d_str, 99.5, 100.5, 99.0, 100.0, 80000))

    # Pole: 8 bars rising from 100.0 to 118.0
    p = 100.0
    for i in range(8):
        d_str = (start_date + dt.timedelta(days=25 + i)).isoformat()
        o = p
        p += 2.25
        c = p
        h = p + 0.4
        l = o - 0.2
        candles.append(_generate_synthetic_candle(d_str, o, h, l, c, 180000))

    # Flag: 8 bars drifting slightly downwards from 118 to 115
    flag_p = 117.5
    for i in range(8):
        d_str = (start_date + dt.timedelta(days=33 + i)).isoformat()
        upper = 118.0 - (0.25 * i)
        lower = 116.0 - (0.25 * i)
        o = (upper + lower) / 2
        c = o - 0.3
        h = upper
        l = lower
        candles.append(_generate_synthetic_candle(d_str, o, h, l, c, 60000))

    # Breakout bar on day 9
    upper_now = 118.0 - (0.25 * 8) # 116.0
    d_bo = (start_date + dt.timedelta(days=41)).isoformat()
    candles.append(_generate_synthetic_candle(d_bo, upper_now - 0.1, upper_now + 2.0, upper_now - 0.3, upper_now + 1.2, 200000))

    setup = detect_pole_and_flag("TEST_FLAG", "Test Flag Corp", candles, timeframe="daily")

    assert setup is not None, "Failed to detect clean pole and flag"
    assert setup["pattern"] == "Pole & Flag"
    assert setup["status"] == "Pole & Flag Breakout"
    assert setup["pole_rise_pct"] >= 12.0
    assert setup["rr_ratio"] >= 2.0


# ═══════════════════════════════════════════════════════════════════════════
# 4. RANDOM WALK TEST (MUST PRODUCE ZERO SIGNALS)
# ═══════════════════════════════════════════════════════════════════════════
def test_random_walk_produces_zero_signals():
    """
    A 150-bar random walk with noise should NOT trigger any pattern breakout.
    """
    np.random.seed(42)
    start_date = dt.date(2023, 1, 1)

    price = 100.0
    candles = []
    for i in range(150):
        d_str = (start_date + dt.timedelta(days=i)).isoformat()
        ret = np.random.normal(0, 0.015)
        price = price * (1.0 + ret)
        rng = price * np.random.uniform(0.008, 0.02)
        h = price + rng / 2
        l = price - rng / 2
        o = price - (ret * price * 0.5)
        c = price
        v = int(np.random.uniform(50000, 150000))
        candles.append(_generate_synthetic_candle(d_str, o, h, l, c, v))

    asc = detect_ascending_triangle("RAND_WALK", "Random Walk Corp", candles, timeframe="daily")
    sym = detect_symmetrical_triangle("RAND_WALK", "Random Walk Corp", candles, timeframe="daily")
    flag = detect_pole_and_flag("RAND_WALK", "Random Walk Corp", candles, timeframe="daily")

    assert asc is None, f"Ascending triangle falsely triggered on random walk: {asc}"
    assert sym is None, f"Symmetrical triangle falsely triggered on random walk: {sym}"
    assert flag is None, f"Pole & Flag falsely triggered on random walk: {flag}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. 44 MA SCANNER DISTANCE BAND TEST (-1.0% TO +3.0%)
# ═══════════════════════════════════════════════════════════════════════════
def test_44ma_strict_band():
    """
    Tests that:
      - Stocks outside -1.0% to +3.0% are strictly excluded.
      - A touch with Close > +3.0% or Close < -1.0% does NOT qualify.
      - Correct status badges are assigned.
    """
    # 1. Band verification
    assert is_in_44ma_band(-1.0) is True
    assert is_in_44ma_band(0.0) is True
    assert is_in_44ma_band(3.0) is True
    assert is_in_44ma_band(-1.01) is False
    assert is_in_44ma_band(3.01) is False
    assert is_in_44ma_band(5.0) is False

    # 2. Status badge logic
    # Touching (Low <= MA <= High, and inside band)
    status_touch = get_status(touch=True, close=101.0, ma44=100.0, dist_pct=1.0)
    assert status_touch == "Touching"

    # Touching but Close outside band (+4%) -> must be None (excluded!)
    status_touch_excluded = get_status(touch=True, close=104.0, ma44=100.0, dist_pct=4.0)
    assert status_touch_excluded is None

    # Above (0-3%)
    status_above = get_status(touch=False, close=102.5, ma44=100.0, dist_pct=2.5)
    assert status_above == "Above (0–3%)"

    # Near Below (-1-0%)
    status_below = get_status(touch=False, close=99.2, ma44=100.0, dist_pct=-0.8)
    assert status_below == "Near Below (−1–0%)"

    # Far Below (-2.5%) -> Excluded
    status_far_below = get_status(touch=False, close=97.5, ma44=100.0, dist_pct=-2.5)
    assert status_far_below is None
