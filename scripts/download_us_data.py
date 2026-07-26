"""美股数据下载脚本（道指 30 成分股）。

数据源（akshare，均从本地网络发出请求）：
  1. stock_us_spot_em()        东方财富美股实时行情 → 取每只股票的 EM 代码(105.AAPL)
                               + 实时 市盈率/总市值（用于兜底与交叉校验）
  2. stock_us_hist(code,...)   东方财富美股日线（前复权 qfq）→ 价格面板
  3. stock_us_valuation_baidu 百度股市通美股估值时间序列
                               （总市值 / 市盈率(TTM) / 市净率 / 市现率）→ 估值面板

产出：
  data/us_panel_price.parquet      columns: date, ticker, open, high, low, close, volume, amount
  data/us_panel_valuation.parquet  columns: date, ticker, market_cap, pe_ttm, pb, pcf

缓存：
  每个 ticker 的行情/估值分别缓存到 data/cache/us_price_<TICKER>.parquet /
  us_val_<TICKER>.parquet；已缓存且末日较新则跳过。--force 强制重下。

注意：
  - 本脚本联网；sandbox 出口被限时会失败，需在本地正常网络运行。
  - EM 代码前缀：105=NYSE, 106=NASDAQ, 107=AMEX；spot_em 返回精确值，
    仅当 spot_em 不可达时才用内置兜底映射（可能不准，会尝试切换前缀）。
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

PRICE_OUT = "data/us_panel_price.parquet"  # 兼容占位（实际存 us.db）
VAL_OUT = "data/us_panel_valuation.parquet"

START_DATE = "20200101"
END_DATE = datetime.now().strftime("%Y%m%d")

# EM 代码兜底（仅 spot_em 不可达时使用）；105=NYSE, 106=NASDAQ
EM_CODE_FALLBACK = {
    "CSCO": "106.CSCO", "AXP": "105.AXP", "GS": "105.GS", "JPM": "105.JPM",
    "UNH": "105.UNH", "AMZN": "106.AMZN", "HON": "106.HON", "AAPL": "106.AAPL",
    "HD": "105.HD", "SHW": "105.SHW", "MMM": "105.MMM", "MSFT": "106.MSFT",
    "V": "105.V", "TRV": "105.TRV", "NKE": "105.NKE", "DIS": "105.DIS",
    "MCD": "105.MCD", "NVDA": "106.NVDA", "MRK": "105.MRK", "WMT": "105.WMT",
    "BA": "105.BA", "GOOGL": "106.GOOG" if False else "106.GOOGL", "KO": "105.KO",
    "CAT": "105.CAT", "PG": "105.PG", "CVX": "105.CVX", "AMGN": "106.AMGN",
    "JNJ": "105.JNJ", "IBM": "105.IBM", "CRM": "105.CRM",
}

VAL_INDICATORS = {
    "market_cap": "总市值",
    "pe_ttm": "市盈率(TTM)",
    "pb": "市净率",
    "pcf": "市现率",
}


def _load_cache(prefix: str, ticker: str):
    table = "daily_price" if prefix == "us_price" else "valuation"
    df = query(
        f"SELECT * FROM {table} WHERE ticker=? AND date>=? AND date<=?",
        [ticker, START_DATE, END_DATE], market="us",
    )
    return df if not df.empty else None


def _save_cache(prefix: str, ticker: str, df: pd.DataFrame):
    if df is None or df.empty:
        return
    table = "daily_price" if prefix == "us_price" else "valuation"
    conn = get_conn("us")
    upsert(df, table, ["ticker", "date"], conn)
    conn.close()


def fetch_em_code_map(universe: pd.DataFrame) -> dict:
    """返回 ticker(upper) -> EM代码(如 105.AAPL)。

    优先用 stock_us_spot_em 的 代码 字段精确匹配；失败则用兜底映射。
    """
    want = set(universe["ticker"].str.upper())
    code_map: dict[str, str] = {}
    try:
        import akshare as ak
        spot = ak.stock_us_spot_em()
        # 代码 = 编码.简称，简称即纯 ticker
        for _, r in spot.iterrows():
            code = str(r.get("代码", ""))
            if "." in code:
                plain = code.split(".", 1)[1].upper()
                if plain in want:
                    code_map[plain] = code
        print(f"  [spot_em] 匹配到 {len(code_map)}/{len(want)} 只 EM 代码")
    except Exception as e:
        print(f"  [spot_em] 获取失败（{type(e).__name__}），改用兜底映射: {e}")

    # 兜底补缺失
    for t in want:
        if t not in code_map:
            code_map[t] = EM_CODE_FALLBACK.get(t, f"105.{t}")
    return code_map


def download_price(ticker: str, em_code: str, force: bool) -> pd.DataFrame | None:
    """下载单只美股日线（前复权）。缓存优先。"""
    if not force:
        cached = _load_cache("us_price", ticker)
        if cached is not None and not cached.empty:
            return cached

    import akshare as ak
    # 尝试 em_code；若返回空，尝试切换 NYSE/NASDAQ 前缀
    for code in (em_code, _swap_prefix(em_code)):
        try:
            df = ak.stock_us_hist(
                symbol=code, period="daily",
                start_date=START_DATE, end_date=END_DATE, adjust="qfq",
            )
        except Exception as e:
            print(f"    [WARN] {ticker} hist({code}) 异常: {e}")
            continue
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
            })
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            df["ticker"] = ticker
            for c in ("open", "high", "low", "close", "volume", "amount"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df[["date", "ticker", "open", "high", "low", "close", "volume", "amount"]]
            _save_cache("us_price", ticker, df)
            return df
    print(f"    [WARN] {ticker} 行情为空（{em_code} 及切换前缀均失败）")
    return None


def _swap_prefix(em_code: str) -> str:
    if "." not in em_code:
        return em_code
    pre, tick = em_code.split(".", 1)
    alt = "106" if pre == "105" else "105"
    return f"{alt}.{tick}"


def download_valuation(ticker: str, force: bool) -> pd.DataFrame | None:
    """下载单只美股估值时间序列（总市值/PE_TTM/PB/PCF）。缓存优先。"""
    if not force:
        cached = _load_cache("us_val", ticker)
        if cached is not None and not cached.empty:
            return cached

    import akshare as ak
    frames = []
    for col, indicator in VAL_INDICATORS.items():
        try:
            s = ak.stock_us_valuation_baidu(symbol=ticker, indicator=indicator, period="全部")
            if s is not None and not s.empty:
                s = s.rename(columns={"date": "date", "value": col})
                s["date"] = pd.to_datetime(s["date"]).dt.normalize()
                s[col] = pd.to_numeric(s[col], errors="coerce")
                s = s[["date", col]]
                frames.append(s.set_index("date"))
            time.sleep(0.3)
        except Exception as e:
            print(f"    [WARN] {ticker} 估值({indicator}) 异常: {e}")
            time.sleep(0.3)

    if not frames:
        print(f"    [WARN] {ticker} 估值全部失败")
        return None

    out = pd.concat(frames, axis=1).reset_index()
    out["ticker"] = ticker
    out = out[["date", "ticker", "market_cap", "pe_ttm", "pb", "pcf"]]
    _save_cache("us_val", ticker, out)
    return out


def main():
    ap = argparse.ArgumentParser(description="下载道指 30 美股行情与估值")
    ap.add_argument("start_date", nargs="?", default=None,
                    help="开始日期 YYYYMMDD, 默认从配置取")
    ap.add_argument("end_date", nargs="?", default=None,
                    help="结束日期 YYYYMMDD, 默认当日")
    ap.add_argument("--universe", default="data/dj_universe_20260710.csv")
    ap.add_argument("--force", action="store_true", help="忽略缓存强制重下")
    ap.add_argument("--only", default=None, help="只下载指定 ticker（逗号分隔），调试用")
    args = ap.parse_args()

    # Override global date range from CLI args
    global START_DATE, END_DATE
    if args.start_date:
        START_DATE = args.start_date
    if args.end_date:
        END_DATE = args.end_date

    if not Path(args.universe).exists():
        print(f"[ERROR] universe 文件不存在: {args.universe}")
        return 1

    uni = pd.read_csv(args.universe, dtype={"ticker": str})
    uni["ticker"] = uni["ticker"].str.upper()
    if args.only:
        keep = [t.strip().upper() for t in args.only.split(",")]
        uni = uni[uni["ticker"].isin(keep)]
    print(f"Universe: {len(uni)} 只 | 区间 {START_DATE}~{END_DATE}")

    code_map = fetch_em_code_map(uni)

    price_frames, val_frames = [], []
    for _, r in uni.iterrows():
        t = r["ticker"]
        print(f"  -> {t} ({r.get('name','')})")
        p = download_price(t, code_map.get(t, f"105.{t}"), args.force)
        if p is not None:
            price_frames.append(p)
        v = download_valuation(t, args.force)
        if v is not None:
            val_frames.append(v)
        time.sleep(0.3)

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
