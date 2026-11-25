"""
patterns/ascending_triangle.py — Ascending Triangle Breakout & Retest Detector
==============================================================================
Strict institutional implementation:
  - Pattern begins at first confirmed pivot of consolidation (30-90 daily, 15-40 weekly)
  - Prior trend validation (higher 40+ bars ago or >=10%/15% rise in preceding 60/20 bars)
  - Flat resistance: >=2 confirmed swing highs (3 preferred), slope within ±0.05%/bar
  - Rising support: >=2 confirmed swing lows, slope >= +0.05%/bar, R² >= 0.6, no close violation
  - Pivots spaced >= 5 bars apart
  - True pattern height: resistance minus lowest swing low inside pattern >= 3% of price
  - Apex convergence: apex within 1 to 15 bars after the last pattern bar
  - Status: Confirmed Breakout, Retest Entry, or Forming (Watchlist)
  - Target = entry + triangle height (minimum R:R 1:3, reject if below, no inflating)
"""

from typing import Optional, Dict, Any, List, Tuple
import numpy as np
from patterns.config import (
    ASC_MIN_DAILY_BARS,
    ASC_MAX_DAILY_BARS,
    ASC_MIN_WEEKLY_BARS,
    ASC_MAX_WEEKLY_BARS,
    ASC_PRIOR_LOOKBACK_DAILY,
    ASC_PRIOR_RALLY_LOOKBACK_DAILY,
    ASC_PRIOR_RALLY_MIN_DAILY,
    ASC_PRIOR_RALLY_LOOKBACK_WEEKLY,
    ASC_PRIOR_RALLY_MIN_WEEKLY,
    ASC_RES_MAX_SLOPE_NORM,
    ASC_SUP_MIN_SLOPE_NORM,
    ASC_SUP_MIN_R2,
    ASC_MIN_PIVOT_SEPARATION,
    ASC_MIN_HEIGHT_PCT,
    ASC_APEX_MIN_BARS,
    ASC_APEX_MAX_BARS,
    ASC_BREAKOUT_PRICE_BUFFER,
    ASC_BREAKOUT_VOL_MULT,
    ASC_MAX_CHASE_PCT,
    ASC_RETEST_LOOKBACK_MIN,
    ASC_RETEST_LOOKBACK_MAX,
    ASC_FORMING_BAND_PCT,
    ASC_STOP_ATR_MULT,
    ASC_MIN_RR,
)
from patterns.geometry import (
    atr,
    confirmed_pivots,
    fit_line_through_pivots,
    touches_on_line,
    line_value,
    compute_tolerance,
)


def detect_ascending_triangle(
    symbol: str,
    company: str,
    candles: list,
    timeframe: str = "daily",
    pivot_window: int = 3,
    collect_diagnostics: bool = False,
) -> Any:
    """
    Detects an Ascending Triangle setup according to strict geometric and volume rules.
    If collect_diagnostics is True, returns (setup, reject_reasons_dict).
    Otherwise returns setup or None.
    """
    is_weekly = (timeframe.lower() == "weekly")
    min_bars = ASC_MIN_WEEKLY_BARS if is_weekly else ASC_MIN_DAILY_BARS
    max_bars = ASC_MAX_WEEKLY_BARS if is_weekly else ASC_MAX_DAILY_BARS

    total_candles = len(candles)
    diag_reasons: List[str] = []

    if total_candles < (min_bars + 20):
        reason = f"Insufficient history: {total_candles} bars, requires at least {min_bars + 20} bars."
        if collect_diagnostics:
            return None, [reason]
        return None

    cur_atr = atr(candles, period=14)
    cmp_price = float(candles[-1][4])
    tolerance = compute_tolerance(cmp_price, cur_atr)

    eval_slice_len = min(total_candles, max_bars + 20)
    eval_candles = candles[-eval_slice_len:]
    eval_highs = [float(c[2]) for c in eval_candles]
    eval_lows = [float(c[3]) for c in eval_candles]
    eval_closes = [float(c[4]) for c in eval_candles]
    eval_volumes = [float(c[5]) for c in eval_candles]

    # FAST PRE-FILTER (0.001ms): Skip stocks whose price is far below recent highs
    recent_high = max(eval_highs[-60:])
    if (recent_high - cmp_price) / recent_high > 0.12:
        if collect_diagnostics:
            diag_reasons.append(f"Price is {((recent_high-cmp_price)/recent_high)*100:.1f}% below recent 60-bar high (must be within 1.5% for forming or breakout).")
            return None, diag_reasons
        return None

    all_sh, all_sl = confirmed_pivots(
        eval_highs, eval_lows, window=pivot_window, min_separation=ASC_MIN_PIVOT_SEPARATION
    )

    if len(all_sh) < 2 or len(all_sl) < 2:
        reason = f"Not enough confirmed swing pivots (found {len(all_sh)} swing highs, {len(all_sl)} swing lows; minimum 2 each required with separation >= {ASC_MIN_PIVOT_SEPARATION} bars)."
        if collect_diagnostics:
            return None, [reason]
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
        reason = f"No confirmed swing pivots located within consolidation lookback range ({min_bars}–{max_bars} bars back)."
        if collect_diagnostics:
            return None, [reason]
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

        # 1. Prior trend verification
        global_start = total_candles - eval_slice_len + start_idx
        prior_trend_valid = False

        if not is_weekly:
            if global_start >= ASC_PRIOR_LOOKBACK_DAILY:
                close_40_ago = float(candles[global_start - ASC_PRIOR_LOOKBACK_DAILY][4])
                if close_40_ago > float(candles[global_start][4]):
                    prior_trend_valid = True

            if not prior_trend_valid and global_start >= 20:
                lookback_pre = min(global_start, ASC_PRIOR_RALLY_LOOKBACK_DAILY)
                pre_lows = [float(c[3]) for c in candles[global_start - lookback_pre : global_start]]
                if pre_lows:
                    min_pre = min(pre_lows)
                    if (float(candles[global_start][4]) - min_pre) / min_pre >= ASC_PRIOR_RALLY_MIN_DAILY:
                        prior_trend_valid = True
        else:
            if global_start >= 15:
                close_prior = float(candles[global_start - 15][4])
                if close_prior > float(candles[global_start][4]):
                    prior_trend_valid = True

            if not prior_trend_valid and global_start >= 10:
                lookback_pre = min(global_start, ASC_PRIOR_RALLY_LOOKBACK_WEEKLY)
                pre_lows = [float(c[3]) for c in candles[global_start - lookback_pre : global_start]]
                if pre_lows:
                    min_pre = min(pre_lows)
                    if (float(candles[global_start][4]) - min_pre) / min_pre >= ASC_PRIOR_RALLY_MIN_WEEKLY:
                        prior_trend_valid = True

        if not prior_trend_valid:
            diag_reasons.append("Prior trend failed: Pattern does not follow a prior base (higher 40 bars ago) or a preceding 10% rise.")
            continue

        # 2. Confirmed pivots inside pattern
        sh_in_pat, sl_in_pat = confirmed_pivots(
            window_highs, window_lows, window=pivot_window, min_separation=ASC_MIN_PIVOT_SEPARATION
        )

        if len(sh_in_pat) < 2 or len(sl_in_pat) < 2:
            diag_reasons.append(f"Insufficient pivots in candidate pattern window: {len(sh_in_pat)} highs, {len(sl_in_pat)} lows.")
            continue

        # 3. Flat resistance
        res_slope, res_intercept, res_r2, res_valid = fit_line_through_pivots(
            sh_in_pat, window_closes=window_closes, tolerance=tolerance, line_type="upper"
        )
        norm_res_slope = res_slope / avg_price

        if abs(norm_res_slope) > ASC_RES_MAX_SLOPE_NORM:
            diag_reasons.append(f"Resistance not flat: slope is {norm_res_slope*100:+.3f}% per bar (max allowed ±{ASC_RES_MAX_SLOPE_NORM*100:.3f}%).")
            continue

        res_touches = touches_on_line(sh_in_pat, res_slope, res_intercept, tolerance)
        if len(res_touches) < 2:
            diag_reasons.append(f"Resistance touches: {len(res_touches)} touches within tolerance (minimum 2 required).")
            continue

        res_level = float(np.mean([p[1] for p in res_touches]))

        # 4. Rising support
        sup_slope, sup_intercept, sup_r2, sup_valid = fit_line_through_pivots(
            sl_in_pat, window_closes=window_closes, tolerance=tolerance, line_type="lower"
        )
        norm_sup_slope = sup_slope / avg_price

        if norm_sup_slope < ASC_SUP_MIN_SLOPE_NORM:
            diag_reasons.append(f"Support line not rising: slope is {norm_sup_slope*100:+.3f}% per bar (minimum +{ASC_SUP_MIN_SLOPE_NORM*100:.3f}% required).")
            continue

        if sup_r2 < ASC_SUP_MIN_R2:
            diag_reasons.append(f"Support line fit quality R² = {sup_r2:.2f} (below required 0.60 threshold).")
            continue

        if not sup_valid:
            diag_reasons.append("Close violation: One or more bars in the consolidation closed below the rising support line by more than ATR tolerance.")
            continue

        sup_touches = touches_on_line(sl_in_pat, sup_slope, sup_intercept, tolerance)
        if len(sup_touches) < 2:
            diag_reasons.append(f"Support line touches: {len(sup_touches)} touches within tolerance (minimum 2 required).")
            continue

        # 5. Triangle Height
        lowest_sl = min(p[1] for p in sl_in_pat)
        triangle_height = res_level - lowest_sl
        if (triangle_height / res_level) < ASC_MIN_HEIGHT_PCT:
            diag_reasons.append(f"Pattern height is {(triangle_height/res_level)*100:.1f}% of price (minimum 3.0% required).")
            continue

        # 6. Apex convergence
        if sup_slope <= 0:
            diag_reasons.append("Lines do not converge: support slope is flat or negative.")
            continue

        x_apex = (res_level - sup_intercept) / sup_slope
        bars_to_apex = x_apex - (pat_len - 1)
        if not (ASC_APEX_MIN_BARS <= bars_to_apex <= ASC_APEX_MAX_BARS):
            diag_reasons.append(f"Apex distance {bars_to_apex:.1f} bars away (must be between {ASC_APEX_MIN_BARS} and {ASC_APEX_MAX_BARS} bars).")
            continue

        # 7. Status classification
        cur_close = window_closes[-1]
        cur_vol = window_volumes[-1]
        v_20 = float(np.mean(window_volumes[-21:-1])) if len(window_volumes) >= 21 else float(np.mean(window_volumes))

        status = None
        entry_type = None
        entry_price = None
        stop_loss = None
        breakout_date = None

        # Check Confirmed Breakout
        is_breakout = False
        breakout_bar_offset = None
        for b_offset in [1, 2]:
            b_idx = pat_len - b_offset
            b_close = window_closes[b_idx]
            b_vol = window_volumes[b_idx]
            b_v20 = float(np.mean(window_volumes[max(0, b_idx - 20) : b_idx])) if b_idx > 0 else v_20

            if b_close > (res_level * (1.0 + ASC_BREAKOUT_PRICE_BUFFER)):
                if b_vol >= (ASC_BREAKOUT_VOL_MULT * b_v20):
                    if cur_close <= (res_level * (1.0 + ASC_MAX_CHASE_PCT)):
                        is_breakout = True
                        breakout_bar_offset = b_offset
                        breakout_date = pattern_window[b_idx][0]
                        break

        if is_breakout:
            status = "Confirmed Breakout"
            entry_type = "Direct Breakout Entry"
            entry_price = round(cur_close, 2)
            breakout_idx = pat_len - breakout_bar_offset
            breakout_bar_low = window_lows[breakout_idx]
            last_sl_price = sl_in_pat[-1][1]
            raw_stop = min(last_sl_price, breakout_bar_low) - (ASC_STOP_ATR_MULT * cur_atr)
            stop_loss = round(raw_stop, 2)

        # Check Retest Entry
        if not status and pat_len >= (ASC_RETEST_LOOKBACK_MAX + 2):
            for r_offset in range(ASC_RETEST_LOOKBACK_MIN, ASC_RETEST_LOOKBACK_MAX + 1):
                prior_idx = pat_len - 1 - r_offset
                if prior_idx < 0:
                    break
                p_close = window_closes[prior_idx]
                if p_close > (res_level * (1.0 + ASC_BREAKOUT_PRICE_BUFFER)):
                    intervening_lows = window_lows[prior_idx + 1 :]
                    retest_low = min(intervening_lows)
                    if abs(retest_low - res_level) <= tolerance or retest_low <= (res_level + tolerance):
                        if cur_close >= res_level:
                            status = "Retest Entry"
                            entry_type = "Retest Entry"
                            entry_price = round(cur_close, 2)
                            stop_loss = round(retest_low - (ASC_STOP_ATR_MULT * cur_atr), 2)
                            breakout_date = pattern_window[prior_idx][0]
                            break

        # Check Forming
        if not status:
            if (res_level * (1.0 - ASC_FORMING_BAND_PCT)) <= cur_close < (res_level * (1.0 + ASC_BREAKOUT_PRICE_BUFFER)):
                status = "Forming"
                entry_type = "Forming Watchlist"
                entry_price = round(res_level * 1.002, 2)
                last_sl_price = sl_in_pat[-1][1]
                stop_loss = round(last_sl_price - (ASC_STOP_ATR_MULT * cur_atr), 2)

        if not status:
            dist_from_res = ((res_level - cur_close) / res_level) * 100
            diag_reasons.append(f"Price action status: Current price ₹{cur_close:.2f} is {dist_from_res:.1f}% below resistance ₹{res_level:.2f} (must be within 1.5% for Forming or closed above with 1.5x volume for Breakout).")
            continue

        # 8. Target & R:R
        target = round(entry_price + triangle_height, 2)
        risk = entry_price - stop_loss
        if risk <= 0:
            diag_reasons.append(f"Risk calculation invalid: entry ₹{entry_price} <= stop ₹{stop_loss}.")
            continue

        rr = round((target - entry_price) / risk, 2)
        if rr < ASC_MIN_RR:
            diag_reasons.append(f"Risk:Reward ratio 1:{rr:.2f} is below strict 1:{ASC_MIN_RR} minimum threshold.")
            continue

        # Confidence
        conf_score = 70
        if len(res_touches) >= 3:
            conf_score += 10
        if len(sup_touches) >= 3:
            conf_score += 5
        if sup_r2 >= 0.75:
            conf_score += 10
        if status == "Confirmed Breakout" and cur_vol >= (1.5 * v_20):
            conf_score += 5
        conf_score = min(98, conf_score)

        dates_in_pattern = [c[0] for c in pattern_window]
        upper_line_points = [
            {"time": dates_in_pattern[0], "value": round(res_level, 2)},
            {"time": dates_in_pattern[-1], "value": round(res_level, 2)},
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

        abs_dist = abs(round(((cur_close - res_level) / res_level) * 100, 2))

        setup = {
            "symbol": symbol,
            "company": company,
            "pattern": "Ascending Triangle",
            "status": status,
            "entry_type": entry_type,
            "cmp": round(cur_close, 2),
            "resistance_level": round(res_level, 2),
            "support_level": round(sl_in_pat[-1][1], 2),
            "triangle_height": round(triangle_height, 2),
            "buy_price": entry_price,
            "stop_loss": stop_loss,
            "target": target,
            "risk_reward": f"1:{rr}",
            "rr_ratio": rr,
            "touches": len(res_touches) + len(sup_touches),
            "upper_touches_count": len(res_touches),
            "lower_touches_count": len(sup_touches),
            "confidence": conf_score,
            "apex_bars_away": round(bars_to_apex, 1),
            "timeframe": timeframe.capitalize(),
            "sparkline": [round(c, 2) for c in window_closes[-12:]],
            "abs_distance": abs_dist,
            "distance_pct": round(((cur_close - res_level) / res_level) * 100, 2),
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

    if collect_diagnostics:
        return best_setup, (diag_reasons if not best_setup else [])
    return best_setup


def get_ascending_triangle_debug(
    symbol: str, company: str, candles: list, timeframe: str = "daily"
) -> Dict[str, Any]:
    """Helper for debug endpoint /api/debug/<symbol> showing exact granular reject reasons."""
    setup, reasons = detect_ascending_triangle(
        symbol, company, candles, timeframe=timeframe, collect_diagnostics=True
    )
    if setup:
        return {"qualified": True, "setup": setup, "reject_reasons": []}

    # Deduplicate reasons preserving order
    seen = set()
    unique_reasons = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique_reasons.append(r)

    if not unique_reasons:
        unique_reasons = ["Structure does not satisfy concurrent Ascending Triangle rules (flat horizontal resistance, rising support with R² >= 0.60, apex within 1-15 bars, uninflated R:R >= 3.0)."]

    return {"qualified": False, "setup": None, "reject_reasons": unique_reasons}
