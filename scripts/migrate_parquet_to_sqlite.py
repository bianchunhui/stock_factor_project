"""把现有 parquet 缓存迁移进 SQLite（三市场分库）。

- data/cache/*.parquet（A股/港股/美股散落 hash 文件）：按列名推断身份后入对应库对应表。
- data/hk_panel_*.parquet / data/us_panel_*.parquet：按文件名直接入 hk.db / us.db。
- 不重拉、不修改任何 parquet（只读迁移）。

用法：
  python scripts/migrate_parquet_to_sqlite.py --dry-run   # 仅统计分类，不写库
  python scripts/migrate_parquet_to_sqlite.py             # 写入并对账
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetcher.store import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"

# 明确命名的面板文件：直接映射 (market, table, keys)
PANEL_FILES = {
    "data/hk_panel_price.parquet": ("hk", "daily_price", ["ticker", "date"]),
    "data/hk_panel_financial.parquet": ("hk", "financial_indicator", ["ticker", "report_date"]),
    "data/hk_panel_hsgt.parquet": ("hk", "ref_hsgt", ["ticker", "date"]),
    "data/hk_full_factor_panel.parquet": ("hk", "factor_panel", ["ticker", "date"]),
    "data/us_panel_price.parquet": ("us", "daily_price", ["ticker", "date"]),
    "data/us_panel_valuation.parquet": ("us", "valuation", ["ticker", "date"]),
    "data/us_full_factor_panel.parquet": ("us", "factor_panel", ["ticker", "date"]),
}

PK_BY_TABLE = {
    "daily_price": ["ticker", "date"],
    "index_daily": ["ticker", "date"],
    "fund_flow": ["ticker", "date"],
    "financial_income": ["ticker", "report_date"],
    "financial_balance": ["ticker", "report_date"],
    "financial_cashflow": ["ticker", "report_date"],
    "financial_indicator": ["ticker", "report_date"],
    "financial": ["ticker", "report_date"],
    "valuation": ["ticker", "date"],
    "ref_industry": ["ticker"],
    "ref_calendar": ["date"],
    "ref_hsgt": ["ticker", "date"],
    "ref_industry_tree": ["行业代码"],
    "ref_index_weight": ["ticker"],
    "ref_universe": ["ticker"],
}


def infer_market(ticker_val) -> str:
    """从 ticker 字符串推断市场。"""
    if ticker_val is None:
        return "ashare"
    t = str(ticker_val).strip().upper()
    if not t:
        return "ashare"
    if ".HK" in t:
        return "hk"
    if t.isalpha():
        return "us"
    if t.isdigit():
        if len(t) == 6:
            return "ashare"
        if len(t) == 5:
            return "hk"
    return "ashare"


def classify(df: pd.DataFrame, market: str):
    """返回 (table, keys) 或 (None, None)。"""
    cols = set(df.columns)
    # ── 参考/元数据特例（列名非标准）──
    if "trade_date" in cols:
        return "ref_calendar", ["date"]
    if "行业代码" in cols:
        return "ref_industry_tree", ["行业代码"]
    if "weight" in cols and "ticker" in cols:
        return "ref_index_weight", ["ticker"]
    if "ticker" in cols and "name" in cols and "market" in cols:
        return "ref_universe", ["ticker"]
    # ── 财务 ──
    if "report_date" in cols:
        # 优先级：cashflow > indicator > balance > income
        # （indicator 是合并产物，可能含 total_assets，须先于 balance 判定）
        if "operating_cash_flow" in cols or "investing_cash_flow" in cols:
            table = "financial_cashflow"
        elif any(c in cols for c in ("roe", "roa", "debt_ratio", "gross_margin")):
            table = "financial_indicator"
        elif "total_assets" in cols or "owner_equity" in cols or "total_liabilities" in cols:
            table = "financial_balance"
        else:
            table = "financial_income"
    elif "date" in cols:
        if "ticker" not in cols:
            # 只有日期无代码：交易日历等参考表
            table = "ref_calendar"
        else:
            price_like = {"close", "open", "high", "low", "volume"} & cols
            if ("main_net_flow" in cols or "retail_net_flow" in cols
                    or "main_net_inflow" in cols or "super_big_net_inflow" in cols):
                table = "fund_flow"
            elif price_like:
                table = "daily_price"
            else:
                table = "ref_hsgt"
    elif "industry" in cols:
        table = "ref_industry"
    elif "date" in cols:
        table = "ref_calendar"
    else:
        return None, None
    keys = [k for k in PK_BY_TABLE.get(table, []) if k in df.columns]
    if not keys:
        return None, None
    return table, keys


def process_file(path: Path, dry: bool, summary: dict):
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        summary["errors"].append(f"{path.name}: read {e}")
        return
    if df is None or len(df) == 0:
        return

    name = path.name
    # 明确面板文件（统一正斜杠，兼容 Windows 反斜杠）
    rel = path.relative_to(ROOT).as_posix()
    if rel in PANEL_FILES:
        market, table, keys = PANEL_FILES[rel]
    else:
        # us_price_/us_val_ 文件名带 ticker
        if name.startswith("us_price_"):
            market, table, keys = "us", "daily_price", ["ticker", "date"]
        elif name.startswith("us_val_"):
            market, table, keys = "us", "valuation", ["ticker", "date"]
        else:
            # 推断 market
            if "ticker" in df.columns and not df["ticker"].dropna().empty:
                market = infer_market(df["ticker"].dropna().iloc[0])
            else:
                market = "ashare"
            table, keys = classify(df, market)
            if table is None:
                summary["skipped"].append(name)
                return
            # 交易日历列名归一 trade_date -> date
            if table == "ref_calendar" and "trade_date" in df.columns and "date" not in df.columns:
                df = df.rename(columns={"trade_date": "date"})

    key = (market, table)
    summary["plan"][key] = summary["plan"].get(key, 0) + len(df)
    summary["files"][key] = summary["files"].get(key, 0) + 1
    if dry:
        return

    conn = db.get_conn(market)
    try:
        n = db.upsert(df, table, keys, conn)
        summary["written"][key] = summary["written"].get(key, 0) + n
    finally:
        conn.close()


def reconcile(summary: dict):
    print("\n=== 对账 (parquet 预期行数 vs db 实际 COUNT) ===")
    ok = True
    for (market, table), exp in summary["plan"].items():
        try:
            conn = db.get_conn(market)
            actual = int(conn.execute(f'SELECT COUNT(*) FROM "{db._safe_col(table)}"').fetchone()[0])
            conn.close()
        except Exception as e:
            actual = f"ERR {e}"
        match = actual == exp if isinstance(actual, int) else False
        ok = ok and match
        print(f"  {market}.{table:20s} exp={exp:8d} db={actual} {'OK' if match else 'MISMATCH'}")
    print("对账结果:", "全部一致" if ok else "存在不一致")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅统计分类，不写库")
    args = ap.parse_args()

    summary = {"plan": {}, "files": {}, "written": {}, "skipped": [], "errors": []}

    # 1) 明确面板
    for rel in PANEL_FILES:
        p = ROOT / rel
        if p.exists():
            process_file(p, args.dry_run, summary)
    # 2) 散落 cache
    for p in sorted(CACHE.glob("*.parquet")):
        process_file(p, args.dry_run, summary)

    print("=== 迁移计划" + (" (DRY-RUN)" if args.dry_run else "") + " ===")
    for (market, table), rows in sorted(summary["plan"].items(), key=lambda x: (x[0][0], x[0][1])):
        print(f"  {market}.{table:20s} files={summary['files'][(market,table)]:4d} rows={rows}")
    if summary["skipped"]:
        print(f"\n跳过 {len(summary['skipped'])} 个无法分类的文件: {summary['skipped'][:10]}")
    if summary["errors"]:
        print(f"\n错误 {len(summary['errors'])} 个: {summary['errors'][:10]}")

    if not args.dry_run:
        reconcile(summary)


if __name__ == "__main__":
    main()
