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
_daily_cache: Dict[str, list] = {}
_weekly_cache: Dict[str, list] = {}
_last_cache_update_time: Optional[dt.datetime] = None
_cache_lock = threading.Lock()


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
    Returns (daily_candles, weekly_candles).
    """
    ticker_sym = f"{symbol}.NS"
    try:
        ticker = yf.Ticker(ticker_sym)
        # Fetch 1 year of daily history to ensure sufficient lookback for 44 MA
        df = ticker.history(period="1y", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 45:
            # Fallback with auto_adjust=True
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

        # Segment into tabs and separate into Confirmed vs Watchlist
        tf = stock_eval["timeframe"]
        is_conf = stock_eval.get("is_confirmed", False)
        
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

    # Separate Confirmed (Touching / Above) from Pre-Breakout Watchlist (Near Below)
    both_confirmed = [s for s in both_results if s.get("is_confirmed", False)]
    both_watch = [s for s in both_results if not s.get("is_confirmed", False)]

    daily_confirmed = [s for s in daily_results if s.get("is_confirmed", False)]
    daily_watch = [s for s in daily_results if not s.get("is_confirmed", False)]

    weekly_confirmed = [s for s in weekly_results if s.get("is_confirmed", False)]
    weekly_watch = [s for s in weekly_results if not s.get("is_confirmed", False)]

    now_ist = get_current_ist_time()
    last_updated_str = now_ist.strftime("%d-%b-%Y %I:%M %p IST")

    return jsonify({
        "last_updated": last_updated_str,
        "universe": index_param.upper(),
        "total_scanned": len(universe),
        "counts": {
            "both": len(both_results),
            "both_confirmed": len(both_confirmed),
            "both_watch": len(both_watch),
            "daily": len(daily_results),
            "daily_confirmed": len(daily_confirmed),
            "daily_watch": len(daily_watch),
            "weekly": len(weekly_results),
            "weekly_confirmed": len(weekly_confirmed),
            "weekly_watch": len(weekly_watch),
            "total_qualifying": len(both_results) + len(daily_results) + len(weekly_results),
        },
        "results": {
            "both": both_results,
            "both_confirmed": both_confirmed,
            "both_watch": both_watch,
            "daily": daily_results,
            "daily_confirmed": daily_confirmed,
            "daily_watch": daily_watch,
            "weekly": weekly_results,
            "weekly_confirmed": weekly_confirmed,
            "weekly_watch": weekly_watch,
        }
    })


@app.route("/api/scanner/triangles")
def api_scanner_triangles():
    """
    Ascending & Symmetrical Triangle Breakouts endpoint.
    Query parameters:
      - index: 'nifty500', 'nifty100', 'nifty50'
      - timeframe: 'daily' or 'weekly'
    """
    index_param = request.args.get("index", "nifty500").lower()
    universe = UNIVERSE_NIFTY50 if index_param == "nifty50" else (UNIVERSE_NIFTY100 if index_param == "nifty100" else UNIVERSE_NIFTY500)
    tf = request.args.get("timeframe", "daily").lower()

    ascending_triangles = []
    symmetrical_triangles = []

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

        # 2. Symmetrical Triangle Check
        symm = strategies.detect_symmetrical_triangle(sym, comp_name, candles, timeframe=tf)
        if symm:
            symmetrical_triangles.append(symm)

    # Sort by smallest distance to breakout trigger first
    ascending_triangles.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))
    symmetrical_triangles.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))

    asc_confirmed = [x for x in ascending_triangles if "Confirmed" in x["status"]]
    asc_watch = [x for x in ascending_triangles if "Confirmed" not in x["status"]]

    symm_confirmed = [x for x in symmetrical_triangles if "Confirmed" in x["status"]]
    symm_watch = [x for x in symmetrical_triangles if "Confirmed" not in x["status"]]

    now_ist = get_current_ist_time()
    return jsonify({
        "last_updated": now_ist.strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": tf.capitalize(),
        "ascending": ascending_triangles,
        "ascending_confirmed": asc_confirmed,
        "ascending_watch": asc_watch,
        "symmetrical": symmetrical_triangles,
        "symmetrical_confirmed": symm_confirmed,
        "symmetrical_watch": symm_watch,
        "counts": {
            "ascending": len(ascending_triangles),
            "ascending_confirmed": len(asc_confirmed),
            "ascending_watch": len(asc_watch),
            "symmetrical": len(symmetrical_triangles),
            "symmetrical_confirmed": len(symm_confirmed),
            "symmetrical_watch": len(symm_watch),
        }
    })


@app.route("/api/chart/<symbol>")
def api_chart(symbol):
    """
    Provides combined OHLCV candles, 44 MA series, and triangle geometries
    for interactive TradingView / Lightweight Charts rendering.
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

    candle_data = []
    ma_line_data = []

    for i, c in enumerate(candles[-120:]):
        c_idx = len(candles) - 120 + i if len(candles) >= 120 else i
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

    # Pattern check
    comp_name = get_company_name(sym)
    asc = strategies.detect_ascending_triangle(sym, comp_name, candles, timeframe=tf)
    symm = strategies.detect_symmetrical_triangle(sym, comp_name, candles, timeframe=tf)

    # Detect 44 MA Touch date
    touch_date = None
    cur_ma = ma44_series[-1]
    if cur_ma is not None and len(candles) >= 1:
        if lows[-1] <= cur_ma <= highs[-1]:
            touch_date = candles[-1][0]
        elif len(candles) >= 2 and lows[-2] <= ma44_series[-2] <= highs[-2]:
            touch_date = candles[-2][0]

    # Active pattern selection (prioritize confirmed pattern, then watch)
    active_pat = asc if (asc and "Confirmed" in asc.get("status", "")) else (
        symm if (symm and "Confirmed" in symm.get("status", "")) else (asc or symm)
    )

    breakout_date = None
    res_line = None
    sup_line = None
    pat_type = None

    if active_pat:
        pat_type = active_pat.get("pattern")
        breakout_date = active_pat.get("breakout_candle_date")
        res_line = active_pat.get("resistance_line")
        sup_line = active_pat.get("support_line")

    return jsonify({
        "symbol": sym,
        "company": comp_name,
        "timeframe": tf,
        "candles": candle_data,
        "ma44_line": ma_line_data,
        "current_ma44": ma44_series[-1] if ma44_series else None,
        "cmp": closes[-1] if closes else None,
        "pattern_type": pat_type,
        "resistance_line": res_line,
        "support_line": sup_line,
        "breakout_candle_date": breakout_date,
        "touch_candle_date": touch_date,
        "ascending_pattern": asc,
        "symmetrical_pattern": symm,
    })


@app.route("/api/export/csv")
def api_export_csv():
    """Generates and downloads CSV of current 44 MA qualifying stocks."""
    tab = request.args.get("tab", "both").lower()
    index_param = request.args.get("index", "nifty500").lower()
    universe = UNIVERSE_NIFTY50 if index_param == "nifty50" else (UNIVERSE_NIFTY100 if index_param == "nifty100" else UNIVERSE_NIFTY500)

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
