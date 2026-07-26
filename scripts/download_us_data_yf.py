"""美股数据下载 (yfinance 版, 道指 30 成分股)。

相比 akshare 版：yfinance 走雅虎，对个人宽带 IP 通常不被限流
（akshare 美股接口走东财/百度，常不稳定或限流）。沙箱里雅虎也限流，
故需在本地正常网络运行。

产出格式与 scripts/download_us_data.py 完全一致，复用下游：
  data/us_panel_price.parquet      date,ticker,open,high,low,close,volume,amount
  data/us_panel_valuation.parquet  date,ticker,market_cap,pe_ttm,pb,pcf

估值说明：
  - 市值序列 = 历史收盘价 x 最新流通股数
  - 用快照 PE/PB/经营现金流 反推 TTM 盈利/净资产/现金流，得到 EP/BP/CFP 序列
    (横截面选股可用近似；美股无财报接口，无法做精确 TTM)
  - amount(成交额) yfinance 不直接提供，填 NaN（美股 pipeline 无 turnover 因子）
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from fetcher.store.db import get_conn, upsert, query

PRICE_OUT = Path("data/us_panel_price.parquet")  # 兼容占位（实际存 us.db）
VAL_OUT = Path("data/us_panel_valuation.parquet")
START_DATE = "2020-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")


def _load_cache(prefix: str, ticker: str):
    table = "daily_price" if prefix == "us_price" else "valuation"
    # yfinance 用 '-' 日期；db 内存的是 ISO，范围用宽松匹配
    df = query(
        f"SELECT * FROM {table} WHERE ticker=?", [ticker], market="us",
    )
    return df if not df.empty else None


def _save_cache(prefix: str, ticker: str, df: pd.DataFrame):
    if df is None or df.empty:
        return
    table = "daily_price" if prefix == "us_price" else "valuation"
    conn = get_conn("us")
    upsert(df, table, ["ticker", "date"], conn)
    conn.close()


def _safe(obj, *keys, default=np.nan):
    """从 dict 或对象取第一个存在的数值字段。"""
    for k in keys:
        if isinstance(obj, dict):
            v = obj.get(k)
        else:
            v = getattr(obj, k, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
    return default


def download_prices(tickers, force):
    import yfinance as yf

    frames = []
    for t in tickers:
        if not force:
            c = _load_cache("us_price", t)
            if c is not None and not c.empty:
                frames.append(c)
                continue
        try:
            h = yf.Ticker(t).history(start=START_DATE, end=END_DATE, auto_adjust=True)
        except Exception as e:
            print(f"    [WARN] {t} price fetch failed: {e}")
            c = _load_cache("us_price", t)
            if c is not None and not c.empty:
                frames.append(c)
            continue
        if h is None or h.empty:
            print(f"    [WARN] {t} price empty")
            continue
        h = h.reset_index()
        h["ticker"] = t
        date_col = h.columns[0]  # 原 DatetimeIndex（名字可能是 Date/index/Price）
        h = h.rename(columns={
            date_col: "date", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume",
        })
        h["amount"] = np.nan
        h["date"] = pd.to_datetime(h["date"]).dt.normalize()
        for c in ("open", "high", "low", "close", "volume"):
            h[c] = pd.to_numeric(h[c], errors="coerce")
        h = h[["date", "ticker", "open", "high", "low", "close", "volume", "amount"]]
        _save_cache("us_price", t, h)
        frames.append(h)
        time.sleep(0.1)
    return frames


def download_valuations(tickers, force):
    import yfinance as yf

    frames = []
    for t in tickers:
        if not force:
            c = _load_cache("us_val", t)
            if c is not None and not c.empty:
                frames.append(c)
                continue
        try:
            tk = yf.Ticker(t)
            h = tk.history(start=START_DATE, end=END_DATE, auto_adjust=True)
        except Exception as e:
            print(f"    [WARN] {t} valuation fetch failed: {e}")
            c = _load_cache("us_val", t)
            if c is not None and not c.empty:
                frames.append(c)
            continue
        if h is None or h.empty:
            print(f"    [WARN] {t} valuation empty (no price)")
            continue

        info = {}
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        fi = getattr(tk, "fast_info", None)

        shares = _safe(info, "sharesOutstanding") or _safe(fi, "shares")
        mcap_now = _safe(info, "marketCap") or _safe(fi, "market_cap")
        pe = _safe(info, "trailingPE") or _safe(info, "forwardPE")
        pb = _safe(info, "priceToBook")
        cfo = _safe(info, "operatingCashflow")

        close = pd.to_numeric(h["Close"], errors="coerce").astype(float)
        dates = pd.to_datetime(h.index).normalize()
        mcap_t = close * shares if (shares == shares and shares) else np.nan
        earnings_ttm = (mcap_now / pe) if (mcap_now == mcap_now and pe == pe and pe) else np.nan
        equity = (mcap_now / pb) if (mcap_now == mcap_now and pb == pb and pb) else np.nan
        pe_ttm = mcap_t / earnings_ttm if (earnings_ttm == earnings_ttm and earnings_ttm) else np.nan
        pb_t = mcap_t / equity if (equity == equity and equity) else np.nan
        pcf = mcap_t / cfo if (cfo == cfo and cfo) else np.nan

        val = pd.DataFrame({
            "date": dates, "ticker": t,
            "market_cap": mcap_t, "pe_ttm": pe_ttm, "pb": pb_t, "pcf": pcf,
        })
        val = val[["date", "ticker", "market_cap", "pe_ttm", "pb", "pcf"]]
        _save_cache("us_val", t, val)
        frames.append(val)
        time.sleep(0.2)
    return frames


def main():
    ap = argparse.ArgumentParser(description="下载道指30美股 (yfinance)")
    ap.add_argument("--universe", default="data/dj_universe_20260710.csv")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    if not Path(args.universe).exists():
        print(f"[ERROR] universe missing: {args.universe}")
        return 1
    uni = pd.read_csv(args.universe, dtype={"ticker": str})
    uni["ticker"] = uni["ticker"].str.upper()
    if args.only:
        keep = [x.strip().upper() for x in args.only.split(",")]
        uni = uni[uni["ticker"].isin(keep)]
    tickers = uni["ticker"].tolist()
    print(f"Universe: {len(tickers)} | {START_DATE}~{END_DATE} (yfinance)")

    pf = download_prices(tickers, args.force)
    vf = download_valuations(tickers, args.force)

    # 汇总（全部从 us.db 读取，已含历史 + 本次新增）
    conn = get_conn("us")
    try:
        for tbl in ("daily_price", "valuation"):
            try:
                n, nt = conn.execute(
                    f'SELECT COUNT(*), COUNT(DISTINCT ticker) FROM "{tbl}"'
                ).fetchone()
                print(f"[OK] us.db.{tbl}: {n} 行 / {nt} 只")
            except Exception as e:
                print(f"[WARN] us.db.{tbl} 统计失败: {e}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
