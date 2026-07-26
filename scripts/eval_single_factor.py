"""单因子评估端到端脚本。

流程：拉沪深300成分 → 逐个下载日频 → 计算 EP 因子
     → 截面标准化 → forward return 对齐 → 横截面 IC/IR + 分位组合

运行：python scripts/eval_single_factor.py
       python scripts/eval_single_factor.py --factor Mom12m --index 000905
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 项目根入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from fetcher import CalendarFetcher, PriceFetcher
from universe import Universe
from factors import (
    EPFactor, BPFactor, Mom12mFactor, Rev1mFactor,
    Vol60Factor, TurnFactor, LnMVFactor,
)
from processor.normalize import winsorize_cross_section, zscore_cross_section
from processor.align import compute_forward_returns
from evaluator.ic_ir import evaluate_factor, print_ic_summary
from evaluator.returns import quantile_portfolio_returns, summarize_quantile_returns, print_quantile_summary


# 因子名 -> 实例化
FACTOR_REGISTRY = {
    "EP": EPFactor,
    "BP": BPFactor,
    "Mom12m": Mom12mFactor,
    "Rev1m": Rev1mFactor,
    "Vol60": Vol60Factor(window=60),
    "Turn": TurnFactor(window=20),
    "LnMV": LnMVFactor,
}


def download_constituent_prices(
    tickers: list[str],
    start: str,
    end: str,
    market: str = "A",
    max_stocks: int = 0,
) -> pd.DataFrame:
    """批量下载成分股日频行情并拼接为 panel。"""
    pf = PriceFetcher()
    frames = []
    todo = tickers[:max_stocks] if max_stocks > 0 else tickers
    for i, tk in enumerate(todo):
        try:
            df = pf.get_daily(tk, market=market, start_date=start, end_date=end, adjust="hfq")
            if len(df) > 0:
                frames.append(df)
                print(f"    [{i + 1}/{len(todo)}] {tk} OK ({len(df)} rows)")
            else:
                print(f"    [{i + 1}/{len(todo)}] {tk} 空数据")
        except Exception as e:
            print(f"    [{i + 1}/{len(todo)}] {tk} 失败: {type(e).__name__}")
        time.sleep(0.2)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    return panel


def main():
    parser = argparse.ArgumentParser(description="单因子评估")
    parser.add_argument("--factor", default="Vol60", choices=list(FACTOR_REGISTRY.keys()))
    parser.add_argument("--index", default="000300", help="指数代码（默认沪深300）")
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=None)
    parser.add_argument("--max-stocks", type=int, default=0, help="最多下载几只（0=全部）")
    parser.add_argument("--min-ic-count", type=int, default=5, help="IC计算最小样本数")
    args = parser.parse_args()

    print("=" * 56)
    print(f" 单因子评估: {args.factor} | 基准指数: {args.index}")
    print(f" 区间: {args.start} ~ {args.end or '最新'}")
    print("=" * 56)

    # 1. 成分股
    print("\n[Step 1] 获取成分股...")
    u = Universe(mode="A", start=args.start, end=args.end, index_symbol=args.index)
    cons = u.constituents()
    tickers = cons["ticker"].tolist()
    print(f"    成分数: {len(tickers)}")

    # 2. 下载行情
    print(f"\n[Step 2] 下载日频行情（后复权）...")
    panel = download_constituent_prices(
        tickers, args.start, args.end or "", market="A", max_stocks=args.max_stocks
    )
    if panel.empty:
        print("ERROR: 无行情数据，退出")
        return 1
    print(f"    Panel: {panel.shape[0]} rows × {panel.shape[1]} cols")
    print(f"    股票数: {panel['ticker'].nunique()}")
    print(f"    日期范围: {panel['date'].min().date()} ~ {panel['date'].max().date()}")

    # 3. 计算因子
    print(f"\n[Step 3] 计算因子: {args.factor}...")
    factor_cls = FACTOR_REGISTRY[args.factor]
    factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
    raw = factor.compute_aligned(panel)
    panel[f"{args.factor}_raw"] = raw
    valid = raw.notna().sum()
    print(f"    有效值: {valid}/{len(raw)} ({valid / len(raw):.1%})")

    # 4. 截面标准化
    print(f"\n[Step 4] 截面标准化...")
    col = f"{args.factor}_raw"
    panel[col] = winsorize_cross_section(panel, col, n_sigma=3.0)
    panel[f"{args.factor}_z"] = zscore_cross_section(panel[col], panel["date"])
    print(f"    z-score 有效: {panel[f'{args.factor}_z'].notna().sum()}")

    # 5. Forward return
    print(f"\n[Step 5] 计算 forward return...")
    panel = compute_forward_returns(panel, periods=[1, 5, 10, 21])
    fwd_cols = [c for c in panel.columns if c.startswith("forward_")]
    for c in fwd_cols:
        print(f"    {c}: 有效 {panel[c].notna().sum()}")

    # 6. IC/IR 评估
    print(f"\n[Step 6] 横截面 IC/IR 评估...")
    z_col = f"{args.factor}_z"
    df_eval = panel.dropna(subset=[z_col]).copy()
    results = evaluate_factor(df_eval, z_col)
    print_ic_summary(results, factor_name=args.factor)

    # 7. 分位组合收益
    print(f"\n[Step 7] 分位组合收益（5 组，21 日持有期）...")
    q_df = quantile_portfolio_returns(
        df_eval, z_col, return_col="forward_21d_return", n_groups=5
    )
    if not q_df.empty:
        q_sum = summarize_quantile_returns(q_df, n_groups=5)
        print_quantile_summary(q_sum, factor_name=args.factor)

    print(f"\n{'=' * 56}")
    print(" 评估完成")
    print(f"{'=' * 56}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
