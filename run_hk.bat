@echo off
REM ============================================================
REM  HK stocks (HSI cap Stock Connect, 88 names) multi-factor
REM  selection - one-click
REM  3-stage pipeline:
REM    1) download_hk_data.py      download quotes/financials/southbound
REM                                 holdings (akshare, cached)
REM    2) run_hk_factor_calc.py    compute factors -> hk_full_factor_panel.parquet
REM    3) build_composite_hk.py    composite + backtest + select -> Top20
REM  Double-click to run the full pipeline. Requires local python
REM  in PATH, with akshare/pandas/scipy/numpy installed.
REM ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH. Install Python 3.10+ and add python.exe to PATH.
    echo          Then run: pip install akshare pandas scipy numpy
    pause
    exit /b 1
)

python -c "import akshare" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] akshare not installed. Run: pip install akshare pandas scipy numpy
    pause
    exit /b 1
)

echo ============================================================
echo  HK multi-factor selection (HSI cap Stock Connect, 88) - akshare
echo ============================================================

REM ------------------------------------------------------------
REM  Freshness check: read cached price panel's latest date; if it
REM  is older than today, force a full re-download (so the latest
REM  trading day is always pulled). Only when the panel is already
REM  up to date do we skip the slow download and go straight to
REM  factor computation.
REM ------------------------------------------------------------

set PANEL=data/hk_panel_price.parquet

REM NEED_FULL: 1 = re-download, 0 = panel is current
set NEED_FULL=0
if not exist "%PANEL%" (
    set NEED_FULL=1
) else (
    python -c "import pandas as pd, sys, datetime as dt; d=pd.read_parquet(r'%PANEL%'); sys.exit(0 if d['date'].max().date() >= dt.date.today() else 1)" >nul 2>nul
    if errorlevel 1 set NEED_FULL=1
)

if %NEED_FULL%==1 (
    echo [1/3] Panel missing or stale -> downloading HK quotes/financials/southbound (slow)
    python scripts\download_hk_data.py
) else (
    echo [1/3] Panel up to date -> skipping download
)

echo [2/3] Computing HK factors -> data/hk_full_factor_panel.parquet
python scripts\run_hk_factor_calc.py

echo [3/3] Composite + backtest + selection -> Top20
python scripts\build_composite_hk.py

echo ============================================================
echo  DONE. Result files (under data/factors/):
echo    hk_top20_equal_weight.csv        equal-weight Top20 holdings
echo    hk_top20_ic_weight.csv           IC-weight Top20 holdings
echo    hk_nav_equal_weight.csv          equal-weight net value
echo    hk_nav_ic_weight.csv             IC-weight net value
echo    hk_composite_factor.parquet      composite factor panel
echo ============================================================
pause
