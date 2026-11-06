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
import json
import threading
import urllib.request
import datetime as dt
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request, render_template, send_file, Response

import strategies

# ═══════════════════════════════════════════════════════════════════════════
# Flask Application Setup
# ═══════════════════════════════════════════════════════════════════════════
app = Flask(__name__, template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

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
def load_universe_symbols() -> List[str]:
    """Loads Nifty 500 symbols from disk."""
    if not os.path.exists(NIFTY500_FILE):
        return list(COMPANY_NAMES.keys())
    symbols = []
    with open(NIFTY500_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                symbols.append(line.upper())
    return symbols


UNIVERSE_NIFTY500 = load_universe_symbols()
UNIVERSE_NIFTY100 = UNIVERSE_NIFTY500[:100] if len(UNIVERSE_NIFTY500) >= 100 else UNIVERSE_NIFTY500
UNIVERSE_NIFTY50  = UNIVERSE_NIFTY500[:50]  if len(UNIVERSE_NIFTY500) >= 50  else UNIVERSE_NIFTY500

def get_company_name(symbol: str) -> str:
    """Returns human-readable company name for symbol."""
    sym = symbol.upper()
    if sym in COMPANY_NAMES:
        return COMPANY_NAMES[sym]
    return f"{sym} Ltd."


# ═══════════════════════════════════════════════════════════════════════════
# Candle Cache & Data Fetching (Daily & Weekly via Yahoo Finance .NS)
# ═══════════════════════════════════════════════════════════════════════════
CACHE_FILE = os.path.join(DATA_DIR, "eod_cache.json")
_daily_cache: Dict[str, list] = {}
_weekly_cache: Dict[str, list] = {}
_last_cache_update_time: Optional[dt.datetime] = None
_cache_lock = threading.Lock()


def load_disk_cache():
    """Loads cached candles from local disk file if present (Instant Startup)."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                with _cache_lock:
                    for sym, val in data.items():
                        _daily_cache[sym] = val.get("daily", [])
                        _weekly_cache[sym] = val.get("weekly", [])
            print(f"Loaded {len(_daily_cache)} symbols instantly from persistent disk cache.")
        except Exception as e:
            print(f"Warning: Could not load disk cache: {e}")


def save_disk_cache():
    """Persists memory candle cache to disk so restarts are instantaneous."""
    try:
        data = {}
        with _cache_lock:
            for sym in _daily_cache:
                data[sym] = {
                    "daily": _daily_cache[sym],
                    "weekly": _weekly_cache.get(sym, [])
                }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Warning: Could not save disk cache: {e}")


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


def resample_daily_to_weekly(daily_candles: list) -> list:
    """
    Resamples daily OHLCV candles to weekly candles:
    Takes Monday to Friday (or week grouping), aggregating:
      Open = first Open
      High = max High
      Low = min Low
      Close = last Close
      Volume = sum Volume
    """
    if not daily_candles or len(daily_candles) < 5:
        return []

    df = pd.DataFrame(daily_candles, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)

    # Weekly resample ending on Friday (W-FRI)
    weekly_df = df.resample("W-FRI").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    weekly_candles = []
    for date_idx, row in weekly_df.iterrows():
        weekly_candles.append([
            date_idx.strftime("%Y-%m-%d"),
            round(float(row["open"]), 2),
            round(float(row["high"]), 2),
            round(float(row["low"]), 2),
            round(float(row["close"]), 2),
            int(row["volume"]),
        ])
    return weekly_candles


def fetch_stock_candles_yf(symbol: str) -> tuple:
    """
    Fetches daily and weekly candles for an NSE stock via Yahoo Finance.
    Bypasses yfinance's buggy quoteSummary 404 endpoint using direct v8 chart API.
    Returns (daily_candles, weekly_candles).
    """
    ticker_sym = f"{symbol}.NS"
    # 1. Primary: Direct Yahoo Finance v8 chart API (Fast, reliable, never throws quoteSummary 404)
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_sym}?range=1y&interval=1d"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
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
                        weekly = resample_daily_to_weekly(daily)
                        return daily, weekly
    except Exception:
        pass

    # 2. Fallback: yfinance download/history
    try:
        ticker = yf.Ticker(ticker_sym)
        df = ticker.history(period="1y", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 45:
            return None, None

        daily = []
        for index, row in df.iterrows():
            d_str = index.strftime("%Y-%m-%d") if hasattr(index, "strftime") else str(index)[:10]
            daily.append([
                d_str,
                round(float(row["Open"]), 2),
                round(float(row["High"]), 2),
                round(float(row["Low"]), 2),
                round(float(row["Close"]), 2),
                int(row["Volume"]),
            ])

        weekly = resample_daily_to_weekly(daily)
        return daily, weekly
    except Exception as e:
        print(f"Error fetching candles for {symbol}: {e}")
        return None, None


def get_cached_candles(symbol: str, force_refresh: bool = False) -> tuple:
    """Retrieves candles from memory cache or fetches from Yahoo Finance."""
    sym = symbol.upper()
    with _cache_lock:
        if not force_refresh and sym in _daily_cache and sym in _weekly_cache:
            return _daily_cache[sym], _weekly_cache[sym]

    d_candles, w_candles = fetch_stock_candles_yf(sym)
    if d_candles and w_candles:
        with _cache_lock:
            _daily_cache[sym] = d_candles
            _weekly_cache[sym] = w_candles
    return d_candles, w_candles


def background_cache_warmup():
    """Warms up the candle cache for priority stocks in background."""
    print("Initiating candle cache prefetch for top liquid stocks...")
    priority_list = UNIVERSE_NIFTY500[:100]
    for sym in priority_list:
        try:
            get_cached_candles(sym)
            time.sleep(0.05)  # slight pacing to respect rate limits
        except Exception:
            pass
    print("Initial cache prefetch complete.")


# Start warmup thread once on launch
threading.Thread(target=background_cache_warmup, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════
# API Endpoints
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
    })


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

    both_results = []
    daily_results = []
    weekly_results = []

    for sym in universe:
        d_candles, w_candles = get_cached_candles(sym, force_refresh=force_refresh)
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

    return jsonify({
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
    })


# In-memory scanner results cache for instant response (< 5ms) on Render free tier
_SCAN_44MA_CACHE: Dict[str, dict] = {}
_SCAN_ABOVE44_CACHE: Dict[str, dict] = {}
_SCAN_TRIANGLES_CACHE: Dict[str, dict] = {}
_SCAN_44BREAKOUTS_CACHE: Dict[str, dict] = {}
_LAST_SCAN_TIME: Dict[str, float] = {}


@app.route("/api/scanner/44ma_breakouts")
def api_scanner_44ma_breakouts():
    """
    Evaluates 44 MA Breakouts split into:
      - confirmed_breakouts: Close >= MA44 and +1.0% <= Distance % <= +7.0%
      - pre_breakouts: Close < MA44 and -7.0% <= Distance % <= -1.0% (1% to 7% below 44 MA)
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = UNIVERSE_NIFTY50 if index_param == "nifty50" else (UNIVERSE_NIFTY100 if index_param == "nifty100" else UNIVERSE_NIFTY500)
    tf = request.args.get("timeframe", "daily").lower()
    try:
        min_pct = float(request.args.get("min_pct", 1.0))
        max_pct = float(request.args.get("max_pct", 7.0))
    except ValueError:
        min_pct, max_pct = 1.0, 7.0

    cache_key = f"{index_param}_{tf}_{min_pct}_{max_pct}"

    now_time = time.time()
    if cache_key in _SCAN_44BREAKOUTS_CACHE and (now_time - _LAST_SCAN_TIME.get(f"breakouts_{cache_key}", 0) < 180):
        return jsonify(_SCAN_44BREAKOUTS_CACHE[cache_key])

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
    universe = UNIVERSE_NIFTY50 if index_param == "nifty50" else (UNIVERSE_NIFTY100 if index_param == "nifty100" else UNIVERSE_NIFTY500)
    tf = request.args.get("timeframe", "daily").lower()
    cache_key = f"{index_param}_{tf}"

    # Return instantly if cached within last 3 minutes
    now_time = time.time()
    if cache_key in _SCAN_ABOVE44_CACHE and (now_time - _LAST_SCAN_TIME.get(f"above44_{cache_key}", 0) < 180):
        return jsonify(_SCAN_ABOVE44_CACHE[cache_key])

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
    universe = UNIVERSE_NIFTY50 if index_param == "nifty50" else (UNIVERSE_NIFTY100 if index_param == "nifty100" else UNIVERSE_NIFTY500)
    tf = request.args.get("timeframe", "daily").lower()

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
    return jsonify({
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
    })


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
    universe = UNIVERSE_NIFTY50 if index_param == "nifty50" else (UNIVERSE_NIFTY100 if index_param == "nifty100" else UNIVERSE_NIFTY500)

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
