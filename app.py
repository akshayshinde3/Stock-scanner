"""
app.py — 44 MA Touch & Near Scanner Web Application
===================================================
A responsive stock screener website for Indian traders (NSE / Nifty 500, 100, 50).

Features:
  - Universe: Nifty 500, Nifty 100, Nifty 50, Midcap, Smallcap
  - 5-year Daily & Weekly OHLCV from Yahoo Finance (.NS tickers) with EOD caching
  - 44 MA Touch & Near Scanner with fixed distance band (-1.0% to +3.0% ONLY):
      * Status: "Touching", "Above (0–3%)", "Near Below (−1–0%)"
      * Rising 44 MA & Green Candle filters
      * Daily, Weekly, and Both Daily+Weekly view
  - Breakout Pattern Engines:
      * Ascending Triangle (Breakout & Retest, minimum 1:3 R:R)
      * Symmetrical Triangle (Coil Breakout, minimum 1:2.5 R:R)
      * Bull Pole & Flag (Daily & Weekly, minimum 1:2.0 R:R)
  - Interactive Lightweight Charts with touch pivots and trendlines
  - Why Rejected debug endpoint: /api/debug/<symbol>
  - CSV Export & Searchable UI
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
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import requests
import yfinance as yf
from flask import Flask, jsonify, request, render_template, send_file, Response, session, redirect, url_for

import strategies
from patterns.geometry import resample_to_weekly

# ═══════════════════════════════════════════════════════════════════════════
# Flask Application Setup & Security Configuration
# ═══════════════════════════════════════════════════════════════════════════
app = Flask(__name__, template_folder="templates")
app.config["JSON_SORT_KEYS"] = False
app.secret_key = os.environ.get("APP_SECRET_KEY", "trading_scanner_super_secure_key_2026_x7k9")
app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(days=30)

SITE_PASSWORD = (
    os.environ.get("SITE_PASSWORD")
    or os.environ.get("APP_PASSWORD")
    or "Akshay1999"
).strip()

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
NIFTY500_FILE = os.path.join(DATA_DIR, "nifty500.txt")

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
    sym = symbol.upper()
    return COMPANY_NAMES.get(sym, f"{sym} Ltd.")


# ═══════════════════════════════════════════════════════════════════════════
# Candle Cache & Data Fetching (3 to 5 years of daily data for weekly patterns)
# ═══════════════════════════════════════════════════════════════════════════
PERSISTENT_DIR = "/data" if os.path.isdir("/data") else DATA_DIR
CACHE_GZ_FILE = os.path.join(PERSISTENT_DIR, "candle_cache.json.gz")
FALLBACK_GZ_FILE = os.path.join(DATA_DIR, "candle_cache.json.gz")
CACHE_JSON_FILE = os.path.join(PERSISTENT_DIR, "eod_cache.json")

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

_http_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=35, pool_maxsize=35, max_retries=2)
_http_session.mount("https://", _adapter)
_http_session.mount("http://", _adapter)
_http_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
})


def load_disk_cache():
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
            print(f"Warning: Could not load gzip cache ({e})")

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
    threading.Thread(target=_do_save_disk_cache, daemon=True).start()


load_disk_cache()


def get_current_ist_time() -> dt.datetime:
    utc = dt.datetime.now(dt.timezone.utc)
    return utc + dt.timedelta(hours=5, minutes=30)


def is_after_4pm_ist() -> bool:
    ist = get_current_ist_time()
    return ist.hour >= 16


def fetch_stock_candles_yf(symbol: str) -> tuple:
    """
    Fetches daily and weekly candles for an NSE stock via Yahoo Finance direct v8 API.
    Uses range=5y so weekly aggregation has 200+ bars for full 44 MA warmup.
    """
    sym_upper = symbol.upper()
    mapped_sym = SYMBOL_MAP.get(sym_upper, sym_upper)
    ticker_sym = f"{mapped_sym}.NS"
    host = "query2.finance.yahoo.com" if (hash(sym_upper) % 2 == 0) else "query1.finance.yahoo.com"
    url = f"https://{host}/v8/finance/chart/{ticker_sym}?range=2y&interval=1d"

    try:
        resp = _http_session.get(url, timeout=7)
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
                    weekly = resample_to_weekly(daily)
                    return daily, weekly
        elif resp.status_code == 404:
            return None, None
    except Exception:
        pass

    return None, None


def get_cached_candles(symbol: str, force_refresh: bool = False) -> tuple:
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
        print(f"Parallel fetch: {new_count}/{len(symbols_to_fetch)} cached in {t1 - t0:.2f}s")
        if new_count > 0:
            save_disk_cache()


def background_cache_warmup():
    print("Background candle warmup starting...")
    ensure_universe_cached(UNIVERSE_NIFTY500, force_refresh=False)
    print(f"Candle cache ready ({len(_daily_cache)} symbols in memory).")


threading.Thread(target=background_cache_warmup, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════════════
@app.before_request
def require_login():
    exempt_endpoints = {"login", "static"}
    if request.endpoint in exempt_endpoints:
        return None

    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required. Please log in at /login"}), 401
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
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
    session.clear()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard & Scanner API Endpoints
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/")
def index_page():
    return render_template("dashboard.html")


@app.route("/api/universe")
def api_universe():
    return jsonify({
        "nifty50_count": len(UNIVERSE_NIFTY50),
        "nifty100_count": len(UNIVERSE_NIFTY100),
        "nifty500_count": len(UNIVERSE_NIFTY500),
        "midcap_count": len(UNIVERSE_MIDCAP),
        "smallcap_count": len(UNIVERSE_SMALLCAP),
    })


# In-memory scanner results cache
_SCAN_44MA_CACHE: Dict[str, dict] = {}
_SCAN_TRIANGLES_CACHE: Dict[str, dict] = {}
_SCAN_POLEFLAG_CACHE: Dict[str, dict] = {}
_LAST_SCAN_TIME: Dict[str, float] = {}


def clear_scan_caches():
    _SCAN_44MA_CACHE.clear()
    _SCAN_TRIANGLES_CACHE.clear()
    _SCAN_POLEFLAG_CACHE.clear()
    _LAST_SCAN_TIME.clear()


@app.route("/api/scanner/44ma")
def api_scanner_44ma():
    """
    44 MA Institutional Swing Scanner (Chartink "swing-trade-by-pmpatil"):
      Rule 1: 1 day ago SMA(Close, 44) < Daily SMA(Close, 44)
      Rule 2: 2 days ago SMA(Close, 44) < Daily SMA(Close, 44)
      Rule 3: Daily Low < Daily SMA(High, 44)
      Rule 4: Daily Close > Daily SMA(Close, 44)
      Rule 5: Daily Close > Daily Open (Green candle)
    Ultra-fast parallel evaluation across worker threads.
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)

    try:
        min_price = float(request.args.get("min_price", 0.0))
    except ValueError:
        min_price = 0.0

    try:
        min_weekly_vol = int(request.args.get("min_weekly_vol", 100000))
    except ValueError:
        min_weekly_vol = 100000

    rising_only = request.args.get("rising_only", "1") == "1"
    green_only = request.args.get("green_only", "0") == "1"
    strict_chartink = request.args.get("strict_chartink", "0") == "1"
    force_refresh = request.args.get("refresh") == "1"
    status_filter = request.args.get("statuses", "")
    allowed_statuses = [s.strip().lower() for s in status_filter.split(",") if s.strip()] if status_filter else []

    if force_refresh:
        clear_scan_caches()

    cache_key = f"{index_param}_{min_price}_{min_weekly_vol}_{rising_only}_{green_only}_{strict_chartink}_{status_filter}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_44MA_CACHE and (now_time - _LAST_SCAN_TIME.get(f"44ma_{cache_key}", 0) < 300):
        return jsonify(_SCAN_44MA_CACHE[cache_key])

    ensure_universe_cached(universe, force_refresh=force_refresh)

    both_results = []
    daily_results = []
    weekly_results = []

    def _eval_stock(sym):
        d_candles, w_candles = get_cached_candles(sym)
        if not d_candles:
            return None
        return strategies.evaluate_44ma_stock(
            symbol=sym,
            company_name=get_company_name(sym),
            daily_candles=d_candles,
            weekly_candles=w_candles,
            min_price=min_price,
            min_weekly_vol=min_weekly_vol,
            rising_only=rising_only,
            green_only=green_only,
            strict_chartink=strict_chartink,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        for stock_eval in executor.map(_eval_stock, universe):
            if not stock_eval:
                continue

            if allowed_statuses:
                stat = stock_eval["status"].lower()
                if not any(a in stat for a in allowed_statuses):
                    continue

            tf = stock_eval["timeframe"]
            if tf == "Both":
                both_results.append(stock_eval)
            elif tf == "Daily":
                daily_results.append(stock_eval)
            elif tf == "Weekly":
                weekly_results.append(stock_eval)

    both_results.sort(key=lambda s: s["abs_distance"])
    daily_results.sort(key=lambda s: s["abs_distance"])
    weekly_results.sort(key=lambda s: s["abs_distance"])

    now_ist = get_current_ist_time()
    payload = {
        "last_updated": now_ist.strftime("%d-%b-%Y %I:%M %p IST"),
        "universe": index_param.upper(),
        "strategy": "44 MA Rising Stocks (-1.0% to +3.0%)",
        "dist_min": -1.0,
        "dist_max": 3.0,
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


@app.route("/api/scanner/triangles")
def api_scanner_triangles():
    """
    Ascending & Symmetrical Triangle Breakouts endpoint (Daily or Weekly).
    Ultra-fast parallel evaluation across worker threads.
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)
    tf = request.args.get("timeframe", "daily").lower()
    force_refresh = request.args.get("refresh") == "1"

    if force_refresh:
        clear_scan_caches()

    cache_key = f"{index_param}_{tf}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_TRIANGLES_CACHE and (now_time - _LAST_SCAN_TIME.get(f"triangles_{cache_key}", 0) < 300):
        return jsonify(_SCAN_TRIANGLES_CACHE[cache_key])

    ensure_universe_cached(universe, force_refresh=force_refresh)

    ascending_triangles = []
    symmetrical_triangles = []
    asc_confirmed = []
    asc_pre = []
    symm_confirmed = []
    symm_pre = []
    confirmed_breakouts = []
    pre_breakouts = []

    def _eval_triangle(sym):
        d_candles, w_candles = get_cached_candles(sym)
        candles = w_candles if tf == "weekly" else d_candles
        if not candles or len(candles) < 25:
            return None, None
        comp_name = get_company_name(sym)
        asc = strategies.detect_ascending_triangle(sym, comp_name, candles, timeframe=tf)
        symm = strategies.detect_symmetrical_triangle(sym, comp_name, candles, timeframe=tf)
        return asc, symm

    with ThreadPoolExecutor(max_workers=8) as executor:
        for asc, symm in executor.map(_eval_triangle, universe):
            if asc:
                ascending_triangles.append(asc)
                if asc["status"] in ["Confirmed Breakout", "Retest Entry"]:
                    asc_confirmed.append(asc)
                    confirmed_breakouts.append(asc)
                elif asc["status"] == "Forming":
                    asc_pre.append(asc)
                    pre_breakouts.append(asc)

            if symm:
                symmetrical_triangles.append(symm)
                if symm["status"] in ["Confirmed Breakout", "Retest Entry"]:
                    symm_confirmed.append(symm)
                    confirmed_breakouts.append(symm)
                elif symm["status"] == "Forming":
                    symm_pre.append(symm)
                    pre_breakouts.append(symm)

    ascending_triangles.sort(key=lambda x: (0 if "Breakout" in x["status"] or "Retest" in x["status"] else 1, x["abs_distance"]))
    symmetrical_triangles.sort(key=lambda x: (0 if "Breakout" in x["status"] or "Retest" in x["status"] else 1, x["abs_distance"]))
    confirmed_breakouts.sort(key=lambda x: x["abs_distance"])
    pre_breakouts.sort(key=lambda x: x["abs_distance"])

    now_ist = get_current_ist_time()
    payload = {
        "last_updated": now_ist.strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": tf.capitalize(),
        "total_scanned": len(universe),
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


@app.route("/api/scanner/pole_and_flag")
def api_scanner_pole_and_flag():
    """
    PART 4: Bull Pole & Flag scanner endpoint (Daily & Weekly).
    Ultra-fast parallel evaluation across worker threads.
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)
    tf = request.args.get("timeframe", "daily").lower()
    force_refresh = request.args.get("refresh") == "1"

    if force_refresh:
        clear_scan_caches()

    cache_key = f"{index_param}_{tf}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_POLEFLAG_CACHE and (now_time - _LAST_SCAN_TIME.get(f"poleflag_{cache_key}", 0) < 300):
        return jsonify(_SCAN_POLEFLAG_CACHE[cache_key])

    ensure_universe_cached(universe, force_refresh=force_refresh)

    all_flags = []
    confirmed = []
    pre_breakouts = []

    def _eval_flag(sym):
        d_candles, w_candles = get_cached_candles(sym)
        candles = w_candles if tf == "weekly" else d_candles
        if not candles or len(candles) < 30:
            return None
        comp_name = get_company_name(sym)
        return strategies.detect_pole_and_flag(sym, comp_name, candles, timeframe=tf)

    with ThreadPoolExecutor(max_workers=8) as executor:
        for flag in executor.map(_eval_flag, universe):
            if flag:
                all_flags.append(flag)
                if flag["status"] in ["Pole & Flag Breakout", "Pole & Flag Retest"]:
                    confirmed.append(flag)
                elif flag["status"] == "Pole & Flag Forming":
                    pre_breakouts.append(flag)

    all_flags.sort(key=lambda x: (0 if "Breakout" in x["status"] or "Retest" in x["status"] else 1, x["abs_distance"]))
    confirmed.sort(key=lambda x: x["abs_distance"])
    pre_breakouts.sort(key=lambda x: x["abs_distance"])

    now_ist = get_current_ist_time()
    payload = {
        "last_updated": now_ist.strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": tf.capitalize(),
        "total_scanned": len(universe),
        "results": all_flags,
        "confirmed_breakouts": confirmed,
        "pre_breakouts": pre_breakouts,
        "counts": {
            "total": len(all_flags),
            "confirmed": len(confirmed),
            "pre_breakout": len(pre_breakouts),
        }
    }

    _SCAN_POLEFLAG_CACHE[cache_key] = payload
    _LAST_SCAN_TIME[f"poleflag_{cache_key}"] = now_time
    return jsonify(payload)


@app.route("/api/debug/<symbol>")
def api_debug_symbol(symbol: str):
    """
    PART 6: Why Rejected debug panel/endpoint.
    Returns reject reasons and diagnostic metrics for any stock and strategy.
    """
    sym = symbol.upper()
    strategy = request.args.get("strategy", "ascending").lower()
    tf = request.args.get("timeframe", "daily").lower()

    d_candles, w_candles = get_cached_candles(sym)
    candles = w_candles if tf == "weekly" else d_candles

    if not candles:
        return jsonify({"error": f"Candle data not available for symbol {sym}"}), 404

    comp_name = get_company_name(sym)
    diag = strategies.get_strategy_debug(sym, comp_name, candles, strategy=strategy, timeframe=tf)
    return jsonify({
        "symbol": sym,
        "company": comp_name,
        "strategy": strategy,
        "timeframe": tf.capitalize(),
        "bars_analyzed": len(candles),
        **diag
    })


@app.route("/api/chart/<symbol>")
def api_chart(symbol: str):
    """
    Interactive TradingView Lightweight Chart endpoint.
    Draws only the pivot points that actually touched each line, plus the fitted lines.
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
    ma44_series = strategies.calculate_ma44(closes)
    ma44_high_series = strategies.calculate_ma44_high(highs)

    display_bars = candles[-120:] if len(candles) >= 120 else candles
    offset = len(candles) - len(display_bars)

    candle_data = []
    ma_line_data = []
    ma_high_line_data = []

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
        ma_high_val = ma44_high_series[c_idx]
        if ma_high_val is not None:
            ma_high_line_data.append({
                "time": c[0],
                "value": ma_high_val
            })

    current_ma = ma44_series[-1]
    current_ma_high = ma44_high_series[-1]
    cmp_price = closes[-1]
    dist_pct = round(((cmp_price - current_ma) / current_ma) * 100, 2) if current_ma else 0.0
    touch = strategies.is_touch(lows[-1], highs[-1], current_ma)
    status_44ma = strategies.get_status(touch, cmp_price, current_ma, dist_pct, cur_low=lows[-1], ma44_high=current_ma_high) or "Outside Band"

    comp_name = get_company_name(sym)
    asc = strategies.detect_ascending_triangle(sym, comp_name, candles, timeframe=tf)
    symm = strategies.detect_symmetrical_triangle(sym, comp_name, candles, timeframe=tf)
    poleflag = strategies.detect_pole_and_flag(sym, comp_name, candles, timeframe=tf)

    return jsonify({
        "symbol": sym,
        "company": comp_name,
        "timeframe": tf,
        "candles": candle_data,
        "ma44_line": ma_line_data,
        "ma44_high_line": ma_high_line_data,
        "current_ma44": current_ma,
        "current_ma44_high": current_ma_high,
        "cmp": cmp_price,
        "status_44ma": status_44ma,
        "distance_pct": dist_pct,
        "ascending_pattern": asc,
        "symmetrical_pattern": symm,
        "pole_and_flag_pattern": poleflag,
    })


@app.route("/api/export/csv")
def api_export_csv():
    tab = request.args.get("tab", "ascending_confirmed").lower()
    index_param = request.args.get("index", "nifty500").lower()
    universe = get_universe(index_param)
    ensure_universe_cached(universe)

    output = io.StringIO()
    writer = csv.writer(output)

    # Pole and Flag export
    if "pole" in tab or "flag" in tab:
        is_weekly = "weekly" in tab
        tf_str = "weekly" if is_weekly else "daily"
        writer.writerow(["Symbol", "Company", "Pattern", "Timeframe", "CMP", "Entry Price", "Stop Loss", "Target", "R:R", "Status", "Pole Rise %", "Pole Height"])
        for sym in universe:
            d_c, w_c = get_cached_candles(sym)
            c = w_c if is_weekly else d_c
            if not c or len(c) < 30:
                continue
            flag = strategies.detect_pole_and_flag(sym, get_company_name(sym), c, timeframe=tf_str)
            if flag:
                writer.writerow([
                    flag["symbol"], flag["company"], flag["pattern"], flag["timeframe"],
                    flag["cmp"], flag["buy_price"], flag["stop_loss"], flag["target"],
                    flag["risk_reward"], flag["status"], f"{flag['pole_rise_pct']}%", flag["pole_height"]
                ])
        filename = f"PoleFlag_{tab}_{index_param}_{dt.date.today().strftime('%Y%m%d')}.csv"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={filename}"})

    # Triangles export
    if any(k in tab for k in ["ascending", "symmetrical", "triangle"]):
        writer.writerow(["Symbol", "Company", "Pattern", "Timeframe", "CMP", "Resistance", "Support", "Entry", "Stop Loss", "Target", "R:R", "Status", "Touches"])
        is_weekly = "weekly" in tab
        tf_str = "weekly" if is_weekly else "daily"
        is_asc = "ascending" in tab or "asc" in tab
        is_symm = "symmetrical" in tab or "symm" in tab

        for sym in universe:
            d_c, w_c = get_cached_candles(sym)
            c = w_c if is_weekly else d_c
            if not c or len(c) < 30:
                continue
            comp = get_company_name(sym)

            if is_asc or (not is_symm):
                asc = strategies.detect_ascending_triangle(sym, comp, c, timeframe=tf_str)
                if asc:
                    writer.writerow([
                        asc["symbol"], asc["company"], asc["pattern"], asc["timeframe"],
                        asc["cmp"], asc["resistance_level"], asc["support_level"],
                        asc["buy_price"], asc["stop_loss"], asc["target"], asc["risk_reward"],
                        asc["status"], asc.get("touches", 2)
                    ])

            if is_symm or (not is_asc):
                symm = strategies.detect_symmetrical_triangle(sym, comp, c, timeframe=tf_str)
                if symm:
                    writer.writerow([
                        symm["symbol"], symm["company"], symm["pattern"], symm["timeframe"],
                        symm["cmp"], symm["resistance_level"], symm["support_level"],
                        symm["buy_price"], symm["stop_loss"], symm["target"], symm["risk_reward"],
                        symm["status"], symm.get("touches", 2)
                    ])
        filename = f"Triangles_{tab}_{index_param}_{dt.date.today().strftime('%Y%m%d')}.csv"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={filename}"})

    # 44 MA export (-1% to +3% band)
    writer.writerow(["Symbol", "Company", "CMP", "44 MA", "Distance %", "Status", "Day Change %", "Volume", "Timeframe"])
    for sym in universe:
        d_candles, w_candles = get_cached_candles(sym)
        if not d_candles:
            continue
        eval_res = strategies.evaluate_44ma_stock(
            symbol=sym,
            company_name=get_company_name(sym),
            daily_candles=d_candles,
            weekly_candles=w_candles,
        )
        if not eval_res:
            continue
        if tab in ["daily", "weekly", "both"] and eval_res["timeframe"].lower() != tab:
            continue
        writer.writerow([
            eval_res["symbol"], eval_res["company"], eval_res["cmp"], eval_res["ma44"],
            f"{eval_res['distance_pct']}%", eval_res["status"], f"{eval_res['day_change_pct']}%",
            eval_res["volume"], eval_res["timeframe"]
        ])

    filename = f"44MA_Scanner_{index_param}_{tab}_{dt.date.today().strftime('%Y%m%d')}.csv"
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={filename}"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n=======================================================")
    print(f" 🚀 Stock Screener Active at http://0.0.0.0:{port}")
    print(f"=======================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False)
