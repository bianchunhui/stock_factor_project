"""港股 88 只标的池批量下载：行情 + 财务指标 + 南向持股。

标的池: data/hsi_hkgt_universe_20260709.csv (88 stocks) 或 db(ref_universe, market='HK')
数据源:
  - 行情: stock_hk_daily (sina, qfq + hfq)
  - 基准: stock_hk_index_daily_sina (HSI)
  - 财务指标: stock_financial_hk_analysis_indicator_em (年度+季度)
  - 财报: stock_financial_hk_report_em (利润表/资产负债表/现金流量表)
  - 南向持股: stock_hsgt_individual_em (港股代码查南向持股历史)

存储: 全部走 SQLite (hk.db)
  - 行情/指数 -> daily_price (ticker, date)
  - 财务指标   -> financial_indicator (ticker, report_date)
  - 南向持股   -> ref_hsgt (ticker, date)
增量更新：已有数据从 db 读、不重抓；只有新片段 INSERT OR REPLACE 入库。
"""
import sys, os, time, re, logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import akshare as ak

# ---- logging (ASCII safe for GBK console) ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

from fetcher.store.db import get_conn, upsert, query

UNIVERSE_FILE = "data/hsi_hkgt_universe_20260709.csv"
START_DATE = "20210101"
# END_DATE is dynamic (today) so every run pulls up to the latest trading day.
END_DATE = time.strftime("%Y%m%d")

# Override from CLI: python download_hk_data.py [start_date] [end_date]
if len(sys.argv) >= 2:
    START_DATE = sys.argv[1]
if len(sys.argv) >= 3:
    END_DATE = sys.argv[2]


# ================================================================
# db-backed 缓存层（替代散落 parquet）
# ================================================================
def _hk_conn():
    return get_conn("hk")


def _is_coverage_complete(df: pd.DataFrame | None, max_gap_days: int = 3) -> bool:
    """Check if cached data covers through END_DATE (allow small gap for weekends/holidays).

    Handles both 'date' (price/HSGT) and 'report_date' (financial) column names.
    """
    if df is None or df.empty:
        return False
    try:
        date_col = "date" if "date" in df.columns else "report_date"
        last = pd.to_datetime(df[date_col].max()).date()
        target = datetime.strptime(END_DATE, "%Y%m%d").date()
        return (target - last).days <= max_gap_days
    except Exception:
        return False


def load_hk_price(ticker: str) -> pd.DataFrame | None:
    df = query(
        "SELECT * FROM daily_price WHERE ticker=? AND date>=? AND date<=?",
        [ticker, START_DATE, END_DATE], market="hk",
    )
    # Only accept as "cached" if data reaches near END_DATE (fresh enough)
    if _is_coverage_complete(df):
        return df
    return None  # stale or missing → trigger re-download


def save_hk_price(df: pd.DataFrame) -> None:
    if df is None or len(df) == 0:
        return
    conn = _hk_conn()
    upsert(df, "daily_price", ["ticker", "date"], conn)
    conn.close()


def download_hk_price(ticker, adjust="qfq"):
    """Download HK daily price via sina, with db cache."""
    cached = load_hk_price(ticker)
    if cached is not None:
        return cached, True
    try:
        raw = ak.stock_hk_daily(symbol=ticker, adjust=adjust)
        if raw is None or len(raw) == 0:
            return pd.DataFrame(), False
        df = raw.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df = df[(df["date"] >= pd.to_datetime(START_DATE)) &
                (df["date"] <= pd.to_datetime(END_DATE))]
        df["ticker"] = ticker
        for c in ("open", "high", "low", "close", "volume", "amount"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        save_hk_price(df)
        return df, False
    except Exception as e:
        log.warning(f"  price FAIL {ticker} ({adjust}): {type(e).__name__}: {e}")
        return pd.DataFrame(), False


# ================================================================
# 3. HK benchmark (HSI)
# ================================================================
def load_hsi_index() -> pd.DataFrame:
    df = query(
        "SELECT * FROM daily_price WHERE ticker=? AND date>=? AND date<=?",
        ["HSI", START_DATE, END_DATE], market="hk",
    )
    if _is_coverage_complete(df):
        return df
    return pd.DataFrame()


def download_hsi_index() -> pd.DataFrame:
    cached = load_hsi_index()
    if not cached.empty:
        return cached
    # stock_hk_index_daily_sina has a bug in this akshare version (KeyError 'date')
    # Fallback: use stock_zh_index_daily with hkHSI, or manual approach
    try:
        raw = ak.stock_zh_index_daily(symbol="hkHSI")
        df = raw.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        for c in ("open", "high", "low", "close", "volume"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[(df["date"] >= pd.to_datetime(START_DATE)) &
                (df["date"] <= pd.to_datetime(END_DATE))]
        df["ticker"] = "HSI"
        df = df.sort_values("date").reset_index(drop=True)
        save_hk_price(df)
        return df
    except Exception as e:
        log.warning(f"HSI index via stock_zh_index_daily failed: {e}")
        try:
            log.info("  Falling back to 02800 (Tracker Fund) as HSI proxy")
            raw = ak.stock_hk_daily(symbol="02800", adjust="qfq")
            df = raw.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            for c in ("open", "high", "low", "close", "volume"):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df[(df["date"] >= pd.to_datetime(START_DATE)) &
                    (df["date"] <= pd.to_datetime(END_DATE))]
            df["ticker"] = "HSI_PROXY_02800"
            df = df.sort_values("date").reset_index(drop=True)
            save_hk_price(df)
            return df
        except Exception as e2:
            log.error(f"HSI proxy also failed: {e2}")
            return pd.DataFrame()


# ================================================================
# 4. Financial indicators (stock_financial_hk_analysis_indicator_em)
# ================================================================
def load_hk_financial(ticker: str) -> pd.DataFrame:
    df = query(
        "SELECT * FROM financial_indicator WHERE ticker=?", [ticker], market="hk"
    )
    if _is_coverage_complete(df, max_gap_days=120):
        return df
    return pd.DataFrame()


def download_hk_financial(ticker):
    """Download HK financial indicators (annual + quarterly)."""
    cached = load_hk_financial(ticker)
    if not cached.empty:
        return cached, True
    all_dfs = []
    for indicator in ["年度", "报告期"]:
        try:
            df = ak.stock_financial_hk_analysis_indicator_em(symbol=ticker, indicator=indicator)
            if df is not None and len(df) > 0:
                all_dfs.append(df)
        except Exception as e:
            log.warning(f"  fin FAIL {ticker} ({indicator}): {type(e).__name__}")
        time.sleep(0.3)
    if not all_dfs:
        return pd.DataFrame(), False
    combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates(subset=["REPORT_DATE"])
    combined["ticker"] = ticker
    combined["REPORT_DATE"] = pd.to_datetime(combined["REPORT_DATE"], errors="coerce")
    col_map = {
        "SECURITY_CODE": "ticker_code",
        "REPORT_DATE": "report_date",
        "DATE_TYPE_CODE": "date_type",
        "BASIC_EPS": "basic_eps",
        "DILUTED_EPS": "diluted_eps",
        "BPS": "bps",
        "PER_NETCASH_OPERATE": "ocf_per_share",
        "OPERATE_INCOME": "total_revenue",
        "OPERATE_INCOME_YOY": "revenue_yoy",
        "GROSS_PROFIT": "gross_profit",
        "GROSS_PROFIT_YOY": "gross_profit_yoy",
        "HOLDER_PROFIT": "holder_profit",
        "HOLDER_PROFIT_YOY": "holder_profit_yoy",
        "GROSS_PROFIT_RATIO": "gross_margin",
        "EPS_TTM": "eps_ttm",
        "OPERATE_INCOME_QOQ": "revenue_qoq",
    }
    combined = combined.rename(columns={k: v for k, v in col_map.items() if k in combined.columns})
    conn = _hk_conn()
    upsert(combined, "financial_indicator", ["ticker", "report_date"], conn)
    conn.close()
    return combined, False


# ================================================================
# 5. Southbound holding (stock_hsgt_individual_em for HK stocks)
# ================================================================
def load_south_holding(ticker: str) -> pd.DataFrame:
    df = query(
        "SELECT * FROM ref_hsgt WHERE ticker=?", [ticker], market="hk"
    )
    if _is_coverage_complete(df):
        return df
    return pd.DataFrame()


def download_south_holding(ticker):
    """Download southbound (港股通) holding history for a HK stock."""
    cached = load_south_holding(ticker)
    if not cached.empty:
        return cached, True
    try:
        df = ak.stock_hsgt_individual_em(symbol=ticker)
        if df is None or len(df) == 0:
            return pd.DataFrame(), False
        col_map = {
            "持股日期": "date",
            "当日收盘价": "close_price",
            "当日涨跌幅": "change_pct",
            "持股数量": "holding_shares",
            "持股市值": "holding_value",
            "持股数量占A股百分比": "holding_pct",
            "今日增持股数": "share_change",
            "今日增持资金": "fund_change",
            "今日持股市值变化": "value_change",
        }
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["ticker"] = ticker
        for c in ["close_price", "change_pct", "holding_shares", "holding_value",
                  "holding_pct", "share_change", "fund_change", "value_change"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        conn = _hk_conn()
        upsert(df, "ref_hsgt", ["ticker", "date"], conn)
        conn.close()
        return df, False
    except Exception as e:
        log.warning(f"  hsgt FAIL {ticker}: {type(e).__name__}")
        return pd.DataFrame(), False


# ================================================================
# 0. Load universe
# ================================================================
def load_universe_tickers() -> list:
    try:
        from fetcher.store.db import load_universe
        uni = load_universe("hk")
        if uni is not None and not uni.empty:
            tickers = uni["ticker"].astype(str).tolist()
            log.info(f"Universe: {len(tickers)} HK stocks from db(ref_universe)")
            return tickers
    except Exception as e:
        log.warning(f"db universe load failed: {e}")
    universe = pd.read_csv(UNIVERSE_FILE, dtype={"ticker": str})
    tickers = universe["ticker"].tolist()
    log.info(f"Universe: {len(tickers)} HK stocks from {UNIVERSE_FILE}")
    return tickers


# ================================================================
# MAIN: batch download all 88 stocks
# ================================================================
if __name__ == "__main__":
    tickers = load_universe_tickers()
    log.info("=" * 60)
    log.info("HK Stock Batch Download (SQLite)")
    log.info(f"  Universe: {len(tickers)} stocks")
    log.info(f"  Date range: {START_DATE} ~ {END_DATE}")
    log.info("=" * 60)

    # --- HSI benchmark ---
    log.info("[1/4] Downloading HSI benchmark...")
    hsi = download_hsi_index()
    if len(hsi) > 0:
        log.info(f"  HSI: {len(hsi)} rows, {hsi['date'].min()} ~ {hsi['date'].max()}")
    else:
        log.warning("  HSI benchmark download failed, continuing without it")

    # --- Price (qfq) ---
    log.info(f"[2/4] Downloading HK prices (qfq) for {len(tickers)} stocks...")
    ok, cached, fail = 0, 0, 0
    for i, t in enumerate(tickers, 1):
        df, was_cached = download_hk_price(t, adjust="qfq")
        if len(df) > 0:
            ok += 1
            if was_cached:
                cached += 1
        else:
            fail += 1
        if i % 10 == 0 or i == len(tickers):
            log.info(f"  [{i}/{len(tickers)}] ok={ok} (cached={cached}) fail={fail}")
        if not was_cached:
            time.sleep(0.3)

    # --- Financial indicators ---
    log.info(f"[3/4] Downloading HK financials for {len(tickers)} stocks...")
    ok, cached, fail = 0, 0, 0
    for i, t in enumerate(tickers, 1):
        df, was_cached = download_hk_financial(t)
        if len(df) > 0:
            ok += 1
            if was_cached:
                cached += 1
        else:
            fail += 1
        if i % 10 == 0 or i == len(tickers):
            log.info(f"  [{i}/{len(tickers)}] ok={ok} (cached={cached}) fail={fail}")
        if not was_cached:
            time.sleep(0.5)

    # --- Southbound holdings ---
    log.info(f"[4/4] Downloading southbound holdings for {len(tickers)} stocks...")
    ok, cached, fail = 0, 0, 0
    for i, t in enumerate(tickers, 1):
        df, was_cached = download_south_holding(t)
        if len(df) > 0:
            ok += 1
            if was_cached:
                cached += 1
        else:
            fail += 1
        if i % 10 == 0 or i == len(tickers):
            log.info(f"  [{i}/{len(tickers)}] ok={ok} (cached={cached}) fail={fail}")
        if not was_cached:
            time.sleep(0.3)

    # --- Summary (from db) ---
    conn = _hk_conn()
    cur = conn.cursor()
    for tbl in ("daily_price", "financial_indicator", "ref_hsgt"):
        try:
            cur.execute(f'SELECT COUNT(*), COUNT(DISTINCT ticker) FROM "{tbl}"')
            n, nt = cur.fetchone()
            log.info(f"  {tbl}: {n} rows / {nt} tickers")
        except Exception as e:
            log.info(f"  {tbl}: ERR {e}")
    conn.close()
    log.info("=" * 60)
    log.info("DONE. All data in hk.db (SQLite).")
    log.info("=" * 60)
