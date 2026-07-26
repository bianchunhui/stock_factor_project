# 全量重下沪深300行情数据（baostock源，不限流、全历史、后复权）
#
# 解决两类历史问题：
#   1) akshare 新浪源限流导致部分股票(如 000001)行情被截断
#   2) 旧版 _normalize_sina 未保留 ticker 列，缓存命中后 concat 报 KeyError
#
# 本脚本用 baostock 重下全部 HS300 成分股，并写入与 fetcher/price.py
# get_a_share_daily 完全一致的 cache_key，使后续 select_stocks 直接命中
# 干净缓存、不再触碰新浪限流源。
#
# 用法:
#   cd stock_factor_project
#   python scripts/redownload_prices_baostock.py
from __future__ import annotations

import hashlib
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import baostock as bs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import CACHE_DIR, DEFAULT_START  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def cache_key(*parts) -> str:
    raw = "_".join(str(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def normalize_ticker(t: str) -> str:
    t = str(t).strip()
    if t.startswith(("sh", "sz", "bj", "SH", "SZ", "BJ")):
        t = t[2:]
    if t.isdigit() and len(t) < 6:
        t = t.zfill(6)
    return t


def baostock_code(ticker: str) -> str:
    ticker = normalize_ticker(ticker)
    if ticker.startswith(("60", "68")):
        return f"sh.{ticker}"
    elif ticker.startswith(("00", "30")):
        return f"sz.{ticker}"
    elif ticker.startswith(("83", "87", "43", "88", "92")):
        return f"bj.{ticker}"
    return f"sz.{ticker}"


def fetch_price_baostock(ticker: str, start_date: str, end_date: str,
                         adjust: str = "1") -> pd.DataFrame:
    """baostock 下载日频后复权行情，返回与项目一致的列（含 ticker）。

    baostock adjust: 1=后复权 2=前复权 3=不复权；项目默认 hfq -> "1"
    返回列: date, ticker, open, high, low, close, volume, amount, turnover
    """
    bs_code = baostock_code(ticker)
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,code,open,high,low,close,volume,amount,turn",
        start_date=f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}",
        end_date=f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}",
        frequency="d",
        adjustflag=adjust,
    )
    if str(rs.error_code) != "0":
        raise RuntimeError(f"baostock查询失败 {bs_code}: {rs.error_msg}")
    data = []
    while rs.next():
        data.append(rs.get_row_data())
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=rs.fields)
    df = df.rename(columns={"turn": "turnover"})
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = normalize_ticker(ticker)
    for col in ("open", "high", "low", "close", "volume", "amount", "turnover"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["close"] > 0].copy()
    df = df.sort_values("date").reset_index(drop=True)
    keep = ["date", "ticker", "open", "close", "high", "low",
            "volume", "amount", "turnover"]
    keep = [c for c in keep if c in df.columns]
    return df[keep]


def get_hs300_tickers() -> list[str]:
    """优先用 akshare 取最新成分股；失败则回退到既有因子面板的 ticker。"""
    try:
        import akshare as ak
        df = ak.index_stock_cons_csindex(symbol="000300")
        codes = sorted(df["成分券代码"].astype(str).str.zfill(6).unique().tolist())
        logger.info("HS300 成分股(akshare): %d 只", len(codes))
        return codes
    except Exception as e:
        logger.warning("akshare 取成分股失败(%s)，回退到既有面板", e)
        for f in ("data/factors/select_panel_5stocks.parquet",
                  "data/factors/hs300_full_factor_panel.parquet"):
            p = PROJECT_ROOT / f
            if p.exists():
                try:
                    df = pd.read_parquet(p, columns=["ticker"])
                    codes = sorted(df["ticker"].astype(str).str.zfill(6).unique().tolist())
                    logger.info("HS300 成分股(回退 %s): %d 只", f, len(codes))
                    return codes
                except Exception:
                    continue
        raise RuntimeError("无法获取 HS300 成分股列表")


def main():
    start_date = "20230101"
    end_date = today_str()
    adjust = "1"          # baostock 后复权
    adjust_label = "hfq"  # 与 get_a_share_daily 一致

    logger.info("=" * 60)
    logger.info("HS300 行情全量干净重下 (baostock, 后复权)")
    logger.info("范围: %s ~ %s", start_date, end_date)
    logger.info("=" * 60)

    tickers = get_hs300_tickers()
    total = len(tickers)

    lg = bs.login()
    if str(lg.error_code) != "0" and "success" not in str(lg.error_msg).lower():
        logger.error("baostock 登录失败: %s %s", lg.error_code, lg.error_msg)
        return
    logger.info("baostock 登录成功")

    today_dt = pd.to_datetime(end_date)
    success = failed = 0
    failed_list = []
    truncated_list = []

    try:
        for i, code in enumerate(tickers):
            ok = False
            for attempt in range(2):
                try:
                    df = fetch_price_baostock(code, start_date, end_date, adjust)
                    if df is not None and len(df) > 0:
                        # 完整性校验：末日须接近今日，且行数充足(>700≈3年)
                        last = df["date"].max()
                        if (today_dt - last).days > 5:
                            truncated_list.append((code, str(last.date())))
                            logger.warning("[%d/%d] %s 末日过旧 %s，重试",
                                           i + 1, total, code, last.date())
                            continue
                        if len(df) < 700:
                            truncated_list.append((code, f"{len(df)}行"))
                            logger.warning("[%d/%d] %s 行数偏少 %d，重试",
                                           i + 1, total, code, len(df))
                            continue
                        key = cache_key("ashare", code, start_date, end_date, adjust_label)
                        df.to_parquet(CACHE_DIR / f"{key}.parquet")
                        ok = True
                        break
                except Exception as e:
                    logger.warning("[%d/%d] %s 异常(第%d次): %s",
                                   i + 1, total, code, attempt + 1, e)
                    time.sleep(1)
            if ok:
                success += 1
            else:
                failed += 1
                failed_list.append(code)
            if (i + 1) % 50 == 0:
                logger.info("进度 %d/%d 成功%d 失败%d", i + 1, total, success, failed)
                time.sleep(0.3)
    finally:
        bs.logout()
        logger.info("baostock 已登出")

    logger.info("=" * 60)
    logger.info("重下完成: 成功 %d / 失败 %d / 共 %d", success, failed, total)
    if failed_list:
        logger.warning("失败列表: %s", ",".join(failed_list))
    if truncated_list:
        logger.warning("截断/异常列表(末日或行数不达标): %s",
                       ",".join(f"{c}:{info}" for c, info in truncated_list[:30]))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
