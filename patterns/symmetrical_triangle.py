"""
patterns/symmetrical_triangle.py — Symmetrical Triangle Coil Breakout Detector
=============================================================================
Strict institutional implementation:
  - Pattern window: 30-90 daily bars or 15-40 weekly bars starting at first confirmed pivot
  - Upper descending line: normalized slope <= -0.05%/bar, R² >= 0.6, >= 2 confirmed touches
  - Lower ascending line: normalized slope >= +0.05%/bar, R² >= 0.6, >= 2 confirmed touches
  - No close violates either line by more than tolerance
  - Apex intersection: breakout occurs between 50% and 85% of pattern start to apex (reject if after apex)
  - Volatility contraction: last 1/3 average range (H-L) <= 75% of first 1/3 (>=25% smaller)
  - Volume dry-up: last 1/3 average volume < 85% of first 1/3
  - Base height = upper line - lower line at start (x=0) >= 4% of price
  - Status: Confirmed Breakout, Retest Entry, or Forming (Watchlist)
  - Stop-loss: below tighter of last swing low or lower line, below breakout low - 0.5 * ATR
  - Target = breakout level + base height (minimum R:R 2.5, reject if below, no inflating)
"""

from typing import Optional, Dict, Any, List, Tuple
import numpy as np
from patterns.config import (
    SYM_MIN_DAILY_BARS,
    SYM_MAX_DAILY_BARS,
    SYM_MIN_WEEKLY_BARS,
    SYM_MAX_WEEKLY_BARS,
    SYM_RES_MAX_SLOPE_NORM,
    SYM_SUP_MIN_SLOPE_NORM,
    SYM_MIN_R2,
    SYM_APEX_PROGRESS_MIN,
    SYM_APEX_PROGRESS_MAX,
    SYM_RANGE_CONTRACTION_MAX,
    SYM_VOLUME_DRYUP_MAX,
    SYM_MIN_BASE_HEIGHT_PCT,
    SYM_BREAKOUT_PRICE_BUFFER,
    SYM_BREAKOUT_VOL_MULT,
    SYM_MAX_CHASE_PCT,
    SYM_RETEST_LOOKBACK_MIN,
    SYM_RETEST_LOOKBACK_MAX,
    SYM_FORMING_BAND_PCT,
    SYM_STOP_ATR_MULT,
    SYM_MIN_RR,
)
from patterns.geometry import (
    atr,
    confirmed_pivots,
    fit_line_through_pivots,
    touches_on_line,
    line_value,
    compute_tolerance,
)


def detect_symmetrical_triangle(
    symbol: str,
    company: str,
    candles: list,
    timeframe: str = "daily",
    pivot_window: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Detects a Symmetrical Triangle (Coil) according to strict geometric, contraction,
    volume dry-up, apex, and breakout rules.
    """
    is_weekly = (timeframe.lower() == "weekly")
    min_bars = SYM_MIN_WEEKLY_BARS if is_weekly else SYM_MIN_DAILY_BARS
    max_bars = SYM_MAX_WEEKLY_BARS if is_weekly else SYM_MAX_DAILY_BARS

    total_candles = len(candles)
    if total_candles < (min_bars + 10):
        return None

    cur_atr = atr(candles, period=14)
    cmp_price = float(candles[-1][4])
    tolerance = compute_tolerance(cmp_price, cur_atr)

    reject_reasons: List[str] = []

    # Deterministic pattern start search:
    eval_slice_len = min(total_candles, max_bars + 20)
    eval_candles = candles[-eval_slice_len:]
    eval_highs = [float(c[2]) for c in eval_candles]
    eval_lows = [float(c[3]) for c in eval_candles]
    eval_closes = [float(c[4]) for c in eval_candles]
    eval_volumes = [float(c[5]) for c in eval_candles]

    all_sh, all_sl = confirmed_pivots(
        eval_highs, eval_lows, window=pivot_window, min_separation=4
    )

    if len(all_sh) < 2 or len(all_sl) < 2:
        return None

    last_idx = len(eval_candles) - 1
    candidate_starts = []
    for p_idx, _ in all_sh + all_sl:
        bars_back = last_idx - p_idx
        if min_bars <= bars_back <= max_bars:
            candidate_starts.append(p_idx)

    if not candidate_starts:
        for p_idx, _ in all_sh + all_sl:
            bars_back = last_idx - p_idx
            if bars_back >= min_bars:
                candidate_starts.append(p_idx)

    if not candidate_starts:
        return None

    candidate_starts = sorted(list(set(candidate_starts)))
    best_setup = None

    for start_idx in candidate_starts:
        pattern_window = eval_candles[start_idx:]
        pat_len = len(pattern_window)
        if pat_len < min_bars or pat_len > max_bars:
            continue

        window_highs = [float(c[2]) for c in pattern_window]
        window_lows = [float(c[3]) for c in pattern_window]
        window_closes = [float(c[4]) for c in pattern_window]
        window_volumes = [float(c[5]) for c in pattern_window]
        avg_price = float(np.mean(window_closes))

        # 1. Contraction check:
        # Range of last 1/3 at least 25% smaller than first 1/3
        third_len = pat_len // 3
        if third_len < 3:
            continue

        first_third_ranges = [window_highs[i] - window_lows[i] for i in range(third_len)]
        last_third_ranges = [window_highs[i] - window_lows[i] for i in range(pat_len - third_len, pat_len)]

        avg_range_first = float(np.mean(first_third_ranges))
        avg_range_last = float(np.mean(last_third_ranges))

        if avg_range_first <= 0 or (avg_range_last / avg_range_first) > SYM_RANGE_CONTRACTION_MAX:
            reject_reasons.append(f"Range contraction failed: last 1/3 ({avg_range_last:.2f}) > {SYM_RANGE_CONTRACTION_MAX*100}% of first 1/3 ({avg_range_first:.2f})")
            continue

        # 2. Volume dry-up check:
        # Last 1/3 volume < 85% of first 1/3
        avg_vol_first = float(np.mean(window_volumes[:third_len]))
        avg_vol_last = float(np.mean(window_volumes[pat_len - third_len :]))

        if avg_vol_first <= 0 or (avg_vol_last / avg_vol_first) >= SYM_VOLUME_DRYUP_MAX:
            reject_reasons.append(f"Volume dry-up failed: last 1/3 volume ({avg_vol_last:.0f}) >= {SYM_VOLUME_DRYUP_MAX*100}% of first 1/3 ({avg_vol_first:.0f})")
            continue

        # 3. Confirmed pivots in pattern
        sh_in_pat, sl_in_pat = confirmed_pivots(
            window_highs, window_lows, window=pivot_window, min_separation=4
        )

        if len(sh_in_pat) < 2 or len(sl_in_pat) < 2:
            reject_reasons.append("Insufficient confirmed pivots in pattern window")
            continue

        # 4. Fit upper descending line
        res_slope, res_intercept, res_r2, res_valid = fit_line_through_pivots(
            sh_in_pat, window_closes=window_closes, tolerance=tolerance, line_type="upper"
        )
        norm_res_slope = res_slope / avg_price

        if norm_res_slope > SYM_RES_MAX_SLOPE_NORM:
            reject_reasons.append(f"Upper line not descending: normalized slope {norm_res_slope:.5f} > {SYM_RES_MAX_SLOPE_NORM}")
            continue

        if res_r2 < SYM_MIN_R2:
            reject_reasons.append(f"Upper line R² {res_r2:.2f} < {SYM_MIN_R2}")
            continue

        if not res_valid:
            reject_reasons.append("Close in pattern violated upper descending line by more than tolerance")
            continue

        res_touches = touches_on_line(sh_in_pat, res_slope, res_intercept, tolerance)
        if len(res_touches) < 2:
            reject_reasons.append(f"Upper line has {len(res_touches)} touches, minimum 2 required")
            continue

        # 5. Fit lower ascending line
        sup_slope, sup_intercept, sup_r2, sup_valid = fit_line_through_pivots(
            sl_in_pat, window_closes=window_closes, tolerance=tolerance, line_type="lower"
        )
        norm_sup_slope = sup_slope / avg_price

        if norm_sup_slope < SYM_SUP_MIN_SLOPE_NORM:
            reject_reasons.append(f"Lower line not ascending: normalized slope {norm_sup_slope:.5f} < {SYM_SUP_MIN_SLOPE_NORM}")
            continue

        if sup_r2 < SYM_MIN_R2:
            reject_reasons.append(f"Lower line R² {sup_r2:.2f} < {SYM_MIN_R2}")
            continue

        if not sup_valid:
            reject_reasons.append("Close in pattern violated lower ascending line by more than tolerance")
            continue

        sup_touches = touches_on_line(sl_in_pat, sup_slope, sup_intercept, tolerance)
        if len(sup_touches) < 2:
            reject_reasons.append(f"Lower line has {len(sup_touches)} touches, minimum 2 required")
            continue

        # Combined touches: at least 3 total preferred
        total_touches = len(res_touches) + len(sup_touches)
        if total_touches < 4:
            # 2 on upper and 2 on lower = 4 minimum
            pass

        # 6. Base height at pattern start (x = 0)
        base_upper = res_slope * 0 + res_intercept
        base_lower = sup_slope * 0 + sup_intercept
        base_height = base_upper - base_lower

        if (base_height / avg_price) < SYM_MIN_BASE_HEIGHT_PCT:
            reject_reasons.append(f"Base height {base_height:.2f} ({(base_height/avg_price)*100:.2f}%) < {SYM_MIN_BASE_HEIGHT_PCT*100}%")
            continue

        # 7. Apex intersection calculation
        # res_slope * x + res_intercept = sup_slope * x + sup_intercept
        slope_diff = res_slope - sup_slope
        if abs(slope_diff) < 1e-9:
            reject_reasons.append("Trendlines are parallel; no apex intersection")
            continue

        x_apex = (sup_intercept - res_intercept) / slope_diff
        if x_apex <= 0:
            reject_reasons.append("Lines diverge; apex lies before pattern start")
            continue

        # 8. Status Classification
        cur_close = window_closes[-1]
        cur_vol = window_volumes[-1]
        v_20 = float(np.mean(window_volumes[-21:-1])) if len(window_volumes) >= 21 else float(np.mean(window_volumes))

        upper_now = line_value(res_slope, res_intercept, pat_len - 1)
        lower_now = line_value(sup_slope, sup_intercept, pat_len - 1)

        status = None
        entry_type = None
        entry_price = None
        stop_loss = None
        breakout_date = None
        breakout_bar_idx = None

        # Check Confirmed Breakout: within last 2 bars
        for b_offset in [1, 2]:
            b_idx = pat_len - b_offset
            b_close = window_closes[b_idx]
            b_vol = window_volumes[b_idx]
            b_upper = line_value(res_slope, res_intercept, b_idx)
            b_v20 = float(np.mean(window_volumes[max(0, b_idx - 20) : b_idx])) if b_idx > 0 else v_20

            if b_close > (b_upper * (1.0 + SYM_BREAKOUT_PRICE_BUFFER)):
                if b_vol >= (SYM_BREAKOUT_VOL_MULT * b_v20):
                    if cur_close <= (b_upper * (1.0 + SYM_MAX_CHASE_PCT)):
                        # Apex progress check: breakout must occur between 50% and 85% of distance to apex
                        apex_progress = b_idx / x_apex
                        if SYM_APEX_PROGRESS_MIN <= apex_progress <= SYM_APEX_PROGRESS_MAX:
                            status = "Confirmed Breakout"
                            entry_type = "Coil Breakout Entry"
                            entry_price = round(cur_close, 2)
                            breakout_date = pattern_window[b_idx][0]
                            breakout_bar_idx = b_idx
                            break
                        elif b_idx >= x_apex:
                            reject_reasons.append("Breakout occurred after the apex")
                        else:
                            reject_reasons.append(f"Apex progress {apex_progress:.2f} outside allowed 0.50–0.85")

        # Check Retest Entry: breakout 2 to 8 bars ago, pullback to upper line tolerance, close back above
        if not status and pat_len >= (SYM_RETEST_LOOKBACK_MAX + 2):
            for r_offset in range(SYM_RETEST_LOOKBACK_MIN, SYM_RETEST_LOOKBACK_MAX + 1):
                prior_idx = pat_len - 1 - r_offset
                if prior_idx < 0:
                    break
                p_close = window_closes[prior_idx]
                p_upper = line_value(res_slope, res_intercept, prior_idx)

                if p_close > (p_upper * (1.0 + SYM_BREAKOUT_PRICE_BUFFER)):
                    apex_progress = prior_idx / x_apex
                    if SYM_APEX_PROGRESS_MIN <= apex_progress <= SYM_APEX_PROGRESS_MAX:
                        intervening_lows = window_lows[prior_idx + 1 :]
                        retest_low = min(intervening_lows)
                        if abs(retest_low - upper_now) <= tolerance or retest_low <= (upper_now + tolerance):
                            if cur_close >= upper_now:
                                status = "Retest Entry"
                                entry_type = "Coil Retest Entry"
                                entry_price = round(cur_close, 2)
                                breakout_date = pattern_window[prior_idx][0]
                                breakout_bar_idx = prior_idx
                                stop_loss = round(retest_low - (SYM_STOP_ATR_MULT * cur_atr), 2)
                                break

        # Check Forming (Watchlist): within 1.5% below upper line, no breakout yet
        if not status:
            if (upper_now * (1.0 - SYM_FORMING_BAND_PCT)) <= cur_close < (upper_now * (1.0 + SYM_BREAKOUT_PRICE_BUFFER)):
                # Must also be before apex and ideally between 50% and 85%
                current_progress = (pat_len - 1) / x_apex
                if current_progress <= SYM_APEX_PROGRESS_MAX:
                    status = "Forming"
                    entry_type = "Coil Forming Watchlist"
                    entry_price = round(upper_now * 1.002, 2)
                    breakout_bar_idx = pat_len - 1

        if not status:
            reject_reasons.append("Price action does not meet Symmetrical Breakout, Retest, or Forming rules")
            continue

        # 9. Stop-Loss Calculation:
        # Below the last swing low inside the pattern or the lower line at breakout,
        # whichever is tighter (higher price, less risk), minus 0.5 * ATR.
        # Keep it below the breakout candle low.
        b_idx_eval = breakout_bar_idx if breakout_bar_idx is not None else (pat_len - 1)
        lower_line_at_breakout = line_value(sup_slope, sup_intercept, b_idx_eval)
        last_sl_price = sl_in_pat[-1][1]

        if stop_loss is None:
            tighter_support = max(last_sl_price, lower_line_at_breakout)
            raw_stop = tighter_support - (SYM_STOP_ATR_MULT * cur_atr)
            # Ensure it is below the breakout candle low
            breakout_low = window_lows[b_idx_eval]
            if raw_stop >= breakout_low:
                raw_stop = breakout_low - (SYM_STOP_ATR_MULT * cur_atr)
            stop_loss = round(raw_stop, 2)

        # 10. Target = breakout level + base height
        target = round(entry_price + base_height, 2)
        risk = entry_price - stop_loss
        if risk <= 0:
            reject_reasons.append(f"Invalid risk: entry ({entry_price}) <= stop ({stop_loss})")
            continue

        rr = round((target - entry_price) / risk, 2)
        if rr < SYM_MIN_RR:
            reject_reasons.append(f"Risk:Reward {rr:.2f} below required {SYM_MIN_RR}:1")
            continue

        # Confidence score
        conf_score = 72
        if len(res_touches) >= 3:
            conf_score += 8
        if len(sup_touches) >= 3:
            conf_score += 8
        if (res_r2 + sup_r2) / 2 >= 0.75:
            conf_score += 8
        if status == "Confirmed Breakout" and cur_vol >= (1.3 * v_20):
            conf_score += 4
        conf_score = min(98, conf_score)

        # Build chart lines
        dates_in_pattern = [c[0] for c in pattern_window]
        upper_line_points = [
            {"time": dates_in_pattern[0], "value": round(res_slope * 0 + res_intercept, 2)},
            {"time": dates_in_pattern[-1], "value": round(res_slope * (pat_len - 1) + res_intercept, 2)},
        ]
        lower_line_points = [
            {"time": dates_in_pattern[0], "value": round(sup_slope * 0 + sup_intercept, 2)},
            {"time": dates_in_pattern[-1], "value": round(sup_slope * (pat_len - 1) + sup_intercept, 2)},
        ]

        upper_touch_points = [
            {"time": dates_in_pattern[idx], "price": round(price, 2), "index": idx}
            for idx, price in res_touches
        ]
        lower_touch_points = [
            {"time": dates_in_pattern[idx], "price": round(price, 2), "index": idx}
            for idx, price in sup_touches
        ]

        abs_dist = abs(round(((cur_close - upper_now) / upper_now) * 100, 2))

        setup = {
            "symbol": symbol,
            "company": company,
            "pattern": "Symmetrical Triangle",
            "status": status,
            "entry_type": entry_type,
            "cmp": round(cur_close, 2),
            "resistance_level": round(upper_now, 2),
            "support_level": round(lower_now, 2),
            "triangle_height": round(base_height, 2),
            "base_height": round(base_height, 2),
            "buy_price": entry_price,
            "stop_loss": stop_loss,
            "target": target,
            "risk_reward": f"1:{rr}",
            "rr_ratio": rr,
            "touches": total_touches,
            "upper_touches_count": len(res_touches),
            "lower_touches_count": len(sup_touches),
            "confidence": conf_score,
            "apex_bars_away": round(x_apex - (pat_len - 1), 1),
            "timeframe": timeframe.capitalize(),
            "sparkline": [round(c, 2) for c in window_closes[-12:]],
            "abs_distance": abs_dist,
            "distance_pct": round(((cur_close - upper_now) / upper_now) * 100, 2),
            "breakout_date": breakout_date,
            "upper_touches": upper_touch_points,
            "lower_touches": lower_touch_points,
            "upper_line_points": upper_line_points,
            "lower_line_points": lower_line_points,
            "pattern_start_date": dates_in_pattern[0],
            "pattern_end_date": dates_in_pattern[-1],
            "pattern_bars": pat_len,
            "reject_reasons": [],
        }

        if best_setup is None or (setup["confidence"], setup["touches"]) > (best_setup["confidence"], best_setup["touches"]):
            best_setup = setup

    return best_setup


def get_symmetrical_triangle_debug(
    symbol: str, company: str, candles: list, timeframe: str = "daily"
) -> Dict[str, Any]:
    """Helper for debug endpoint /api/debug/<symbol> showing reject reasons."""
    setup = detect_symmetrical_triangle(symbol, company, candles, timeframe=timeframe)
    if setup:
        return {"qualified": True, "setup": setup, "reject_reasons": []}

    reasons = []
    is_weekly = (timeframe.lower() == "weekly")
    min_bars = SYM_MIN_WEEKLY_BARS if is_weekly else SYM_MIN_DAILY_BARS
    if len(candles) < (min_bars + 10):
        reasons.append(f"Insufficient history: {len(candles)} bars, need at least {min_bars + 10}")
    else:
        reasons.append("Structure did not satisfy Symmetrical Triangle criteria (contraction >=25%, volume dry-up <85%, R² >= 0.6 on both lines, apex 50-85%, R:R >= 2.5)")

    return {"qualified": False, "setup": None, "reject_reasons": reasons}
