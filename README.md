# Institutional Swing Screener — Indian Stocks (NSE / Nifty 500)

A high-performance stock screener and technical breakout engine for Indian technical swing traders scanning the Nifty 500, Nifty 100, Nifty 50, Midcap, and Smallcap universes on the National Stock Exchange (NSE).

Includes 4 core swing trading engines:
1. **Ascending Triangle Pattern** (Breakout & Retest with uninflated 1:3 R:R)
2. **Symmetrical Triangle Pattern** (Coil contraction, volume dry-up, apex intersection, 1:2.5 R:R)
3. **Bull Pole & Flag Pattern** (Daily & Weekly momentum continuation, 1:2.0 R:R)
4. **44 MA Touch & Near Strategy** (Strictly fixed **-1.0% to +3.0%** distance band)

---

## 1. 44 MA Rising Stocks (-1.0% to +3.0%)

Scans for liquid stocks that are trading within **-1.0% to +3.0%** of an active, **rising 44-period Moving Average**:

- **MA44 Rising**: `today's SMA(Close, 44) > yesterday's SMA(Close, 44)` (strictly upward sloping).
- **Strict Qualification Band**: A stock qualifies **ONLY** if `-1.0 <= Distance % <= +3.0`.
- **Status Badges**:
  1. **Touching** (Blue): `Low <= MA44 <= High` (intraday touch of the rising 44 MA line inside -1% to +3%).
  2. **Above (0–3%)** (Green): `Close >= MA44` and `Distance % <= +3.0%`.
  3. **Near Below (−1–0%)** (Orange): `Close < MA44` and `Distance % >= -1.0%`.
- **Chartink Filter Support (`swing-trade-by-pmpatil`)**:
  - The screener tags stocks meeting all 5 Chartink rules:
    1. `Today SMA44 > Yesterday SMA44`
    2. `Today SMA44 > 2d Ago SMA44`
    3. `Daily Low < 44 SMA of Highs`
    4. `Daily Close > 44 SMA of Close`
    5. `Daily Close > Daily Open (Green Candle)`
  - Qualifying stocks receive a **`PMPatil`** tag.
- **Timeframe Tabs**:
  - **Both**: Qualifies on Daily AND Weekly simultaneously (Highest conviction multi-timeframe swing setup).
  - **Daily**: Standard Daily swing setup.
  - **Weekly**: Higher timeframe position setup.
  - **Weekly**: Higher timeframe position setup.
- **Interactive Visualizer**: In the chart modal, both the solid red **44 MA Close line** and the dashed amber **44 MA High band line** are plotted, so traders can visually inspect the intraday dip and rejection.
- **Diagnostic Debugger**: The "Why Rejected?" panel checks all 5 rules individually with exact price and MA levels.

---

## 2. Breakout Pattern Strategies

### A. Ascending Triangle Pattern
- **Consolidation Window**: Last 30–90 daily bars (or 15–40 weekly bars), starting at the first confirmed pivot of the consolidation.
- **Prior Trend**: Price higher 40+ bars ago than pattern start, OR preceded by a rise of at least 10% (daily) / 15% (weekly) in the preceding 60 / 20 bars.
- **Flat Resistance**: At least 2 confirmed swing highs (3 preferred) within ATR-based tolerance (`max(0.4% price, 0.35 * ATR)`) of a horizontal level. Normalized slope within ±0.05% per bar.
- **Rising Support**: At least 2 confirmed swing lows, positive normalized slope >= +0.05% per bar, $R^2 \ge 0.6$, with no close violating the line by more than tolerance.
- **Apex Convergence**: Lines converge within 1 to 15 bars after the last pattern bar.
- **Triangle Height**: Resistance level minus lowest confirmed swing low inside the pattern (>= 3% of price).
- **Status**:
  - `Confirmed Breakout`: Close above resistance × 1.002 within last 2 bars with volume >= 1.5× 20-bar average. Close <= resistance × 1.03.
  - `Retest Entry`: Breakout occurred 2 to 10 bars ago, low pulled back to resistance band, current bar closed back above resistance.
  - `Forming`: Price within 1.5% below resistance (Watchlist only).
- **Target**: `Entry + Triangle Height`. Target is never inflated. Minimum 1:3 R:R (reject if below).

### B. Symmetrical Triangle Pattern
- **Consolidation Window**: 30–90 daily bars or 15–40 weekly bars starting at the first confirmed pivot.
- **Upper Line**: Normalized slope <= -0.05% per bar, $R^2 \ge 0.6$, >= 2 confirmed touches.
- **Lower Line**: Normalized slope >= +0.05% per bar, $R^2 \ge 0.6$, >= 2 confirmed touches.
- **Volatility Contraction**: Average range (High - Low) of last third is at least 25% smaller than first third.
- **Volume Dry-up**: Average volume of last third < 85% of first third.
- **Apex Intersection**: Breakout occurs between 50% and 85% of distance to apex (rejected if after apex).
- **Base Height**: Upper line minus Lower line at pattern start (x = 0), >= 4% of price.
- **Target**: `Breakout Level + Base Height`. Minimum 1:2.5 R:R (reject if below).

### C. Bull Pole & Flag Pattern
- **Pole**:
  - *Daily*: Impulsive rise >= 12% over 5–15 bars, >= 60% green candles, volume >= 1.3× 20-bar average before pole.
  - *Weekly*: Impulsive rise >= 20% over 3–8 bars, volume >= 1.3× 20-bar average.
- **Flag**:
  - 5–20 bars (daily) or 3–10 bars (weekly) consolidation.
  - Retracement <= 50% of pole height. Price does not close below pole base.
  - Parallel-ish channel sloping down or sideways (slope between -0.4% and +0.1% per bar, slope difference <= 0.15% per bar).
  - Volume contraction: average flag volume < 80% of pole volume.
- **Breakout**: Close above upper flag line × 1.002 with volume >= 1.3× 20-bar average.
- **Target**: `Breakout Price + Pole Height`. Minimum 1:2.0 R:R.

---

## 3. Tech Stack & Architecture

- **Frontend**: Lightweight Charts (TradingView) + Tailwind CSS + Vanilla JS SPA in `templates/dashboard.html`.
- **Backend Options**:
  - **Flask**: `python app.py` (or `gunicorn app:app`)
  - **FastAPI**: `uvicorn main:app --reload --port 5000`
- **Pattern Engine**: `patterns/` module:
  - `patterns/geometry.py`: Shared pivot engine (`confirmed_pivots`, `fit_line_through_pivots`, `touches_on_line`, `atr`).
  - `patterns/ascending_triangle.py`: Deterministic ascending triangle breakout detector.
  - `patterns/symmetrical_triangle.py`: Symmetrical coil and volume dry-up detector.
  - `patterns/pole_and_flag.py`: Bull pole & flag detector.
  - `patterns/config.py`: Shared tolerances and constants.

---

## 4. API Endpoints

- `GET /api/scanner/44ma`: 44 MA Scanner with fixed `-1% to +3%` distance band.
- `GET /api/scanner/triangles?timeframe=daily|weekly`: Ascending and Symmetrical Triangles.
- `GET /api/scanner/pole_and_flag?timeframe=daily|weekly`: Pole & Flag Scanner.
- `GET /api/debug/<symbol>?strategy=<name>&timeframe=daily|weekly`: Returns diagnostic check and reject reasons for any symbol.
- `GET /api/chart/<symbol>?tf=daily|weekly`: OHLCV, 44 MA line, and pattern trendlines with touch points.
- `GET /api/export/csv?tab=<name>`: Download CSV exports.

---

## 5. How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run Unit Tests (pytest)
pytest test_patterns.py -v

# 3. Run Historical Backtest (3-Year Walk-Forward)
python backtest.py

# 4. Launch Application
# Option A: Flask
python app.py

# Option B: FastAPI
uvicorn main:app --reload --port 5000
```

Open `http://localhost:5000` in your web browser.

---

## 6. Changelog

- **Fixed Pivot Engine**: Replaced noisy `window=2` swing detector with `confirmed_pivots(window=3, min_separation=4)` requiring local dominance on each side and enforcing separation between same-type pivots.
- **Corrected Touch Counting**: Touches now count only genuine confirmed swing pivots within tolerance of the fitted line; non-pivot bars are excluded.
- **Unified Tolerances**: Unified all flatness and touch thresholds to ATR-based constant: `max(0.4% price, 0.35 * ATR)`.
- **Deterministic Pattern Windows**: Eliminated arbitrary lookback loops; patterns start at the first confirmed consolidation pivot.
- **Removed Target Inflation**: Strict uninflated targets (`Entry + Pattern Height`). Any setup with R:R below the minimum is rejected.
- **Added Symmetrical Triangle Volume Dry-Up & Apex**: Implemented volume contraction (< 85%) and apex progress bounds (50% to 85%).
- **Added Pole & Flag Strategy**: Full Daily & Weekly bull pole and flag detector with impulse rise, parallel channel, and volume contraction.
- **Updated 44 MA Scanner**: Replaced A/B sliders with a fixed `-1.0% to +3.0%` band across Touching, Above (0–3%), and Near Below (−1–0%).
- **Added Why Rejected Debugger**: `/api/debug/<symbol>` endpoint and UI diagnostic modal.
- **Added Automated Testing & Backtesting**: Added `test_patterns.py` unit test suite and `backtest.py` walk-forward engine.

---

*Disclaimer: For educational purposes only. Not financial or investment advice.*
