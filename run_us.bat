@echo off
REM ============================================================
REM  US stock selection one-click runner (Dow 30 constituents)
REM  Uses yfinance (Yahoo) - more reliable than akshare for US stocks
REM  Double-click to run the full pipeline on your local machine
REM  Requires: python in PATH, with akshare / pandas / scipy / yfinance
REM ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH. Install Python, then: pip install akshare pandas scipy yfinance
    pause
    exit /b 1
)

python -c "import yfinance" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] yfinance not installed. Run: pip install yfinance
    pause
    exit /b 1
)

echo ============================================================
echo  US stock pipeline (Dow 30) - yfinance
echo ============================================================
echo [1/4] build universe
python scripts\build_dj_universe.py

REM Freshness check: if the price panel is missing or older than today,
REM force a full re-download (--force) so the latest trading day is pulled.
REM Otherwise reuse the cache for speed.
set PANEL=data/us_panel_price.parquet
set FORCE_FLAG=
if not exist "%PANEL%" (
    set FORCE_FLAG=--force
) else (
    python -c "import pandas as pd, sys, datetime as dt; d=pd.read_parquet(r'%PANEL%'); sys.exit(0 if str(d['date'].max().date()) >= str(dt.date.today()) else 1)" >nul 2>nul
    if errorlevel 1 set FORCE_FLAG=--force
)

echo [2/4] download price + valuation (yfinance, needs internet) %FORCE_FLAG%
python scripts\download_us_data_yf.py %FORCE_FLAG%

echo [3/4] compute factors
python scripts\run_us_factor_calc.py

echo [4/4] composite + backtest + select
python scripts\build_composite_us.py

echo ============================================================
echo  DONE. Result files:
echo    data/factors/us_top10_equal_weight.csv
echo    data/factors/us_top10_ic_weight.csv
echo    data/factors/us_nav_*.csv
echo ============================================================
pause
