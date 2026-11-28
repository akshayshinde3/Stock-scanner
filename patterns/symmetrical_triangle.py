"""
patterns/symmetrical_triangle.py — Symmetrical Triangle Coil Breakout Detector
=============================================================================
Matches real-world Daily (20-90 bars) & Weekly (12-95 bars) Symmetrical Coils:
  - Upper descending line: normalized slope <= -0.04%/bar, R² >= 0.50, >= 2 confirmed touches
  - Lower ascending line: normalized slope >= +0.04%/bar, R² >= 0.50, >= 2 confirmed touches
  - Volatility squeeze & coil volume dry-up measured prior to breakout buildup
  - Apex convergence: breakout or BO Zone occurs between 40% and 95% of distance to apex
  - Target = entry + triangle base height (minimum R:R 1:2.0, uninflated)
"""

from typing import Optional, Dict, Any, List, Tuple
from patterns.config import (
    DEFAULT_PIVOT_WINDOW,
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
    pivot_window: int = DEFAULT_PIVOT_WINDOW,
    collect_diagnostics: bool = False,
) -> Any:
    """
    Detects a Symmetrical Triangle (Coil) matching descending lower highs and ascending higher lows.
    If collect_diagnostics is True, returns (setup, reject_reasons).
    """
    is_weekly = (timeframe.lower() == "weekly")
    min_bars = SYM_MIN_WEEKLY_BARS if is_weekly else SYM_MIN_DAILY_BARS
    max_bars = SYM_MAX_WEEKLY_BARS if is_weekly else SYM_MAX_DAILY_BARS

    total_candles = len(candles)
    diag_reasons: List[str] = []

    if total_candles < (min_bars + 5):
        reason = f"Insufficient history: {total_candles} bars, requires at least {min_bars + 5} bars."
        if collect_diagnostics:
            return None, [reason]
        return None

    cur_atr = atr(candles, period=14)
    cmp_price = float(candles[-1][4])
    tolerance = compute_tolerance(cmp_price, cur_atr)

    eval_slice_len = min(total_candles, max_bars + 10)
    eval_candles = candles[-eval_slice_len:]
    eval_highs = [float(c[2]) for c in eval_candles]
    eval_lows = [float(c[3]) for c in eval_candles]
    eval_closes = [float(c[4]) for c in eval_candles]
    eval_volumes = [float(c[5]) for c in eval_candles]

    # Pre-filter: symmetrical coils slope downward from left peak, so allow up to 35% below peak
    recent_high = max(eval_highs[-min(len(eval_highs), max_bars):])
    if recent_high > 0 and (recent_high - cmp_price) / recent_high > 0.35:
        if collect_diagnostics:
            diag_reasons.append(
                f"Price is {((recent_high - cmp_price) / recent_high) * 100:.1f}% below pattern high (> 35%)."
            )
            return None, diag_reasons
        return None

    all_sh, all_sl = confirmed_pivots(
        eval_highs, eval_lows, window=pivot_window, min_separation=3
    )

    if len(all_sh) < 2 or len(all_sl) < 2:
        reason = f"Not enough confirmed swing pivots: found {len(all_sh)} highs, {len(all_sl)} lows (minimum 2 each required)."
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

        window_highs = eval_highs[start_idx:]
        window_lows = eval_lows[start_idx:]
        window_closes = eval_closes[start_idx:]
        window_volumes = eval_volumes[start_idx:]

        # Preserve pivot at start_idx itself (offset 0) instead of slicing it away
        sh_in_pat = [(idx - start_idx, px) for idx, px in all_sh if idx >= start_idx]
        sl_in_pat = [(idx - start_idx, px) for idx, px in all_sl if idx >= start_idx]

        if len(sh_in_pat) < 2 or len(sl_in_pat) < 2:
            if collect_diagnostics:
                diag_reasons.append(f"Insufficient pivots in consolidation window: {len(sh_in_pat)} highs, {len(sl_in_pat)} lows.")
            continue

        # 1. Range contraction & coil volume dry-up (early coil half vs late pre-breakout third)
        coil_len = max(9, pat_len - 2)
        half_len = max(3, coil_len // 2)
        third_len = coil_len // 3
        if third_len >= 3:
            avg_range_first = sum(window_highs[i] - window_lows[i] for i in range(half_len)) / half_len
            avg_range_last = sum(window_highs[i] - window_lows[i] for i in range(coil_len - third_len, coil_len)) / third_len

            if avg_range_first <= 0 or (avg_range_last / avg_range_first) > SYM_RANGE_CONTRACTION_MAX:
                if collect_diagnostics:
                    diag_reasons.append(
                        f"Range contraction failed: late coil range (₹{avg_range_last:.2f}) is "
                        f"{(avg_range_last / avg_range_first) * 100:.1f}% of early coil (must be <= {SYM_RANGE_CONTRACTION_MAX * 100:.0f}%)."
                    )
                continue

            avg_vol_first = sum(window_volumes[:half_len]) / half_len
            avg_vol_last = sum(window_volumes[coil_len - third_len : coil_len]) / third_len
            if avg_vol_first > 0 and (avg_vol_last / avg_vol_first) >= SYM_VOLUME_DRYUP_MAX:
                if collect_diagnostics:
                    diag_reasons.append(
                        f"Volume dry-up failed: pre-breakout coil volume is {(avg_vol_last / avg_vol_first) * 100:.1f}% "
                        f"of early volume (must be < {SYM_VOLUME_DRYUP_MAX * 100:.0f}%)."
                    )
                continue

        avg_price = sum(window_closes) / pat_len

        # 2. Upper descending line (close violations checked strictly before breakout bar)
        res_slope, res_intercept, res_r2, _ = fit_line_through_pivots(sh_in_pat)
        norm_res_slope = res_slope / avg_price

        if norm_res_slope > SYM_RES_MAX_SLOPE_NORM:
            if collect_diagnostics:
                diag_reasons.append(
                    f"Upper line not descending: slope is {norm_res_slope * 100:+.3f}% per bar (must be <= {SYM_RES_MAX_SLOPE_NORM * 100:.2f}%)."
                )
            continue

        if res_r2 < SYM_MIN_R2:
            if collect_diagnostics:
                diag_reasons.append(f"Upper line fit quality R² = {res_r2:.2f} (below required {SYM_MIN_R2:.2f}).")
            continue

        res_touches = touches_on_line(sh_in_pat, res_slope, res_intercept, tolerance)
        if len(res_touches) < 2:
            if collect_diagnostics:
                diag_reasons.append(f"Upper descending line touches: {len(res_touches)} (minimum 2 required).")
            continue

        # 3. Lower ascending line (no close breakdown below rising support)
        sup_slope, sup_intercept, sup_r2, sup_valid = fit_line_through_pivots(
            sl_in_pat, window_closes=window_closes, tolerance=tolerance, line_type="lower"
        )
        norm_sup_slope = sup_slope / avg_price

        if norm_sup_slope < SYM_SUP_MIN_SLOPE_NORM:
            if collect_diagnostics:
                diag_reasons.append(
                    f"Lower line not ascending: slope is {norm_sup_slope * 100:+.3f}% per bar (must be >= +{SYM_SUP_MIN_SLOPE_NORM * 100:.2f}%)."
                )
            continue

        if sup_r2 < SYM_MIN_R2:
            if collect_diagnostics:
                diag_reasons.append(f"Lower line fit quality R² = {sup_r2:.2f} (below required {SYM_MIN_R2:.2f}).")
            continue

        if not sup_valid:
            if collect_diagnostics:
                diag_reasons.append("Support breakdown: Price closed below lower ascending trendline.")
            continue

        sup_touches = touches_on_line(sl_in_pat, sup_slope, sup_intercept, tolerance)
        if len(sup_touches) < 2:
            if collect_diagnostics:
                diag_reasons.append(f"Lower ascending line touches: {len(sup_touches)} (minimum 2 required).")
            continue

        # 4. Base height at triangle start (evaluated from earliest actual pivot x=min_p_x)
        earliest_px = min(sh_in_pat[0][0], sl_in_pat[0][0])
        base_height = line_value(res_slope, res_intercept, earliest_px) - line_value(sup_slope, sup_intercept, earliest_px)

        if base_height <= 0 or (base_height / avg_price) < SYM_MIN_BASE_HEIGHT_PCT:
            if collect_diagnostics:
                diag_reasons.append(f"Base height is {(base_height / avg_price) * 100:.1f}% of price (minimum 4.0% required).")
            continue

        # 5. Apex calculation
        slope_diff = res_slope - sup_slope
        if abs(slope_diff) < 1e-9:
            continue

        x_apex = (sup_intercept - res_intercept) / slope_diff
        if x_apex <= (pat_len - 2):
            if collect_diagnostics:
                diag_reasons.append("Lines already crossed past apex before current setup.")
            continue

        # 6. Status Classification
        pattern_window = eval_candles[start_idx:]
        cur_close = window_closes[-1]
        cur_vol = window_volumes[-1]
        v_20 = (sum(window_volumes[-21:-1]) / 20.0) if pat_len >= 21 else (sum(window_volumes[:-1] or window_volumes) / max(1, pat_len - 1))

        upper_now = line_value(res_slope, res_intercept, pat_len - 1)
        lower_now = line_value(sup_slope, sup_intercept, pat_len - 1)

        if upper_now <= lower_now:
            continue

        status = None
        entry_type = None
        entry_price = None
        stop_loss = None
        breakout_date = None
        breakout_bar_idx = None

        # Check Confirmed Breakout in last 2 bars
        for b_offset in (1, 2):
            b_idx = pat_len - b_offset
            if b_idx < 4:
                continue
            b_close = window_closes[b_idx]
            b_vol = window_volumes[b_idx]
            b_upper = line_value(res_slope, res_intercept, b_idx)
            b_start = max(0, b_idx - 20)
            b_v20 = sum(window_volumes[b_start:b_idx]) / max(1, b_idx - b_start)

            if b_close > (b_upper * (1.0 + SYM_BREAKOUT_PRICE_BUFFER)):
                if b_vol >= (SYM_BREAKOUT_VOL_MULT * b_v20) and cur_close <= (b_upper * (1.0 + SYM_MAX_CHASE_PCT)):
                    # Check no earlier candle violated the upper descending line before breakout bar
                    if any(window_closes[k] > line_value(res_slope, res_intercept, k) + tolerance for k in range(b_idx)):
                        continue
                    apex_progress = b_idx / x_apex
                    if SYM_APEX_PROGRESS_MIN <= apex_progress <= SYM_APEX_PROGRESS_MAX:
                        status = "Confirmed Breakout"
                        entry_type = "Coil Breakout Entry"
                        entry_price = round(cur_close, 2)
                        breakout_date = pattern_window[b_idx][0]
                        breakout_bar_idx = b_idx
                        break
                    elif collect_diagnostics:
                        diag_reasons.append(
                            f"Apex progress {apex_progress * 100:.1f}% outside {SYM_APEX_PROGRESS_MIN * 100:.0f}%–{SYM_APEX_PROGRESS_MAX * 100:.0f}%."
                        )

        # Check Retest Entry
        if not status and pat_len >= (SYM_RETEST_LOOKBACK_MAX + 3):
            for r_offset in range(SYM_RETEST_LOOKBACK_MIN, min(pat_len - 3, SYM_RETEST_LOOKBACK_MAX) + 1):
                prior_idx = pat_len - 1 - r_offset
                if prior_idx < 4:
                    break
                p_close = window_closes[prior_idx]
                p_upper = line_value(res_slope, res_intercept, prior_idx)

                if p_close > (p_upper * (1.0 + SYM_BREAKOUT_PRICE_BUFFER)):
                    if any(window_closes[k] > line_value(res_slope, res_intercept, k) + tolerance for k in range(prior_idx)):
                        continue
                    apex_progress = prior_idx / x_apex
                    if SYM_APEX_PROGRESS_MIN <= apex_progress <= SYM_APEX_PROGRESS_MAX:
                        retest_low = min(window_lows[prior_idx + 1 :])
                        if abs(retest_low - upper_now) <= tolerance or retest_low <= (upper_now + tolerance):
                            if cur_close >= upper_now:
                                status = "Retest Entry"
                                entry_type = "Coil Retest Entry"
                                entry_price = round(cur_close, 2)
                                breakout_date = pattern_window[prior_idx][0]
                                breakout_bar_idx = prior_idx
                                stop_loss = round(retest_low - (SYM_STOP_ATR_MULT * cur_atr), 2)
                                break

        # Check Forming (BO Zone near apex)
        if not status:
            if any(window_closes[k] > line_value(res_slope, res_intercept, k) + tolerance for k in range(pat_len)):
                if collect_diagnostics:
                    diag_reasons.append("Upper descending line violated prior to forming zone.")
                continue
            if (upper_now * (1.0 - SYM_FORMING_BAND_PCT)) <= cur_close < (upper_now * (1.0 + SYM_BREAKOUT_PRICE_BUFFER)):
                current_progress = (pat_len - 1) / x_apex
                if SYM_APEX_PROGRESS_MIN <= current_progress <= SYM_APEX_PROGRESS_MAX:
                    status = "Forming"
                    entry_type = "Coil Forming Watchlist (BO Zone)"
                    entry_price = round(upper_now * 1.002, 2)
                    breakout_bar_idx = pat_len - 1

        if not status:
            if collect_diagnostics:
                dist_to_upper = ((upper_now - cur_close) / upper_now) * 100
                diag_reasons.append(
                    f"Price ₹{cur_close:.2f} is {dist_to_upper:.1f}% below upper line ₹{upper_now:.2f} "
                    f"(must be within {SYM_FORMING_BAND_PCT * 100:.1f}% for BO Zone or breakout with volume)."
                )
            continue

        # 7. Stop Loss
        b_idx_eval = breakout_bar_idx if breakout_bar_idx is not None else (pat_len - 1)
        lower_line_at_breakout = line_value(sup_slope, sup_intercept, b_idx_eval)
        last_sl_price = sl_in_pat[-1][1]

        if stop_loss is None:
            tighter_support = max(last_sl_price, lower_line_at_breakout)
            raw_stop = tighter_support - (SYM_STOP_ATR_MULT * cur_atr)
            breakout_low = window_lows[b_idx_eval]
            if raw_stop >= breakout_low:
                raw_stop = breakout_low - (SYM_STOP_ATR_MULT * cur_atr)
            stop_loss = round(raw_stop, 2)

        # 8. Target & R:R
        target = round(entry_price + base_height, 2)
        risk = entry_price - stop_loss
        if risk <= 0:
            continue

        rr = round((target - entry_price) / risk, 2)
        if rr < SYM_MIN_RR:
            if collect_diagnostics:
                diag_reasons.append(f"Risk:Reward ratio 1:{rr:.2f} below strict 1:{SYM_MIN_RR} minimum threshold.")
            continue

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

        dates_in_pattern = [c[0] for c in pattern_window]
        u_start_x = sh_in_pat[0][0]
        l_start_x = sl_in_pat[0][0]
        upper_line_points = [
            {"time": dates_in_pattern[u_start_x], "value": round(res_slope * u_start_x + res_intercept, 2)},
            {"time": dates_in_pattern[-1], "value": round(res_slope * (pat_len - 1) + res_intercept, 2)},
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
            "touches": len(res_touches) + len(sup_touches),
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

    if collect_diagnostics:
        return best_setup, (diag_reasons if not best_setup else [])
    return best_setup


def get_symmetrical_triangle_debug(
    symbol: str, company: str, candles: list, timeframe: str = "daily"
) -> Dict[str, Any]:
    """Helper for debug endpoint /api/debug/<symbol> showing exact granular reject reasons."""
    setup, reasons = detect_symmetrical_triangle(
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
            f"No qualifying Symmetrical Triangle found (opposite slopes with R² >= {SYM_MIN_R2}, "
            f"contraction <= {SYM_RANGE_CONTRACTION_MAX * 100:.0f}%, apex progress {SYM_APEX_PROGRESS_MIN * 100:.0f}–{SYM_APEX_PROGRESS_MAX * 100:.0f}%, R:R >= {SYM_MIN_RR})."
        ]

    return {"qualified": False, "setup": None, "reject_reasons": unique_reasons}
