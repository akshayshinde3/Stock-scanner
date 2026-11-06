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
    try:
        df = yf.Ticker(f"{sym}.NS").history(period="1y", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 45:
            df = yf.Ticker(f"{sym}.NS").history(period="1y", interval="1d", auto_adjust=True)
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

    both_confirmed = [s for s in both if s.get("is_confirmed", False)]
    both_watch = [s for s in both if not s.get("is_confirmed", False)]
    daily_confirmed = [s for s in daily if s.get("is_confirmed", False)]
    daily_watch = [s for s in daily if not s.get("is_confirmed", False)]
    weekly_confirmed = [s for s in weekly if s.get("is_confirmed", False)]
    weekly_watch = [s for s in weekly if not s.get("is_confirmed", False)]

    return {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "universe": index.upper(),
        "total_scanned": len(universe),
        "counts": {
            "both": len(both),
            "both_confirmed": len(both_confirmed),
            "both_watch": len(both_watch),
            "daily": len(daily),
            "daily_confirmed": len(daily_confirmed),
            "daily_watch": len(daily_watch),
            "weekly": len(weekly),
            "weekly_confirmed": len(weekly_confirmed),
            "weekly_watch": len(weekly_watch),
            "total_qualifying": len(both)+len(daily)+len(weekly)
        },
        "results": {
            "both": both,
            "both_confirmed": both_confirmed,
            "both_watch": both_watch,
            "daily": daily,
            "daily_confirmed": daily_confirmed,
            "daily_watch": daily_watch,
            "weekly": weekly,
            "weekly_confirmed": weekly_confirmed,
            "weekly_watch": weekly_watch
        }
    }

@app.get("/api/scanner/triangles")
async def scan_triangles(index: str = "nifty500", timeframe: str = "daily"):
    universe = UNIVERSE_50 if index == "nifty50" else (UNIVERSE_100 if index == "nifty100" else UNIVERSE_500)
    ascending, symmetrical = [], []
    for sym in universe:
        d_c, w_c = fetch_candles(sym)
        c = w_c if timeframe == "weekly" else d_c
        if not c or len(c) < 30:
            continue
        comp = get_company(sym)
        asc = strategies.detect_ascending_triangle(sym, comp, c, timeframe=timeframe)
        if asc:
            ascending.append(asc)
        symm = strategies.detect_symmetrical_triangle(sym, comp, c, timeframe=timeframe)
        if symm:
            symmetrical.append(symm)

    ascending.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))
    symmetrical.sort(key=lambda x: (0 if "Confirmed" in x["status"] else 1, x["abs_distance"]))

    asc_confirmed = [x for x in ascending if "Confirmed" in x["status"]]
    asc_watch = [x for x in ascending if "Confirmed" not in x["status"]]
    symm_confirmed = [x for x in symmetrical if "Confirmed" in x["status"]]
    symm_watch = [x for x in symmetrical if "Confirmed" not in x["status"]]

    return {
        "last_updated": get_ist().strftime("%d-%b-%Y %I:%M %p IST"),
        "timeframe": timeframe.capitalize(),
        "ascending": ascending,
        "ascending_confirmed": asc_confirmed,
        "ascending_watch": asc_watch,
        "symmetrical": symmetrical,
        "symmetrical_confirmed": symm_confirmed,
        "symmetrical_watch": symm_watch,
        "counts": {
            "ascending": len(ascending),
            "ascending_confirmed": len(asc_confirmed),
            "ascending_watch": len(asc_watch),
            "symmetrical": len(symmetrical),
            "symmetrical_confirmed": len(symm_confirmed),
            "symmetrical_watch": len(symm_watch),
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
    candle_data = [{"time": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in candles[-120:]]
    ma_line = [{"time": c[0], "value": ma44[len(candles)-120+i]} for i, c in enumerate(candles[-120:]) if ma44[len(candles)-120+i] is not None]
    
    comp_name = get_company(sym)
    asc = strategies.detect_ascending_triangle(sym, comp_name, candles, timeframe=tf)
    symm = strategies.detect_symmetrical_triangle(sym, comp_name, candles, timeframe=tf)

    touch_date = None
    cur_ma = ma44[-1] if ma44 else None
    if cur_ma is not None and len(candles) >= 1:
        if lows[-1] <= cur_ma <= highs[-1]:
            touch_date = candles[-1][0]
        elif len(candles) >= 2 and lows[-2] <= ma44[-2] <= highs[-2]:
            touch_date = candles[-2][0]

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

    return {
        "symbol": sym,
        "company": comp_name,
        "timeframe": tf,
        "candles": candle_data,
        "ma44_line": ma_line,
        "current_ma44": cur_ma,
        "cmp": closes[-1] if closes else None,
        "pattern_type": pat_type,
        "resistance_line": res_line,
        "support_line": sup_line,
        "breakout_candle_date": breakout_date,
        "touch_candle_date": touch_date,
        "ascending_pattern": asc,
        "symmetrical_pattern": symm,
    }
    candle_data = [{"time": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in candles[-120:]]
    ma_line = [{"time": c[0], "value": ma44[len(candles)-120+i]} for i, c in enumerate(candles[-120:]) if ma44[len(candles)-120+i] is not None]
    return {
        "symbol": sym,
        "company": get_company(sym),
        "timeframe": tf,
        "candles": candle_data,
        "ma44_line": ma_line,
        "current_ma44": ma44[-1] if ma44 else None,
        "cmp": closes[-1] if closes else None,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
