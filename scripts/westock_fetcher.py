"""westock CLI 资金流日更脚本（增量，替代原 akshare 东财管线）。

数据源切换后，资金流日更走 vendored westock CLI（tools/westock_cli）：
  - 默认：取当日（最新交易日）快照，append 进 SQLite fund_flow 表（ticker+date upsert）
  - --date YYYY-MM-DD：补指定历史单日
  - 断点续跑：目标日已存在记录的 ticker 自动跳过（--force 强制重抓）

与行情数据一致的「增量更新」方式：重跑只补新数据，旧数据覆盖。

用法（与 _download_a_share.py 一致的区间约定）：
  python scripts/westock_fetcher.py 2026-07-16 2026-07-17   # 区间补数（逐日循环）
  python scripts/westock_fetcher.py                          # 默认取最新交易日（daily_price MAX）
  python scripts/westock_fetcher.py --date 2026-07-16        # 兼容：单日补数
  python scripts/westock_fetcher.py --limit 50 --pace 0.3
  python scripts/westock_fetcher.py --force                  # 强制全部重抓
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# 允许以 `python scripts/westock_fetcher.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.fund_flow import fetch_fund_flow_via_cli, upsert_fund_flow_records
from fetcher.store.db import query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("westock_fetcher")

BATCH = 20  # 每批 ticker 数（CLI 支持逗号批量，控制并发避免限频）


def get_universe() -> list:
    """A 股宇宙：优先沪深300（ref_index_weight），回退 daily_price 去重。"""
    try:
        from fetcher.store.db import load_universe
        df = load_universe("ashare")
        if df is not None and not df.empty:
            return df["ticker"].astype(str).str.zfill(6).tolist()
    except Exception as e:
        logger.warning("load_universe 失败，回退 daily_price: %s", e)
    try:
        df = query("SELECT DISTINCT ticker FROM daily_price", market="ashare")
        if not df.empty:
            return df["ticker"].astype(str).str.zfill(6).tolist()
    except Exception as e:
        logger.warning("daily_price 去重也失败: %s", e)
    return []


def _latest_trading_day() -> Optional[str]:
    """真实最新交易日 = 行情表 daily_price 的 MAX(date)。

    资金流应与之同频。注意：不能取 fund_flow 表自身的 MAX(date)，
    否则 fund_flow 永远停在最后一条历史记录（如 2026-07-17），
    新交易日永远不会被补（即“冻结” bug）。
    """
    try:
        df = query("SELECT MAX(date) AS d FROM daily_price", market="ashare")
        d = df["d"].iloc[0] if not df.empty else None
        return str(d)[:10] if d else None
    except Exception:
        return None


def _already_done(tickers: list, date_str: str) -> set:
    if not date_str:
        return set()
    ph = ", ".join("?" for _ in tickers)
    try:
        df = query(
            f"SELECT ticker FROM fund_flow WHERE date=? AND ticker IN ({ph})",
            [date_str] + tickers, market="ashare",
        )
        return set(df["ticker"].astype(str).str.zfill(6))
    except Exception:
        return set()


def _date_range(start: str, end: str) -> list:
    """展开 [start, end] 为按日递增的日期列表（含端点）。

    与行情下载一致：区间参数交给脚本，脚本内部逐日循环。
    CLI asfund --date 仅支持单日，所以这里一天发一次调用。
    """
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d").date()
        d1 = datetime.strptime(end, "%Y-%m-%d").date()
    except Exception:
        return []
    if d1 < d0:
        d0, d1 = d1, d0
    days = []
    cur = d0
    while cur <= d1:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def _resolve_target_days(args) -> list:
    """解析目标日期列表（优先级：--date > 位置区间 > 默认最新交易日）。"""
    if getattr(args, "date", None):
        return [args.date]
    if getattr(args, "start_date", None) and getattr(args, "end_date", None):
        days = _date_range(args.start_date, args.end_date)
        if days:
            return days
        logger.warning("区间解析失败，回退最新交易日: %s~%s",
                       args.start_date, args.end_date)
    latest = _latest_trading_day()
    return [latest] if latest else []


def main():
    ap = argparse.ArgumentParser(description="westock CLI 资金流日更（增量，区间补数）")
    # 与 _download_a_share.py 一致的区间约定：位置参数 start/end
    ap.add_argument("start_date", nargs="?", default=None,
                    help="开始日期 YYYY-MM-DD（区间补数，与行情下载同约定）")
    ap.add_argument("end_date", nargs="?", default=None,
                    help="结束日期 YYYY-MM-DD")
    ap.add_argument("--date", default=None, help="兼容：补指定历史单日 YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 只（调试）")
    ap.add_argument("--pace", type=float, default=0.3, help="批次/日之间间隔秒")
    ap.add_argument("--force", action="store_true", help="忽略断点，强制重抓")
    ap.add_argument("--dry-run", action="store_true", help="仅统计，不写库")
    args = ap.parse_args()

    target_days = _resolve_target_days(args)
    tickers = get_universe()
    if args.limit:
        tickers = tickers[: args.limit]
    if not tickers:
        logger.error("宇宙为空，退出")
        return
    if not target_days:
        logger.error("无目标日期，退出")
        return

    logger.info("目标区间=%s ~ %s | 共 %d 个交易日 | 宇宙 %d 只",
                target_days[0], target_days[-1], len(target_days), len(tickers))

    total_written = 0
    for day in target_days:
        # 断点：以当天为基准，已落库者跳过（--force 强制重抓）
        done = set() if args.force else _already_done(tickers, day)
        todo = [t for t in tickers if t not in done]
        if not todo:
            logger.info("  %s 全部已存在，跳过", day)
            continue
        logger.info("  >>> %s | 待抓 %d / %d%s", day, len(todo), len(tickers),
                    " [dry-run]" if args.dry_run else "")
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            df = fetch_fund_flow_via_cli(chunk, date=day)
            if not df.empty:
                if args.dry_run:
                    logger.info("本批将写入 %d 条（dry-run）", len(df))
                else:
                    n = upsert_fund_flow_records(df)
                    total_written += n
                    logger.info("进度 %d/%d | 本批 %d 条 | 累计 %d",
                                min(i + BATCH, len(todo)), len(todo), n, total_written)
            else:
                logger.warning("本批 %d 只无数据（可能停牌/非交易日）", len(chunk))
            if args.pace and i + BATCH < len(todo):
                time.sleep(args.pace)
        if args.pace:
            time.sleep(args.pace)

    logger.info("完成：共写入 %d 条（覆盖 %d 个交易日）", total_written, len(target_days))


if __name__ == "__main__":
    main()
