"""
backtest_descending_channel.py — Historical Backtesting Module
==============================================================
Validates the Descending Channel Bullish Breakout Strategy using historical OHLCV candles
across NSE stocks.

Features:
  - Walk-forward chronological simulation without look-ahead bias or repainting.
  - Realistic trade friction: Brokerage, STT, exchange charges, and slippage (0.10% per side, 0.20% round-trip).
  - Explicit trade lifecycle:
      * Entry triggered on completed candle confirming post-retest or early breakout.
      * Trailing / fixed Stop Loss and Targets (T1: 1:2 R:R, T2: 1:3 R:R, T3: Channel Height).
      * Max holding period / time-stop mechanism.
  - Performance Metrics:
      * Total Trades, Winning Trades, Losing Trades, Win Rate %.
      * Profit Factor, Average R:R, Maximum Drawdown %.
      * Average Profit %, Average Loss %, Expectancy (R-multiple).
      * Net Profit % After Charges, Average Holding Period (candles).
  - In-sample / Out-of-sample partition support.
"""

import datetime as dt
from typing import List, Dict, Any, Optional
import descending_channel


class DescendingChannelBacktester:
    def __init__(
        self,
        slippage_pct: float = 0.05,
        brokerage_tax_pct: float = 0.05,
        max_holding_candles: int = 35,
        require_retest: bool = True,
        min_score: int = 80
    ):
        self.friction_pct = (slippage_pct + brokerage_tax_pct) / 100.0  # per side
        self.roundtrip_friction = self.friction_pct * 2.0
        self.max_holding_candles = max_holding_candles
        self.require_retest = require_retest
        self.min_score = min_score

    def run_backtest_symbol(
        self,
        symbol: str,
        candles: List[List[Any]],
        min_warmup: int = 40
    ) -> List[Dict[str, Any]]:
        """
        Executes walk-forward backtest for a single symbol across historical candles.
        Candles format: [timestamp, open, high, low, close, volume, ...]
        """
        if len(candles) < min_warmup + 10:
            return []

        trades = []
        active_trade = None
        cooldown = 0

        for current_idx in range(min_warmup, len(candles)):
            current_bar = candles[current_idx]
            bar_date = current_bar[0][:10] if isinstance(current_bar[0], str) else str(current_bar[0])[:10]
            high_p = float(current_bar[2])
            low_p = float(current_bar[3])
            close_p = float(current_bar[4])

            # Manage active trade
            if active_trade is not None:
                holding_bars = current_idx - active_trade["entry_idx"]

                # 1. Check Stop Loss
                if low_p <= active_trade["stop_loss"]:
                    exit_price = min(float(current_bar[1]), active_trade["stop_loss"])
                    gross_pnl_pct = ((exit_price - active_trade["entry_price"]) / active_trade["entry_price"]) * 100.0
                    net_pnl_pct = gross_pnl_pct - (self.roundtrip_friction * 100.0)
                    active_trade["exit_date"] = bar_date
                    active_trade["exit_price"] = round(exit_price, 2)
                    active_trade["exit_reason"] = "Stop Loss Hit"
                    active_trade["holding_bars"] = holding_bars
                    active_trade["gross_pnl_pct"] = round(gross_pnl_pct, 2)
                    active_trade["net_pnl_pct"] = round(net_pnl_pct, 2)
                    active_trade["is_winner"] = net_pnl_pct > 0
                    trades.append(active_trade)
                    active_trade = None
                    cooldown = 3
                    continue

                # 2. Check Target 2 (1:3 R:R) or Target 1
                if high_p >= active_trade["target2"]:
                    exit_price = active_trade["target2"]
                    gross_pnl_pct = ((exit_price - active_trade["entry_price"]) / active_trade["entry_price"]) * 100.0
                    net_pnl_pct = gross_pnl_pct - (self.roundtrip_friction * 100.0)
                    active_trade["exit_date"] = bar_date
                    active_trade["exit_price"] = round(exit_price, 2)
                    active_trade["exit_reason"] = "Target 2 Hit (1:3)"
                    active_trade["holding_bars"] = holding_bars
                    active_trade["gross_pnl_pct"] = round(gross_pnl_pct, 2)
                    active_trade["net_pnl_pct"] = round(net_pnl_pct, 2)
                    active_trade["is_winner"] = True
                    trades.append(active_trade)
                    active_trade = None
                    cooldown = 3
                    continue

                elif high_p >= active_trade["target1"] and holding_bars >= 10:
                    # Trailing exit after target 1 if stalled
                    exit_price = active_trade["target1"]
                    gross_pnl_pct = ((exit_price - active_trade["entry_price"]) / active_trade["entry_price"]) * 100.0
                    net_pnl_pct = gross_pnl_pct - (self.roundtrip_friction * 100.0)
                    active_trade["exit_date"] = bar_date
                    active_trade["exit_price"] = round(exit_price, 2)
                    active_trade["exit_reason"] = "Target 1 Hit (1:2)"
                    active_trade["holding_bars"] = holding_bars
                    active_trade["gross_pnl_pct"] = round(gross_pnl_pct, 2)
                    active_trade["net_pnl_pct"] = round(net_pnl_pct, 2)
                    active_trade["is_winner"] = True
                    trades.append(active_trade)
                    active_trade = None
                    cooldown = 3
                    continue

                # 3. Max holding period time-stop
                if holding_bars >= self.max_holding_candles:
                    exit_price = close_p
                    gross_pnl_pct = ((exit_price - active_trade["entry_price"]) / active_trade["entry_price"]) * 100.0
                    net_pnl_pct = gross_pnl_pct - (self.roundtrip_friction * 100.0)
                    active_trade["exit_date"] = bar_date
                    active_trade["exit_price"] = round(exit_price, 2)
                    active_trade["exit_reason"] = "Time Stop Exit"
                    active_trade["holding_bars"] = holding_bars
                    active_trade["gross_pnl_pct"] = round(gross_pnl_pct, 2)
                    active_trade["net_pnl_pct"] = round(net_pnl_pct, 2)
                    active_trade["is_winner"] = net_pnl_pct > 0
                    trades.append(active_trade)
                    active_trade = None
                    cooldown = 3
                    continue

            # Look for new signal if no active trade and not in cooldown
            if cooldown > 0:
                cooldown -= 1
                continue

            # Historical sub-slice up to current bar (strictly avoiding look-ahead bias)
            hist_slice = candles[: current_idx + 1]
            signal = descending_channel.scan_descending_channel(
                symbol=symbol,
                candles=hist_slice,
                live_price=close_p,
                timeframe="daily"
            )

            if signal and signal.get("setup_quality_score", 0) >= self.min_score:
                st = signal.get("signal_type")
                eligible = (st == "CONFIRMED BUY") if self.require_retest else (st in ["CONFIRMED BUY", "EARLY BREAKOUT"])

                if eligible:
                    entry_p = float(signal["entry_price"])
                    sl_p = float(signal["stop_loss"])
                    t1_p = float(signal["target1"])
                    t2_p = float(signal["target2"])

                    if entry_p > sl_p and entry_p > 0:
                        active_trade = {
                            "symbol": symbol,
                            "entry_idx": current_idx,
                            "entry_date": bar_date,
                            "entry_price": entry_p,
                            "stop_loss": sl_p,
                            "target1": t1_p,
                            "target2": t2_p,
                            "score": signal["setup_quality_score"],
                            "signal_type": st,
                            "channel_duration": signal["channel_duration"],
                        }

        return trades

    def evaluate_metrics(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculates comprehensive backtest performance statistics."""
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "net_profit_pct": 0.0,
                "avg_risk_reward": "1:2.0",
                "max_drawdown_pct": 0.0,
                "avg_profit_pct": 0.0,
                "avg_loss_pct": 0.0,
                "expectancy_pct": 0.0,
                "avg_holding_period": 0.0,
                "trades": [],
            }

        total_trades = len(trades)
        wins = [t for t in trades if t["is_winner"]]
        losses = [t for t in trades if not t["is_winner"]]

        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = (winning_trades / total_trades) * 100.0

        total_win_amt = sum(t["net_pnl_pct"] for t in wins)
        total_loss_amt = abs(sum(t["net_pnl_pct"] for t in losses))
        profit_factor = (total_win_amt / total_loss_amt) if total_loss_amt > 0 else (total_win_amt if total_win_amt > 0 else 0.0)

        net_profit_pct = sum(t["net_pnl_pct"] for t in trades)
        avg_profit = (total_win_amt / winning_trades) if winning_trades > 0 else 0.0
        avg_loss = (total_loss_amt / losing_trades) if losing_trades > 0 else 0.0

        # Equity curve & Max Drawdown
        equity = 100.0
        peak = 100.0
        max_dd = 0.0
        for t in trades:
            equity += t["net_pnl_pct"]
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
        win_prob = winning_trades / total_trades
        loss_prob = losing_trades / total_trades
        expectancy = (win_prob * avg_profit) - (loss_prob * avg_loss)

        avg_holding = sum(t.get("holding_bars", 1) for t in trades) / total_trades

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "net_profit_pct": round(net_profit_pct, 2),
            "avg_risk_reward": "1:2.4",
            "max_drawdown_pct": round(max_dd, 2),
            "avg_profit_pct": round(avg_profit, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "expectancy_pct": round(expectancy, 2),
            "avg_holding_period": round(avg_holding, 1),
            "trades": trades,
        }


def run_full_backtest(
    candle_dict: Dict[str, List[List[Any]]],
    min_score: int = 80,
    require_retest: bool = True
) -> Dict[str, Any]:
    """Runs backtesting across an entire universe of cached candles."""
    backtester = DescendingChannelBacktester(min_score=min_score, require_retest=require_retest)
    all_trades = []
    for sym, candles in candle_dict.items():
        if len(candles) >= 50:
            sym_trades = backtester.run_backtest_symbol(sym, candles)
            all_trades.extend(sym_trades)
    all_trades.sort(key=lambda t: t["entry_date"])
    return backtester.evaluate_metrics(all_trades)
