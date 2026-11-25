"""
patterns/pole_and_flag.py — Bull Pole & Flag Momentum Continuation Strategy
===========================================================================
Strict institutional rules (Daily and Weekly):
  DAILY:
    - Pole: impulsive rise >= 12% (close-to-close) over 5-15 bars, >= 60% green bars, ends at swing high
    - Pole volume: average volume >= 1.3x 20-bar average before pole
    - Flag: 5-20 bars after pole top, retracement <= 50% of pole height, no close below pole base
    - Flag shape: parallel-ish channels sloping down or sideways (slope between -0.4% and +0.1%/bar)
    - Both lines fit with R² >= 0.5, slope difference <= 0.15%/bar (parallel check)
    - Flag volume: average volume < 80% of pole volume (volume contraction)
    - Breakout: close above upper flag line * 1.002 within last 2 bars, volume >= 1.3x 20-bar avg, close <= upper * 1.03
    - Retest entry: breakout 2-8 bars ago, pullback to upper line tolerance, close back above
    - Stop-loss: below flag low - 0.5 * ATR (direct) or below retest low - 0.5 * ATR (retest)
    - Target: breakout price + pole height, minimum R:R 2.0 (reject if below)
  WEEKLY:
    - Pole: rise >= 20% over 3-8 bars, >= 60% green, volume >= 1.3x 20-bar avg
    - Flag: 3-10 bars, retracement <= 50%
    - Volume contraction: flag volume < 80% of pole volume
    - Breakout / Retest / Stop / Target rules with weekly thresholds, min R:R 2.0
"""

from typing import Optional, Dict, Any, List, Tuple
import numpy as np
from patterns.config import (
    FLAG_DAILY_POLE_MIN_RISE,
    FLAG_DAILY_POLE_MIN_BARS,
    FLAG_DAILY_POLE_MAX_BARS,
    FLAG_POLE_GREEN_RATIO,
    FLAG_POLE_VOL_MULT,
    FLAG_DAILY_FLAG_MIN_BARS,
    FLAG_DAILY_FLAG_MAX_BARS,
    FLAG_MAX_RETRACE,
    FLAG_SLOPE_NORM_MIN,
    FLAG_SLOPE_NORM_MAX,
    FLAG_MIN_R2,
    FLAG_MAX_SLOPE_DIFF_NORM,
    FLAG_VOL_CONTRACTION_MAX,
    FLAG_BREAKOUT_PRICE_BUFFER,
    FLAG_BREAKOUT_VOL_MULT,
    FLAG_MAX_CHASE_PCT,
    FLAG_RETEST_LOOKBACK_MIN,
    FLAG_RETEST_LOOKBACK_MAX,
    FLAG_FORMING_BAND_PCT,
    FLAG_MIN_RR,
    FLAG_WEEKLY_POLE_MIN_RISE,
    FLAG_WEEKLY_POLE_MIN_BARS,
    FLAG_WEEKLY_POLE_MAX_BARS,
    FLAG_WEEKLY_FLAG_MIN_BARS,
    FLAG_WEEKLY_FLAG_MAX_BARS,
)
from patterns.geometry import (
    atr,
    confirmed_pivots,
    fit_line_through_pivots,
    touches_on_line,
    line_value,
    compute_tolerance,
)


def detect_pole_and_flag(
    symbol: str,
    company: str,
    candles: list,
    timeframe: str = "daily",
) -> Optional[Dict[str, Any]]:
    """
    Detects Pole and Flag pattern for Daily or Weekly timeframe.
    Returns setup dictionary or None if rejected.
    """
    is_weekly = (timeframe.lower() == "weekly")

    pole_min_rise = FLAG_WEEKLY_POLE_MIN_RISE if is_weekly else FLAG_DAILY_POLE_MIN_RISE
    pole_min_bars = FLAG_WEEKLY_POLE_MIN_BARS if is_weekly else FLAG_DAILY_POLE_MIN_BARS
    pole_max_bars = FLAG_WEEKLY_POLE_MAX_BARS if is_weekly else FLAG_DAILY_POLE_MAX_BARS

    flag_min_bars = FLAG_WEEKLY_FLAG_MIN_BARS if is_weekly else FLAG_DAILY_FLAG_MIN_BARS
    flag_max_bars = FLAG_WEEKLY_FLAG_MAX_BARS if is_weekly else FLAG_DAILY_FLAG_MAX_BARS

    total_candles = len(candles)
    min_required_bars = pole_max_bars + flag_max_bars + 25
    if total_candles < min_required_bars:
        return None

    cur_atr = atr(candles, period=14)
    cmp_price = float(candles[-1][4])
    tolerance = compute_tolerance(cmp_price, cur_atr)

    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    opens = [float(c[1]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    # Find potential pole tops (swing highs) in the recent lookback
    # The flag itself must be between flag_min_bars and flag_max_bars long
    # So pole top must lie between flag_min_bars and flag_max_bars back from latest bar
    last_idx = total_candles - 1
    best_setup = None

    for flag_len in range(flag_min_bars, flag_max_bars + 1):
        pole_top_idx = last_idx - flag_len
        if pole_top_idx < pole_max_bars + 20:
            continue

        # Pole top must be a swing high: local peak around pole_top_idx
        # Check window around pole_top_idx
        check_w = 2 if is_weekly else 3
        pole_top_high = highs[pole_top_idx]
        is_local_high = (pole_top_high == max(highs[max(0, pole_top_idx - check_w) : min(total_candles, pole_top_idx + check_w + 1)]))
        if not is_local_high:
            continue

        pole_top_close = closes[pole_top_idx]

        # Scan possible pole bases (5 to 15 bars before pole top for daily, 3 to 8 for weekly)
        for pole_len in range(pole_min_bars, pole_max_bars + 1):
            pole_base_idx = pole_top_idx - pole_len
            if pole_base_idx < 20:
                continue

            pole_base_close = closes[pole_base_idx]
            pole_base_low = lows[pole_base_idx]

            # 1. Pole rise check: impulsive close-to-close rise
            pole_rise = (pole_top_close - pole_base_close) / pole_base_close
            if pole_rise < pole_min_rise:
                continue

            # 2. Green candle check: at least 60% of pole bars are green
            pole_candles_closes = closes[pole_base_idx : pole_top_idx + 1]
            pole_candles_opens = opens[pole_base_idx : pole_top_idx + 1]
            green_bars = sum(1 for c, o in zip(pole_candles_closes, pole_candles_opens) if c > o)
            if (green_bars / len(pole_candles_closes)) < FLAG_POLE_GREEN_RATIO:
                continue

            # 3. Pole volume check: avg volume during pole >= 1.3x 20-bar avg before pole
            pole_vols = volumes[pole_base_idx : pole_top_idx + 1]
            avg_pole_vol = float(np.mean(pole_vols))
            pre_pole_vols = volumes[max(0, pole_base_idx - 20) : pole_base_idx]
            avg_pre_vol = float(np.mean(pre_pole_vols)) if pre_pole_vols else 1.0

            if avg_pole_vol < (FLAG_POLE_VOL_MULT * avg_pre_vol):
                continue

            # 4. Flag analysis
            flag_candles = candles[pole_top_idx : last_idx + 1]
            flag_len_actual = len(flag_candles)
            if flag_len_actual < flag_min_bars or flag_len_actual > flag_max_bars:
                continue

            flag_closes = closes[pole_top_idx : last_idx + 1]
            flag_highs = highs[pole_top_idx : last_idx + 1]
            flag_lows = lows[pole_top_idx : last_idx + 1]
            flag_vols = volumes[pole_top_idx : last_idx + 1]

            pole_height = pole_top_high - pole_base_low
            min_flag_low = min(flag_lows)

            # Retracement check: <= 50% of pole height
            retrace_pct = (pole_top_high - min_flag_low) / pole_height if pole_height > 0 else 1.0
            if retrace_pct > FLAG_MAX_RETRACE:
                continue

            # Price must not close below pole base
            if any(c < pole_base_low for c in flag_closes):
                continue

            # 5. Flag volume contraction: average flag volume < 80% of pole volume
            avg_flag_vol = float(np.mean(flag_vols))
            if avg_flag_vol >= (FLAG_VOL_CONTRACTION_MAX * avg_pole_vol):
                continue

            # 6. Flag shape & trendlines:
            # Fit upper line through flag highs and lower line through flag lows
            # In small flags (5-20 bars), find swing points with window=1 or 2
            f_pivot_w = 1 if flag_len_actual < 8 else 2
            sh_flag, sl_flag = confirmed_pivots(flag_highs, flag_lows, window=f_pivot_w, min_separation=2)

            # If not enough pivots, use local peak slices
            if len(sh_flag) < 2:
                sh_flag = [(0, flag_highs[0]), (flag_len_actual - 1, max(flag_highs[-3:]))]
            if len(sl_flag) < 2:
                sl_flag = [(0, flag_lows[0]), (flag_len_actual - 1, min(flag_lows[-3:]))]

            avg_flag_price = float(np.mean(flag_closes))
            upper_slope, upper_intercept, upper_r2, _ = fit_line_through_pivots(sh_flag)
            lower_slope, lower_intercept, lower_r2, _ = fit_line_through_pivots(sl_flag)

            norm_upper_slope = upper_slope / avg_flag_price
            norm_lower_slope = lower_slope / avg_flag_price

            # Slopes must be down or sideways: between -0.4% and +0.1% per bar
            if not (FLAG_SLOPE_NORM_MIN <= norm_upper_slope <= FLAG_SLOPE_NORM_MAX):
                continue
            if not (FLAG_SLOPE_NORM_MIN <= norm_lower_slope <= FLAG_SLOPE_NORM_MAX):
                continue

            # Fit quality
            if upper_r2 < FLAG_MIN_R2 and lower_r2 < FLAG_MIN_R2:
                continue

            # Parallel check: slope difference <= 0.15% per bar
            if abs(norm_upper_slope - norm_lower_slope) > FLAG_MAX_SLOPE_DIFF_NORM:
                continue

            # 7. Status classification
            cur_close = flag_closes[-1]
            cur_vol = flag_vols[-1]
            v_20 = float(np.mean(volumes[last_idx - 20 : last_idx])) if last_idx >= 20 else avg_pre_vol

            flag_last_x = flag_len_actual - 1
            upper_line_now = upper_slope * flag_last_x + upper_intercept
            lower_line_now = lower_slope * flag_last_x + lower_intercept

            status = None
            entry_type = None
            entry_price = None
            stop_loss = None
            breakout_date = None
            breakout_idx = None

            # Confirmed Breakout: within last 2 bars
            for b_offset in [1, 2]:
                b_idx_in_flag = flag_len_actual - b_offset
                b_close = flag_closes[b_idx_in_flag]
                b_vol = flag_vols[b_idx_in_flag]
                b_upper = upper_slope * b_idx_in_flag + upper_intercept
                b_global_idx = pole_top_idx + b_idx_in_flag
                b_v20 = float(np.mean(volumes[max(0, b_global_idx - 20) : b_global_idx])) if b_global_idx > 0 else v_20

                if b_close > (b_upper * (1.0 + FLAG_BREAKOUT_PRICE_BUFFER)):
                    if b_vol >= (FLAG_BREAKOUT_VOL_MULT * b_v20):
                        if cur_close <= (b_upper * (1.0 + FLAG_MAX_CHASE_PCT)):
                            status = "Pole & Flag Breakout"
                            entry_type = "Flag Breakout Direct"
                            entry_price = round(cur_close, 2)
                            breakout_date = flag_candles[b_idx_in_flag][0]
                            breakout_idx = b_idx_in_flag
                            # Stop-loss below flag low minus 0.5 * ATR
                            stop_loss = round(min_flag_low - (0.5 * cur_atr), 2)
                            break

            # Retest Entry: breakout occurred 2-8 bars ago, pullback to upper line tolerance, close back above
            if not status and flag_len_actual >= (FLAG_RETEST_LOOKBACK_MAX + 1):
                for r_offset in range(FLAG_RETEST_LOOKBACK_MIN, FLAG_RETEST_LOOKBACK_MAX + 1):
                    prior_idx_flag = flag_len_actual - 1 - r_offset
                    if prior_idx_flag < 0:
                        break
                    p_close = flag_closes[prior_idx_flag]
                    p_upper = upper_slope * prior_idx_flag + upper_intercept
                    if p_close > (p_upper * (1.0 + FLAG_BREAKOUT_PRICE_BUFFER)):
                        intervening_lows = flag_lows[prior_idx_flag + 1 :]
                        retest_low = min(intervening_lows)
                        if abs(retest_low - upper_line_now) <= tolerance or retest_low <= (upper_line_now + tolerance):
                            if cur_close >= upper_line_now:
                                status = "Pole & Flag Retest"
                                entry_type = "Flag Retest Entry"
                                entry_price = round(cur_close, 2)
                                breakout_date = flag_candles[prior_idx_flag][0]
                                stop_loss = round(retest_low - (0.5 * cur_atr), 2)
                                break

            # Forming Watchlist: within 2% below upper flag line
            if not status:
                if (upper_line_now * (1.0 - FLAG_FORMING_BAND_PCT)) <= cur_close < (upper_line_now * (1.0 + FLAG_BREAKOUT_PRICE_BUFFER)):
                    status = "Pole & Flag Forming"
                    entry_type = "Flag Forming Watchlist"
                    entry_price = round(upper_line_now * 1.002, 2)
                    stop_loss = round(min_flag_low - (0.5 * cur_atr), 2)

            if not status:
                continue

            # 8. Target & R:R
            # Target = breakout price + pole height
            target = round(entry_price + pole_height, 2)
            risk = entry_price - stop_loss
            if risk <= 0:
                continue

            rr = round((target - entry_price) / risk, 2)
            if rr < FLAG_MIN_RR:
                continue

            # Confidence score
            conf = 75
            if (green_bars / len(pole_candles_closes)) >= 0.70:
                conf += 5
            if avg_flag_vol < (0.65 * avg_pole_vol):
                conf += 5
            if upper_r2 >= 0.70:
                conf += 5
            if (upper_slope - lower_slope) <= 0.0005:
                conf += 5
            if status == "Pole & Flag Breakout":
                conf += 4
            conf = min(98, conf)

            # Chart line points
            flag_dates = [c[0] for c in flag_candles]
            upper_line_points = [
                {"time": flag_dates[0], "value": round(upper_slope * 0 + upper_intercept, 2)},
                {"time": flag_dates[-1], "value": round(upper_slope * (flag_len_actual - 1) + upper_intercept, 2)},
            ]
            lower_line_points = [
                {"time": flag_dates[0], "value": round(lower_slope * 0 + lower_intercept, 2)},
                {"time": flag_dates[-1], "value": round(lower_slope * (flag_len_actual - 1) + lower_intercept, 2)},
            ]

            abs_dist = abs(round(((cur_close - upper_line_now) / upper_line_now) * 100, 2))

            setup = {
                "symbol": symbol,
                "company": company,
                "pattern": "Pole & Flag",
                "status": status,
                "entry_type": entry_type,
                "cmp": round(cur_close, 2),
                "buy_price": entry_price,
                "stop_loss": stop_loss,
                "target": target,
                "risk_reward": f"1:{rr}",
                "rr_ratio": rr,
                "confidence": conf,
                "pole_base_price": round(pole_base_low, 2),
                "pole_top_price": round(pole_top_high, 2),
                "pole_base_date": candles[pole_base_idx][0],
                "pole_top_date": candles[pole_top_idx][0],
                "pole_height": round(pole_height, 2),
                "pole_rise_pct": round(pole_rise * 100, 2),
                "flag_high": round(max(flag_highs), 2),
                "flag_low": round(min_flag_low, 2),
                "resistance_level": round(upper_line_now, 2),
                "support_level": round(lower_line_now, 2),
                "timeframe": timeframe.capitalize(),
                "sparkline": [round(c, 2) for c in flag_closes[-12:]],
                "abs_distance": abs_dist,
                "distance_pct": round(((cur_close - upper_line_now) / upper_line_now) * 100, 2),
                "breakout_date": breakout_date,
                "upper_line_points": upper_line_points,
                "lower_line_points": lower_line_points,
                "flag_upper_line_points": upper_line_points,
                "flag_lower_line_points": lower_line_points,
                "reject_reasons": [],
            }

            if best_setup is None or setup["confidence"] > best_setup["confidence"]:
                best_setup = setup

    return best_setup


def get_pole_and_flag_debug(
    symbol: str, company: str, candles: list, timeframe: str = "daily"
) -> Dict[str, Any]:
    """Helper for debug endpoint /api/debug/<symbol> showing reject reasons."""
    setup = detect_pole_and_flag(symbol, company, candles, timeframe=timeframe)
    if setup:
        return {"qualified": True, "setup": setup, "reject_reasons": []}

    reasons = []
    is_weekly = (timeframe.lower() == "weekly")
    min_rise = FLAG_WEEKLY_POLE_MIN_RISE if is_weekly else FLAG_DAILY_POLE_MIN_RISE
    reasons.append(
        f"No qualifying pole & flag found (requires >={min_rise*100}% pole rise, >=60% green candles, volume >=1.3x, flag retrace <=50%, parallel channel slope -0.4% to +0.1%, R:R >= 2.0)"
    )
    return {"qualified": False, "setup": None, "reject_reasons": reasons}
