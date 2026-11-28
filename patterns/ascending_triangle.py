"""
patterns/ascending_triangle.py — Ascending Triangle Breakout & Retest Detector
==============================================================================
Detects clean Ascending Triangles across Daily (20-90 bars) & Weekly (12-95 bars):
  - Flat resistance with >=2 confirmed swing highs
  - Rising support with >=2 confirmed swing lows (R² >= 0.50, no support close breakdown)
  - Breakout (close > resistance + 0.2%, volume >= 1.25x), Retest Entry, or BO Zone Forming
  - Target = entry + triangle height (uninflated, minimum 1:2.0 R:R)
"""

from typing import Optional, Dict, Any, List, Tuple
from patterns.config import (
    DEFAULT_PIVOT_WINDOW,
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
    compute_tolerance,
)


def detect_ascending_triangle(
    symbol: str,
    company: str,
    candles: list,
    timeframe: str = "daily",
    pivot_window: int = DEFAULT_PIVOT_WINDOW,
    collect_diagnostics: bool = False,
) -> Any:
    """
    Detects an Ascending Triangle setup according to clean geometric and volume rules.
    If collect_diagnostics is True, returns (setup, reject_reasons).
    Otherwise returns setup or None.
    """
    is_weekly = (timeframe.lower() == "weekly")
    min_bars = ASC_MIN_WEEKLY_BARS if is_weekly else ASC_MIN_DAILY_BARS
    max_bars = ASC_MAX_WEEKLY_BARS if is_weekly else ASC_MAX_DAILY_BARS

    total_candles = len(candles)
    diag_reasons: List[str] = []

    if total_candles < (min_bars + 10):
        reason = f"Insufficient history: {total_candles} bars, requires at least {min_bars + 10} bars."
        if collect_diagnostics:
            return None, [reason]
        return None

    cur_atr = atr(candles, period=14)
    cmp_price = float(candles[-1][4])
    tolerance = compute_tolerance(cmp_price, cur_atr)

    eval_slice_len = min(total_candles, max_bars + 15)
    eval_candles = candles[-eval_slice_len:]
    eval_highs = [float(c[2]) for c in eval_candles]
    eval_lows = [float(c[3]) for c in eval_candles]
    eval_closes = [float(c[4]) for c in eval_candles]
    eval_volumes = [float(c[5]) for c in eval_candles]

    # Fast pre-filter: skip stocks trading > 18% below recent highs
    recent_high = max(eval_highs[-min(len(eval_highs), max_bars):])
    if (recent_high - cmp_price) / recent_high > 0.18:
        if collect_diagnostics:
            diag_reasons.append(
                f"Price is {((recent_high - cmp_price) / recent_high) * 100:.1f}% below recent high (must be near resistance)."
            )
            return None, diag_reasons
        return None

    all_sh, all_sl = confirmed_pivots(
        eval_highs, eval_lows, window=pivot_window, min_separation=ASC_MIN_PIVOT_SEPARATION
    )

    if len(all_sh) < 2 or len(all_sl) < 2:
        reason = (
            f"Not enough confirmed swing pivots (found {len(all_sh)} highs, {len(all_sl)} lows; "
            f"minimum 2 each required with separation >= {ASC_MIN_PIVOT_SEPARATION} bars)."
        )
        if collect_diagnostics:
            return None, [reason]
        return None

    last_idx = len(eval_candles) - 1
    candidate_starts = []
    for p_idx, _ in all_sh + all_sl:
        bars_back = last_idx - p_idx
        if (min_bars - 1) <= bars_back < max_bars:
            candidate_starts.append(p_idx)

    if not candidate_starts:
        reason = f"No confirmed swing pivots located within consolidation lookback range ({min_bars}–{max_bars} bars)."
        if collect_diagnostics:
            return None, [reason]
        return None

    candidate_starts = sorted(set(candidate_starts))
    best_setup = None

    for start_idx in candidate_starts:
        pat_len = eval_slice_len - start_idx
        if pat_len < min_bars or pat_len > max_bars:
            continue

        # 1. Prior trend check (allow multi-month bases of >=35 bars or prior rally/base)
        global_start = total_candles - eval_slice_len + start_idx
        prior_trend_valid = (pat_len >= 35)
        start_close = eval_closes[start_idx]

        if not prior_trend_valid:
            if not is_weekly:
                if global_start >= ASC_PRIOR_LOOKBACK_DAILY and float(candles[global_start - ASC_PRIOR_LOOKBACK_DAILY][4]) > start_close:
                    prior_trend_valid = True
                if not prior_trend_valid and global_start >= 15:
                    lookback_pre = min(global_start, ASC_PRIOR_RALLY_LOOKBACK_DAILY)
                    min_pre = min(float(c[3]) for c in candles[global_start - lookback_pre : global_start])
                    if min_pre > 0 and (start_close - min_pre) / min_pre >= ASC_PRIOR_RALLY_MIN_DAILY:
                        prior_trend_valid = True
            else:
                if global_start >= 12 and float(candles[global_start - 12][4]) > start_close:
                    prior_trend_valid = True
                if not prior_trend_valid and global_start >= 8:
                    lookback_pre = min(global_start, ASC_PRIOR_RALLY_LOOKBACK_WEEKLY)
                    min_pre = min(float(c[3]) for c in candles[global_start - lookback_pre : global_start])
                    if min_pre > 0 and (start_close - min_pre) / min_pre >= ASC_PRIOR_RALLY_MIN_WEEKLY:
                        prior_trend_valid = True

        if not prior_trend_valid:
            if collect_diagnostics:
                diag_reasons.append("Prior trend failed: Pattern does not follow a prior rally or consolidation base.")
            continue

        window_closes = eval_closes[start_idx:]
        window_lows = eval_lows[start_idx:]

        # Preserve the pivot at start_idx itself (offset 0) instead of slicing it off
        sh_in_pat = [(idx - start_idx, px) for idx, px in all_sh if idx >= start_idx]
        sl_in_pat = [(idx - start_idx, px) for idx, px in all_sl if idx >= start_idx]

        if len(sh_in_pat) < 2 or len(sl_in_pat) < 2:
            if collect_diagnostics:
                diag_reasons.append(f"Insufficient pivots in pattern window: {len(sh_in_pat)} highs, {len(sl_in_pat)} lows.")
            continue

        avg_price = sum(window_closes) / pat_len

        # 2. Flat resistance (close violations checked strictly before breakout zone)
        res_slope, res_intercept, _, _ = fit_line_through_pivots(sh_in_pat)
        norm_res_slope = res_slope / avg_price

        if abs(norm_res_slope) > ASC_RES_MAX_SLOPE_NORM:
            if collect_diagnostics:
                diag_reasons.append(
                    f"Resistance not flat: slope is {norm_res_slope * 100:+.3f}% per bar (max allowed ±{ASC_RES_MAX_SLOPE_NORM * 100:.2f}%)."
                )
            continue

        res_touches = touches_on_line(sh_in_pat, res_slope, res_intercept, tolerance)
        if len(res_touches) < 2:
            if collect_diagnostics:
                diag_reasons.append(f"Resistance touches: {len(res_touches)} within tolerance (minimum 2 required).")
            continue

        res_level = sum(p[1] for p in res_touches) / len(res_touches)

        # 3. Rising support (check close violations strictly across entire window)
        sup_slope, sup_intercept, sup_r2, sup_valid = fit_line_through_pivots(
            sl_in_pat, window_closes=window_closes, tolerance=tolerance, line_type="lower"
        )
        norm_sup_slope = sup_slope / avg_price

        if norm_sup_slope < ASC_SUP_MIN_SLOPE_NORM:
            if collect_diagnostics:
                diag_reasons.append(
                    f"Support line not rising: slope is {norm_sup_slope * 100:+.3f}% per bar (minimum +{ASC_SUP_MIN_SLOPE_NORM * 100:.2f}% required)."
                )
            continue

        if sup_r2 < ASC_SUP_MIN_R2:
            if collect_diagnostics:
                diag_reasons.append(f"Support line fit quality R² = {sup_r2:.2f} (below required {ASC_SUP_MIN_R2:.2f}).")
            continue

        if not sup_valid:
            if collect_diagnostics:
                diag_reasons.append("Support breakdown: Price closed below the rising support trendline.")
            continue

        sup_touches = touches_on_line(sl_in_pat, sup_slope, sup_intercept, tolerance)
        if len(sup_touches) < 2:
            if collect_diagnostics:
                diag_reasons.append(f"Support line touches: {len(sup_touches)} within tolerance (minimum 2 required).")
            continue

        # 4. Triangle Height
        lowest_sl = min(p[1] for p in sl_in_pat)
        triangle_height = res_level - lowest_sl
        if (triangle_height / res_level) < ASC_MIN_HEIGHT_PCT:
            if collect_diagnostics:
                diag_reasons.append(f"Pattern height is {(triangle_height / res_level) * 100:.1f}% of price (minimum 3.0% required).")
            continue

        # 5. Apex convergence
        if sup_slope <= 0:
            continue

        x_apex = (res_level - sup_intercept) / sup_slope
        bars_to_apex = x_apex - (pat_len - 1)
        if not (ASC_APEX_MIN_BARS <= bars_to_apex <= ASC_APEX_MAX_BARS):
            if collect_diagnostics:
                diag_reasons.append(
                    f"Apex distance {bars_to_apex:.1f} bars away (must be {ASC_APEX_MIN_BARS}–{ASC_APEX_MAX_BARS} bars)."
                )
            continue

        # 6. Status classification (Breakout / Retest / Forming BO Zone)
        pattern_window = eval_candles[start_idx:]
        window_volumes = eval_volumes[start_idx:]
        cur_close = window_closes[-1]
        cur_vol = window_volumes[-1]
        v_20 = (sum(window_volumes[-21:-1]) / 20.0) if pat_len >= 21 else (sum(window_volumes[:-1] or window_volumes) / max(1, pat_len - 1))

        status = None
        entry_type = None
        entry_price = None
        stop_loss = None
        breakout_date = None
        pre_bo_limit = pat_len  # Index up to which resistance cannot have closed above earlier

        # Check Confirmed Breakout in last 2 bars
        for b_offset in (1, 2):
            b_idx = pat_len - b_offset
            if b_idx < 4:
                continue
            b_close = window_closes[b_idx]
            b_vol = window_volumes[b_idx]
            b_start = max(0, b_idx - 20)
            b_v20 = sum(window_volumes[b_start:b_idx]) / max(1, b_idx - b_start)

            if b_close > (res_level * (1.0 + ASC_BREAKOUT_PRICE_BUFFER)):
                if b_vol >= (ASC_BREAKOUT_VOL_MULT * b_v20) and cur_close <= (res_level * (1.0 + ASC_MAX_CHASE_PCT)):
                    # Verify no prior close penetrated resistance before b_idx
                    res_ceil = res_level + tolerance
                    if not any(c > res_ceil for c in window_closes[:b_idx]):
                        status = "Confirmed Breakout"
                        entry_type = "Direct Breakout Entry"
                        entry_price = round(cur_close, 2)
                        breakout_bar_low = window_lows[b_idx]
                        last_sl_price = sl_in_pat[-1][1]
                        stop_loss = round(min(last_sl_price, breakout_bar_low) - (ASC_STOP_ATR_MULT * cur_atr), 2)
                        breakout_date = pattern_window[b_idx][0]
                        pre_bo_limit = b_idx
                        break

        # Check Retest Entry
        if not status and pat_len >= (ASC_RETEST_LOOKBACK_MAX + 3):
            for r_offset in range(ASC_RETEST_LOOKBACK_MIN, min(pat_len - 3, ASC_RETEST_LOOKBACK_MAX) + 1):
                prior_idx = pat_len - 1 - r_offset
                if prior_idx < 4:
                    break
                p_close = window_closes[prior_idx]
                if p_close > (res_level * (1.0 + ASC_BREAKOUT_PRICE_BUFFER)):
                    res_ceil = res_level + tolerance
                    if any(c > res_ceil for c in window_closes[:prior_idx]):
                        continue
                    retest_low = min(window_lows[prior_idx + 1 :])
                    if abs(retest_low - res_level) <= tolerance or retest_low <= (res_level + tolerance):
                        if cur_close >= res_level:
                            status = "Retest Entry"
                            entry_type = "Retest Entry"
                            entry_price = round(cur_close, 2)
                            stop_loss = round(retest_low - (ASC_STOP_ATR_MULT * cur_atr), 2)
                            breakout_date = pattern_window[prior_idx][0]
                            pre_bo_limit = prior_idx
                            break

        # Check Forming (BO Zone)
        if not status:
            res_ceil = res_level + tolerance
            if any(c > res_ceil for c in window_closes):
                if collect_diagnostics:
                    diag_reasons.append("Resistance violated: Price already closed above resistance earlier without holding.")
                continue
            if (res_level * (1.0 - ASC_FORMING_BAND_PCT)) <= cur_close < (res_level * (1.0 + ASC_BREAKOUT_PRICE_BUFFER)):
                status = "Forming"
                entry_type = "Forming Watchlist (BO Zone)"
                entry_price = round(res_level * 1.002, 2)
                last_sl_price = sl_in_pat[-1][1]
                stop_loss = round(last_sl_price - (ASC_STOP_ATR_MULT * cur_atr), 2)

        if not status:
            if collect_diagnostics:
                dist_from_res = ((res_level - cur_close) / res_level) * 100
                diag_reasons.append(
                    f"Price ₹{cur_close:.2f} is {dist_from_res:.1f}% below resistance ₹{res_level:.2f} "
                    f"(must be within {ASC_FORMING_BAND_PCT * 100:.1f}% for Forming or breakout with >= {ASC_BREAKOUT_VOL_MULT:.2f}x volume)."
                )
            continue

        # 7. Target & R:R
        target = round(entry_price + triangle_height, 2)
        risk = entry_price - stop_loss
        if risk <= 0:
            continue

        rr = round((target - entry_price) / risk, 2)
        if rr < ASC_MIN_RR:
            if collect_diagnostics:
                diag_reasons.append(f"Risk:Reward ratio 1:{rr:.2f} below 1:{ASC_MIN_RR} minimum threshold.")
            continue

        conf_score = 72
        if len(res_touches) >= 3:
            conf_score += 8
        if len(sup_touches) >= 3:
            conf_score += 7
        if sup_r2 >= 0.75:
            conf_score += 7
        if status == "Confirmed Breakout" and cur_vol >= (1.5 * v_20):
            conf_score += 4
        conf_score = min(98, conf_score)

        dates_in_pattern = [c[0] for c in pattern_window]
        u_start_x = sh_in_pat[0][0]
        l_start_x = sl_in_pat[0][0]
        upper_line_points = [
            {"time": dates_in_pattern[u_start_x], "value": round(res_level, 2)},
            {"time": dates_in_pattern[-1], "value": round(res_level, 2)},
        ]
        lower_line_points = [
            {"time": dates_in_pattern[l_start_x], "value": round(sup_slope * l_start_x + sup_intercept, 2)},
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

    seen = set()
    unique_reasons = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique_reasons.append(r)

    if not unique_reasons:
        unique_reasons = [
            f"No qualifying Ascending Triangle found (requires flat resistance, rising support with R² >= {ASC_SUP_MIN_R2}, "
            f"apex within {ASC_APEX_MIN_BARS}–{ASC_APEX_MAX_BARS} bars, R:R >= {ASC_MIN_RR})."
        ]

    return {"qualified": False, "setup": None, "reject_reasons": unique_reasons}
