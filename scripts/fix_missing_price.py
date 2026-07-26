# 补下沪深300缺失行情数据（baostock源，不限流）
#
# 原理：
# 1. 扫描已有 parquet 缓存，提取已下载行情的 ticker 列表
# 2. 从 akshare 获取沪深300最新成分股
# 3. 对缺失的 ticker 用 baostock 下载日频后复权行情
# 4. 保存为与项目一致的 parquet 缓存（使用相同的 cache_key 格式）
#
# 用法:
#   cd stock_factor_project
#   python scripts/fix_missing_price.py
from __future__ import annotations

import hashlib
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import baostock as bs

from config.settings import CACHE_DIR, DEFAULT_START

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 复用项目的 cache_key 逻辑
def cache_key(*parts) -> str:
    raw = "_".join(str(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def normalize_ticker(t: str) -> str:
    """规范化为6位数字代码。"""
    t = str(t).strip()
    if t.startswith(("sh", "sz", "bj", "SH", "SZ", "BJ")):
        t = t[2:]
    if t.isdigit() and len(t) < 6:
        t = t.zfill(6)
    return t


def scan_existing_price_tickers(cache_dir: Path) -> set[str]:
    """扫描缓存目录，返回已有行情数据的 ticker 集合。"""
    tickers = set()
    for f in cache_dir.glob("*.parquet"):
        try:
            df = pd.read_parquet(f, columns=["ticker", "date", "close"])
            if "date" in df.columns and "close" in df.columns and len(df) > 0:
                for t in df["ticker"].unique():
                    tickers.add(normalize_ticker(str(t)))
        except Exception:
            continue
    # 去掉指数
    tickers.discard("000300")
    return tickers


def get_hs300_constituents() -> list[str]:
    """获取沪深300最新成分股代码列表。"""
    import akshare as ak
    logger.info("获取沪深300成分股列表...")
    df = ak.index_stock_cons_csindex(symbol="000300")
    codes = sorted(df["成分券代码"].astype(str).str.zfill(6).unique().tolist())
    logger.info("沪深300成分股: %d 只", len(codes))
    return codes


def baostock_code(ticker: str) -> str:
    """6位代码转baostock格式: sh.600000 / sz.000001"""
    ticker = normalize_ticker(ticker)
    if ticker.startswith(("60", "68")):
        return f"sh.{ticker}"
    elif ticker.startswith(("00", "30")):
        return f"sz.{ticker}"
    elif ticker.startswith(("83", "87", "43", "88", "92")):
        return f"bj.{ticker}"
    return f"sz.{ticker}"


def fetch_price_baostock(
    ticker: str,
    start_date: str = "20200101",
    end_date: str | None = None,
    adjust: str = "2",  # 1=后复权(qfq改了akshare默认), 2=前复权, 3=不复权 → baostock: 1=后 2=前 3=不复权
) -> pd.DataFrame:
    """用baostock下载日频行情，返回与项目一致的列名。
    
    baostock adjust: 1=后复权 2=前复权 3=不复权
    项目默认用 hfq(后复权), 所以 adjust=1
    
    返回列: date, ticker, open, high, low, close, volume, amount, turnover, pct_chg
    """
    bs_code = baostock_code(ticker)
    
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,code,open,high,low,close,volume,amount,turn,pctChg",
        start_date=f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}",
        end_date=f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if end_date else None,
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
    
    # 标准化列名
    df = df.rename(columns={
        "date": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "amount": "amount",
        "turn": "turnover",      # 换手率%
        "pctChg": "pct_chg",     # 涨跌幅%
    })
    
    # 类型转换
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = normalize_ticker(ticker)
    for col in ("open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # 过滤无效行（baostock有时返回空字符串）
    df = df[df["close"] > 0].copy()
    
    # 排序
    df = df.sort_values("date").reset_index(drop=True)
    
    # 保留与项目一致的列顺序
    keep = ["date", "ticker", "open", "close", "high", "low",
            "volume", "amount", "turnover", "pct_chg"]
    keep = [c for c in keep if c in df.columns]
    return df[keep]


def main():
    start_date = DEFAULT_START  # "20210101"
    end_date = today_str()
    adjust = "1"  # baostock: 1=后复权（与项目hfq一致）
    adjust_label = "hfq"
    
    logger.info("=" * 60)
    logger.info("行情数据补下工具 (baostock源)")
    logger.info("日期范围: %s ~ %s, 复权: %s", start_date, end_date, adjust_label)
    logger.info("=" * 60)
    
    # 1. 扫描已有缓存
    logger.info("扫描已有行情缓存...")
    existing = scan_existing_price_tickers(CACHE_DIR)
    logger.info("已有行情数据: %d 只", len(existing))
    
    # 2. 获取沪深300成分股
    all_codes = get_hs300_constituents()
    
    # 3. 计算缺失
    missing = sorted(set(all_codes) - existing)
    logger.info("缺失行情数据: %d 只", len(missing))
    
    if not missing:
        logger.info("✅ 所有沪深300成分股行情数据已完整，无需补下！")
        return
    
    # 打印缺失列表
    logger.info("缺失ticker: %s", ", ".join(missing[:30]) + ("..." if len(missing) > 30 else ""))
    
    # 4. 登录baostock
    lg = bs.login()
    # baostock login 有时 error_code != 0 但实际登录成功(error_msg='success')
    if str(lg.error_code) != "0" and 'success' not in str(lg.error_msg).lower():
        logger.error("baostock登录失败: code=%s msg=%s", lg.error_code, lg.error_msg)
        return
    logger.info("baostock登录成功 (code=%s, msg=%s)", lg.error_code, lg.error_msg)
    
    # 5. 逐个补下
    success = 0
    failed = 0
    failed_list = []
    
    try:
        for i, code in enumerate(missing):
            try:
                df = fetch_price_baostock(code, start_date, end_date, adjust)
                if df is not None and len(df) > 0:
                    # 保存缓存（与项目一致的cache_key格式）
                    key = cache_key("ashare", code, start_date, end_date, adjust_label)
                    cache_path = CACHE_DIR / f"{key}.parquet"
                    df.to_parquet(cache_path)
                    success += 1
                    logger.info("[%d/%d] ✅ %s: %d 天数据 → %s",
                                i + 1, len(missing), code, len(df), cache_path.name)
                else:
                    failed += 1
                    failed_list.append(code)
                    logger.warning("[%d/%d] ❌ %s: 无数据",
                                   i + 1, len(missing), code)
            except Exception as e:
                failed += 1
                failed_list.append(code)
                logger.warning("[%d/%d] ❌ %s: %s",
                               i + 1, len(missing), code, e)
            
            # baostock不需要额外节流，但稍微pause一下避免连接问题
            if (i + 1) % 50 == 0:
                logger.info("进度: %d/%d (成功%d, 失败%d)",
                            i + 1, len(missing), success, failed)
                time.sleep(0.5)
    finally:
        bs.logout()
        logger.info("baostock已登出")
    
    # 6. 汇总
    logger.info("=" * 60)
    logger.info("补下完成！")
    logger.info("成功: %d, 失败: %d, 总计: %d", success, failed, len(missing))
    if failed_list:
        logger.info("失败列表: %s", ", ".join(failed_list))
    
    # 7. 验证最终覆盖率
    final_existing = scan_existing_price_tickers(CACHE_DIR)
    final_coverage = len(final_existing & set(all_codes))
    logger.info("最终行情覆盖: %d / %d (%.1f%%)",
                final_coverage, len(all_codes), final_coverage / len(all_codes) * 100)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
