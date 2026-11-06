"""
main.py — FastAPI Backend for 44 MA Touch & Near Scanner
=======================================================
Full FastAPI implementation with pandas for high performance async execution.
Run with:
  uvicorn main:app --reload --port 5000
"""

import os
import io
import csv
import json
import urllib.request
import datetime as dt
from typing import Optional, List
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import strategies

app = FastAPI(
    title="44 MA Touch & Near Scanner API",
    description="Stock screener for Nifty 500 with 44 MA & Breakout Patterns",
    version="2.0.0"
)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
NIFTY500_FILE = os.path.join(DATA_DIR, "nifty500.txt")
TEMPLATE_FILE = os.path.join(DATA_DIR, "templates", "dashboard.html")

SITE_PASSWORD = (
    os.environ.get("SITE_PASSWORD")
    or os.environ.get("APP_PASSWORD")
    or "Akshay1999"
).strip()

# Company Name Mapping
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

UNIVERSE_500 = load_symbols()
UNIVERSE_100 = UNIVERSE_500[:100]
UNIVERSE_50  = UNIVERSE_500[:50]

_d_cache = {}
_w_cache = {}

def get_company(sym: str):
    return COMPANY_NAMES.get(sym, f"{sym} Ltd.")

def get_ist():
    utc = dt.datetime.now(dt.timezone.utc)
    return utc + dt.timedelta(hours=5, minutes=30)

def fetch_candles(sym: str):
    if sym in _d_cache and sym in _w_cache:
        return _d_cache[sym], _w_cache[sym]
    ticker_sym = f"{sym}.NS"
    # 1. Primary: Direct v8 chart API (bypasses yfinance quoteSummary 404 bug)
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
                        df_temp = pd.DataFrame(daily, columns=["date", "open", "high", "low", "close", "volume"])
                        df_temp["date"] = pd.to_datetime(df_temp["date"])
                        df_temp.set_index("date", inplace=True)
                        df_w = df_temp.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
                        weekly = []
                        for idx, row in df_w.iterrows():
                            weekly.append([idx.strftime("%Y-%m-%d"), round(float(row["open"]), 2), round(float(row["high"]), 2), round(float(row["low"]), 2), round(float(row["close"]), 2), int(row["volume"])])
                        _d_cache[sym] = daily
                        _w_cache[sym] = weekly
                        return daily, weekly
    except Exception:
        pass

    # 2. Fallback
    try:
        df = yf.Ticker(ticker_sym).history(period="1y", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 45:
            return None, None
        daily = []
        for idx, row in df.iterrows():
            d_str = idx.strftime("%Y-%m-%d")
            daily.append([d_str, round(float(row["Open"]), 2), round(float(row["High"]), 2), round(float(row["Low"]), 2), round(float(row["Close"]), 2), int(row["Volume"])])
        
        # Resample to weekly using pandas
        df_w = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
        weekly = []
        for idx, row in df_w.iterrows():
            weekly.append([idx.strftime("%Y-%m-%d"), round(float(row["Open"]), 2), round(float(row["High"]), 2), round(float(row["Low"]), 2), round(float(row["Close"]), 2), int(row["Volume"])])
        
        _d_cache[sym] = daily
        _w_cache[sym] = weekly
        return daily, weekly
    except Exception:
        return None, None

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    if os.path.exists(TEMPLATE_FILE):
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>44 MA Touch & Near Scanner Active</h1>")

@app.get("/api/scanner/44ma")
async def scan_44ma(
    index: str = "nifty500",
    max_above: float = 2.0,
    max_below: float = 3.0,
    min_price: float = 0.0,
    min_weekly_vol: int = 100000,
    rising_only: str = "0",
    green_only: str = "0",
    statuses: str = ""
):
    universe = UNIVERSE_50 if index == "nifty50" else (UNIVERSE_100 if index == "nifty100" else UNIVERSE_500)
    allowed_stats = [s.strip().lower() for s in statuses.split(",") if s.strip()]

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
            max_above_a=max_above,
            max_below_b=max_below,
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

    return {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "universe": index.upper(),
        "total_scanned": len(universe),
        "counts": {"both": len(both), "daily": len(daily), "weekly": len(weekly), "total_qualifying": len(both)+len(daily)+len(weekly)},
        "results": {"both": both, "daily": daily, "weekly": weekly}
    }

@app.get("/api/scanner/44ma_breakouts")
async def scan_44ma_breakouts(index: str = "nifty500", timeframe: str = "daily"):
    universe = UNIVERSE_50 if index == "nifty50" else (UNIVERSE_100 if index == "nifty100" else UNIVERSE_500)
    confirmed, pre_breakout = [], []
    for sym in universe:
        d_c, w_c = fetch_candles(sym)
        c = w_c if timeframe == "weekly" else d_c
        if not c or len(c) < 45:
            continue
        comp = get_company(sym)
        eval_res = strategies.evaluate_44ma_breakout(sym, comp, c, timeframe=timeframe)
        if not eval_res:
            continue
        if eval_res["type"] == "confirm_breakout":
            confirmed.append(eval_res)
        elif eval_res["type"] == "pre_breakout":
            pre_breakout.append(eval_res)

    # Sort lowest percentage first (1% at top, 2% below, progressing up to 7%)
    confirmed.sort(key=lambda s: s["distance_pct"])
    pre_breakout.sort(key=lambda s: abs(s["distance_pct"]))

    return {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": timeframe.capitalize(),
        "total_scanned": len(universe),
        "counts": {"confirmed": len(confirmed), "pre_breakout": len(pre_breakout)},
        "confirmed_breakouts": confirmed,
        "pre_breakouts": pre_breakout
    }

@app.get("/api/scanner/above44")
async def scan_above44(index: str = "nifty500", timeframe: str = "daily"):
    universe = UNIVERSE_50 if index == "nifty50" else (UNIVERSE_100 if index == "nifty100" else UNIVERSE_500)
    results = []
    for sym in universe:
        d_c, w_c = fetch_candles(sym)
        c = w_c if timeframe == "weekly" else d_c
        if not c or len(c) < 45:
            continue
        comp = get_company(sym)
        res = strategies.analyze_above_44ma(sym, comp, c, timeframe=timeframe)
        if res:
            results.append(res)

    results.sort(key=lambda s: (0 if "Breakout" in s["status"] else (1 if "Near" in s["status"] else 2), s["distance_pct"]))
    return {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": timeframe.capitalize(),
        "total_scanned": len(universe),
        "count": len(results),
        "results": results
    }

@app.get("/api/scanner/triangles")
async def scan_triangles(index: str = "nifty500", timeframe: str = "daily"):
    universe = UNIVERSE_50 if index == "nifty50" else (UNIVERSE_100 if index == "nifty100" else UNIVERSE_500)
    ascending, symmetrical = [], []
    confirmed_breakouts, pre_breakouts = [], []

    for sym in universe:
        d_c, w_c = fetch_candles(sym)
        c = w_c if timeframe == "weekly" else d_c
        if not c or len(c) < 30:
            continue
        comp = get_company(sym)
        asc = strategies.detect_ascending_triangle(sym, comp, c, timeframe=timeframe)
        if asc:
            ascending.append(asc)
            if "Confirmed" in asc["status"]:
                confirmed_breakouts.append(asc)
            elif "Watch" in asc["status"]:
                pre_breakouts.append(asc)

        symm = strategies.detect_symmetrical_triangle(sym, comp, c, timeframe=timeframe)
        if symm:
            symmetrical.append(symm)
            if "Confirmed" in symm["status"]:
                confirmed_breakouts.append(symm)
            elif "Watch" in symm["status"]:
                pre_breakouts.append(symm)

    ascending.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))
    symmetrical.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))
    confirmed_breakouts.sort(key=lambda x: x["abs_distance"])
    pre_breakouts.sort(key=lambda x: x["abs_distance"])

    return {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": timeframe.capitalize(),
        "ascending": ascending,
        "symmetrical": symmetrical,
        "confirmed_breakouts": confirmed_breakouts,
        "pre_breakouts": pre_breakouts,
        "counts": {
            "ascending": len(ascending),
            "symmetrical": len(symmetrical),
            "confirmed_breakouts": len(confirmed_breakouts),
            "pre_breakouts": len(pre_breakouts),
        }
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
    near_bel = strategies.is_near_below(cmp_price, current_ma, dist_pct, 3.0)
    above_z = strategies.is_above_zone(cmp_price, current_ma, dist_pct, 2.0)
    status_44ma = strategies.get_status(touch, above_z, near_bel, 2.0)

    comp = get_company(sym)
    asc = strategies.detect_ascending_triangle(sym, comp, candles, timeframe=tf)
    symm = strategies.detect_symmetrical_triangle(sym, comp, candles, timeframe=tf)

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
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
