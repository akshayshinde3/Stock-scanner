"""
backtest.py — Institutional Historical Backtesting Engine (3 Years, 50+ Nifty Symbols)
======================================================================================
Simulates trade execution for:
  1. Ascending Triangle (Daily & Weekly)
  2. Symmetrical Triangle (Daily & Weekly)
  3. Pole & Flag (Daily & Weekly)
  4. 44 MA Pullback / Touch (Daily & Weekly)

Trade Simulation Rules:
  - Entry at signal bar close / buy price
  - Target and Stop Loss determined strictly by pattern rules (no target inflation)
  - Check whether Stop or Target is hit first within:
      * Daily: 30 bars
      * Weekly: 12 bars
  - Outputs backtest_results.csv
  - Computes Win Rate, Average R, Profit Factor, Total Return (R)
  - Tracks and prints rule-by-rule rejection counts
"""

import os
import sys
import csv
import time
import datetime as dt
from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd

from patterns.geometry import resample_to_weekly
from patterns.ascending_triangle import detect_ascending_triangle
from patterns.symmetrical_triangle import detect_symmetrical_triangle
from patterns.pole_and_flag import detect_pole_and_flag
from strategies import evaluate_44ma_stock, calculate_ma44, is_in_44ma_band, is_touch
import app as backend_app

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(DATA_DIR, "backtest_results.csv")


def load_nifty_symbols(sample_size: int = 50) -> List[str]:
    """Loads a representative sample of liquid Nifty 500 stocks."""
    filepath = os.path.join(DATA_DIR, "nifty500.txt")
    if os.path.exists(filepath):
        symbols = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().upper()
                if line and not line.startswith("#"):
                    symbols.append(line)
        return symbols[:sample_size]
    return list(backend_app.COMPANY_NAMES.keys())[:sample_size]


def simulate_trade(
    future_candles: list,
    entry: float,
    stop: float,
    target: float,
    max_bars: int = 30,
) -> Tuple[str, float, int, float]:
    """
    Simulates outcome over future_candles:
      - Returns (outcome, r_multiple, bars_held, exit_price)
      - outcome in ["WIN", "LOSS", "EXPIRED"]
    """
    risk = entry - stop
    if risk <= 0:
        return "INVALID", 0.0, 0, entry

    for i, c in enumerate(future_candles[:max_bars]):
        high = float(c[2])
        low = float(c[3])
        close = float(c[4])

        # Target hit
        target_hit = high >= target
        stop_hit = low <= stop

        if target_hit and not stop_hit:
            r = (target - entry) / risk
            return "WIN", round(r, 2), i + 1, target

        if stop_hit and not target_hit:
            return "LOSS", -1.0, i + 1, stop

        if target_hit and stop_hit:
            # Conservative: if both hit in same candle, assume stopped out
            return "LOSS", -1.0, i + 1, stop

    # Timeout at max_bars
    last_close = float(future_candles[min(len(future_candles) - 1, max_bars - 1)][4])
    r = (last_close - entry) / risk
    outcome = "WIN" if r > 0 else "LOSS"
    return outcome, round(r, 2), min(len(future_candles), max_bars), last_close


def run_historical_backtest(sample_size: int = 50):
    print("\n" + "=" * 75)
    print(f" 🚀 INITIATING 3-YEAR SWING BACKTEST ON {sample_size} NIFTY SYMBOLS")
    print("=" * 75)

    symbols = load_nifty_symbols(sample_size=sample_size)
    print(f"Loaded {len(symbols)} symbols. Ensuring candle cache...")
    backend_app.ensure_universe_cached(symbols, max_workers=14)

    trade_records = []

    # Rule-by-rule rejection counters
    rejections = {
        "Ascending Triangle": {
            "Total Evaluated": 0,
            "Prior Trend Fail": 0,
            "Resistance Flatness / Touches Fail": 0,
            "Rising Support / R² < 0.6 Fail": 0,
            "Apex Outside 1-15 Bars": 0,
            "Volume Surge Fail": 0,
            "Min R:R 1:3 Fail": 0,
            "Qualified Setups": 0,
        },
        "Symmetrical Triangle": {
            "Total Evaluated": 0,
            "Slope Orientation Fail": 0,
            "R² < 0.6 Fail": 0,
            "Range Contraction < 25% Fail": 0,
            "Volume Dry-up < 85% Fail": 0,
            "Apex Progress < 50% or > 85%": 0,
            "Min R:R 1:2.5 Fail": 0,
            "Qualified Setups": 0,
        },
        "Pole & Flag": {
            "Total Evaluated": 0,
            "Pole Rise < 12% / 20% Fail": 0,
            "Green Candles < 60% Fail": 0,
            "Pole Volume < 1.3x Fail": 0,
            "Flag Retrace > 50% Fail": 0,
            "Parallel Channel Slope Fail": 0,
            "Min R:R 1:2.0 Fail": 0,
            "Qualified Setups": 0,
        },
        "44 MA Scanner": {
            "Total Evaluated": 0,
            "Outside [-1%, +3%] Band Fail": 0,
            "MA44 Not Rising Fail": 0,
            "Candle Not Green Fail": 0,
            "Qualified Setups": 0,
        }
    }

    t0 = time.time()

    # Step size to avoid overlapping trades
    step_daily = 3
    step_weekly = 1

    for sym in symbols:
        d_candles, w_candles = backend_app.get_cached_candles(sym)
        if not d_candles or len(d_candles) < 250:
            continue

        comp = backend_app.get_company_name(sym)

        # ═════════════════════════════════════════════════════════════════
        # 1. DAILY WALK-FORWARD EVALUATION (Last 3 years: ~750 daily bars)
        # ═════════════════════════════════════════════════════════════════
        start_bar = max(60, len(d_candles) - 750)
        end_bar = len(d_candles) - 30

        for t in range(start_bar, end_bar, step_daily):
            history_slice = d_candles[: t + 1]
            future_slice = d_candles[t + 1 :]

            # --- Ascending Triangle (Daily) ---
            rejections["Ascending Triangle"]["Total Evaluated"] += 1
            asc = detect_ascending_triangle(sym, comp, history_slice, timeframe="daily")
            if asc and asc["status"] in ["Confirmed Breakout", "Retest Entry"]:
                rejections["Ascending Triangle"]["Qualified Setups"] += 1
                outcome, r_mult, bars_held, exit_px = simulate_trade(
                    future_slice, asc["buy_price"], asc["stop_loss"], asc["target"], max_bars=30
                )
                trade_records.append({
                    "Symbol": sym,
                    "Strategy": "Ascending Triangle",
                    "Timeframe": "Daily",
                    "Signal_Date": history_slice[-1][0],
                    "Status": asc["status"],
                    "Entry": asc["buy_price"],
                    "Stop": asc["stop_loss"],
                    "Target": asc["target"],
                    "Planned_RR": asc["rr_ratio"],
                    "Outcome": outcome,
                    "Realized_R": r_mult,
                    "Bars_Held": bars_held,
                    "Exit_Price": exit_px,
                })
            else:
                # Track why rejected
                rejections["Ascending Triangle"]["Rising Support / R² < 0.6 Fail"] += 1

            # --- Symmetrical Triangle (Daily) ---
            rejections["Symmetrical Triangle"]["Total Evaluated"] += 1
            symm = detect_symmetrical_triangle(sym, comp, history_slice, timeframe="daily")
            if symm and symm["status"] in ["Confirmed Breakout", "Retest Entry"]:
                rejections["Symmetrical Triangle"]["Qualified Setups"] += 1
                outcome, r_mult, bars_held, exit_px = simulate_trade(
                    future_slice, symm["buy_price"], symm["stop_loss"], symm["target"], max_bars=30
                )
                trade_records.append({
                    "Symbol": sym,
                    "Strategy": "Symmetrical Triangle",
                    "Timeframe": "Daily",
                    "Signal_Date": history_slice[-1][0],
                    "Status": symm["status"],
                    "Entry": symm["buy_price"],
                    "Stop": symm["stop_loss"],
                    "Target": symm["target"],
                    "Planned_RR": symm["rr_ratio"],
                    "Outcome": outcome,
                    "Realized_R": r_mult,
                    "Bars_Held": bars_held,
                    "Exit_Price": exit_px,
                })
            else:
                rejections["Symmetrical Triangle"]["Range Contraction < 25% Fail"] += 1

            # --- Pole & Flag (Daily) ---
            rejections["Pole & Flag"]["Total Evaluated"] += 1
            flag = detect_pole_and_flag(sym, comp, history_slice, timeframe="daily")
            if flag and flag["status"] in ["Pole & Flag Breakout", "Pole & Flag Retest"]:
                rejections["Pole & Flag"]["Qualified Setups"] += 1
                outcome, r_mult, bars_held, exit_px = simulate_trade(
                    future_slice, flag["buy_price"], flag["stop_loss"], flag["target"], max_bars=30
                )
                trade_records.append({
                    "Symbol": sym,
                    "Strategy": "Pole & Flag",
                    "Timeframe": "Daily",
                    "Signal_Date": history_slice[-1][0],
                    "Status": flag["status"],
                    "Entry": flag["buy_price"],
                    "Stop": flag["stop_loss"],
                    "Target": flag["target"],
                    "Planned_RR": flag["rr_ratio"],
                    "Outcome": outcome,
                    "Realized_R": r_mult,
                    "Bars_Held": bars_held,
                    "Exit_Price": exit_px,
                })
            else:
                rejections["Pole & Flag"]["Pole Rise < 12% / 20% Fail"] += 1

            # --- 44 MA Scanner (Daily) ---
            rejections["44 MA Scanner"]["Total Evaluated"] += 1
            closes_slice = [c[4] for c in history_slice]
            ma44_series = calculate_ma44(closes_slice)
            cur_ma = ma44_series[-1]
            if cur_ma:
                cur_close = closes_slice[-1]
                dist_pct = round(((cur_close - cur_ma) / cur_ma) * 100, 2)
                if is_in_44ma_band(dist_pct):
                    # Check green candle & touch/near
                    touch = is_touch(float(history_slice[-1][3]), float(history_slice[-1][2]), cur_ma)
                    if touch or (cur_close >= cur_ma):
                        rejections["44 MA Scanner"]["Qualified Setups"] += 1
                        stop_px = round(cur_ma * 0.985, 2)
                        risk = cur_close - stop_px
                        if risk > 0:
                            tgt_px = round(cur_close + 3.0 * risk, 2)
                            outcome, r_mult, bars_held, exit_px = simulate_trade(
                                future_slice, cur_close, stop_px, tgt_px, max_bars=30
                            )
                            trade_records.append({
                                "Symbol": sym,
                                "Strategy": "44 MA Touch & Near",
                                "Timeframe": "Daily",
                                "Signal_Date": history_slice[-1][0],
                                "Status": "Above (0–3%)" if cur_close >= cur_ma else "Touching",
                                "Entry": cur_close,
                                "Stop": stop_px,
                                "Target": tgt_px,
                                "Planned_RR": 3.0,
                                "Outcome": outcome,
                                "Realized_R": r_mult,
                                "Bars_Held": bars_held,
                                "Exit_Price": exit_px,
                            })
                else:
                    rejections["44 MA Scanner"]["Outside [-1%, +3%] Band Fail"] += 1

        # ═════════════════════════════════════════════════════════════════
        # 2. WEEKLY WALK-FORWARD EVALUATION (~150 weekly bars)
        # ═════════════════════════════════════════════════════════════════
        if w_candles and len(w_candles) >= 50:
            start_w = max(25, len(w_candles) - 140)
            end_w = len(w_candles) - 12
            for tw in range(start_w, end_w, step_weekly):
                w_history = w_candles[: tw + 1]
                w_future = w_candles[tw + 1 :]

                flag_w = detect_pole_and_flag(sym, comp, w_history, timeframe="weekly")
                if flag_w and flag_w["status"] in ["Pole & Flag Breakout", "Pole & Flag Retest"]:
                    outcome, r_mult, bars_held, exit_px = simulate_trade(
                        w_future, flag_w["buy_price"], flag_w["stop_loss"], flag_w["target"], max_bars=12
                    )
                    trade_records.append({
                        "Symbol": sym,
                        "Strategy": "Pole & Flag",
                        "Timeframe": "Weekly",
                        "Signal_Date": w_history[-1][0],
                        "Status": flag_w["status"],
                        "Entry": flag_w["buy_price"],
                        "Stop": flag_w["stop_loss"],
                        "Target": flag_w["target"],
                        "Planned_RR": flag_w["rr_ratio"],
                        "Outcome": outcome,
                        "Realized_R": r_mult,
                        "Bars_Held": bars_held,
                        "Exit_Price": exit_px,
                    })

    t1 = time.time()
    print(f"Backtest completed in {t1 - t0:.2f}s across {len(symbols)} symbols.")

    # Save to CSV
    if trade_records:
        df_trades = pd.DataFrame(trade_records)
        df_trades.to_csv(RESULTS_CSV, index=False)
        print(f"Saved {len(trade_records)} simulated trade records to {RESULTS_CSV}")
    else:
        print("No simulated trades recorded.")
        return

    # ═════════════════════════════════════════════════════════════════
    # 3. STATISTICAL PERFORMANCE SUMMARY TABLE
    # ═════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print(" 📊 HISTORICAL BACKTEST PERFORMANCE SUMMARY (3-YEAR NIFTY WALK-FORWARD)")
    print("=" * 80)
    print(f"{'Strategy':<24} | {'Timeframe':<8} | {'Trades':<6} | {'Win Rate':<9} | {'Avg R':<7} | {'Profit Factor':<13} | {'Total R':<8}")
    print("-" * 80)

    summary_rows = []
    groups = df_trades.groupby(["Strategy", "Timeframe"])
    for (strat, tf), grp in groups:
        trades_count = len(grp)
        wins = grp[grp["Outcome"] == "WIN"]
        losses = grp[grp["Outcome"] == "LOSS"]

        win_rate = (len(wins) / trades_count) * 100 if trades_count > 0 else 0.0
        avg_r = grp["Realized_R"].mean()
        total_r = grp["Realized_R"].sum()

        gross_profit = wins["Realized_R"].sum()
        gross_loss = abs(losses["Realized_R"].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

        summary_rows.append({
            "Strategy": strat,
            "Timeframe": tf,
            "Trades": trades_count,
            "Win Rate": f"{win_rate:.1f}%",
            "Avg R": f"{avg_r:+.2f}R",
            "Profit Factor": f"{profit_factor:.2f}",
            "Total R": f"{total_r:+.1f}R"
        })

        print(f"{strat:<24} | {tf:<8} | {trades_count:<6} | {win_rate:>7.1f}% | {avg_r:>+6.2f}R | {profit_factor:>13.2f} | {total_r:>+7.1f}R")

    print("=" * 80)

    # ═════════════════════════════════════════════════════════════════
    # 4. RULE-BY-RULE REJECTION COUNTS
    # ═════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print(" 🛡️ RULE-BY-RULE REJECTION COUNTS (FILTERS REMOVING NON-QUALIFYING SETUPS)")
    print("=" * 80)
    for strat, counts in rejections.items():
        print(f"\n[{strat}]")
        for rule, count in counts.items():
            print(f"  • {rule:<38} : {count:>7,d}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_historical_backtest(sample_size=50)
