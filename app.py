"""
Swing Trading Scanner — Upstox Edition
----------------------------------------
Runs locally on your PC. Logs into your Upstox account (OAuth),
polls your watchlist during market hours, evaluates swing-trading
pattern strategies (Descending Channel, Triangle, Pennant), and shows live
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
# CONFIG & TIMEZONE
# ---------------------------------------------------------------------------
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "")

POLL_INTERVAL_SECONDS = 180         # how often to re-scan
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)

# Exact Indian Standard Time (IST = UTC+5:30)
IST_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))

def get_ist_now():
    """Return current datetime in Indian Standard Time (IST, UTC+5:30)."""
    return dt.datetime.now(dt.timezone.utc).astimezone(IST_TZ)

# Liquidity filter: skip stocks whose 20-day average daily turnover (price * volume)
# is below this, in INR crore.
MIN_AVG_DAILY_TURNOVER_CR = 1.0

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

# Nifty Midcap 100 constituent universe
MIDCAP100_SYMBOLS = {
    "FEDERALBNK", "IDFCFIRSTB", "BANDHANBNK", "AUBANK", "AUROPHARMA", "LUPIN", 
    "BIOCON", "GLENMARK", "TORNTPHARM", "ALKEM", "IPCALAB", "VOLTAS", "WHIRLPOOL", 
    "CROMPTON", "POLYCAB", "KEI", "DIXON", "ASTRAL", "SUPREMEIND", "ASHOKLEY", 
    "BHARATFORG", "BALKRISIND", "MRF", "APOLLOTYRE", "EXIDEIND", "ESCORTS", 
    "PERSISTENT", "COFORGE", "MPHASIS", "LTTS", "TATAELXSI", "KPITTECH", 
    "CYIENT", "SONACOMS", "SUNDRMFAST", "SCHAEFFLER", "SKFINDIA", "AIAENG", 
    "CUMMINSIND", "THERMAX", "OBEROIRLTY", "PHOENIXLTD", "PRESTIGE", "BRIGADE", 
    "GODREJPROP", "CONCOR", "GMRAIRPORT", "ABCAPITAL", "MFSL", "L&TFH", "CHOLAFIN", 
    "POONAWALLA", "SHRIRAMFIN", "MUTHOOTFIN", "MANAPPURAM", "CANFINHOME", "LICHSGFIN", 
    "HUDCO", "PETRONET", "GUJGASLTD", "IGL", "MGL", "OIL", "CASTROLIND", 
    "DEEPAKNTR", "TATACHEM", "PIIND", "UPL", "COROMANDEL", "CHAMBLFERT", "GNFC", 
    "ATUL", "SRF", "NAVINFLUOR", "FLUOROCHEM", "SAIL", "JINDALSTEL", "NATIONALUM", 
    "NMDC", "APLAPOLLO", "RATNAMANI", "PAGEIND", "BATAINDIA", "RELAXO", "DEVYANI", 
    "JUBLFOOD", "KALYANKJIL", "RADICO", "ZYDUSLIFE", "ABFRL", "TRENT", "JUBLPHARMA", 
    "MAXHEALTH", "FORTIS", "SYNGENE", "GLAXO", "PFIZER", "SANOFI", "AJANTPHARM", 
    "JBCHEPHARM", "METROPOLIS", "LALPATHLAB", "SUZLON", "BHEL", "COCHINSHIP", 
    "MAZDOCK", "BDL", "BEL", "HAL", "IDEA", "YESBANK", "NHPC", "SJVN", "IREDA", 
    "TATACOMM", "INDIAMART", "JUBLINGREA", "PVRINOX", "ZEEL", "SUNTV", "DELHIVERY"
}

# ---------------------------------------------------------------------------
# ntfy.sh Push Notifications (100% free, no signup)
# ---------------------------------------------------------------------------
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_ENABLED = os.environ.get("NTFY_ENABLED", "false").lower() == "true"
NTFY_SERVER = "https://ntfy.sh"

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

# In-memory state
STATE = {
    "universe": [],           # Nifty 500 symbols being scanned
    "confirmed_alerts": [],   # breakouts that already triggered
    "watch_alerts": [],       # pre-breakout candidates (not yet triggered)
    "weekly_confirmed_alerts": [], # weekly breakouts
    "weekly_watch_alerts": [],     # weekly pre-breakout candidates
    "last_scan": None,
    "scan_progress": None,
    "scanning": False,
    "error": None,
}

# Exclude known dummy / test / delisted ticker symbols
EXCLUDE_SYMBOLS = {"DUMMYHEG", "BAGMANE", "ISEC"}


def load_nifty500_symbols():
    path = os.path.join(os.path.dirname(__file__), "nifty500.txt")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                syms = [line.strip().upper() for line in f if line.strip() and not line.startswith("#") and line.strip().upper() not in EXCLUDE_SYMBOLS and not line.strip().upper().startswith("DUMMY")]
                if len(syms) >= 100:
                    return syms
        except Exception as e:
            app.logger.warning(f"Error reading nifty500.txt: {e}")

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "text/csv"}
        r = requests.get(NIFTY500_URL, headers=headers, timeout=3)
        r.raise_for_status()
        lines = r.text.splitlines()
        symbols = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) >= 3:
                s = parts[2].strip().upper()
                if s and s not in EXCLUDE_SYMBOLS and not s.startswith("DUMMY"):
                    symbols.append(s)
        if len(symbols) >= 100:
            return symbols
    except Exception as e:
        app.logger.warning(f"Could not fetch live Nifty 500 list from NSE ({e}); checking cache fallback.")

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
        if site_password:
            session["authenticated"] = True
        else:
            session.pop("authenticated", None)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Data fetch helpers (Yahoo Finance & Direct Chart API)
# ---------------------------------------------------------------------------
SYMBOL_MAP = {
    "MCDOWELL-N": "UNITDSPR",
    "LTI": "LTIM",
    "CADILAHC": "ZYDUSLIFE",
    "MINDTREE": "LTIM",
    "TATAMTRDVR": "TATAMOTORS",
    "KALPATPOWR": "KPIL",
    "GMRINFRA": "GMRAIRPORT",
    "MAHINDCIE": "CIEINDIA",
    "TBOEK": "TBOTEK",
    "NIPPON": "NAM-INDIA",
    "ARCHIAN": "ACI",
    "VENKYS": "VENKEYS",
    "AEGISCHEM": "AEGISLOG",
    "CAPL": "CAPLIPOI",
    "ISEC": "PVRINOX",
}

_yf_session = None

def get_yf_session():
    """Return a shared persistent requests.Session configured with browser headers."""
    global _yf_session
    if _yf_session is None:
        _yf_session = requests.Session()
        _yf_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
    return _yf_session

def reset_yf_session():
    """Reset session and crumb cache if Yahoo returns 429 or 401."""
    global _yf_session
    try:
        if _yf_session:
            _yf_session.close()
    except Exception:
        pass
    _yf_session = None
    return get_yf_session()


def fetch_candles_via_chart_api(symbol, period="1y"):
    """Fetch 1y daily OHLCV candles via Yahoo v8 Chart API (no crumb / quoteSummary errors)."""
    mapped_sym = SYMBOL_MAP.get(symbol.upper(), symbol.upper())
    ticker = f"{mapped_sym}.NS"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.yahoo.com"
    }
    try:
        session = get_yf_session()
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        chart = data.get("chart", {})
        result = chart.get("result")
        if not result or not result[0]:
            return []
        quote = result[0]
        timestamps = quote.get("timestamp", [])
        indicators = quote.get("indicators", {})
        quote_list = indicators.get("quote", [{}])
        if not quote_list:
            return []
        quote_data = quote_list[0]
        opens = quote_data.get("open", [])
        highs = quote_data.get("high", [])
        lows = quote_data.get("low", [])
        closes = quote_data.get("close", [])
        volumes = quote_data.get("volume", [])

        candles = []
        for i in range(len(timestamps)):
            c = closes[i] if i < len(closes) else None
            if c is None:
                continue
            t = dt.datetime.fromtimestamp(timestamps[i], tz=IST_TZ).strftime("%Y-%m-%dT00:00:00+05:30")
            o = opens[i] if i < len(opens) and opens[i] is not None else c
            h = highs[i] if i < len(highs) and highs[i] is not None else c
            l = lows[i] if i < len(lows) and lows[i] is not None else c
            v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
            candles.append([t, round(float(o), 2), round(float(h), 2), round(float(l), 2), round(float(c), 2), int(v), 0])
        return candles
    except Exception:
        return []


def get_daily_candles(symbol, days=365):
    # Fast direct chart API first
    candles = fetch_candles_via_chart_api(symbol, "1y")
    if candles:
        return candles

    mapped_sym = SYMBOL_MAP.get(symbol.upper(), symbol.upper())
    ticker_symbol = f"{mapped_sym}.NS"
    try:
        df = yf.download(
            [ticker_symbol],
            period="1y",
            interval="1d",
            ignore_tz=True,
            progress=False,
            threads=False,
            session=get_yf_session()
        )
        if df is None or df.empty:
            return []
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(ticker_symbol, axis=1, level=1)
        df = df.dropna(subset=["Close"])
        
        res_candles = []
        for index, row in df.iterrows():
            ts = index.strftime("%Y-%m-%dT00:00:00+05:30")
            res_candles.append([
                ts,
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                0
            ])
        return res_candles
    except Exception as e:
        app.logger.warning(f"Error fetching daily candles for {symbol}: {e}")
        if "401" in str(e) or "429" in str(e) or "Crumb" in str(e):
            reset_yf_session()
        return []


def resample_daily_to_weekly(daily_candles):
    """Instantly converts daily candles into weekly candles in memory."""
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
        key = (cal[0], cal[1])

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
    """Fetch current price, net change, change percentage, and volume for symbols in bulk."""
    if not symbols:
        return {}
    
    mapped_to_orig = {f"{SYMBOL_MAP.get(sym.upper(), sym.upper())}.NS": sym.upper() for sym in symbols}
    tickers = list(mapped_to_orig.keys())
    
    try:
        session = get_yf_session()
        df = yf.download(tickers, period="5d", ignore_tz=True, progress=False, threads=False, session=session)
        if df is None or df.empty:
            return {}
        
        result = {}
        for ticker_ns, sym in mapped_to_orig.items():
            try:
                ticker_df = _extract_ticker_df(df, ticker_ns, tickers)
                if ticker_df is None or ticker_df.empty:
                    continue
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
                        
                    result[sym] = {
                        "ltp": round(ltp, 2),
                        "change_pct": round(change_pct, 2),
                        "volume": volume,
                        "net_change": round(net_change, 2)
                    }
            except Exception as e:
                app.logger.warning(f"Error fetching yfinance quote for {sym}: {e}")
                
        return result
    except Exception as e:
        app.logger.warning(f"get_yfinance_quotes error: {e}")
        if "401" in str(e) or "429" in str(e) or "Crumb" in str(e):
            reset_yf_session()
        return {}


def merge_candles(existing_candles, new_candles):
    """Merge new candles into existing candles list, avoiding duplicates by date."""
    candle_dict = {c[0][:10]: c for c in existing_candles}
    for nc in new_candles:
        date_str = nc[0][:10]
        candle_dict[date_str] = nc
    sorted_dates = sorted(candle_dict.keys())
    return [candle_dict[d] for d in sorted_dates]


def passes_liquidity_filter(candles):
    if len(candles) < 20:
        return False
    turnovers = [c[4] * c[5] for c in candles[-20:]]
    avg_turnover_cr = (sum(turnovers) / len(turnovers)) / 1e7
    return avg_turnover_cr >= MIN_AVG_DAILY_TURNOVER_CR


def evaluate_symbol(symbol, candles, live_ltp):
    if not passes_liquidity_filter(candles):
        return None
    try:
        return strategies.build_alert(symbol, candles, live_ltp, timeframe="daily")
    except Exception:
        return None


def evaluate_symbol_weekly(symbol, candles, live_ltp):
    if len(candles) < 20:
        return None
    try:
        return strategies.build_alert(symbol, candles, live_ltp, timeframe="weekly")
    except Exception:
        return None


def get_news_flag(symbol):
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
_candle_cache = {}
_weekly_candle_cache = {}
_candle_cache_date   = None
_weekly_cache_date   = None

CANDLE_CACHE_FILE = os.path.join(
    "/data" if os.path.isdir("/data") else os.path.dirname(os.path.abspath(__file__)),
    "candle_cache.json.gz"
)


def save_candle_cache_to_disk():
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
    global _candle_cache_date, _weekly_cache_date
    today = dt.date.today()
    if _candle_cache_date != today:
        _candle_cache_date = today
    if _weekly_cache_date != today:
        _weekly_cache_date = today


def _extract_ticker_df(df, ticker_ns, tickers_ns):
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
    """Download daily candles for a batch using parallel chart API fetching."""
    if not batch:
        return {}

    batch_candles = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_sym = {executor.submit(fetch_candles_via_chart_api, s, period): s for s in batch}
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                c = future.result()
                if c:
                    batch_candles[sym] = c
            except Exception:
                pass

    missing = [s for s in batch if s not in batch_candles]
    if missing:
        try:
            mapped_to_orig = {f"{SYMBOL_MAP.get(sym.upper(), sym.upper())}.NS": sym.upper() for sym in missing}
            tickers_ns = list(mapped_to_orig.keys())
            session = get_yf_session()
            df = yf.download(
                tickers_ns,
                period=period,
                interval="1d",
                ignore_tz=True,
                progress=False,
                threads=False,
                session=session
            )
            if df is not None and not df.empty:
                for ticker_ns, sym in mapped_to_orig.items():
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
        except Exception:
            pass

    return batch_candles


def warm_cache_for_all_symbols(quick_only=False):
    universe = STATE.get("universe") or []
    if not universe:
        return

    _maybe_invalidate_candle_cache()

    target_symbols = universe[:100] if quick_only else universe
    missing_daily = [sym for sym in target_symbols if sym not in _candle_cache]
    total_missing = len(missing_daily)

    if total_missing > 0:
        app.logger.info(f"Warming daily candles for {total_missing} symbols in sequential batches...")
        batch_size = 50
        batches = [missing_daily[i:i+batch_size] for i in range(0, total_missing, batch_size)]
        completed = 0
        STATE["scan_progress"] = f"0/{total_missing}"

        for b in batches:
            b_res = _download_batch_daily(b, period="1y")
            for sym, candles in b_res.items():
                _candle_cache[sym] = candles
                _weekly_candle_cache[sym] = resample_daily_to_weekly(candles)
            completed += len(b)
            STATE["scan_progress"] = f"{min(completed, total_missing)}/{total_missing}"
            _evaluate_all_symbols()
            if len(batches) > 1:
                time.sleep(0.3)

        save_candle_cache_to_disk()
        app.logger.info("Finished warming daily & weekly candles.")
    else:
        for sym in target_symbols:
            if sym not in _weekly_candle_cache and sym in _candle_cache:
                _weekly_candle_cache[sym] = resample_daily_to_weekly(_candle_cache[sym])


def is_market_open():
    """True if Indian stock market is open: Mon-Fri, 9:15 AM to 3:30 PM IST."""
    now_ist = get_ist_now()
    if now_ist.weekday() >= 5:
        return False
    return MARKET_OPEN <= now_ist.time() <= MARKET_CLOSE


def _evaluate_all_symbols():
    universe = STATE.get("universe") or []
    if not universe:
        return [], [], [], []
    confirmed, watch = [], []
    w_confirmed, w_watch = [], []

    ist_time_str = get_ist_now().strftime("%H:%M:%S")

    for sym in universe:
        candles = _candle_cache.get(sym)
        if candles:
            live_price = candles[-1][4]
            res = evaluate_symbol(sym, candles, live_price)
            if res:
                res["timestamp"] = ist_time_str
                res["is_midcap"] = sym in MIDCAP100_SYMBOLS
                if res["status"] == "confirmed":
                    # STRICT RULE: Confirmation stock ONLY above 60%
                    if res.get("confidence", 0) >= 60:
                        confirmed.append(res)
                else:
                    watch.append(res)
                
            if passes_liquidity_filter(candles):
                w_candles = _weekly_candle_cache.get(sym)
                if w_candles:
                    last_close_w = w_candles[-1][4]
                    w_res = evaluate_symbol_weekly(sym, w_candles, last_close_w)
                    if w_res:
                        w_res["timestamp"] = ist_time_str
                        w_res["is_midcap"] = sym in MIDCAP100_SYMBOLS
                        if w_res["status"] == "confirmed":
                            if w_res.get("confidence", 0) >= 60:
                                w_confirmed.append(w_res)
                        else:
                            w_watch.append(w_res)

    STATE["confirmed_alerts"] = sorted(confirmed, key=lambda x: -x["confidence"])
    STATE["watch_alerts"] = sorted(watch, key=lambda x: -x["confidence"])
    STATE["weekly_confirmed_alerts"] = sorted(w_confirmed, key=lambda x: -x["confidence"])
    STATE["weekly_watch_alerts"] = sorted(w_watch, key=lambda x: -x["confidence"])
    return confirmed, watch, w_confirmed, w_watch


_scan_event = threading.Event()
_latest_synced_date = None


def sync_latest_daily_candles(symbols=None):
    global _latest_synced_date
    target_symbols = symbols or STATE.get("universe") or []
    if not target_symbols:
        return
    app.logger.info(f"Syncing live daily candles for {len(target_symbols)} symbols...")
    batch_size = 50
    batches = [target_symbols[i:i+batch_size] for i in range(0, len(target_symbols), batch_size)]

    for b in batches:
        b_res = _download_batch_daily(b, period="5d")
        for sym, new_candles in b_res.items():
            if sym in _candle_cache:
                _candle_cache[sym] = merge_candles(_candle_cache[sym], new_candles)
            else:
                _candle_cache[sym] = new_candles
            _weekly_candle_cache[sym] = resample_daily_to_weekly(_candle_cache[sym])
        if len(batches) > 1:
            time.sleep(0.3)

    _latest_synced_date = get_ist_now().date()
    save_candle_cache_to_disk()


def scan_loop():
    global _latest_synced_date
    STATE["scanning"] = True

    load_candle_cache_from_disk()

    if _candle_cache:
        try:
            _evaluate_all_symbols()
            STATE["last_scan"] = get_ist_now().strftime("%H:%M:%S") + " (IST - Cache)"
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

            warm_cache_for_all_symbols()

            if market_open:
                sync_latest_daily_candles()

            confirmed, watch, w_confirmed, w_watch = _evaluate_all_symbols()
            STATE["scan_progress"] = None

            try:
                notify_new_alerts(confirmed + w_confirmed, watch + w_watch)
            except Exception as e:
                app.logger.warning(f"Notification error: {e}")

            if market_open:
                STATE["last_scan"] = get_ist_now().strftime("%H:%M:%S") + " (IST - Live)"
            else:
                STATE["last_scan"] = get_ist_now().strftime("%H:%M:%S") + " (IST - EOD)"
                STATE["error"] = "Market closed (9:15 AM – 3:30 PM IST). Showing EOD patterns. Live scanning resumes tomorrow at 9:15 AM IST."

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
        max_h = max(highs) if highs else None
        min_l = min(lows) if lows else None
        dist_52w = round(((max_h - ltp) / max_h) * 100, 2) if max_h and max_h > 0 else None

        stocks.append({
            "symbol":       sym,
            "close":        round(ltp, 2),
            "prev_close":   round(prev_close, 2),
            "change_pct":   change_pct,
            "volume":       int(volume),
            "high_52w":     round(max_h, 2) if max_h else None,
            "low_52w":      round(min_l, 2) if min_l else None,
            "dist_52w_pct": dist_52w,
            "is_52w_high":  (dist_52w is not None and dist_52w <= 0.5),
            "is_midcap":    sym in MIDCAP100_SYMBOLS,
            "pattern":      alert_map.get(sym, {}).get("pattern", ""),
            "status":       alert_map.get(sym, {}).get("status", ""),
            "confidence":   alert_map.get(sym, {}).get("confidence", 0),
        })

    stocks.sort(key=lambda x: (-x["confidence"], x["symbol"]))
    return jsonify({
        "stocks": stocks,
        "total": len(stocks),
        "loaded": sum(1 for s in stocks if s["close"] is not None),
        "last_scan": STATE["last_scan"],
        "scan_progress": STATE["scan_progress"],
    })


@app.route("/api/stocks/52w")
def api_stocks_52w():
    """
    Return all Nifty 500 stocks within 5% of their 52-week high,
    identifying 52W Box Breakouts, Descending Channels, and Midcap 100 stocks.
    """
    universe = STATE.get("universe") or []
    alert_map = {}
    for a in STATE.get("confirmed_alerts", []):
        alert_map[a["symbol"]] = {"pattern": a["strategy_used"], "status": "confirmed", "confidence": a["confidence"]}
    for a in STATE.get("watch_alerts", []):
        if a["symbol"] not in alert_map:
            alert_map[a["symbol"]] = {"pattern": a["strategy_used"], "status": "watch", "confidence": a["confidence"]}

    results = []
    for sym in universe:
        candles = _candle_cache.get(sym)
        if not candles or len(candles) < 20:
            continue
        
        h_bars = candles[-252:]
        highs = [c[2] for c in h_bars]
        lows = [c[3] for c in h_bars]
        if not highs:
            continue
        
        high_52w = max(highs)
        low_52w = min(lows)
        ltp = candles[-1][4]
        prev_close = candles[-2][4] if len(candles) >= 2 else ltp
        volume = candles[-1][5]

        if high_52w <= 0:
            continue

        dist_pct = round(((high_52w - ltp) / high_52w) * 100, 2)
        change_pct = round((ltp - prev_close) / prev_close * 100, 2) if prev_close else 0.0

        if dist_pct <= 5.0:
            is_box = False
            box_label = ""
            box_top = high_52w
            if len(candles) >= 25:
                c_bars = candles[-35:-1]
                c_highs = [c[2] for c in c_bars]
                c_lows = [c[3] for c in c_bars]
                box_top = max(c_highs)
                box_bottom = min(c_lows)
                box_h_pct = ((box_top - box_bottom) / box_bottom) * 100 if box_bottom > 0 else 999

                if ltp >= box_top * 0.995 or dist_pct <= 0.5:
                    is_box = True
                    box_label = "📦 52W Box Breakout"
                elif dist_pct <= 2.5 and box_h_pct <= 16.0:
                    is_box = True
                    box_label = "📦 52W Box Setup"

            existing_pattern = alert_map.get(sym, {}).get("pattern", "")
            existing_status = alert_map.get(sym, {}).get("status", "")
            existing_conf = alert_map.get(sym, {}).get("confidence", 0)

            # Check descending channel if not already in alert map
            if not existing_pattern:
                ch = strategies.detect_descending_channel(candles, timeframe="daily", live_price=ltp)
                if ch:
                    existing_pattern = "Descending Channel"
                    existing_status = ch["status"]
                    existing_conf = 78 if ch["status"] == "confirmed" else 62

            final_pattern = existing_pattern if existing_pattern else (box_label if box_label else "52W High")
            final_status = existing_status if existing_status else ("confirmed" if (dist_pct <= 0.5 or (is_box and ltp >= box_top * 0.995)) else "watch")
            final_conf = existing_conf if existing_conf > 0 else (88 if is_box else 75)

            results.append({
                "symbol": sym,
                "ltp": round(ltp, 2),
                "change_pct": change_pct,
                "high_52w": round(high_52w, 2),
                "low_52w": round(low_52w, 2),
                "dist_52w_pct": max(0.0, dist_pct),
                "is_at_high": dist_pct <= 0.5,
                "is_box_breakout": is_box,
                "box_label": box_label,
                "is_midcap": sym in MIDCAP100_SYMBOLS,
                "volume": int(volume),
                "pattern": final_pattern,
                "status": final_status,
                "confidence": final_conf,
            })

    results.sort(key=lambda x: (x["dist_52w_pct"], -x["confidence"], x["symbol"]))

    return jsonify({
        "stocks": results,
        "total": len(results),
        "at_high_count": sum(1 for s in results if s["is_at_high"]),
        "within_2pct_count": sum(1 for s in results if s["dist_52w_pct"] <= 2.0),
        "within_5pct_count": len(results),
        "box_count": sum(1 for s in results if s["is_box_breakout"]),
        "midcap_count": sum(1 for s in results if s["is_midcap"]),
        "last_scan": STATE.get("last_scan"),
    })


def get_or_fetch_candles(symbol):
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


@app.route("/api/scan/quick", methods=["POST"])
def api_scan_quick():
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
    mode = request.args.get("mode", "full")
    if mode == "quick":
        return api_scan_quick()
    global _latest_synced_date
    _latest_synced_date = None
    _scan_event.set()
    return jsonify({"success": True, "message": "Full scan triggered immediately."})


@app.route("/api/cache/clear", methods=["POST"])
def api_clear_cache():
    global _candle_cache, _weekly_candle_cache, _candle_cache_date, _weekly_cache_date
    count = len(_candle_cache) + len(_weekly_candle_cache)
    _candle_cache.clear()
    _weekly_candle_cache.clear()
    _candle_cache_date  = None
    _weekly_cache_date  = None
    app.logger.info("Candle cache manually cleared via /api/cache/clear")
    return jsonify({"success": True, "cleared_symbols": count})


@app.route("/api/candles/<symbol>")
def api_candles(symbol):
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
    """
    sym = symbol.upper()
    candles = get_or_fetch_candles(sym)
    if not candles:
        return jsonify({"error": "No candle data"}), 404

    window = candles[-120:]
    dates = []
    for c in window:
        ts = c[0]
        dates.append(ts[:10] if isinstance(ts, str) else str(ts)[:10])

    n = len(window)
    patterns = {}

    def trendline_pts(slope, intercept, x_start, x_end, bar_offset=0):
        pts = []
        for xi in (x_start, x_end):
            idx = bar_offset + xi
            if 0 <= idx < len(dates):
                pts.append({"time": dates[idx], "value": round(slope * xi + intercept, 2)})
        return pts if len(pts) == 2 else []

    # ── DESCENDING CHANNEL ───────────────────────────────────────────────────
    try:
        ch = strategies.detect_descending_channel(candles, timeframe="daily")
        if ch:
            LOOKBACK = ch.get("lookback", 30)
            off = n - LOOKBACK
            lx = LOOKBACK - 1
            res_line = trendline_pts(ch["res_slope"], ch["res_intercept"], 0, lx, off)
            sup_line = trendline_pts(ch["sup_slope"], ch["sup_intercept"], 0, lx, off)
            patterns["channel"] = {
                "type": ch["type"],
                "resistance_line": res_line,
                "support_line": sup_line,
                "resistance_level": ch["resistance_now"],
                "support_level": ch["support_now"],
                "channel_height": ch["channel_height"],
            }
    except Exception:
        pass

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
            sup_line = trendline_pts(ss, si_, 0, lx, off)
            patterns["triangle"] = {
                "type": tri["type"],
                "resistance_line": res_line,
                "support_line":    sup_line,
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
                if move >= 6.0:
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
    drawing data for weekly chart overlays.
    """
    sym = symbol.upper()
    candles = get_or_fetch_weekly_candles(sym)
    if not candles:
        return jsonify({"error": "No candle data"}), 404

    window = candles[-120:]
    dates = []
    for c in window:
        ts = c[0]
        dates.append(ts[:10] if isinstance(ts, str) else str(ts)[:10])

    n = len(window)
    patterns = {}

    def trendline_pts(slope, intercept, x_start, x_end, bar_offset=0):
        pts = []
        for xi in (x_start, x_end):
            idx = bar_offset + xi
            if 0 <= idx < len(dates):
                pts.append({"time": dates[idx], "value": round(slope * xi + intercept, 2)})
        return pts if len(pts) == 2 else []

    # ── DESCENDING CHANNEL WEEKLY ────────────────────────────────────────────
    try:
        ch = strategies.detect_descending_channel(candles, timeframe="weekly")
        if ch:
            LOOKBACK = ch.get("lookback", 20)
            off = n - LOOKBACK
            lx = LOOKBACK - 1
            res_line = trendline_pts(ch["res_slope"], ch["res_intercept"], 0, lx, off)
            sup_line = trendline_pts(ch["sup_slope"], ch["sup_intercept"], 0, lx, off)
            patterns["channel"] = {
                "type": ch["type"],
                "resistance_line": res_line,
                "support_line": sup_line,
                "resistance_level": ch["resistance_now"],
                "support_level": ch["support_now"],
                "channel_height": ch["channel_height"],
            }
    except Exception:
        pass

    # ── TRIANGLE WEEKLY ──────────────────────────────────────────────────────
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
            sup_line = trendline_pts(ss, si_, 0, lx, off)
            patterns["triangle"] = {
                "type": tri["type"],
                "resistance_line": res_line,
                "support_line":    sup_line,
                "resistance_level": tri["resistance_now"],
                "support_level":    tri["support_now"],
            }
    except Exception:
        pass

    # ── PENNANT WEEKLY ───────────────────────────────────────────────────────
    try:
        pennant = strategies.detect_pennant(candles)
        if pennant:
            closes = [c[4] for c in window]
            pole_si, pole_ei, consol_si = 0, 0, 0
            for i in range(max(0, n - 25), n - 8):
                move = (closes[i + 8] - closes[i]) / closes[i] * 100
                if move >= 6.0:
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
