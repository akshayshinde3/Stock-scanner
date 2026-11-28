@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   NSE Swing Stock Screener - Launcher
echo ============================================

if not exist ".env" (
    echo [ERROR] .env file not found in %cd%
    echo Create a .env file with:
    echo   SITE_PASSWORD=your_password
    echo   APP_SECRET_KEY=your_random_secret
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    pause
    exit /b 1
)

echo Installing/verifying dependencies...
pip install -r requirements.txt --quiet

echo.
echo Starting server at http://localhost:5000
echo Press Ctrl+C to stop.
echo.

start "" http://localhost:5000
python app.py
pause
