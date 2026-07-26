@echo off
REM ============================================================
REM  A-share (CSI 300) multi-factor stock selection - one-click
REM  Self-contained single script: download quotes/financials
REM    -> 24 factors -> IC-weighted composite -> monthly rebalance
REM    backtest -> output latest holdings
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
echo  A-share multi-factor selection (CSI 300) - akshare
echo ============================================================

REM ------------------------------------------------------------
REM  Selection logic: scripts/select_stocks.py does the whole flow.
REM  Freshness check: read cached panel's latest date; if it is
REM  older than today, force a full re-download (so the latest
REM  trading day is always pulled). Only when the cache is already
REM  up to date do we use --from-panel to skip the slow download.
REM
REM  Notes:
REM  --skip-fund-flow  skips per-stock fund flow (avoids long retries
REM                     when eastmoney rate-limits). Remove to enable.
REM  --top-pct 10      top 10% by composite score (~30 stocks). Tunable.
REM  --start 20230101  backtest/data start date. Tunable.
REM ------------------------------------------------------------

set PANEL=data/factors/select_panel_0stocks.parquet

REM NEED_FULL: 1 = re-download, 0 = cache is current
set NEED_FULL=0
if not exist "%PANEL%" (
    set NEED_FULL=1
) else (
    python -c "import pandas as pd, sys, datetime as dt; d=pd.read_parquet(r'%PANEL%'); sys.exit(0 if d['date'].max().date() >= dt.date.today() else 1)" >nul 2>nul
    if errorlevel 1 set NEED_FULL=1
)

if %NEED_FULL%==1 (
    echo [MODE] Cache missing or stale -> re-calc from db (no live index fetch)
    echo.
    python scripts\select_stocks.py --from-panel "%PANEL%" --index 000300 --max-stocks 0 --top-pct 10
) else (
    echo [MODE] Cache is up to date -> using --from-panel (fast)
    echo.
    python scripts\select_stocks.py --from-panel "%PANEL%" --index 000300 --max-stocks 0 --top-pct 10
)

echo ============================================================
echo  DONE. Result files (under data/factors/):
echo    holdings_YYYYMMDD.csv            latest recommended holdings
echo    equity_000300_10.0pct.csv       net-value curve
echo    select_panel_0stocks.parquet     full factor panel
echo ============================================================
pause
