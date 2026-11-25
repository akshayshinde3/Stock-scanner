"""
main.py — FastAPI Backend for 44 MA Scanner & Breakout Chart Patterns
=====================================================================
Full FastAPI implementation with async execution and pandas integration.
Run with:
  uvicorn main:app --reload --port 5000
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
from typing import Optional, List, Dict, Any
import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import strategies
from patterns.geometry import resample_to_weekly

app = FastAPI(
    title="Indian Stock Screener API",
    description="44 MA Touch & Near (-1% to +3%), Ascending & Symmetrical Triangles, and Pole & Flag",
    version="3.0.0"
)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
NIFTY500_FILE = os.path.join(DATA_DIR, "nifty500.txt")
TEMPLATE_FILE = os.path.join(DATA_DIR, "templates", "dashboard.html")

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
}


def load_symbols():
    if not os.path.exists(NIFTY500_FILE):
        return list(COMPANY_NAMES.keys())
    symbols = []
    with open(NIFTY500_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                symbols.append(line.upper())
    return symbols


def load_symbol_file(filename):
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


UNIVERSE_500 = load_symbols()
UNIVERSE_100 = UNIVERSE_500[:100]
UNIVERSE_50  = UNIVERSE_500[:50]
UNIVERSE_MIDCAP   = load_symbol_file("niftymidcap.txt")
UNIVERSE_SMALLCAP = load_symbol_file("niftysmallcap.txt")


def get_universe(index_param: str):
    if index_param == "nifty50":
        return UNIVERSE_50
    elif index_param == "nifty100":
        return UNIVERSE_100
    elif index_param == "midcap":
        return UNIVERSE_MIDCAP
    elif index_param == "smallcap":
        return UNIVERSE_SMALLCAP
    return UNIVERSE_500


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

_d_cache: Dict[str, list] = {}
_w_cache: Dict[str, list] = {}
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

_SCAN_CACHE: Dict[str, dict] = {}
_LAST_SCAN_TIME: Dict[str, float] = {}


def get_company(sym: str) -> str:
    return COMPANY_NAMES.get(sym.upper(), f"{sym.upper()} Ltd.")


def get_ist():
    utc = dt.datetime.now(dt.timezone.utc)
    return utc + dt.timedelta(hours=5, minutes=30)


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
                        _d_cache[sym] = [[str(c[0])[:10], float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5])] for c in candles]
                for sym, candles in weekly_data.items():
                    if candles:
                        _w_cache[sym] = [[str(c[0])[:10], float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5])] for c in candles]
            print(f"FastAPI: Loaded {len(_d_cache)} symbols from {target_file}.")
            return
        except Exception as e:
            print(f"FastAPI Warning: Could not load gzip cache ({e})")

    if os.path.exists(CACHE_JSON_FILE):
        try:
            with open(CACHE_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _cache_lock:
                for sym, val in data.items():
                    _d_cache[sym] = val.get("daily", [])
                    _w_cache[sym] = val.get("weekly", [])
        except Exception:
            pass


load_disk_cache()


def fetch_candles(sym: str) -> tuple:
    sym_upper = sym.upper()
    with _cache_lock:
        if sym_upper in _d_cache and sym_upper in _w_cache:
            return _d_cache[sym_upper], _w_cache[sym_upper]

    if sym_upper in _failed_symbols:
        return None, None

    mapped_sym = SYMBOL_MAP.get(sym_upper, sym_upper)
    ticker_sym = f"{mapped_sym}.NS"
    host = "query2.finance.yahoo.com" if (hash(sym_upper) % 2 == 0) else "query1.finance.yahoo.com"
    url = f"https://{host}/v8/finance/chart/{ticker_sym}?range=5y&interval=1d"

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
                    daily.append([d_str, round(float(o), 2), round(float(h), 2), round(float(l), 2), round(float(c), 2), int(v or 0)])
                if len(daily) >= 45:
                    weekly = resample_to_weekly(daily)
                    with _cache_lock:
                        _d_cache[sym_upper] = daily
                        _w_cache[sym_upper] = weekly
                    return daily, weekly
        elif resp.status_code == 404:
            _failed_symbols.add(sym_upper)
            return None, None
    except Exception:
        pass

    _failed_symbols.add(sym_upper)
    return None, None


def ensure_universe_cached(universe: List[str], force_refresh: bool = False, max_workers: int = 14) -> None:
    with _batch_lock:
        if force_refresh:
            _failed_symbols.clear()
            symbols_to_fetch = list(universe)
        else:
            with _cache_lock:
                symbols_to_fetch = [s for s in universe if (s not in _d_cache or s not in _w_cache) and (s not in _failed_symbols)]

        if not symbols_to_fetch:
            return

        def _fetch_worker(s: str):
            d, w = fetch_candles(s)
            return s, d, w

        new_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_fetch_worker, s): s for s in symbols_to_fetch}
            for fut in as_completed(future_map):
                try:
                    s, d_candles, w_candles = fut.result()
                    if d_candles and w_candles:
                        with _cache_lock:
                            _d_cache[s] = d_candles
                            _w_cache[s] = w_candles
                        new_count += 1
                    else:
                        _failed_symbols.add(s)
                except Exception:
                    pass


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    if os.path.exists(TEMPLATE_FILE):
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Indian Stock Screener API Active</h1>")


@app.get("/api/scanner/44ma")
async def scan_44ma(
    index: str = "nifty500",
    min_price: float = 0.0,
    min_weekly_vol: int = 100000,
    rising_only: str = "0",
    green_only: str = "0",
    statuses: str = "",
    refresh: str = "0"
):
    universe = get_universe(index)
    allowed_stats = [s.strip().lower() for s in statuses.split(",") if s.strip()]
    force_refresh = (refresh == "1")

    cache_key = f"44ma_{index}_{min_price}_{min_weekly_vol}_{rising_only}_{green_only}_{statuses}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_CACHE and (now_time - _LAST_SCAN_TIME.get(cache_key, 0) < 180):
        return _SCAN_CACHE[cache_key]

    ensure_universe_cached(universe, force_refresh=force_refresh)

    both, daily, weekly = [], [], []
    for sym in universe:
        d_c, w_c = fetch_candles(sym)
        if not d_c:
            continue
        res = strategies.evaluate_44ma_stock(
            symbol=sym,
            company_name=get_company(sym),
            daily_candles=d_c,
            weekly_candles=w_c,
            min_price=min_price,
            min_weekly_vol=min_weekly_vol,
            rising_only=(rising_only == "1"),
            green_only=(green_only == "1")
        )
        if not res:
            continue
        if allowed_stats and not any(a in res["status"].lower() for a in allowed_stats):
            continue
        if res["timeframe"] == "Both":
            both.append(res)
        elif res["timeframe"] == "Daily":
            daily.append(res)
        elif res["timeframe"] == "Weekly":
            weekly.append(res)

    both.sort(key=lambda x: x["abs_distance"])
    daily.sort(key=lambda x: x["abs_distance"])
    weekly.sort(key=lambda x: x["abs_distance"])

    result = {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "universe": index.upper(),
        "dist_min": -1.0,
        "dist_max": 3.0,
        "total_scanned": len(universe),
        "counts": {"both": len(both), "daily": len(daily), "weekly": len(weekly), "total_qualifying": len(both)+len(daily)+len(weekly)},
        "results": {"both": both, "daily": daily, "weekly": weekly}
    }
    _SCAN_CACHE[cache_key] = result
    _LAST_SCAN_TIME[cache_key] = now_time
    return result


@app.get("/api/scanner/triangles")
async def scan_triangles(index: str = "nifty500", timeframe: str = "daily", refresh: str = "0"):
    universe = get_universe(index)
    force_refresh = (refresh == "1")
    cache_key = f"triangles_{index}_{timeframe}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_CACHE and (now_time - _LAST_SCAN_TIME.get(cache_key, 0) < 180):
        return _SCAN_CACHE[cache_key]

    ensure_universe_cached(universe, force_refresh=force_refresh)

    ascending, symmetrical = [], []
    asc_confirmed, asc_pre = [], []
    symm_confirmed, symm_pre = [], []
    confirmed_breakouts, pre_breakouts = [], []

    for sym in universe:
        d_c, w_c = fetch_candles(sym)
        c = w_c if timeframe == "weekly" else d_c
        if not c or len(c) < 25:
            continue
        comp = get_company(sym)
        asc = strategies.detect_ascending_triangle(sym, comp, c, timeframe=timeframe)
        if asc:
            ascending.append(asc)
            if asc["status"] in ["Confirmed Breakout", "Retest Entry"]:
                asc_confirmed.append(asc)
                confirmed_breakouts.append(asc)
            elif asc["status"] == "Forming":
                asc_pre.append(asc)
                pre_breakouts.append(asc)

        symm = strategies.detect_symmetrical_triangle(sym, comp, c, timeframe=timeframe)
        if symm:
            symmetrical.append(symm)
            if symm["status"] in ["Confirmed Breakout", "Retest Entry"]:
                symm_confirmed.append(symm)
                confirmed_breakouts.append(symm)
            elif symm["status"] == "Forming":
                symm_pre.append(symm)
                pre_breakouts.append(symm)

    ascending.sort(key=lambda x: (0 if "Breakout" in x["status"] or "Retest" in x["status"] else 1, x["abs_distance"]))
    symmetrical.sort(key=lambda x: (0 if "Breakout" in x["status"] or "Retest" in x["status"] else 1, x["abs_distance"]))

    result = {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": timeframe.capitalize(),
        "ascending": ascending,
        "symmetrical": symmetrical,
        "ascending_confirmed": asc_confirmed,
        "ascending_pre": asc_pre,
        "symmetrical_confirmed": symm_confirmed,
        "symmetrical_pre": symm_pre,
        "confirmed_breakouts": confirmed_breakouts,
        "pre_breakouts": pre_breakouts,
        "counts": {
            "ascending": len(ascending),
            "symmetrical": len(symmetrical),
            "ascending_confirmed": len(asc_confirmed),
            "ascending_pre": len(asc_pre),
            "symmetrical_confirmed": len(symm_confirmed),
            "symmetrical_pre": len(symm_pre),
            "confirmed_breakouts": len(confirmed_breakouts),
            "pre_breakouts": len(pre_breakouts),
            "total_patterns": len(ascending) + len(symmetrical),
        }
    }
    _SCAN_CACHE[cache_key] = result
    _LAST_SCAN_TIME[cache_key] = now_time
    return result


@app.get("/api/scanner/pole_and_flag")
async def scan_pole_and_flag(index: str = "nifty500", timeframe: str = "daily", refresh: str = "0"):
    universe = get_universe(index)
    force_refresh = (refresh == "1")
    cache_key = f"poleflag_{index}_{timeframe}"
    now_time = time.time()
    if not force_refresh and cache_key in _SCAN_CACHE and (now_time - _LAST_SCAN_TIME.get(cache_key, 0) < 180):
        return _SCAN_CACHE[cache_key]

    ensure_universe_cached(universe, force_refresh=force_refresh)

    all_flags = []
    confirmed = []
    pre_breakouts = []

    for sym in universe:
        d_c, w_c = fetch_candles(sym)
        c = w_c if timeframe == "weekly" else d_c
        if not c or len(c) < 30:
            continue
        comp = get_company(sym)
        flag = strategies.detect_pole_and_flag(sym, comp, c, timeframe=timeframe)
        if flag:
            all_flags.append(flag)
            if flag["status"] in ["Pole & Flag Breakout", "Pole & Flag Retest"]:
                confirmed.append(flag)
            elif flag["status"] == "Pole & Flag Forming":
                pre_breakouts.append(flag)

    all_flags.sort(key=lambda x: (0 if "Breakout" in x["status"] or "Retest" in x["status"] else 1, x["abs_distance"]))
    confirmed.sort(key=lambda x: x["abs_distance"])
    pre_breakouts.sort(key=lambda x: x["abs_distance"])

    result = {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": timeframe.capitalize(),
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
    _SCAN_CACHE[cache_key] = result
    _LAST_SCAN_TIME[cache_key] = now_time
    return result


@app.get("/api/debug/{symbol}")
async def debug_symbol(symbol: str, strategy: str = "ascending", timeframe: str = "daily"):
    sym = symbol.upper()
    d_c, w_c = fetch_candles(sym)
    candles = w_c if timeframe == "weekly" else d_c
    if not candles:
        raise HTTPException(status_code=404, detail="Candle data not found")
    comp = get_company(sym)
    diag = strategies.get_strategy_debug(sym, comp, candles, strategy=strategy, timeframe=timeframe)
    return {
        "symbol": sym,
        "company": comp,
        "strategy": strategy,
        "timeframe": timeframe.capitalize(),
        "bars_analyzed": len(candles),
        **diag
    }


@app.get("/api/chart/{symbol}")
async def get_chart(symbol: str, tf: str = "daily"):
    sym = symbol.upper()
    d_c, w_c = fetch_candles(sym)
    candles = w_c if tf == "weekly" else d_c
    if not candles:
        raise HTTPException(status_code=404, detail="Candles not found")
    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    ma44 = strategies.calculate_ma44(closes)

    display_bars = candles[-120:] if len(candles) >= 120 else candles
    offset = len(candles) - len(display_bars)

    candle_data = [{"time": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in display_bars]
    ma_line = [{"time": c[0], "value": ma44[offset + i]} for i, c in enumerate(display_bars) if ma44[offset + i] is not None]

    current_ma = ma44[-1] if ma44 else None
    cmp_price = closes[-1] if closes else None
    dist_pct = round(((cmp_price - current_ma) / current_ma) * 100, 2) if current_ma else 0.0
    touch = strategies.is_touch(lows[-1], highs[-1], current_ma)
    status_44ma = strategies.get_status(touch, cmp_price, current_ma, dist_pct) or "Outside Band"

    comp = get_company(sym)
    asc = strategies.detect_ascending_triangle(sym, comp, candles, timeframe=tf)
    symm = strategies.detect_symmetrical_triangle(sym, comp, candles, timeframe=tf)
    poleflag = strategies.detect_pole_and_flag(sym, comp, candles, timeframe=tf)

    return {
        "symbol": sym,
        "company": comp,
        "timeframe": tf,
        "candles": candle_data,
        "ma44_line": ma_line,
        "current_ma44": current_ma,
        "cmp": cmp_price,
        "status_44ma": status_44ma,
        "distance_pct": dist_pct,
        "ascending_pattern": asc,
        "symmetrical_pattern": symm,
        "pole_and_flag_pattern": poleflag,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
