# Stock Screener — Maintenance Guide & Reusable Prompt Script

Use this guide to keep the site running fast and smoothly, and use the copy-paste **Prompt Script** below whenever you want an AI assistant to update strategies, UI, or performance safely.

---

## 1. Quick Changes to Keep the Site Running Smoothly

### A. One-Time Cleanup (Remove Unused Files)
Delete the duplicate FastAPI server (`main.py`) since production uses `app.py` (`Procfile` runs `gunicorn app:app`):
```cmd
cd /d G:\trading
del main.py
```

### B. Environment Variables (Required for Login Security)
Ensure `.env` exists locally (already gitignored) and configure the same keys in your hosting provider (e.g., Render -> Environment):
- `SITE_PASSWORD=<your_password>` (required — server refuses to start without it)
- `APP_SECRET_KEY=<long_random_hex_string>` (recommended so login sessions stay valid across server restarts; generate with `python -c "import secrets; print(secrets.token_hex(32))"`)

### C. Why Stock Loading Was Slow & How to Keep It Fast
1. **Priority Warmup + Progressive Cache**: On a cold start without `candle_cache.json.gz`, the backend now fetches the top 50 liquid stocks first (`max_workers=16`) and flushes scan results immediately (~2–3 seconds) while streaming the remaining Nifty 500 stocks in the background.
2. **Switch to Nifty 50 / Nifty 100 First**: If you want instant results right after deploy, select `Nifty 50` in the Universe dropdown — it finishes downloading first before `Midcap`/`Smallcap`.
3. **Do NOT Spam Refresh**: Clicking `Refresh` forces a live re-download of the entire selected universe from Yahoo Finance (`?refresh=1`). Only click it after market close (post 4:00 PM IST) when you want fresh EOD candles.
4. **Render Persistent Disk (Optional Upgrade)**: On Render Free Tier, local disk resets on every redeploy so `candle_cache.json.gz` is rebuilt on boot. Mounting a persistent disk at `/data` lets `app.py` save `candle_cache.json.gz` across deploys (`PERSISTENT_DIR = "/data"`).
5. **Single Worker + Multi-Thread Gunicorn**: Keep `Procfile` as `web: gunicorn app:app --workers 1 --threads 4 --timeout 120` so all requests share the same in-memory `_daily_cache` instead of duplicating 500 stocks per worker process.

### D. Daily Verification Commands
```cmd
:: 1. Run strategy unit tests
pytest test_patterns.py -v

:: 2. Start website locally (loads .env automatically)
python app.py
```

---

## 2. Reusable AI Prompt Script (Copy & Paste)

Whenever you ask an AI coding assistant to modify this project, paste this prompt and fill in `[YOUR TASK]` at the bottom:

```text
You are working on the NSE Swing Stock Screener repository in G:\trading.

Before editing anything, read ONLY the relevant files:
- Backend server & cache: app.py
- Strategy router: strategies.py
- Pattern configs & detectors: patterns/config.py, patterns/geometry.py, patterns/ascending_triangle.py, patterns/symmetrical_triangle.py, patterns/pole_and_flag.py
- UI templates: templates/dashboard.html, templates/login.html
- Unit tests: test_patterns.py

Strict Project Rules:
1. Primary backend is Flask (`app.py`) deployed via `Procfile` (`gunicorn app:app --workers 1 --threads 4 --timeout 120`). Do not recreate duplicate backends.
2. Never hardcode passwords or fallback secret keys in Python source; read `SITE_PASSWORD` and `APP_SECRET_KEY` from environment / `.env`.
3. Keep all pattern rules deterministic and uninflated (`Target = Entry + Pattern Height`, strict minimum R:R checks in `patterns/config.py`).
4. Keep the UI clean light theme (`#ffffff` background, crisp slate text `#1e293b`, tabular numbers for prices/ratios, dark theme ONLY inside the TradingView chart modal, zero decorative emojis).
5. Preserve non-blocking background Yahoo Finance fetching with thread-safe `_cache_lock` / `_batch_lock` and gzip response compression.
6. After making changes, run `pytest test_patterns.py -v` and verify syntax/endpoints before finishing.

[YOUR TASK]:
Describe exactly what you want added, changed, or fixed here (e.g., "Add a minimum volume filter to 44 MA scanner", "Adjust Symmetrical Triangle R:R from 2.5 to 3.0", "Add RSI column to the results table").
```
