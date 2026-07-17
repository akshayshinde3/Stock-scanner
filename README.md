# Nifty 500 Swing Scanner — Selected Chart Pattern Breakouts

Scans the full Nifty 500 universe every trading day, live, and flags stocks matching:
- **Triangle Breakout** (Ascending / Symmetrical).
- **Bull Flag** only.
- **Rising Wedge** only.
- **Ascending Channel** only.

Dashboard at `http://localhost:5000` shows two tables: **Confirmed Breakout Alerts** and
**Pre-Breakout Watchlist**, each with Buy Price, Stop Loss, Target 1, Target 2, Risk:Reward,
Confidence Score, and Expected Breakout Date — exactly the fields you asked for.

**⚠️ Read this before trusting any alert:**
- "Pre-breakout" flags are *pattern recognition on tightening ranges* — not a prediction
  with certainty. Treat the confidence score as **setup quality**, not a probability of
  profit. No public strategy reliably hits 80%+ accuracy on Indian equities.
- Every alert already enforces your rules: min 1:2 Risk:Reward and min ₹5 Cr average
  daily turnover (adjustable). No volume gate is applied.
- **Paper-trade this for a few weeks before using real capital.** Watch how the pre-breakout
  watchlist actually performs on your own data before trusting it.

---

## 1. Create your Upstox developer app (one-time, 5 minutes)

1. Go to https://developer.upstox.com and log in with your Upstox account.
2. Create a new app.
3. Set **Redirect URI** to exactly: `http://127.0.0.1:5000/callback`
4. Copy your **API Key (client_id)** and **API Secret (client_secret)**.

## 2. Install dependencies

```bash
cd swing-scanner
pip install -r requirements.txt
```

## 3. Set your credentials

```bash
export UPSTOX_API_KEY="your_api_key"
export UPSTOX_API_SECRET="your_api_secret"
# optional — enables the news headline lookup, get a free key at newsapi.org
export NEWSAPI_KEY="your_newsapi_key"
```

(Windows PowerShell: `$env:UPSTOX_API_KEY="..."` instead of `export`.)

## 4. Run it

```bash
python app.py
```

Open **http://127.0.0.1:5000**. You'll be redirected to Upstox's own login page,
log in there, and you're sent back to the dashboard. The app then:

1. Downloads the current Nifty 500 constituent list from NSE automatically
   (falls back to the included `nifty500.txt` if NSE blocks the request — see that
   file's comments for how to refresh it manually).
2. "Warms" its cache by pulling ~1 year of daily candles for all ~500 stocks
   (takes roughly 1–2 minutes the first time — you'll see progress in the header).
3. From then on, re-scans live prices every 3 minutes and re-evaluates the enabled
   chart patterns, updating the two alert tables.

**Note:** Upstox access tokens expire daily (~3:30am). Restart `app.py` and log in
again each trading morning.

---

## How each strategy actually works here

### Triangle Breakout (`strategies.py`)
- Finds swing highs/lows over the last 40 daily candles.
- Fits a trendline through the highs (resistance) and one through the lows (support)
  using linear regression.
- Classifies the shape as **Ascending** or **Symmetrical**.
- **Confirmed breakout**: today's candle is green and closes above the resistance line.
- **Pre-breakout watch**: the range has contracted 40%+ from where the triangle started,
  price is within 6 bars of the apex, and price is already within 1.5% of resistance —
  i.e., the classic "coiling spring" right before a move.

### Bull Flag
- Looks for a sharp bullish pole followed by a tight, downward-drifting flag.
- **Confirmed breakout**: price breaks above flag resistance.
- **Pre-breakout watch**: price is close to flag resistance while the flag is still forming.

### Rising Wedge
- Looks for rising, converging support and resistance lines.
- **Confirmed breakout**: price breaks above wedge resistance.
- **Pre-breakout watch**: price is within 1% of wedge resistance.

### Ascending Channel
- Looks for parallel support and resistance lines that both slope upward.
- **Confirmed breakout**: price breaks above channel resistance.
- **Pre-breakout watch**: price is near channel support inside the rising channel.

### Trade levels
- **Buy price**: just above the active pattern resistance, or today's close for an
  in-channel support watch.
- **Stop loss**: the active pattern support, or an ATR-based fallback when needed.
- **Targets**: 2x and 3x the risk (buy − stop) from the buy price.
- Any setup where Target 1 doesn't clear a 1:2 Risk:Reward is dropped automatically.

## Customizing

- `MIN_AVG_DAILY_TURNOVER_CR` in `app.py` — liquidity floor (default ₹5 Cr).
- `POLL_INTERVAL_SECONDS` in `app.py` — re-scan frequency (default 180s; Nifty 500
  is a lot of API calls, don't go much lower without checking Upstox's rate limits).
- Pattern sensitivity (`FLAT_SLOPE_THRESHOLD`, `LOOKBACK`, contraction/apex thresholds,
  and trendline slope thresholds) lives in `strategies.py`, plain Python, easy to tune.

## Limitations to know about

- Pattern detection is geometric (trendline fitting), not a vision model looking at
  chart shapes — it's a faithful, testable interpretation of the triangle logic in
  your reference images, but it won't catch every visually-obvious pattern a human
  eye would.
- Uses daily candles (correct for swing trading holding periods of days-to-weeks).
- Nothing here executes trades — it only displays alerts; you place orders yourself.
- News integration (optional) is a plain headline pull, not sentiment-scored.
