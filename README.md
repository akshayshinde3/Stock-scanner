# 44 MA Touch & Near Scanner — Indian Stocks Screener

A responsive stock screener website for Indian traders scanning the Nifty 500, Nifty 100, and Nifty 50 universes on the National Stock Exchange (NSE).

Includes:
1. **44 MA Touch & Near Strategy** (Daily, Weekly, and Both Daily+Weekly)
2. **Ascending Triangle Pattern Breakouts** (Direct Breakout & Retest/Pullback with 1:3 R:R)
3. **Symmetrical Triangle Pattern Breakouts** (Coil Breakout with volume expansion & height targets)

All old strategies have been removed.

---

## 1. 44 MA Strategy Definitions

- **MA44**: 44-period simple moving average of Close calculated separately for Daily and Weekly.
- **Distance %**: `(Close - MA44) / MA44 * 100`
- **TOUCH**: `Low <= MA44 <= High`
- **NEAR_BELOW**: `Close < MA44 AND Distance % >= -B` (default B = 3%, slider 0.5% - 5%)
- **ABOVE_ZONE**: `Close >= MA44 AND Distance % <= +A` (default A = 2%, slider 0.5% - 5%)
- **Qualification**: Stock qualifies if `TOUCH` or `NEAR_BELOW` or `ABOVE_ZONE` is true. Stocks more than A% above MA44 are excluded.
- **Status Badges** (First match wins):
  - **Touching** (Blue)
  - **Above (0-2%)** (Green)
  - **Near Below** (Orange)
- **Timeframe Tabs**:
  - **Both**: Qualifies on Daily AND Weekly simultaneously (Highest priority)
  - **Daily**: Qualifies on Daily timeframe
  - **Weekly**: Qualifies on Weekly timeframe

---

## 2. Breakout Pattern Strategies

### Ascending Triangle Pattern
- Flat horizontal upper resistance with 2-3+ touches.
- Rising lower support line connecting higher swing lows.
- **Direct Breakout Entry**: Price closes above resistance with volume surge.
- **Retest Entry**: Price retests broken resistance as new support.
- **Target**: `Breakout Price + Triangle Height (B - A)`.
- **Stop-Loss**: Below last swing low or retest low.
- **Risk to Reward**: Minimum 1:3.

### Symmetrical Triangle Pattern
- Two converging trendlines with opposite slopes (descending upper line + ascending lower line).
- Volume contraction during pattern development (indecision coil).
- Upside breakout with volume surge.
- **Target**: `Breakout Price + Triangle Base Height`.
- **Stop-Loss**: Right below breakout point.
- **Risk to Reward**: Minimum 1:2.5 to 1:3.

---

## 3. Tech Stack & Execution

- **Frontend**: React 18 + Tailwind CSS + TradingView Lightweight Charts (Standalone SPA in `templates/dashboard.html`).
- **Backend**:
  - **Flask**: `python app.py` (or `gunicorn app:app`)
  - **FastAPI**: `uvicorn main:app --reload --port 5000`
- **Data Engine**: Pandas + Yahoo Finance (`.NS` tickers) with EOD caching refreshed after 4:00 PM IST.

---

## 4. How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Option A: Run Flask App
python app.py

# Option B: Run FastAPI App
uvicorn main:app --reload --port 5000
```

Open `http://localhost:5000` in your web browser.

---

*Disclaimer: For educational purposes only. Not investment advice.*
