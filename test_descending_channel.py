"""
test_descending_channel.py — Unit Tests for Descending Channel Strategy Engine
=============================================================================
Verifies all strategy functions including channel identification, volume confirmation,
breakout validation, retest detection, double bottom detection, setup score, and trade levels.
"""

import unittest
import descending_channel


class TestDescendingChannelScanner(unittest.TestCase):
    def setUp(self):
        self.config = dict(descending_channel.DEFAULT_CONFIG)

    def generate_synthetic_descending_channel_candles(self):
        """
        Creates a clean 40-candle synthetic descending channel with:
        - Downward sloping resistance and support (3 LH, 3 LL)
        - Clean breakout on candle 35 with volume spike
        - Pullback retest on candle 38 with lower volume
        - Bullish reversal confirmation on candle 40
        """
        candles = []
        base_res = 500.0
        base_sup = 450.0
        slope = -1.5  # drops 1.5 per candle

        for i in range(35):
            res = base_res + (slope * i)
            sup = base_sup + (slope * i)
            mid = (res + sup) / 2.0
            # Alternate wave inside channel
            phase = i % 8
            if phase in [0, 1]:  # near resistance (LH)
                high = res + 0.5
                close = res - 1.0
                open_p = res - 3.0
                low = res - 5.0
            elif phase in [4, 5]: # near support (LL)
                low = sup - 0.5
                close = sup + 2.0
                open_p = sup + 4.0
                high = sup + 6.0
            else:
                high = mid + 5.0
                low = mid - 5.0
                open_p = mid - 2.0
                close = mid + 2.0
            vol = 100000 + (i * 500)
            date_str = f"2026-01-{(i+1):02d}T09:15:00+05:30"
            candles.append([date_str, open_p, high, low, close, vol, 0])

        # Candle 35: Breakout candle with volume spike (2.5x volume)
        res_35 = base_res + (slope * 35)
        b_open = res_35 - 1.0
        b_close = res_35 + 8.0  # clean breakout above resistance
        b_high = b_close + 1.0
        b_low = b_open - 1.0
        b_vol = 300000  # 3x volume expansion
        candles.append(["2026-02-05T09:15:00+05:30", b_open, b_high, b_low, b_close, b_vol, 0])

        # Candle 36-37: Mild consolidation above resistance with lower volume
        candles.append(["2026-02-06T09:15:00+05:30", b_close, b_close + 2.0, b_close - 2.0, b_close + 1.0, 90000, 0])
        candles.append(["2026-02-07T09:15:00+05:30", b_close + 1.0, b_close + 2.0, b_close - 3.0, b_close - 1.0, 80000, 0])

        # Candle 38: Retest candle touching previous resistance (now support) with lower volume
        retest_sup = res_35
        r_open = retest_sup + 4.0
        r_low = retest_sup + 0.2  # tests resistance level cleanly
        r_close = retest_sup + 2.5
        r_high = r_open + 1.0
        candles.append(["2026-02-08T09:15:00+05:30", r_open, r_high, r_low, r_close, 70000, 0])

        # Candle 39: Bullish reversal continuation off retest
        c_open = r_close
        c_close = c_open + 7.0
        c_high = c_close + 1.0
        c_low = c_open - 0.5
        candles.append(["2026-02-09T09:15:00+05:30", c_open, c_high, c_low, c_close, 180000, 0])

        return candles

    def test_pivot_detection(self):
        highs = [10, 12, 15, 12, 10, 11, 14, 11, 8]
        lows = [9, 10, 11, 9, 8, 9, 10, 8, 7]
        sh = descending_channel.detect_swing_highs(highs, window=2)
        sl = descending_channel.detect_swing_lows(lows, window=2)
        self.assertTrue(len(sh) >= 1)
        self.assertTrue(len(sl) >= 1)

    def test_relative_volume(self):
        candles = []
        for i in range(25):
            candles.append([f"date_{i}", 100, 105, 95, 102, 10000, 0])
        # Add high volume candle
        candles.append(["date_25", 100, 108, 99, 107, 25000, 0])
        rvol, desc = descending_channel.calculate_relative_volume(candles, -1)
        self.assertGreaterEqual(rvol, 2.0)
        self.assertEqual(desc, "Excellent")

    def test_channel_identification(self):
        candles = self.generate_synthetic_descending_channel_candles()
        # Test on pre-breakout window (first 35 candles)
        ch = descending_channel.identify_descending_channel(candles[:35], lookback=30, config=self.config)
        self.assertIsNotNone(ch)
        self.assertTrue(ch["res_slope_norm"] < 0)
        self.assertTrue(ch["sup_slope_norm"] < 0)
        self.assertGreaterEqual(ch["lh_count"], 3)
        self.assertGreaterEqual(ch["ll_count"], 3)

    def test_breakout_validation(self):
        candles = self.generate_synthetic_descending_channel_candles()
        atr = descending_channel.calculate_atr(candles)
        ch = descending_channel.identify_descending_channel(candles[:35], lookback=30, config=self.config)
        self.assertIsNotNone(ch)
        breakout = descending_channel.detect_breakout(candles, ch, atr, self.config)
        self.assertIsNotNone(breakout)
        self.assertGreaterEqual(breakout["relative_volume"], 1.5)

    def test_retest_and_reversal(self):
        candles = self.generate_synthetic_descending_channel_candles()
        atr = descending_channel.calculate_atr(candles)
        ch = descending_channel.identify_descending_channel(candles[:35], lookback=30, config=self.config)
        self.assertIsNotNone(ch)
        breakout = descending_channel.detect_breakout(candles, ch, atr, self.config)
        self.assertIsNotNone(breakout)
        retest_ok, retest_info = descending_channel.detect_breakout_retest(candles, breakout, ch, atr, self.config)
        self.assertTrue(retest_ok)
        self.assertEqual(retest_info["status"], "Retest Successful")

    def test_setup_quality_score(self):
        score, breakdown = descending_channel.calculate_setup_score(
            channel_valid=True,
            lh_count=3,
            ll_count=3,
            strong_breakout_candle=True,
            volume_confirmed=True,
            retest_successful=True,
            double_bottom=False,
            bullish_reversal=True,
            rr_favorable=True
        )
        self.assertEqual(score, 95)
        self.assertEqual(breakdown["valid_channel"], 15)
        self.assertEqual(breakdown["lower_highs"], 10)
        self.assertEqual(breakdown["lower_lows"], 10)
        self.assertEqual(breakdown["breakout_candle"], 15)
        self.assertEqual(breakdown["volume_confirmed"], 15)
        self.assertEqual(breakdown["retest_successful"], 15)
        self.assertEqual(breakdown["bullish_reversal"], 5)
        self.assertEqual(breakdown["risk_reward"], 10)

    def test_scan_descending_channel_master(self):
        candles = self.generate_synthetic_descending_channel_candles()
        res = descending_channel.scan_descending_channel(
            symbol="TEST_STOCK",
            candles=candles,
            timeframe="daily",
            company_name="Test Stock Ltd"
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["signal_type"], "CONFIRMED BUY")
        self.assertGreaterEqual(res["setup_quality_score"], 80)
        self.assertGreater(res["target1"], res["entry_price"])
        self.assertGreater(res["target2"], res["target1"])
        self.assertLess(res["stop_loss"], res["entry_price"])


if __name__ == "__main__":
    unittest.main()
