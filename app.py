"""
app.py — 44 MA Touch & Near Scanner Web Application
===================================================
A responsive stock screener website for Indian traders (NSE / Nifty 500).

Features:
  - Universe: Nifty 500, Nifty 100, Nifty 50
  - Daily & Weekly OHLCV from Yahoo Finance (.NS tickers) with caching (refreshed daily after 4:00 PM IST)
  - 44 MA Touch & Near Scanner with adjustable parameters:
      * Max above MA44 (0.5% - 5%, default 2%)
      * Max below MA44 (0.5% - 5%, default 3%)
      * Status checkboxes: Touching, Above (0-A%), Near Below
      * Min Price, Min Weekly Volume (default 100,000)
      * MA44 Rising Only (today's MA44 > MA44 5 bars ago)
      * Green Candle Only (Close > Open)
  - Symmetrical Triangle & Ascending Triangle Breakout Engines (with 1:3 R:R and breakout / retest entries)
  - TradingView Chart integration with 44 MA overlay
  - CSV Export & Searchable, Sortable React + Tailwind UI
"""

import os
import io
import csv
import time
import gzip
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import datetime as dt
from typing import Dict, List, Optional, Tuple
import pandas as pd
import requests
import yfinance as yf
from flask import Flask, jsonify, request, render_template, send_file, Response, session, redirect, url_for

import strategies

# ═══════════════════════════════════════════════════════════════════════════
# Flask Application Setup & Security Configuration
# ═══════════════════════════════════════════════════════════════════════════
app = Flask(__name__, template_folder="templates")
app.config["JSON_SORT_KEYS"] = False
app.secret_key = os.environ.get("APP_SECRET_KEY", "trading_scanner_super_secure_key_2026_x7k9")
app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(days=30)

# Website Access Password (reads SITE_PASSWORD or APP_PASSWORD from Render environment, stripped of any whitespace)
SITE_PASSWORD = (
    os.environ.get("SITE_PASSWORD")
    or os.environ.get("APP_PASSWORD")
    or "Akshay1999"
).strip()

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
NIFTY500_FILE = os.path.join(DATA_DIR, "nifty500.txt")

# Major NSE Company Names Dictionary
COMPANY_NAMES = {
    "RELIANCE": "Reliance Industries Ltd.",
    "TCS": "Tata Consultancy Services Ltd.",
    "HDFCBANK": "HDFC Bank Ltd.",
    "ICICIBANK": "ICICI Bank Ltd.",
    "BHARTIARTL": "Bharti Airtel Ltd.",
    "SBIN": "State Bank of India",
    "INFY": "Infosys Ltd.",
    "ITC": "ITC Ltd.",
    "HINDUNILVR": "Hindustan Unilever Ltd.",
    "LT": "Larsen & Toubro Ltd.",
    "BAJFINANCE": "Bajaj Finance Ltd.",
    "HCLTECH": "HCL Technologies Ltd.",
    "MARUTI": "Maruti Suzuki India Ltd.",
    "SUNPHARMA": "Sun Pharmaceutical Ind. Ltd.",
    "ADANIENT": "Adani Enterprises Ltd.",
    "TATAMOTORS": "Tata Motors Ltd.",
    "KOTAKBANK": "Kotak Mahindra Bank Ltd.",
    "TITAN": "Titan Company Ltd.",
    "ONGC": "Oil & Natural Gas Corp Ltd.",
    "NTPC": "NTPC Ltd.",
    "AXISBANK": "Axis Bank Ltd.",
    "ADANIGREEN": "Adani Green Energy Ltd.",
    "POWERGRID": "Power Grid Corporation of India",
    "COALINDIA": "Coal India Ltd.",
    "TATASTEEL": "Tata Steel Ltd.",
    "BAJAJFINSV": "Bajaj Finserv Ltd.",
    "M&M": "Mahindra & Mahindra Ltd.",
    "ADANIPORTS": "Adani Ports & SEZ Ltd.",
    "ASIANPAINT": "Asian Paints Ltd.",
    "WIPRO": "Wipro Ltd.",
    "ULTRACEMCO": "UltraTech Cement Ltd.",
    "IOC": "Indian Oil Corporation Ltd.",
    "NESTLEIND": "Nestle India Ltd.",
    "GRASIM": "Grasim Industries Ltd.",
    "JSWSTEEL": "JSW Steel Ltd.",
    "BEL": "Bharat Electronics Ltd.",
    "VEDL": "Vedanta Ltd.",
    "ZOMATO": "Zomato Ltd.",
    "VBL": "Varun Beverages Ltd.",
    "TRENT": "Trent Ltd.",
    "HAL": "Hindustan Aeronautics Ltd.",
    "DLF": "DLF Ltd.",
    "SIEMENS": "Siemens Ltd.",
    "PFC": "Power Finance Corporation Ltd.",
    "RECLTD": "REC Ltd.",
    "INDUSINDBK": "IndusInd Bank Ltd.",
    "TATACONSUM": "Tata Consumer Products Ltd.",
    "DRREDDY": "Dr. Reddy's Laboratories Ltd.",
    "DIVISLAB": "Divi's Laboratories Ltd.",
    "CIPLA": "Cipla Ltd.",
    "SBILIFE": "SBI Life Insurance Co Ltd.",
    "EICHERMOT": "Eicher Motors Ltd.",
    "BRITANNIA": "Britannia Industries Ltd.",
    "APOLLOHOSP": "Apollo Hospitals Enterprise Ltd.",
    "HINDALCO": "Hindalco Industries Ltd.",
    "PIDILITIND": "Pidilite Industries Ltd.",
    "HDFCLIFE": "HDFC Life Insurance Co Ltd.",
    "BAJAJ-AUTO": "Bajaj Auto Ltd.",
    "LTIM": "LTIMindtree Ltd.",
    "TECHM": "Tech Mahindra Ltd.",
    "PERSISTENT": "Persistent Systems Ltd.",
    "COFORGE": "Coforge Ltd.",
    "POLYCAB": "Polycab India Ltd.",
    "DIXON": "Dixon Technologies Ltd.",
    "CHOLAFIN": "Cholamandalam Inv & Fin Co",
    "TORNTPHARM": "Torrent Pharmaceuticals Ltd.",
    "MAXHEALTH": "Max Healthcare Institute Ltd.",
    "INDIANB": "Indian Bank",
    "INDHOTEL": "The Indian Hotels Co Ltd.",
    "SHREECEM": "Shree Cement Ltd.",
    "BALKRISIND": "Balkrishna Industries Ltd.",
    "GLAND": "Gland Pharma Ltd.",
    "HONASA": "Honasa Consumer Ltd.",
    "SANSERA": "Sansera Engineering Ltd.",
    "ASTRAZEN": "AstraZeneca Pharma India",
    "GICRE": "General Insurance Corp of India",
}

# ═══════════════════════════════════════════════════════════════════════════
# Universe Loading & Symbol Cache
# ═══════════════════════════════════════════════════════════════════════════
def load_symbol_file(filename: str) -> List[str]:
    """Loads stock symbols from a text file in DATA_DIR."""
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        return []
    symbols = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                symbols.append(line.upper())
    return symbols


UNIVERSE_NIFTY500 = load_symbol_file("nifty500.txt") or list(COMPANY_NAMES.keys())
UNIVERSE_NIFTY100 = UNIVERSE_NIFTY500[:100] if len(UNIVERSE_NIFTY500) >= 100 else UNIVERSE_NIFTY500
UNIVERSE_NIFTY50  = UNIVERSE_NIFTY500[:50]  if len(UNIVERSE_NIFTY500) >= 50  else UNIVERSE_NIFTY500
UNIVERSE_MIDCAP   = load_symbol_file("niftymidcap.txt")
UNIVERSE_SMALLCAP = load_symbol_file("niftysmallcap.txt")


def get_universe(index_param: str) -> List[str]:
    """Returns the universe list for a given index parameter."""
    if index_param == "nifty50":
        return UNIVERSE_NIFTY50
    elif index_param == "nifty100":
        return UNIVERSE_NIFTY100
    elif index_param == "midcap":
        return UNIVERSE_MIDCAP
    elif index_param == "smallcap":
        return UNIVERSE_SMALLCAP
    return UNIVERSE_NIFTY500

def get_company_name(symbol: str) -> str:
    """Returns human-readable company name for symbol."""
    sym = symbol.upper()
    if sym in COMPANY_NAMES:
        return COMPANY_NAMES[sym]
    return f"{sym} Ltd."


# ═══════════════════════════════════════════════════════════════════════════
# Candle Cache & Data Fetching (Daily & Weekly via Yahoo Finance .NS)
# ═══════════════════════════════════════════════════════════════════════════
PERSISTENT_DIR = "/data" if os.path.isdir("/data") else DATA_DIR
CACHE_GZ_FILE = os.path.join(PERSISTENT_DIR, "candle_cache.json.gz")
FALLBACK_GZ_FILE = os.path.join(DATA_DIR, "candle_cache.json.gz")
CACHE_JSON_FILE = os.path.join(PERSISTENT_DIR, "eod_cache.json")

# Symbol renames / corporate action mapping for Yahoo Finance
SYMBOL_MAP = {
    "TATAMOTORS": "TMPV",
    "ZOMATO": "ETERNAL",
    "MCDOWELL-N": "UNITDSPR",
    "LTI": "LTIM",
    "CADILAHC": "ZYDUSLIFE",
    "MINDTREE": "LTIM",
    "TATAMTRDVR": "TMCV",
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

_daily_cache: Dict[str, list] = {}
_weekly_cache: Dict[str, list] = {}
_last_cache_update_time: Optional[dt.datetime] = None
_cache_lock = threading.Lock()
_batch_lock = threading.Lock()
_failed_symbols: set = set()

# High-performance persistent HTTP session with connection pooling
_http_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=35, pool_maxsize=35, max_retries=2)
_http_session.mount("https://", _adapter)
_http_session.mount("http://", _adapter)
_http_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
})


def resample_daily_to_weekly_fast(daily_candles: list) -> list:
    """
    High-performance pure Python weekly candle aggregation (0.2s for 500 stocks).
    Aggregates Monday to Friday (or latest day in week):
      Open = first Open
      High = max High
      Low = min Low
      Close = last Close
      Volume = sum Volume
    """
    if not daily_candles or len(daily_candles) < 5:
        return []
    weeks = {}
    for c in daily_candles:
        d_str = str(c[0])[:10]
        try:
            d = dt.date.fromisoformat(d_str)
        except Exception:
            continue
        key = d.isocalendar()[:2]  # (year, week_num)
        if key not in weeks:
            weeks[key] = {
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": int(c[5]),
                "last_date": d_str
            }
        else:
            w = weeks[key]
            h = float(c[2])
            l = float(c[3])
            if h > w["high"]:
                w["high"] = h
            if l < w["low"]:
                w["low"] = l
            w["close"] = float(c[4])
            w["volume"] += int(c[5])
            w["last_date"] = d_str

    weekly = []
    for _, w in weeks.items():
        weekly.append([
            w["last_date"],
            round(w["open"], 2),
            round(w["high"], 2),
            round(w["low"], 2),
            round(w["close"], 2),
            int(w["volume"])
        ])
    return weekly


def load_disk_cache():
    """Loads cached candles from persistent disk file if present (Instant Startup)."""
    target_file = None
    if os.path.exists(CACHE_GZ_FILE):
        target_file = CACHE_GZ_FILE
    elif os.path.exists(FALLBACK_GZ_FILE):
        target_file = FALLBACK_GZ_FILE

    if target_file:
        try:
            with gzip.open(target_file, "rt", encoding="utf-8") as f:
                data = json.load(f)
            daily_data = data.get("daily", {})
            weekly_data = data.get("weekly", {})
            with _cache_lock:
                for sym, candles in daily_data.items():
                    if candles:
                        _daily_cache[sym] = [
                            [str(c[0])[:10], float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5])]
                            for c in candles
                        ]
                for sym, candles in weekly_data.items():
                    if candles:
                        _weekly_cache[sym] = [
                            [str(c[0])[:10], float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5])]
                            for c in candles
                        ]
            print(f"Loaded {len(_daily_cache)} symbols instantly from {target_file}.")
            return
        except Exception as e:
            print(f"Warning: Could not load gzip cache ({e}), checking JSON cache...")

    if os.path.exists(CACHE_JSON_FILE):
        try:
            with open(CACHE_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _cache_lock:
                for sym, val in data.items():
                    _daily_cache[sym] = val.get("daily", [])
                    _weekly_cache[sym] = val.get("weekly", [])
            print(f"Loaded {len(_daily_cache)} symbols from JSON cache.")
        except Exception as e:
            print(f"Warning: Could not load disk cache: {e}")


def _do_save_disk_cache():
    """Background task to persist candle cache to disk."""
    try:
        data = {
            "date": dt.date.today().isoformat(),
            "daily": {},
            "weekly": {}
        }
        with _cache_lock:
            data["daily"] = dict(_daily_cache)
            data["weekly"] = dict(_weekly_cache)

        target_path = CACHE_GZ_FILE if os.path.isdir(PERSISTENT_DIR) else FALLBACK_GZ_FILE
        tmp_path = target_path + ".tmp"
        try:
            with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
                json.dump(data, f)

            if os.path.exists(target_path):
                os.replace(tmp_path, target_path)
            else:
                os.rename(tmp_path, target_path)
            print(f"Candle cache saved to disk ({len(data['daily'])} symbols).")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    except Exception as e:
        print(f"Warning: Could not save disk cache: {e}")


def save_disk_cache():
    """Persists memory candle cache to disk asynchronously."""
    threading.Thread(target=_do_save_disk_cache, daemon=True).start()


# Load on module import
load_disk_cache()


def get_current_ist_time() -> dt.datetime:
    """Returns current Indian Standard Time (UTC+5:30)."""
    utc = dt.datetime.now(dt.timezone.utc)
    ist = utc + dt.timedelta(hours=5, minutes=30)
    return ist


def is_after_4pm_ist() -> bool:
    """Returns True if current IST time is after 4:00 PM IST."""
    ist = get_current_ist_time()
    return ist.hour >= 16 or (ist.hour == 16 and ist.minute >= 0)


def fetch_stock_candles_yf(symbol: str) -> tuple:
    """
    Fetches daily and weekly candles for an NSE stock via Yahoo Finance direct v8 API.
    Bypasses yfinance's buggy quoteSummary 404 endpoint and uses connection pooling.
    Returns (daily_candles, weekly_candles).
    """
    sym_upper = symbol.upper()
    mapped_sym = SYMBOL_MAP.get(sym_upper, sym_upper)
    ticker_sym = f"{mapped_sym}.NS"
    host = "query2.finance.yahoo.com" if (hash(sym_upper) % 2 == 0) else "query1.finance.yahoo.com"
    url = f"https://{host}/v8/finance/chart/{ticker_sym}?range=1y&interval=1d"

    try:
        resp = _http_session.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            res_list = data.get("chart", {}).get("result")
            if res_list:
                item = res_list[0]
                timestamps = item.get("timestamp", [])
                quotes = item.get("indicators", {}).get("quote", [{}])[0]
                opens = quotes.get("open", [])
                highs = quotes.get("high", [])
                lows = quotes.get("low", [])
                closes = quotes.get("close", [])
                volumes = quotes.get("volume", [])

                daily = []
                for ts, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes):
                    if o is None or h is None or l is None or c is None:
                        continue
                    d_str = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")
                    daily.append([
                        d_str,
                        round(float(o), 2),
                        round(float(h), 2),
                        round(float(l), 2),
                        round(float(c), 2),
                        int(v or 0)
                    ])
                if len(daily) >= 45:
                    weekly = resample_daily_to_weekly_fast(daily)
                    return daily, weekly
        elif resp.status_code == 404:
            return None, None
    except Exception:
        pass

    return None, None


def get_cached_candles(symbol: str, force_refresh: bool = False) -> tuple:
    """Retrieves candles from memory cache or fetches from Yahoo Finance."""
    sym = symbol.upper()
    with _cache_lock:
        if not force_refresh and sym in _daily_cache and sym in _weekly_cache:
            return _daily_cache[sym], _weekly_cache[sym]

    if sym in _failed_symbols and not force_refresh:
        return None, None

    d_candles, w_candles = fetch_stock_candles_yf(sym)
    if d_candles and w_candles:
        with _cache_lock:
            _daily_cache[sym] = d_candles
            _weekly_cache[sym] = w_candles
    else:
        _failed_symbols.add(sym)
    return d_candles, w_candles


def ensure_universe_cached(universe: List[str], force_refresh: bool = False, max_workers: int = 14) -> None:
    """
    Ensures all symbols in universe are cached in memory.
    If any are missing (or force_refresh=True), fetches them in parallel using ThreadPoolExecutor.
    Thread-safe to prevent redundant fetch storms.
    """
    with _batch_lock:
        if force_refresh:
            _failed_symbols.clear()
            symbols_to_fetch = list(universe)
        else:
            with _cache_lock:
                symbols_to_fetch = [
                    s for s in universe
                    if (s not in _daily_cache or s not in _weekly_cache) and (s not in _failed_symbols)
                ]

        if not symbols_to_fetch:
            return

        print(f"Parallel fetching candles for {len(symbols_to_fetch)} symbols...")
        t0 = time.time()
        new_count = 0

        def _fetch_worker(s: str):
            d, w = fetch_stock_candles_yf(s)
            return s, d, w

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_fetch_worker, s): s for s in symbols_to_fetch}
            for fut in as_completed(future_map):
                try:
                    s, d_candles, w_candles = fut.result()
                    if d_candles and w_candles:
                        with _cache_lock:
                            _daily_cache[s] = d_candles
                            _weekly_cache[s] = w_candles
                        new_count += 1
                    else:
                        _failed_symbols.add(s)
                except Exception:
                    pass

        t1 = time.time()
        print(f"Parallel fetch finished: {new_count}/{len(symbols_to_fetch)} in {t1 - t0:.2f}s")
        if new_count > 0:
            save_disk_cache()


def background_cache_warmup():
    """Warms up any missing universe candles in the background."""
    print("Initiating background candle check for universe...")
    ensure_universe_cached(UNIVERSE_NIFTY500, force_refresh=False)
    print(f"Candle cache ready ({len(_daily_cache)} symbols in memory).")


# Start warmup thread once on launch
threading.Thread(target=background_cache_warmup, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════
# Authentication & Route Protection
# ═══════════════════════════════════════════════════════════════════════════

@app.before_request
def require_login():
    """Protects all web pages and API routes with password authentication."""
    exempt_endpoints = {"login", "static"}
    if request.endpoint in exempt_endpoints:
        return None

    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required. Please log in at /login"}), 401
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page and password verification handler."""
    if session.get("authenticated"):
        return redirect(url_for("index_page"))

    error = None
    if request.method == "POST":
        entered_password = request.form.get("password", "").strip()
        remember = request.form.get("remember") == "on"

        if entered_password == SITE_PASSWORD or entered_password == SITE_PASSWORD.strip():
            session.permanent = remember
            session["authenticated"] = True
            return redirect(url_for("index_page"))
        else:
            error = "Incorrect security password. Please try again."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    """Logs user out and redirects to login screen."""
    session.clear()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard & Scanner API Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index_page():
    """Renders the main responsive dashboard."""
    return render_template("dashboard.html")


@app.route("/api/universe")
def api_universe():
    """Returns universe options and stock counts."""
    return jsonify({
        "nifty50_count": len(UNIVERSE_NIFTY50),
        "nifty100_count": len(UNIVERSE_NIFTY100),
        "nifty500_count": len(UNIVERSE_NIFTY500),
        "midcap_count": len(UNIVERSE_MIDCAP),
        "smallcap_count": len(UNIVERSE_SMALLCAP),
    })


# In-memory scanner results cache for instant response (< 5ms) on Render free tier
_SCAN_44MA_CACHE: Dict[str, dict] = {}
_SCAN_ABOVE44_CACHE: Dict[str, dict] = {}
_SCAN_TRIANGLES_CACHE: Dict[str, dict] = {}
_SCAN_44BREAKOUTS_CACHE: Dict[str, dict] = {}
_LAST_SCAN_TIME: Dict[str, float] = {}


def clear_scan_caches():
    """Clears all scanner result caches on forced refresh."""
    _SCAN_44MA_CACHE.clear()
    _SCAN_ABOVE44_CACHE.clear()
    _SCAN_TRIANGLES_CACHE.clear()
    _SCAN_44BREAKOUTS_CACHE.clear()
    _LAST_SCAN_TIME.clear()


@app.route("/api/scanner/44ma")
def api_scanner_44ma():
    """
    Core 44 MA Touch & Near Scanner endpoint.
    Query parameters:
      - index: 'nifty500' (default), 'nifty100', 'nifty50'
      - max_above: float (default 2.0)
      - max_below: float (default 3.0)
      - statuses: comma-separated list of statuses (e.g. 'Touching,Above,Near Below')
      - min_price: float (default 0.0)
      - min_weekly_vol: int (default 100000)
      - rising_only: '1' or '0' (default '0')
      - green_only: '1' or '0' (default '0')
      - refresh: '1' or '0'
    """
    index_param = request.args.get("index", "nifty500").lower()
    if index_param == "nifty50":
        universe = UNIVERSE_NIFTY50
    elif index_param == "nifty100":
        universe = UNIVERSE_NIFTY100
    elif index_param == "midcap":
        universe = UNIVERSE_MIDCAP
    elif index_param == "smallcap":
        universe = UNIVERSE_SMALLCAP
    else:
        universe = UNIVERSE_NIFTY500

    try:
        max_above = float(request.args.get("max_above", 2.0))
    except ValueError:
        max_above = 2.0

    try:
        max_below = float(request.args.get("max_below", 3.0))
    except ValueError:
        max_below = 3.0

    try:
        min_price = float(request.args.get("min_price", 0.0))
    except ValueError:
        min_price = 0.0

    try:
        min_weekly_vol = int(request.args.get("min_weekly_vol", 100000))
    except ValueError:
        min_weekly_vol = 100000

    rising_only = request.args.get("rising_only") == "1"
    green_only = request.args.get("green_only") == "1"
    force_refresh = request.args.get("refresh") == "1"

    status_filter = request.args.get("statuses", "")
    allowed_statuses = [s.strip().lower() for s in status_filter.split(",") if s.strip()] if status_filter else []

    if force_refresh:
        clear_scan_caches()

    cache_key = f"{index_param}_{max_above}_{max_below}_{min_price}_{min_weekly_vol}_{rising_only}_{green_only}_{status_filter}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_44MA_CACHE and (now_time - _LAST_SCAN_TIME.get(f"44ma_{cache_key}", 0) < 180):
        return jsonify(_SCAN_44MA_CACHE[cache_key])

    ensure_universe_cached(universe, force_refresh=force_refresh)

    both_results = []
    daily_results = []
    weekly_results = []

    for sym in universe:
        d_candles, w_candles = get_cached_candles(sym)
        if not d_candles:
            continue

        comp_name = get_company_name(sym)
        stock_eval = strategies.evaluate_44ma_stock(
            symbol=sym,
            company_name=comp_name,
            daily_candles=d_candles,
            weekly_candles=w_candles,
            max_above_a=max_above,
            max_below_b=max_below,
            min_price=min_price,
            min_weekly_vol=min_weekly_vol,
            rising_only=rising_only,
            green_only=green_only,
        )

        if not stock_eval:
            continue

        # Status filter check
        if allowed_statuses:
            stat = stock_eval["status"].lower()
            if not any(a in stat for a in allowed_statuses):
                continue

        # Segment into tabs
        tf = stock_eval["timeframe"]
        if tf == "Both":
            both_results.append(stock_eval)
        elif tf == "Daily":
            daily_results.append(stock_eval)
        elif tf == "Weekly":
            weekly_results.append(stock_eval)

    # Sort each list by smallest abs(Distance %) first (closest to 44 MA first!)
    both_results.sort(key=lambda s: s["abs_distance"])
    daily_results.sort(key=lambda s: s["abs_distance"])
    weekly_results.sort(key=lambda s: s["abs_distance"])

    now_ist = get_current_ist_time()
    last_updated_str = now_ist.strftime("%d-%b-%Y %I:%M %p IST")

    payload = {
        "last_updated": last_updated_str,
        "universe": index_param.upper(),
        "total_scanned": len(universe),
        "counts": {
            "both": len(both_results),
            "daily": len(daily_results),
            "weekly": len(weekly_results),
            "total_qualifying": len(both_results) + len(daily_results) + len(weekly_results),
        },
        "results": {
            "both": both_results,
            "daily": daily_results,
            "weekly": weekly_results,
        }
    }

    _SCAN_44MA_CACHE[cache_key] = payload
    _LAST_SCAN_TIME[f"44ma_{cache_key}"] = now_time
    return jsonify(payload)


@app.route("/api/scanner/44ma_breakouts")
def api_scanner_44ma_breakouts():
    """
    Evaluates 44 MA Breakouts split into:
      - confirmed_breakouts: Close >= MA44 and +0.5% <= Distance % <= +6.0%
      - pre_breakouts: Close < MA44 and -6.0% <= Distance % <= -0.5% (0.5% to 6% below 44 MA)
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)
    tf = request.args.get("timeframe", "daily").lower()
    try:
        min_pct = float(request.args.get("min_pct", 0.5))
        max_pct = float(request.args.get("max_pct", 6.0))
    except ValueError:
        min_pct, max_pct = 0.5, 6.0

    force_refresh = request.args.get("refresh") == "1"
    if force_refresh:
        clear_scan_caches()

    cache_key = f"{index_param}_{tf}_{min_pct}_{max_pct}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_44BREAKOUTS_CACHE and (now_time - _LAST_SCAN_TIME.get(f"breakouts_{cache_key}", 0) < 180):
        return jsonify(_SCAN_44BREAKOUTS_CACHE[cache_key])

    ensure_universe_cached(universe, force_refresh=force_refresh)

    confirmed = []
    pre_breakout = []

    for sym in universe:
        d_candles, w_candles = get_cached_candles(sym)
        candles = w_candles if tf == "weekly" else d_candles
        if not candles or len(candles) < 45:
            continue

        comp_name = get_company_name(sym)
        eval_res = strategies.evaluate_44ma_breakout(
            sym, comp_name, candles, timeframe=tf, min_dist_pct=min_pct, max_dist_pct=max_pct
        )
        if not eval_res:
            continue

        if eval_res["type"] == "confirm_breakout":
            confirmed.append(eval_res)
        elif eval_res["type"] == "pre_breakout":
            pre_breakout.append(eval_res)

    # Sort lowest percentage first (1% at top, 2% below, progressing up to 7%)
    confirmed.sort(key=lambda s: s["distance_pct"])
    pre_breakout.sort(key=lambda s: abs(s["distance_pct"]))

    now_ist = get_current_ist_time()
    payload = {
        "last_updated": now_ist.strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": tf.capitalize(),
        "min_pct": min_pct,
        "max_pct": max_pct,
        "total_scanned": len(universe),
        "counts": {
            "confirmed": len(confirmed),
            "pre_breakout": len(pre_breakout)
        },
        "confirmed_breakouts": confirmed,
        "pre_breakouts": pre_breakout
    }

    _SCAN_44BREAKOUTS_CACHE[cache_key] = payload
    _LAST_SCAN_TIME[f"breakouts_{cache_key}"] = now_time
    return jsonify(payload)


@app.route("/api/scanner/above44")
def api_scanner_above44():
    """
    Above 44 MA Strategy Scanner (Bullish Momentum & Breakout above 44 MA).
    Returns all stocks actively trading above the 44-period Moving Average:
      - 44 MA Fresh Breakout (crossed above within last 1-3 bars)
      - 44 MA Near Support (trading 0% - 3% above 44 MA)
      - Above 44 MA Trending (strong bullish momentum above 44 MA)
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)
    tf = request.args.get("timeframe", "daily").lower()
    force_refresh = request.args.get("refresh") == "1"
    if force_refresh:
        clear_scan_caches()

    cache_key = f"{index_param}_{tf}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_ABOVE44_CACHE and (now_time - _LAST_SCAN_TIME.get(f"above44_{cache_key}", 0) < 180):
        return jsonify(_SCAN_ABOVE44_CACHE[cache_key])

    ensure_universe_cached(universe, force_refresh=force_refresh)

    results = []
    for sym in universe:
        d_candles, w_candles = get_cached_candles(sym)
        candles = w_candles if tf == "weekly" else d_candles
        if not candles or len(candles) < 45:
            continue

        comp_name = get_company_name(sym)
        res = strategies.analyze_above_44ma(sym, comp_name, candles, timeframe=tf)
        if res:
            results.append(res)

    # Sort: Fresh Breakouts first, then closest to 44 MA support
    results.sort(key=lambda s: (0 if "Breakout" in s["status"] else (1 if "Near" in s["status"] else 2), s["distance_pct"]))

    now_ist = get_current_ist_time()
    payload = {
        "last_updated": now_ist.strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": tf.capitalize(),
        "total_scanned": len(universe),
        "count": len(results),
        "fresh_breakouts_count": sum(1 for s in results if "Breakout" in s["status"]),
        "results": results,
    }

    _SCAN_ABOVE44_CACHE[cache_key] = payload
    _LAST_SCAN_TIME[f"above44_{cache_key}"] = now_time

    return jsonify(payload)


@app.route("/api/scanner/triangles")
def api_scanner_triangles():
    """
    Ascending & Symmetrical Triangle Breakouts endpoint.
    Returns categorized lists:
      - ascending: all ascending triangles
      - symmetrical: all symmetrical triangles
      - confirmed_breakouts: all confirmed breakout stocks across both patterns
      - pre_breakouts: all pre-breakout watchlist stocks coiling near apex
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)
    tf = request.args.get("timeframe", "daily").lower()
    force_refresh = request.args.get("refresh") == "1"
    if force_refresh:
        clear_scan_caches()

    cache_key = f"{index_param}_{tf}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_TRIANGLES_CACHE and (now_time - _LAST_SCAN_TIME.get(f"triangles_{cache_key}", 0) < 180):
        return jsonify(_SCAN_TRIANGLES_CACHE[cache_key])

    ensure_universe_cached(universe, force_refresh=force_refresh)

    ascending_triangles = []
    symmetrical_triangles = []
    confirmed_breakouts = []
    pre_breakouts = []

    for sym in universe:
        d_candles, w_candles = get_cached_candles(sym)
        candles = w_candles if tf == "weekly" else d_candles
        if not candles or len(candles) < 30:
            continue

        comp_name = get_company_name(sym)

        # 1. Ascending Triangle Check
        asc = strategies.detect_ascending_triangle(sym, comp_name, candles, timeframe=tf)
        if asc:
            ascending_triangles.append(asc)
            if asc["status"] in ["Confirmed Breakout", "Confirmed Retest"]:
                confirmed_breakouts.append(asc)
            elif asc["status"] == "Pre-Breakout Watch":
                pre_breakouts.append(asc)

        # 2. Symmetrical Triangle Check
        symm = strategies.detect_symmetrical_triangle(sym, comp_name, candles, timeframe=tf)
        if symm:
            symmetrical_triangles.append(symm)
            if symm["status"] == "Confirmed Breakout":
                confirmed_breakouts.append(symm)
            elif symm["status"] == "Pre-Breakout Watch":
                pre_breakouts.append(symm)

    # Sort by smallest distance to breakout trigger first
    ascending_triangles.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))
    symmetrical_triangles.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))
    confirmed_breakouts.sort(key=lambda x: x["abs_distance"])
    pre_breakouts.sort(key=lambda x: x["abs_distance"])

    asc_confirmed = [x for x in ascending_triangles if "Confirmed" in x.get("status", "")]
    asc_pre = [x for x in ascending_triangles if "Watch" in x.get("status", "") or "Pre" in x.get("status", "")]
    symm_confirmed = [x for x in symmetrical_triangles if "Confirmed" in x.get("status", "")]
    symm_pre = [x for x in symmetrical_triangles if "Watch" in x.get("status", "") or "Pre" in x.get("status", "")]

    now_ist = get_current_ist_time()
    payload = {
        "last_updated": now_ist.strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": tf.capitalize(),
        "ascending": ascending_triangles,
        "symmetrical": symmetrical_triangles,
        "ascending_confirmed": asc_confirmed,
        "ascending_pre": asc_pre,
        "symmetrical_confirmed": symm_confirmed,
        "symmetrical_pre": symm_pre,
        "confirmed_breakouts": confirmed_breakouts,
        "pre_breakouts": pre_breakouts,
        "counts": {
            "ascending": len(ascending_triangles),
            "symmetrical": len(symmetrical_triangles),
            "ascending_confirmed": len(asc_confirmed),
            "ascending_pre": len(asc_pre),
            "symmetrical_confirmed": len(symm_confirmed),
            "symmetrical_pre": len(symm_pre),
            "confirmed_breakouts": len(confirmed_breakouts),
            "pre_breakouts": len(pre_breakouts),
            "total_patterns": len(ascending_triangles) + len(symmetrical_triangles),
        }
    }

    _SCAN_TRIANGLES_CACHE[cache_key] = payload
    _LAST_SCAN_TIME[f"triangles_{cache_key}"] = now_time
    return jsonify(payload)


@app.route("/api/chart/<symbol>")
def api_chart(symbol):
    """
    Provides combined OHLCV candles, 44 MA series, pattern trendlines,
    and breakout candle markers for fast interactive charting.
    """
    sym = symbol.upper()
    tf = request.args.get("tf", "daily").lower()
    d_candles, w_candles = get_cached_candles(sym)

    candles = w_candles if tf == "weekly" else d_candles
    if not candles:
        return jsonify({"error": f"No candle data for {sym}"}), 404

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    opens = [c[1] for c in candles]
    ma44_series = strategies.calculate_ma44(closes)

    candle_data = []
    ma_line_data = []

    display_bars = candles[-120:] if len(candles) >= 120 else candles
    offset = len(candles) - len(display_bars)

    for i, c in enumerate(display_bars):
        c_idx = offset + i
        candle_data.append({
            "time": c[0],
            "open": c[1],
            "high": c[2],
            "low": c[3],
            "close": c[4],
            "volume": c[5],
        })
        ma_val = ma44_series[c_idx]
        if ma_val is not None:
            ma_line_data.append({
                "time": c[0],
                "value": ma_val
            })

    # 44 MA Status on latest bar
    current_ma = ma44_series[-1]
    cmp_price = closes[-1]
    dist_pct = round(((cmp_price - current_ma) / current_ma) * 100, 2) if current_ma else 0.0
    touch = strategies.is_touch(lows[-1], highs[-1], current_ma)
    near_bel = strategies.is_near_below(cmp_price, current_ma, dist_pct, 3.0)
    above_z = strategies.is_above_zone(cmp_price, current_ma, dist_pct, 2.0)
    status_44ma = strategies.get_status(touch, above_z, near_bel, 2.0)

    # Patterns & 44 MA Breakouts
    comp_name = get_company_name(sym)
    eval_44_breakout = strategies.evaluate_44ma_breakout(sym, comp_name, candles, timeframe=tf)
    above44 = strategies.analyze_above_44ma(sym, comp_name, candles, timeframe=tf)
    asc = strategies.detect_ascending_triangle(sym, comp_name, candles, timeframe=tf)
    symm = strategies.detect_symmetrical_triangle(sym, comp_name, candles, timeframe=tf)

    return jsonify({
        "symbol": sym,
        "company": comp_name,
        "timeframe": tf,
        "candles": candle_data,
        "ma44_line": ma_line_data,
        "current_ma44": current_ma,
        "cmp": cmp_price,
        "status_44ma": status_44ma,
        "distance_pct": dist_pct,
        "eval_44_breakout": eval_44_breakout,
        "above_44ma": above44,
        "ascending_pattern": asc,
        "symmetrical_pattern": symm,
    })


@app.route("/api/export/csv")
def api_export_csv():
    """Generates and downloads CSV of current 44 MA, Above 44, or Breakout qualifying stocks."""
    tab = request.args.get("tab", "both").lower()
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)
    ensure_universe_cached(universe)

    # 1. 44 MA Daily & Weekly Breakouts CSV Export
    if tab in ["daily_confirmed", "daily_pre", "weekly_confirmed", "weekly_pre", "44_confirm_breakout", "44_pre_breakout"]:
        rows = []
        is_weekly = "weekly" in tab
        target_type = "confirm_breakout" if ("confirm" in tab) else "pre_breakout"
        tf_str = "weekly" if is_weekly else "daily"

        for sym in universe:
            d_candles, w_candles = get_cached_candles(sym)
            c = w_candles if is_weekly else d_candles
            if not c or len(c) < 45:
                continue
            comp = get_company_name(sym)
            res = strategies.evaluate_44ma_breakout(sym, comp, c, tf_str)
            if res and res["type"] == target_type:
                rows.append(res)

        rows.sort(key=lambda s: s["abs_distance"])
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Symbol", "Company", "Type", "Timeframe", "CMP", "44 MA", "Distance %", "Entry Price", "Stop Loss", "Target (1:3)", "Status", "Day Change %"])
        for r in rows:
            writer.writerow([r["symbol"], r["company"], r["pattern"], r.get("timeframe", tf_str.capitalize()), r["cmp"], r["ma44"], f"{r['distance_pct']}%", r["buy_price"], r["stop_loss"], r["target"], r["status"], f"{r['day_change_pct']}%"])
        output.seek(0)
        filename = f"44MA_{tab}_{index_param}_{dt.date.today().strftime('%Y%m%d')}.csv"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={filename}"})

    # 2. Triangles (Ascending & Symmetrical: Pre vs Confirmed) Export
    if any(k in tab for k in ["ascending", "symmetrical", "triangle"]):
        tri_rows = []
        is_asc = "ascending" in tab
        is_symm = "symmetrical" in tab
        want_confirmed = "confirm" in tab
        want_pre = "pre" in tab

        for sym in universe:
            d_candles, _ = get_cached_candles(sym)
            if not d_candles or len(d_candles) < 30:
                continue
            comp = get_company_name(sym)

            if is_asc or (not is_symm):
                asc = strategies.detect_ascending_triangle(sym, comp, d_candles, "daily")
                if asc:
                    if want_confirmed and "Confirmed" in asc.get("status", ""):
                        tri_rows.append(asc)
                    elif want_pre and ("Watch" in asc.get("status", "") or "Pre" in asc.get("status", "")):
                        tri_rows.append(asc)
                    elif not want_confirmed and not want_pre:
                        tri_rows.append(asc)

            if is_symm or (not is_asc):
                symm = strategies.detect_symmetrical_triangle(sym, comp, d_candles, "daily")
                if symm:
                    if want_confirmed and "Confirmed" in symm.get("status", ""):
                        tri_rows.append(symm)
                    elif want_pre and ("Watch" in symm.get("status", "") or "Pre" in symm.get("status", "")):
                        tri_rows.append(symm)
                    elif not want_confirmed and not want_pre:
                        tri_rows.append(symm)

        tri_rows.sort(key=lambda s: s["abs_distance"])
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Symbol", "Company", "Pattern", "CMP", "Resistance", "Support", "Entry", "Target (1:3)", "Stop Loss", "Status", "Touches"])
        for r in tri_rows:
            writer.writerow([
                r["symbol"], r["company"], r["pattern"], r["cmp"],
                r.get("resistance_level", 0), r.get("support_level", 0),
                r["buy_price"], r["target"], r["stop_loss"], r["status"], r.get("touches", 2)
            ])
        output.seek(0)
        filename = f"Triangles_{tab}_{index_param}_{dt.date.today().strftime('%Y%m%d')}.csv"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={filename}"})

    # 2. 44 MA CSV Export
    try:
        max_above = float(request.args.get("max_above", 2.0))
        max_below = float(request.args.get("max_below", 3.0))
    except ValueError:
        max_above, max_below = 2.0, 3.0

    rows = []
    for sym in universe:
        d_candles, w_candles = get_cached_candles(sym)
        if not d_candles:
            continue
        eval_res = strategies.evaluate_44ma_stock(
            symbol=sym,
            company_name=get_company_name(sym),
            daily_candles=d_candles,
            weekly_candles=w_candles,
            max_above_a=max_above,
            max_below_b=max_below,
        )
        if not eval_res:
            continue

        if tab != "all" and eval_res["timeframe"].lower() != tab:
            continue

        rows.append(eval_res)

    rows.sort(key=lambda s: s["abs_distance"])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Symbol", "Company", "CMP", "MA44", "Distance %", "Status", "Day Change %", "Volume", "Timeframe"])
    for r in rows:
        writer.writerow([
            r["symbol"],
            r["company"],
            r["cmp"],
            r["ma44"],
            f"{r['distance_pct']}%",
            r["status"],
            f"{r['day_change_pct']}%",
            r["volume"],
            r["timeframe"]
        ])

    output.seek(0)
    filename = f"44MA_Scanner_{index_param}_{tab}_{dt.date.today().strftime('%Y%m%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


# ═══════════════════════════════════════════════════════════════════════════
# Application Entry Point
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n=======================================================")
    print(f" 🚀 44 MA Touch & Near Scanner Active at http://0.0.0.0:{port}")
    print(f"=======================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False)
