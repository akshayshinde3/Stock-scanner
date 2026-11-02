import os
import gzip
import json
import datetime as dt
from app import evaluate_symbol, evaluate_symbol_weekly, passes_liquidity_filter, load_candle_cache_from_disk, STATE
from excel_export import create_prebreakout_excel


def generate_excel_file_on_disk(output_path="PreBreakout_Stocks.xlsx"):
    load_candle_cache_from_disk()
    
    daily_watch = STATE.get("watch_alerts", [])
    weekly_watch = STATE.get("weekly_watch_alerts", [])
    confirmed_daily = STATE.get("confirmed_alerts", [])
    confirmed_weekly = STATE.get("weekly_confirmed_alerts", [])

    # If STATE is empty, scan candle cache
    if not daily_watch and not weekly_watch:
        cache_file = os.path.join(os.path.dirname(__file__), "candle_cache.json.gz")
        if os.path.exists(cache_file):
            with gzip.open(cache_file, "rt") as f:
                c_data = json.load(f)
            d_cache = c_data.get("daily", {})
            w_cache = c_data.get("weekly", {})
            
            for sym, candles in d_cache.items():
                if candles:
                    res = evaluate_symbol(sym, candles, candles[-1][4])
                    if res:
                        if res["status"] == "pre_breakout_watch":
                            daily_watch.append(res)
                        elif res["status"] == "confirmed":
                            confirmed_daily.append(res)
            for sym, candles in w_cache.items():
                if candles and passes_liquidity_filter(d_cache.get(sym, [])):
                    w_res = evaluate_symbol_weekly(sym, candles, candles[-1][4])
                    if w_res:
                        if w_res["status"] == "pre_breakout_watch":
                            weekly_watch.append(w_res)
                        elif w_res["status"] == "confirmed":
                            confirmed_weekly.append(w_res)

    wb = create_prebreakout_excel(daily_watch, weekly_watch, confirmed_daily, confirmed_weekly)
    wb.save(output_path)
    print(f"✅ Successfully generated Excel sheet: {output_path}")
    print(f"   Daily Pre-Breakouts: {len(daily_watch)}")
    print(f"   Weekly Pre-Breakouts: {len(weekly_watch)}")
    return output_path


if __name__ == "__main__":
    generate_excel_file_on_disk()
