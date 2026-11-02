"""
Swing Trading Scanner — Upstox Edition
----------------------------------------
Runs locally on your PC. Logs into your Upstox account (OAuth),
polls your watchlist during market hours, evaluates 3 swing-trading
pattern strategies (Triangle, Darvas Box, Pennant), and shows live
BUY signals on a dashboard at http://localhost:5000.
Free push notifications via ntfy.sh.

⚠️ Educational tool only. Not investment advice. No strategy here
guarantees any win rate — always paper-trade before risking capital.
"""

import os
import io
import json
import time
import uuid
import gzip
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt

import requests
import pandas as pd
import yfinance as yf
from flask import Flask, request, redirect, jsonify, render_template, session, url_for, send_file
from dotenv import load_dotenv

import strategies

# Load environment variables from .env file
load_dotenv()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
# Optional: free NewsAPI.org key for headline-based news filter (leave blank to skip)
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
# Optional: website security password to lock the dashboard. If empty, the site is unprotected.
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "")

POLL_INTERVAL_SECONDS = 180         # how often to re-scan (Nifty 500 is heavy — keep this >= 120s)
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)

# Liquidity filter: skip stocks whose 20-day average daily turnover (price * volume)
# is below this, in INR crore. Filters out illiquid names prone to false breakouts.
MIN_AVG_DAILY_TURNOVER_CR = 5

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

# ---------------------------------------------------------------------------
# ntfy.sh Push Notifications (100% free, no signup)
# ---------------------------------------------------------------------------
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_ENABLED = os.environ.get("NTFY_ENABLED", "false").lower() == "true"
NTFY_SERVER = "https://ntfy.sh"

# Track which alerts have already been notified (avoid duplicates)
_notified_alerts = set()


def send_ntfy_notification(title, message, priority="default", tags=None):
    """Send a push notification via ntfy.sh (free, no API key needed)."""
    if not NTFY_TOPIC or not NTFY_ENABLED:
        return False
    try:
        headers = {
            "Title": title,
            "Priority": priority,
        }
        if tags:
            headers["Tags"] = ",".join(tags)
        resp = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        app.logger.warning(f"ntfy notification failed: {e}")
        return False


def notify_new_alerts(confirmed_alerts, watch_alerts):
    """Send phone notifications for new confirmed breakout signals."""
    global _notified_alerts
    if not NTFY_TOPIC or not NTFY_ENABLED:
        return

    for alert in confirmed_alerts:
        alert_key = f"{alert['symbol']}_{alert['strategy_used']}_{dt.date.today()}"
        if alert_key in _notified_alerts:
            continue

        title = f"🚀 BREAKOUT: {alert['symbol']}"
        message = (
            f"Strategy: {alert['strategy_used']}\n"
            f"LTP: ₹{alert['ltp']}\n"
            f"Buy: ₹{alert['buy_price']} | SL: ₹{alert['stop_loss']}\n"
            f"Target 1: ₹{alert['target1']} | Target 2: ₹{alert['target2']}\n"
            f"R:R: {alert['risk_reward']} | Confidence: {alert['confidence']}%\n"
            f"Reason: {alert['reasons'][0] if alert['reasons'] else 'N/A'}"
        )
        if send_ntfy_notification(title, message, priority="high", tags=["chart_with_upwards_trend", "money_bag"]):
            _notified_alerts.add(alert_key)

    # Also notify high-confidence watch signals (confidence >= 50)
    for alert in watch_alerts:
        if alert.get("confidence", 0) < 50:
            continue
        alert_key = f"watch_{alert['symbol']}_{alert['strategy_used']}_{dt.date.today()}"
        if alert_key in _notified_alerts:
            continue

        title = f"👀 WATCH: {alert['symbol']}"
        message = (
            f"Strategy: {alert['strategy_used']}\n"
            f"LTP: ₹{alert['ltp']}\n"
            f"Buy Trigger: ₹{alert['buy_price']} | SL: ₹{alert['stop_loss']}\n"
            f"Confidence: {alert['confidence']}%\n"
            f"Reason: {alert['reasons'][0] if alert['reasons'] else 'N/A'}"
        )
        if send_ntfy_notification(title, message, priority="default", tags=["eyes"]):
            _notified_alerts.add(alert_key)


app = Flask(__name__)
app.secret_key = os.urandom(24)

# In-memory state (single-user local app — no DB needed)
STATE = {
    "universe": [],           # Nifty 500 symbols being scanned
    "confirmed_alerts": [],   # breakouts that already triggered
    "watch_alerts": [],       # pre-breakout candidates (not yet triggered)
    "weekly_confirmed_alerts": [], # weekly breakouts
    "weekly_watch_alerts": [],     # weekly pre-breakout candidates
    "last_scan": None,
    "scan_progress": None,    # "120/500" while warming the candle cache
    "scanning": False,
    "error": None,
}


# Exclude known dummy / test / delisted ticker symbols from the NSE constituent list
EXCLUDE_SYMBOLS = {"DUMMYHEG", "BAGMANE"}


def load_nifty500_symbols():
    """Fetch the Nifty 500 constituent list. Prioritizes local nifty500.txt for instant
    startup without cloud IP blocking, falling back to NSE or candle_cache."""
    path = os.path.join(os.path.dirname(__file__), "nifty500.txt")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                syms = [line.strip().upper() for line in f if line.strip() and not line.startswith("#") and line.strip().upper() not in EXCLUDE_SYMBOLS and not line.strip().upper().startswith("DUMMY")]
                if len(syms) >= 100:
                    return syms
        except Exception as e:
            app.logger.warning(f"Error reading nifty500.txt: {e}")

    # Fallback to NSE if nifty500.txt is missing
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "text/csv"}
        r = requests.get(NIFTY500_URL, headers=headers, timeout=3)
        r.raise_for_status()
        lines = r.text.splitlines()
        symbols = []
        for line in lines[1:]:  # skip header row
            parts = line.split(",")
            if len(parts) >= 3:
                s = parts[2].strip().upper()
                if s and s not in EXCLUDE_SYMBOLS and not s.startswith("DUMMY"):
                    symbols.append(s)
        if len(symbols) >= 100:
            return symbols
    except Exception as e:
        app.logger.warning(f"Could not fetch live Nifty 500 list from NSE ({e}); checking cache fallback.")

    # Check if candle cache file on disk has symbols
    if os.path.exists(CANDLE_CACHE_FILE):
        try:
            with gzip.open(CANDLE_CACHE_FILE, "rt", encoding="utf-8") as f:
                cdata = json.load(f)
                d_syms = [s for s in cdata.get("daily", {}).keys() if s not in EXCLUDE_SYMBOLS and not s.startswith("DUMMY")]
                if len(d_syms) >= 100:
                    return d_syms
        except Exception:
            pass

    return []


@app.before_request
def require_login():
    allowed_routes = ["login", "static"]
    if request.endpoint and request.endpoint not in allowed_routes:
        if SITE_PASSWORD and not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not SITE_PASSWORD:
        return redirect(url_for("home"))
    
    if session.get("authenticated"):
        return redirect(url_for("home"))
        
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == SITE_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("home"))
        else:
            error = "Invalid password. Please try again."
            
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("login"))


@app.route("/favicon.ico")
def favicon():
    """Suppress browser 404 noise — we don't serve a favicon file."""
    return "", 204


@app.route("/")
def home():
    if not STATE["scanning"]:
        try:
            STATE["universe"] = load_nifty500_symbols()
            start_scanner_thread()
        except Exception as e:
            STATE["error"] = f"Failed to start scanner on load: {e}"
            app.logger.exception("start_scanner failed")
    try:
        return render_template("dashboard.html")
    except Exception as e:
        import traceback
        return f"<pre style='color:red;padding:20px'>Dashboard render error:\n{traceback.format_exc()}</pre>", 500


def save_env_keys(newsapi_key, site_password=None):
    global NEWSAPI_KEY, SITE_PASSWORD
    NEWSAPI_KEY = newsapi_key
    if site_password is not None:
        SITE_PASSWORD = site_password

    # Save to .env file (preserving notification settings)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(env_path, "w") as f:
        f.write(f"NEWSAPI_KEY={NEWSAPI_KEY}\n")
        f.write(f"SITE_PASSWORD={SITE_PASSWORD}\n")
        f.write(f"NTFY_TOPIC={NTFY_TOPIC}\n")
        f.write(f"NTFY_ENABLED={'true' if NTFY_ENABLED else 'false'}\n")


@app.route("/get-settings")
def get_settings():
    return jsonify({
        "NEWSAPI_KEY": NEWSAPI_KEY,
        "SITE_PASSWORD": SITE_PASSWORD
    })


@app.route("/update-settings", methods=["POST"])
def update_settings():
    data = request.get_json() or {}
    newsapi_key = data.get("NEWSAPI_KEY", "").strip()
    site_password = data.get("SITE_PASSWORD", "").strip()

    try:
        save_env_keys(newsapi_key, site_password)
        # Authenticate current session if password matches or is disabled
        if site_password:
            session["authenticated"] = True
        else:
            session.pop("authenticated", None)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Data fetch helpers (Yahoo Finance)
# ---------------------------------------------------------------------------
def get_daily_candles(symbol, days=365):
    ticker_symbol = f"{symbol.upper()}.NS"
    df = yf.download([ticker_symbol], period="1y", interval="1d", ignore_tz=True, progress=False)
    df = df.xs(ticker_symbol, axis=1, level=1).dropna(subset=["Close"])
    
    candles = []
    for index, row in df.iterrows():
        ts = index.strftime("%Y-%m-%dT00:00:00+05:30")
        candles.append([
            ts,
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
            int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            0
        ])
    return candles


def resample_daily_to_weekly(daily_candles):
    """Instantly converts daily candles into weekly candles in memory.
    Zero network latency — runs in ~0.0001 seconds per symbol.
    """
    if not daily_candles or len(daily_candles) < 5:
        return []

    weeks = {}
    for c in daily_candles:
        ts = c[0]
        date_str = ts[:10] if isinstance(ts, str) else str(ts)[:10]
        try:
            d = dt.date.fromisoformat(date_str)
        except Exception:
            continue
        cal = d.isocalendar()
        key = (cal[0], cal[1])  # (year, week_num)

        if key not in weeks:
            weeks[key] = {
                "ts": f"{date_str}T00:00:00+05:30",
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": int(c[5]) if c[5] else 0,
            }
        else:
            w = weeks[key]
            w["high"] = max(w["high"], float(c[2]))
            w["low"]  = min(w["low"], float(c[3]))
            w["close"] = float(c[4])
            w["volume"] += int(c[5]) if c[5] else 0
            w["ts"] = f"{date_str}T00:00:00+05:30"

    weekly = []
    for k in sorted(weeks.keys()):
        w = weeks[k]
        weekly.append([
            w["ts"],
            round(w["open"], 2),
            round(w["high"], 2),
            round(w["low"], 2),
            round(w["close"], 2),
            w["volume"],
            0
        ])
    return weekly


def get_weekly_candles(symbol, weeks=120):
    """Return weekly candles, derived in-memory from daily candles."""
    sym = symbol.upper()
    candles = _candle_cache.get(sym)
    if not candles:
        candles = get_daily_candles(sym)
        if candles:
            _candle_cache[sym] = candles
    if candles:
        return resample_daily_to_weekly(candles)
    return []


def get_yfinance_quotes(symbols):
    """Fetch current price, net change, change percentage, and volume for a list of symbols in bulk."""
    if not symbols:
        return {}
    
    tickers = [f"{sym.upper()}.NS" for sym in symbols]
    df = yf.download(tickers, period="5d", ignore_tz=True, progress=False)
    
    result = {}
    for sym in symbols:
        ticker_ns = f"{sym.upper()}.NS"
        try:
            ticker_df = df.xs(ticker_ns, axis=1, level=1)
            close_col = ticker_df['Close'].dropna()
            vol_col = ticker_df['Volume'].dropna()
            
            if len(close_col) >= 1:
                ltp = float(close_col.iloc[-1])
                volume = int(vol_col.iloc[-1]) if len(vol_col) >= 1 else 0
                
                if len(close_col) >= 2:
                    prev_close = float(close_col.iloc[-2])
                    net_change = ltp - prev_close
                    change_pct = (net_change / prev_close) * 100
                else:
                    prev_close = ltp
                    net_change = 0.0
                    change_pct = 0.0
                    
                result[sym.upper()] = {
                    "ltp": round(ltp, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": volume,
                    "net_change": round(net_change, 2)
                }
        except Exception as e:
            app.logger.warning(f"Error fetching yfinance quote for {sym}: {e}")
            
    return result


def merge_candles(existing_candles, new_candles):
    """Merge new candles into existing candles list, avoiding duplicates by date."""
    candle_dict = {c[0][:10]: c for c in existing_candles}
    for nc in new_candles:
        date_str = nc[0][:10]
        candle_dict[date_str] = nc
    sorted_dates = sorted(candle_dict.keys())
    return [candle_dict[d] for d in sorted_dates]


# ---------------------------------------------------------------------------
# Liquidity filter — skip stocks too thin to trade cleanly
# ---------------------------------------------------------------------------
def passes_liquidity_filter(candles):
    if len(candles) < 20:
        return False
    turnovers = [c[4] * c[5] for c in candles[-20:]]  # close * volume, in INR
    avg_turnover_cr = (sum(turnovers) / len(turnovers)) / 1e7  # convert to crore
    return avg_turnover_cr >= MIN_AVG_DAILY_TURNOVER_CR


def evaluate_symbol(symbol, candles, live_ltp):
    """Liquidity gate, then hand off to the enabled chart-pattern scanner."""
    if not passes_liquidity_filter(candles):
        return None
    try:
        return strategies.build_alert(symbol, candles, live_ltp, timeframe="daily")
    except Exception:
        return None


def evaluate_symbol_weekly(symbol, candles, live_ltp):
    """Hand off weekly candles to the chart-pattern scanner."""
    if len(candles) < 20:
        return None
    try:
        return strategies.build_alert(symbol, candles, live_ltp, timeframe="weekly")
    except Exception:
        return None



def get_news_flag(symbol):
    """Optional: recent news headline count via NewsAPI.org (free tier)."""
    if not NEWSAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": symbol, "language": "en", "sortBy": "publishedAt", "pageSize": 3,
                    "apiKey": NEWSAPI_KEY},
            timeout=8,
        )
        arts = r.json().get("articles", [])
        return [{"title": a["title"], "source": a["source"]["name"], "url": a["url"]} for a in arts]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Background scanner loop
# ---------------------------------------------------------------------------
_candle_cache = {}        # symbol -> candles, refreshed once per calendar day
_weekly_candle_cache = {}  # symbol -> weekly candles
_candle_cache_date   = None   # the calendar date on which _candle_cache was last populated
_weekly_cache_date   = None   # the calendar date on which _weekly_candle_cache was last populated

CANDLE_CACHE_FILE = os.path.join(
    "/data" if os.path.isdir("/data") else os.path.dirname(os.path.abspath(__file__)),
    "candle_cache.json.gz"
)


def save_candle_cache_to_disk():
    """Save daily and weekly candle caches to a compressed disk file (trimmed to keep file size tiny)."""
    try:
        trimmed_daily = {sym: c[-180:] for sym, c in _candle_cache.items()}
        trimmed_weekly = {sym: c[-80:] for sym, c in _weekly_candle_cache.items()}
        data = {
            "date": _candle_cache_date.isoformat() if _candle_cache_date else None,
            "weekly_date": _weekly_cache_date.isoformat() if _weekly_cache_date else None,
            "daily": trimmed_daily,
            "weekly": trimmed_weekly
        }
        with gzip.open(CANDLE_CACHE_FILE, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        app.logger.info(f"Candle cache saved to disk ({len(trimmed_daily)} symbols).")
    except Exception as e:
        app.logger.warning(f"Could not save candle cache to disk: {e}")


def load_candle_cache_from_disk():
    """Load daily and weekly candle caches from disk immediately on start."""
    global _candle_cache, _weekly_candle_cache, _candle_cache_date, _weekly_cache_date
    if not os.path.exists(CANDLE_CACHE_FILE):
        return
    try:
        with gzip.open(CANDLE_CACHE_FILE, "rt", encoding="utf-8") as f:
            data = json.load(f)
        cached_daily = data.get("daily", {})
        cached_weekly = data.get("weekly", {})
        if cached_daily:
            _candle_cache.update(cached_daily)
            _candle_cache_date = dt.date.today()
            app.logger.info(f"Loaded {len(_candle_cache)} daily candles from disk cache.")
        if cached_weekly:
            _weekly_candle_cache.update(cached_weekly)
            _weekly_cache_date = dt.date.today()
            app.logger.info(f"Loaded {len(_weekly_candle_cache)} weekly candles from disk cache.")
        if not STATE.get("universe") and _candle_cache:
            STATE["universe"] = sorted(list(_candle_cache.keys()))
    except Exception as e:
        app.logger.warning(f"Could not load candle cache from disk: {e}")



def _maybe_invalidate_candle_cache():
    """Mark cache updated without throwing away historical bars."""
    global _candle_cache_date, _weekly_cache_date
    today = dt.date.today()
    if _candle_cache_date != today:
        _candle_cache_date = today
    if _weekly_cache_date != today:
        _weekly_cache_date = today


def _extract_ticker_df(df, ticker_ns, tickers_ns):
    """Safely extract a single-ticker DataFrame from a yfinance multi-download result."""
    if df is None or df.empty:
        return None

    try:
        if isinstance(df.columns, pd.MultiIndex):
            ticker_df = df.xs(ticker_ns, axis=1, level=1)
        else:
            ticker_df = df

        if isinstance(ticker_df.columns, pd.MultiIndex):
            ticker_df.columns = [c[0] if isinstance(c, tuple) else c for c in ticker_df.columns]

        return ticker_df
    except KeyError:
        return None


def _download_batch_daily(batch, period="1y"):
    """Download daily candles for a batch of symbols and return {sym: candles}."""
    if not batch:
        return {}
    tickers_ns = [f"{sym}.NS" for sym in batch]
    try:
        df = yf.download(tickers_ns, period=period, interval="1d", ignore_tz=True, progress=False, threads=True)
        batch_candles = {}
        for sym in batch:
            ticker_ns = f"{sym}.NS"
            try:
                ticker_df = _extract_ticker_df(df, ticker_ns, tickers_ns)
                if ticker_df is None or ticker_df.empty:
                    continue
                ticker_df = ticker_df.dropna(subset=["Close"])
                candles = []
                for index, row in ticker_df.iterrows():
                    ts = index.strftime("%Y-%m-%dT00:00:00+05:30")
                    candles.append([
                        ts,
                        float(row["Open"]),
                        float(row["High"]),
                        float(row["Low"]),
                        float(row["Close"]),
                        int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                        0
                    ])
                if candles:
                    batch_candles[sym] = candles
            except Exception as e:
                app.logger.warning(f"Error parsing daily candles for {sym}: {e}")
        return batch_candles
    except Exception as e:
        app.logger.error(f"Error downloading batch ({len(batch)} symbols): {e}")
        return {}


def warm_cache_for_all_symbols(quick_only=False):
    """Warms daily candles in parallel via ThreadPoolExecutor and instantly derives weekly candles."""
    universe = STATE.get("universe") or []
    if not universe:
        return

    _maybe_invalidate_candle_cache()

    target_symbols = universe[:100] if quick_only else universe
    missing_daily = [sym for sym in target_symbols if sym not in _candle_cache]
    total_missing = len(missing_daily)

    if total_missing > 0:
        app.logger.info(f"Warming daily candles for {total_missing} symbols in parallel...")
        batch_size = 50
        batches = [missing_daily[i:i+batch_size] for i in range(0, total_missing, batch_size)]
        completed = 0
        STATE["scan_progress"] = f"0/{total_missing}"

        # 1. Download Batch 0 (top liquid symbols) first, so alerts appear in 5s!
        first_batch = batches[0]
        b0_res = _download_batch_daily(first_batch, period="1y")
        for sym, candles in b0_res.items():
            _candle_cache[sym] = candles
            _weekly_candle_cache[sym] = resample_daily_to_weekly(candles)
        completed += len(first_batch)
        STATE["scan_progress"] = f"{completed}/{total_missing}"
        _evaluate_all_symbols()

        # 2. Download remaining batches concurrently with ThreadPoolExecutor (4 threads)
        remaining_batches = batches[1:]
        if remaining_batches:
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_batch = {executor.submit(_download_batch_daily, b, "1y"): b for b in remaining_batches}
                for future in as_completed(future_to_batch):
                    b_res = future.result()
                    for sym, candles in b_res.items():
                        _candle_cache[sym] = candles
                        _weekly_candle_cache[sym] = resample_daily_to_weekly(candles)
                    completed += len(future_to_batch[future])
                    STATE["scan_progress"] = f"{completed}/{total_missing}"
                    _evaluate_all_symbols()

        save_candle_cache_to_disk()
        app.logger.info("Finished warming daily & weekly candles.")
    else:
        # Ensure weekly candles are generated in memory
        for sym in target_symbols:
            if sym not in _weekly_candle_cache and sym in _candle_cache:
                _weekly_candle_cache[sym] = resample_daily_to_weekly(_candle_cache[sym])


def is_market_open():
    now = dt.datetime.now()
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _evaluate_all_symbols():
    universe = STATE.get("universe") or []
    if not universe:
        return [], [], [], []
    confirmed, watch = [], []
    w_confirmed, w_watch = [], []

    for sym in universe:
        candles = _candle_cache.get(sym)
        if candles:
            live_price = candles[-1][4]
            res = evaluate_symbol(sym, candles, live_price)
            if res:
                res["timestamp"] = dt.datetime.now().strftime("%H:%M:%S")
                (confirmed if res["status"] == "confirmed" else watch).append(res)
                
            if passes_liquidity_filter(candles):
                w_candles = _weekly_candle_cache.get(sym)
                if w_candles:
                    last_close_w = w_candles[-1][4]
                    w_res = evaluate_symbol_weekly(sym, w_candles, last_close_w)
                    if w_res:
                        w_res["timestamp"] = dt.datetime.now().strftime("%H:%M:%S")
                        (w_confirmed if w_res["status"] == "confirmed" else w_watch).append(w_res)

    STATE["confirmed_alerts"] = sorted(confirmed, key=lambda x: -x["confidence"])
    STATE["watch_alerts"] = sorted(watch, key=lambda x: -x["confidence"])
    STATE["weekly_confirmed_alerts"] = sorted(w_confirmed, key=lambda x: -x["confidence"])
    STATE["weekly_watch_alerts"] = sorted(w_watch, key=lambda x: -x["confidence"])
    return confirmed, watch, w_confirmed, w_watch


_scan_event = threading.Event()
_latest_synced_date = None


def sync_latest_daily_candles(symbols=None):
    """Fetch latest 5-day candles for symbols and merge into cache using parallel batches."""
    global _latest_synced_date
    target_symbols = symbols or STATE.get("universe") or []
    if not target_symbols:
        return
    app.logger.info(f"Syncing live daily candles for {len(target_symbols)} symbols in parallel...")
    batch_size = 50
    batches = [target_symbols[i:i+batch_size] for i in range(0, len(target_symbols), batch_size)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_batch = {executor.submit(_download_batch_daily, b, "5d"): b for b in batches}
        for future in as_completed(future_to_batch):
            b_res = future.result()
            for sym, new_candles in b_res.items():
                if sym in _candle_cache:
                    _candle_cache[sym] = merge_candles(_candle_cache[sym], new_candles)
                else:
                    _candle_cache[sym] = new_candles
                _weekly_candle_cache[sym] = resample_daily_to_weekly(_candle_cache[sym])

    _latest_synced_date = dt.date.today()
    save_candle_cache_to_disk()


def scan_loop():
    global _latest_synced_date
    STATE["scanning"] = True

    # Try to load cache from disk at startup
    load_candle_cache_from_disk()

    # Fast initial evaluation from disk cache if available
    if _candle_cache:
        try:
            _evaluate_all_symbols()
            STATE["last_scan"] = dt.datetime.now().strftime("%H:%M:%S") + " (Cache)"
        except Exception as e:
            app.logger.warning(f"Initial cache evaluation error: {e}")

    while True:
        try:
            universe = STATE["universe"]
            if not universe:
                STATE["universe"] = load_nifty500_symbols()
                universe = STATE["universe"]
                if not universe:
                    STATE["error"] = "Nifty 500 list not loaded yet."
                    time.sleep(10)
                    continue

            market_open = is_market_open()
            STATE["error"] = None

            # 1. Warm missing daily & weekly candles (top liquid stocks show up in ~5s!)
            warm_cache_for_all_symbols()

            # 2. If market is open, sync live 5-day candles in parallel
            if market_open:
                sync_latest_daily_candles()

            # 3. Final evaluation pass
            confirmed, watch, w_confirmed, w_watch = _evaluate_all_symbols()
            STATE["scan_progress"] = None

            try:
                notify_new_alerts(confirmed + w_confirmed, watch + w_watch)
            except Exception as e:
                app.logger.warning(f"Notification error: {e}")

            if market_open:
                STATE["last_scan"] = dt.datetime.now().strftime("%H:%M:%S")
            else:
                STATE["last_scan"] = dt.datetime.now().strftime("%H:%M:%S") + " (EOD)"
                STATE["error"] = "Market closed — showing EOD pattern signals. Live scanning resumes at 9:15 IST."

        except Exception as e:
            STATE["error"] = f"Scan error: {e}"
            app.logger.exception("Error in scan_loop")

        sleep_secs = POLL_INTERVAL_SECONDS if is_market_open() else 300
        _scan_event.clear()
        _scan_event.wait(timeout=sleep_secs)


_thread_started = False


def start_scanner_thread():
    global _thread_started
    if not _thread_started:
        t = threading.Thread(target=scan_loop, daemon=True)
        t.start()
        _thread_started = True


# ---------------------------------------------------------------------------
# API endpoints for the dashboard
# ---------------------------------------------------------------------------
@app.route("/api/signals")
def api_signals():
    return jsonify({
        "confirmed_alerts": STATE["confirmed_alerts"],
        "watch_alerts": STATE["watch_alerts"],
        "last_scan": STATE["last_scan"],
        "scan_progress": STATE["scan_progress"],
        "market_open": is_market_open(),
        "error": STATE["error"],
        "universe_size": len(STATE["universe"]),
    })


@app.route("/api/signals/weekly")
def api_signals_weekly():
    return jsonify({
        "confirmed_alerts": STATE["weekly_confirmed_alerts"],
        "watch_alerts": STATE["weekly_watch_alerts"],
        "last_scan": STATE["last_scan"],
        "scan_progress": STATE["scan_progress"],
        "market_open": is_market_open(),
        "error": STATE["error"],
        "universe_size": len(STATE["universe"]),
    })


@app.route("/api/news/<symbol>")
def api_news(symbol):
    return jsonify({"news": get_news_flag(symbol)})


@app.route("/api/ltp")
def api_ltp():
    """Lightweight real-time LTP endpoint for dashboard price tickers.
    Usage: GET /api/ltp?symbols=RELIANCE,TCS,INFY
    Returns: { "RELIANCE": { "ltp": 1303.6, "change_pct": 0.82, "volume": 2548273 }, ... }
    """
    raw_symbols = request.args.get("symbols", "")
    symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
    if not symbols:
        return jsonify({}), 200

    try:
        result = get_yfinance_quotes(symbols)
        return jsonify(result)
    except Exception as e:
        app.logger.warning(f"/api/ltp error: {e}")
        return jsonify({}), 500


@app.route("/api/stocks")
def api_stocks():
    """Return all Nifty 500 stocks with live LTP, today's change%, and pattern tags."""
    universe = STATE["universe"]

    alert_map = {}
    for a in STATE["confirmed_alerts"]:
        alert_map[a["symbol"]] = {"pattern": a["strategy_used"], "status": "confirmed", "confidence": a["confidence"]}
    for a in STATE["watch_alerts"]:
        if a["symbol"] not in alert_map:
            alert_map[a["symbol"]] = {"pattern": a["strategy_used"], "status": "watch", "confidence": a["confidence"]}

    stocks = []
    for sym in universe:
        candles = _candle_cache.get(sym)
        
        if not candles or len(candles) < 2:
            stocks.append({
                "symbol": sym,
                "close": None,
                "prev_close": None,
                "change_pct": None,
                "volume": None,
                "high_52w": None,
                "low_52w": None,
                "pattern": alert_map.get(sym, {}).get("pattern", ""),
                "status": alert_map.get(sym, {}).get("status", ""),
                "confidence": alert_map.get(sym, {}).get("confidence", 0),
            })
            continue

        ltp = candles[-1][4]
        prev_close = candles[-2][4]
        volume = candles[-1][5]

        change_pct = round((ltp - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        highs = [c[2] for c in candles[-252:]]
        lows  = [c[3] for c in candles[-252:]]

        stocks.append({
            "symbol":     sym,
            "close":      round(ltp, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": change_pct,
            "volume":     int(volume),
            "high_52w":   round(max(highs), 2) if highs else None,
            "low_52w":    round(min(lows), 2) if lows else None,
            "pattern":    alert_map.get(sym, {}).get("pattern", ""),
            "status":     alert_map.get(sym, {}).get("status", ""),
            "confidence": alert_map.get(sym, {}).get("confidence", 0),
        })

    stocks.sort(key=lambda x: (-x["confidence"], x["symbol"]))
    return jsonify({
        "stocks": stocks,
        "total": len(stocks),
        "loaded": sum(1 for s in stocks if s["close"] is not None),
        "last_scan": STATE["last_scan"],
        "scan_progress": STATE["scan_progress"],
    })


def get_or_fetch_candles(symbol):
    """Get candles from cache or fetch on-demand if not loaded yet."""
    _maybe_invalidate_candle_cache()
    sym = symbol.upper()
    candles = _candle_cache.get(sym)
    if not candles:
        try:
            candles = get_daily_candles(sym)
            _candle_cache[sym] = candles
        except Exception:
            pass
    return candles


def get_or_fetch_weekly_candles(symbol):
    """Get weekly candles from cache or fetch on-demand if not loaded yet."""
    _maybe_invalidate_candle_cache()
    sym = symbol.upper()
    candles = _weekly_candle_cache.get(sym)
    if not candles:
        try:
            candles = get_weekly_candles(sym)
            _weekly_candle_cache[sym] = candles
        except Exception:
            pass
    return candles


# ---------------------------------------------------------------------------
# Cache management & Force Rescan endpoints
# ---------------------------------------------------------------------------
@app.route("/api/scan/quick", methods=["POST"])
def api_scan_quick():
    """Trigger a fast scan of the top 100 liquid stocks (takes ~5 seconds)."""
    def do_quick_scan():
        STATE["scan_progress"] = "Quick Scan (100)..."
        universe = STATE.get("universe") or []
        top100 = universe[:100]
        warm_cache_for_all_symbols(quick_only=True)
        if is_market_open():
            sync_latest_daily_candles(top100)
        _evaluate_all_symbols()
        STATE["scan_progress"] = None
        STATE["last_scan"] = dt.datetime.now().strftime("%H:%M:%S") + " (Quick)"
    
    threading.Thread(target=do_quick_scan, daemon=True).start()
    return jsonify({"success": True, "message": "Quick scan started for top 100 liquid stocks."})


@app.route("/api/scan/force", methods=["POST"])
def api_scan_force():
    """Trigger an immediate re-scan and fetch fresh candle data."""
    mode = request.args.get("mode", "full")
    if mode == "quick":
        return api_scan_quick()
    global _latest_synced_date
    _latest_synced_date = None  # reset to force candle sync
    _scan_event.set()           # wake up the scan loop immediately
    return jsonify({"success": True, "message": "Full scan triggered immediately."})


@app.route("/api/cache/clear", methods=["POST"])
def api_clear_cache():
    """Force-clear the candle cache so fresh data is fetched on next request."""
    global _candle_cache, _weekly_candle_cache, _candle_cache_date, _weekly_cache_date
    count = len(_candle_cache) + len(_weekly_candle_cache)
    _candle_cache.clear()
    _weekly_candle_cache.clear()
    _candle_cache_date  = None
    _weekly_cache_date  = None
    app.logger.info("Candle cache manually cleared via /api/cache/clear")
    return jsonify({"success": True, "cleared_symbols": count})


# ---------------------------------------------------------------------------
# Chart data endpoint
# ---------------------------------------------------------------------------
@app.route("/api/candles/<symbol>")
def api_candles(symbol):
    """Return OHLCV candle data for a symbol so the frontend can render a chart."""
    sym = symbol.upper()
    candles = get_or_fetch_candles(sym)
    if not candles:
        return jsonify({"error": "Symbol candle data not loaded or unavailable."}), 404

    result = []
    for c in candles[-120:]:
        ts = c[0]
        date_str = ts[:10] if isinstance(ts, str) else str(ts)[:10]
        result.append({
            "time":   date_str,
            "open":   round(c[1], 2),
            "high":   round(c[2], 2),
            "low":    round(c[3], 2),
            "close":  round(c[4], 2),
            "volume": int(c[5]),
        })

    return jsonify({"symbol": sym, "candles": result})


@app.route("/api/candles/<symbol>/weekly")
def api_candles_weekly(symbol):
    """Return OHLCV weekly candle data for a symbol so the frontend can render a weekly chart."""
    sym = symbol.upper()
    candles = get_or_fetch_weekly_candles(sym)
    if not candles:
        return jsonify({"error": "Symbol weekly candle data not loaded or unavailable."}), 404

    result = []
    for c in candles[-120:]:
        ts = c[0]
        date_str = ts[:10] if isinstance(ts, str) else str(ts)[:10]
        result.append({
            "time":   date_str,
            "open":   round(c[1], 2),
            "high":   round(c[2], 2),
            "low":    round(c[3], 2),
            "close":  round(c[4], 2),
            "volume": int(c[5]),
        })

    return jsonify({"symbol": sym, "candles": result})



# ---------------------------------------------------------------------------
# Pattern geometry endpoint — returns trendline data for chart drawing
# ---------------------------------------------------------------------------
@app.route("/api/pattern/<symbol>")
def api_pattern(symbol):
    """
    Re-runs all pattern detectors on cached candles and returns geometric
    drawing data so the frontend can overlay trendlines on the chart.
    Each pattern returns point arrays as [{time:'YYYY-MM-DD', value:N}, ...].
    """
    sym = symbol.upper()
    candles = get_or_fetch_candles(sym)
    if not candles:
        return jsonify({"error": "No candle data"}), 404

    # Use the same 120-candle window that the chart shows
    window = candles[-120:]
    dates = []
    for c in window:
        ts = c[0]
        dates.append(ts[:10] if isinstance(ts, str) else str(ts)[:10])

    n = len(window)
    patterns = {}

    def trendline_pts(slope, intercept, x_start, x_end, bar_offset=0):
        """Two-point line segment: start and end of the pattern window."""
        pts = []
        for xi in (x_start, x_end):
            idx = bar_offset + xi
            if 0 <= idx < len(dates):
                pts.append({"time": dates[idx], "value": round(slope * xi + intercept, 2)})
        return pts if len(pts) == 2 else []

    # ── TRIANGLE ─────────────────────────────────────────────────────────────
    try:
        tri = strategies.detect_triangle(candles, timeframe="daily")
        if tri:
            LOOKBACK = tri.get("lookback", 40)
            w = candles[-LOOKBACK:]
            highs = [c[2] for c in w]
            lows  = [c[3] for c in w]
            sh, sl_ = strategies.find_swing_points(highs, lows, window=2)
            rs, ri, _ = strategies.linreg(sh)
            ss, si_, _ = strategies.linreg(sl_)
            off = n - LOOKBACK
            lx  = LOOKBACK - 1
            res_line = trendline_pts(0, tri["resistance_now"], 0, lx, off) if tri["type"] == "Ascending Triangle" else trendline_pts(rs, ri, 0, lx, off)
            patterns["triangle"] = {
                "type": tri["type"],
                "resistance_line": res_line,
                "support_line":    trendline_pts(ss, si_, 0, lx, off),
                "resistance_level": tri["resistance_now"],
                "support_level":    tri["support_now"],
                "swing_highs": [{"time": dates[off + p[0]], "value": round(p[1], 2)}
                                 for p in sh if 0 <= off + p[0] < len(dates)],
                "swing_lows":  [{"time": dates[off + p[0]], "value": round(p[1], 2)}
                                 for p in sl_ if 0 <= off + p[0] < len(dates)],
            }
    except Exception:
        pass









    # ── PENNANT ───────────────────────────────────────────────────────────────
    try:
        pennant = strategies.detect_pennant(candles)
        if pennant:
            closes = [c[4] for c in window]
            pole_si, pole_ei, consol_si = 0, 0, 0
            for i in range(max(0, n - 25), n - 8):
                move = (closes[i + 8] - closes[i]) / closes[i] * 100
                if move >= 8.0:
                    pole_si   = i
                    pole_ei   = i + 8
                    consol_si = pole_ei
                    break
            consol_w = window[consol_si:]
            c_highs = [c[2] for c in consol_w]
            c_lows  = [c[3] for c in consol_w]
            if len(consol_w) >= 2:
                rs, ri, _ = strategies.linreg([(xi, v) for xi, v in enumerate(c_highs)])
                ss, si_v, _ = strategies.linreg([(xi, v) for xi, v in enumerate(c_lows)])
                cx = len(consol_w) - 1
                patterns["pennant"] = {
                    "type": pennant["type"],
                    "pole": [
                        {"time": dates[pole_si],     "value": round(window[pole_si][4],     2)},
                        {"time": dates[pole_ei - 1], "value": round(window[pole_ei - 1][4], 2)},
                    ],
                    "resistance_line": trendline_pts(rs, ri, 0, cx, consol_si),
                    "support_line":    trendline_pts(ss, si_v, 0, cx, consol_si),
                    "resistance_level": pennant["resistance"],
                    "support_level":    pennant["support"],
                    "pole_move_pct":    pennant["pole_move_pct"],
                }
    except Exception:
        pass

    return jsonify({"symbol": sym, "patterns": patterns})


@app.route("/api/pattern/<symbol>/weekly")
def api_pattern_weekly(symbol):
    """
    Re-runs all pattern detectors on cached weekly candles and returns geometric
    drawing data so the frontend can overlay trendlines on the weekly chart.
    Each pattern returns point arrays as [{time:'YYYY-MM-DD', value:N}, ...].
    """
    sym = symbol.upper()
    candles = get_or_fetch_weekly_candles(sym)
    if not candles:
        return jsonify({"error": "No candle data"}), 404

    # Use the same 120-candle window that the chart shows
    window = candles[-120:]
    dates = []
    for c in window:
        ts = c[0]
        dates.append(ts[:10] if isinstance(ts, str) else str(ts)[:10])

    n = len(window)
    patterns = {}

    def trendline_pts(slope, intercept, x_start, x_end, bar_offset=0):
        """Two-point line segment: start and end of the pattern window."""
        pts = []
        for xi in (x_start, x_end):
            idx = bar_offset + xi
            if 0 <= idx < len(dates):
                pts.append({"time": dates[idx], "value": round(slope * xi + intercept, 2)})
        return pts if len(pts) == 2 else []

    # ── TRIANGLE ─────────────────────────────────────────────────────────────
    try:
        tri = strategies.detect_triangle(candles, timeframe="weekly")
        if tri:
            LOOKBACK = tri.get("lookback", 40)
            w = candles[-LOOKBACK:]
            highs = [c[2] for c in w]
            lows  = [c[3] for c in w]
            sh, sl_ = strategies.find_swing_points(highs, lows, window=2)
            rs, ri, _ = strategies.linreg(sh)
            ss, si_, _ = strategies.linreg(sl_)
            off = n - LOOKBACK
            lx  = LOOKBACK - 1
            res_line = trendline_pts(0, tri["resistance_now"], 0, lx, off) if tri["type"] == "Ascending Triangle" else trendline_pts(rs, ri, 0, lx, off)
            patterns["triangle"] = {
                "type": tri["type"],
                "resistance_line": res_line,
                "support_line":    trendline_pts(ss, si_, 0, lx, off),
                "resistance_level": tri["resistance_now"],
                "support_level":    tri["support_now"],
            }
    except Exception:
        pass

    # ── PENNANT ───────────────────────────────────────────────────────────────
    try:
        pennant = strategies.detect_pennant(candles)
        if pennant:
            closes = [c[4] for c in window]
            pole_si, pole_ei, consol_si = 0, 0, 0
            for i in range(max(0, n - 25), n - 8):
                move = (closes[i + 8] - closes[i]) / closes[i] * 100
                if move >= 8.0:
                    pole_si   = i
                    pole_ei   = i + 8
                    consol_si = pole_ei
                    break
            consol_w = window[consol_si:]
            c_highs = [c[2] for c in consol_w]
            c_lows  = [c[3] for c in consol_w]
            if len(consol_w) >= 2:
                rs, ri, _ = strategies.linreg([(xi, v) for xi, v in enumerate(c_highs)])
                ss, si_v, _ = strategies.linreg([(xi, v) for xi, v in enumerate(c_lows)])
                cx = len(consol_w) - 1
                patterns["pennant"] = {
                    "type": pennant["type"],
                    "pole": [
                        {"time": dates[pole_si],     "value": round(window[pole_si][4],     2)},
                        {"time": dates[pole_ei - 1], "value": round(window[pole_ei - 1][4], 2)},
                    ],
                    "resistance_line": trendline_pts(rs, ri, 0, cx, consol_si),
                    "support_line":    trendline_pts(ss, si_v, 0, cx, consol_si),
                    "resistance_level": pennant["resistance"],
                    "support_level":    pennant["support"],
                    "pole_move_pct":    pennant["pole_move_pct"],
                }
    except Exception:
        pass

    return jsonify({"symbol": sym, "patterns": patterns})



# ---------------------------------------------------------------------------
# Notification endpoints (ntfy.sh)
# ---------------------------------------------------------------------------
@app.route("/api/notifications/settings", methods=["GET"])
def api_notification_settings_get():
    return jsonify({
        "topic": NTFY_TOPIC,
        "enabled": NTFY_ENABLED,
        "server": NTFY_SERVER,
    })


@app.route("/api/notifications/settings", methods=["POST"])
def api_notification_settings_save():
    global NTFY_TOPIC, NTFY_ENABLED
    d = request.json or {}
    NTFY_TOPIC = d.get("topic", "").strip()
    NTFY_ENABLED = bool(d.get("enabled", False))

    # Persist to .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if not line.startswith("NTFY_TOPIC=") and not line.startswith("NTFY_ENABLED="):
                    env_lines.append(line.rstrip("\n"))
    env_lines.append(f"NTFY_TOPIC={NTFY_TOPIC}")
    env_lines.append(f"NTFY_ENABLED={'true' if NTFY_ENABLED else 'false'}")
    with open(env_path, "w") as f:
        f.write("\n".join(env_lines) + "\n")

    return jsonify({"success": True})


@app.route("/api/notifications/test", methods=["POST"])
def api_notification_test():
    if not NTFY_TOPIC:
        return jsonify({"success": False, "error": "No topic configured"}), 400
    ok = send_ntfy_notification(
        "🔔 Test Notification",
        "Your Stock Scanner notifications are working! You'll receive alerts here when breakouts are detected.",
        priority="default",
        tags=["white_check_mark"],
    )
    return jsonify({"success": ok, "error": None if ok else "Failed to send notification"})


# ---------------------------------------------------------------------------
# App Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        STATE["universe"] = load_nifty500_symbols()
        start_scanner_thread()
    except Exception as e:
        print(f"Error starting scanner on startup: {e}")
        
    port = int(os.environ.get("PORT", 5000))
    print(f"\nScanner active at http://0.0.0.0:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
