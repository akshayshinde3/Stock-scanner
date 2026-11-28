# Swing Stock Screener — Indian Stocks (NSE / Nifty 500)

A stock screener and technical breakout engine for NSE stocks scanning Nifty 500, Nifty 100, Nifty 50, Midcap, and Smallcap universes.

Includes 4 swing trading engines:
1. **Ascending Triangle Pattern** (Breakout & Retest with uninflated 1:3 R:R)
2. **Symmetrical Triangle Pattern** (Coil contraction, volume dry-up, apex intersection, 1:2.5 R:R)
3. **Bull Pole & Flag Pattern** (Daily & Weekly momentum continuation, 1:2.0 R:R)
4. **44 MA Touch & Near Strategy** (Strictly fixed **-1.0% to +3.0%** distance band)

---

## 1. 44 MA Rising Stocks (-1.0% to +3.0%)

Scans for liquid stocks trading within **-1.0% to +3.0%** of an active, **rising 44-period Moving Average**:

- **MA44 Rising**: `today's SMA(Close, 44) > yesterday's SMA(Close, 44)` (strictly upward sloping).
- **Strict Qualification Band**: Qualifies **ONLY** if `-1.0 <= Distance % <= +3.0`.
- **Status Badges**:
  1. **Touching**: `Low <= MA44 <= High` (intraday touch of rising 44 MA inside -1% to +3%).
  2. **Above (0–3%)**: `Close >= MA44` and `Distance % <= +3.0%`.
  3. **Near Below (−1–0%)**: `Close < MA44` and `Distance % >= -1.0%`.
- **Chartink Filter Support (`swing-trade-by-pmpatil`)**: Tags stocks meeting all 5 Chartink rules with **`PMPatil`**.
- **Timeframe Tabs**: **Both** (Daily + Weekly), **Daily**, **Weekly**.
- **Interactive Chart & Diagnostics**: Plots 44 MA Close, 44 MA High band, trendlines, and touch pivots, plus rule-by-rule diagnostics (`/api/debug/<symbol>`).

---

## 2. Tech Stack & Architecture

- **Frontend**: Clean light-theme SPA (`templates/dashboard.html`) with TradingView Lightweight Charts (dark chart modal for high contrast).
- **Backend**: Flask (`app.py`), served via `gunicorn app:app` in production (`Procfile`).
- **Pattern Engine**: `patterns/` module:
  - `patterns/geometry.py`: Shared pivot engine, OLS line fitting, ATR, weekly resampler.
  - `patterns/ascending_triangle.py`: Ascending triangle detector.
  - `patterns/symmetrical_triangle.py`: Symmetrical triangle coil detector.
  - `patterns/pole_and_flag.py`: Bull pole & flag detector.
  - `patterns/config.py`: Shared tolerances and thresholds.

---

## 3. API Endpoints

- `GET /health`: Health check (`200 OK`).
- `GET /api/cache-status?index=nifty500`: Cache warm-up progress for frontend progress bar.
- `GET /api/scanner/44ma`: 44 MA Scanner (`-1% to +3%` band).
- `GET /api/scanner/triangles?timeframe=daily|weekly`: Ascending and Symmetrical Triangles.
- `GET /api/scanner/pole_and_flag?timeframe=daily|weekly`: Pole & Flag Scanner.
- `GET /api/debug/<symbol>?strategy=<name>&timeframe=daily|weekly`: Diagnostic rule checks and reject reasons.
- `GET /api/chart/<symbol>?tf=daily|weekly`: OHLCV, 44 MA lines, and pattern trendlines.
- `GET /api/export/csv?tab=<name>`: Download CSV exports.

---

## 4. Setup & How to Run

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure environment** (`.env` in project root):
   ```env
   SITE_PASSWORD=your_strong_password
   APP_SECRET_KEY=your_long_random_secret
   ```
3. **Run Unit Tests**:
   ```bash
   pytest test_patterns.py -v
   ```
4. **Launch Application**:
   - Windows one-click: double-click `start.bat` (or run `python app.py`)
   - Production (Render / Linux): `gunicorn app:app --workers 1 --threads 4 --timeout 120`
5. **Run Historical Backtest** (optional dev script):
   ```bash
   python backtest.py
   ```

Open `http://localhost:5000` in your browser.

---

*Disclaimer: For educational purposes only. Not financial or investment advice.*
