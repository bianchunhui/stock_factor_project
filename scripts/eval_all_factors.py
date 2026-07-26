"""全量22因子端到端验证脚本。

流程：
  1. 取沪深300成分股中的少量股票（默认 --max-stocks=5，可扩至300）
  2. 批量下载日频行情
  3. 批量抓取财报指标（FinancialFetcher）并按 PIT 合并
  4. 批量抓取北向持股（HSGTFetcher）并合并
  5. 计算全部 22 个因子
  6. 截面缩尾 + 行业/市值中性化 + z-score
  7. 计算 forward return
  8. 横截面 IC/IR 评估 + 分位组合收益

运行：
  python scripts/eval_all_factors.py
  python scripts/eval_all_factors.py --max-stocks 50 --start 20230101
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from config import FACTOR_DIR, CATEGORIES, FACTOR_CATALOG
from fetcher import (
    CalendarFetcher, PriceFetcher, FinancialFetcher, HSGTFetcher,
    IndustryFetcher, SpotFetcher, FundFlowFetcher, HSGT_DATA_END_DATE,
)
from fetcher.base import to_datetime_safe
from universe import Universe
from factors import ALL_FACTORS, FACTOR_CLASS_MAP
from processor.pit_align import pit_merge
from processor.normalize import standardize_factor, zscore_cross_section, winsorize_cross_section
from processor.align import compute_forward_returns
from evaluator.ic_ir import evaluate_factor, print_ic_summary
from evaluator.returns import quantile_portfolio_returns, summarize_quantile_returns, print_quantile_summary


def download_constituent_prices(
    tickers: list[str],
    start: str,
    end: str,
    market: str = "A",
    max_stocks: int = 0,
    skip_em: bool = False,
) -> pd.DataFrame:
    """批量下载成分股日频行情并拼接为 panel。"""
    pf = PriceFetcher()
    frames = []
    failed = []
    todo = tickers[:max_stocks] if max_stocks > 0 else tickers
    total = len(todo)
    for i, tk in enumerate(todo):
        try:
            df = pf.get_daily(tk, market=market, start_date=start, end_date=end,
                              adjust="hfq", skip_em=skip_em)
            if len(df) > 0:
                frames.append(df)
                print(f"    [{i + 1}/{total}] {tk}: OK ({len(df)} rows)")
            else:
                failed.append(tk)
                print(f"    [{i + 1}/{total}] {tk}: 无数据")
        except Exception as e:
            failed.append(tk)
            print(f"    [{i + 1}/{total}] {tk} 异常: {type(e).__name__}: {e}")
        time.sleep(0.5)  # 增加间隔避免限流
    if failed:
        print(f"\n    ⚠ {len(failed)} 只股票下载失败: {failed[:20]}{'...' if len(failed) > 20 else ''}")
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    return panel


def fetch_and_merge_financial(
    panel: pd.DataFrame,
    tickers: list[str],
    ff: FinancialFetcher,
) -> pd.DataFrame:
    """批量拉财报并 PIT 对齐到 panel。"""
    print("\n[Step 3] 批量抓取财报指标...")
    reports = []
    for i, code in enumerate(tickers):
        try:
            ind = ff.get_indicators(code, use_cache=True)
            if not ind.empty:
                ind = ind.copy()
                ind["ticker"] = code
                # 确保 announcement_date 存在；若缺失则用 report_date 兜底
                if "announcement_date" not in ind.columns:
                    ind["announcement_date"] = ind["report_date"]
                reports.append(ind)
        except Exception as e:
            print(f"    {code} 财报失败: {e}")
        if (i + 1) % 5 == 0 or i == len(tickers) - 1:
            print(f"    财报进度: {i + 1}/{len(tickers)}")
        time.sleep(0.2)

    if not reports:
        print("    无财报数据，跳过")
        return panel

    rep_df = pd.concat(reports, ignore_index=True)
    rep_df = rep_df.rename(columns={"report_date": "report_period"})
    for c in ["report_period", "announcement_date"]:
        if c in rep_df.columns:
            rep_df[c] = to_datetime_safe(rep_df[c])

    # 需要合并的财报字段
    value_cols = ["revenue_yoy", "net_profit_yoy", "parent_net_profit_yoy",
                  "basic_eps", "roe", "roa", "gross_margin", "debt_ratio", "ocf_ratio",
                  "total_assets", "total_liabilities", "parent_net_profit", "net_profit",
                  "operating_cash_flow", "total_revenue",
                  "prev_parent_net_profit", "prev_net_profit"]
    # 只保留 rep_df 中实际存在的字段
    value_cols = [c for c in value_cols if c in rep_df.columns]

    print(f"    合并财报字段: {value_cols}")
    if not value_cols:
        print("    无有效财报字段，跳过")
        return panel
    panel = pit_merge(panel, rep_df, value_cols)
    return panel


def fetch_and_merge_hsgt(
    panel: pd.DataFrame,
    tickers: list[str],
    hf: HSGTFetcher,
) -> pd.DataFrame:
    """批量拉北向持股并合并到 panel。

    ⚠️ 北向数据仅至 2024-08-16；超过该日期的行不会有 holding_pct 等字段。
    """
    print("\n[Step 4] 批量抓取北向持股（数据仅至 2024-08-16）...")
    holdings = []
    for i, code in enumerate(tickers):
        try:
            h = hf.get_stock_holding(code, use_cache=True)
            if not h.empty:
                holdings.append(h)
        except Exception as e:
            print(f"    {code} 北向失败: {e}")
        if (i + 1) % 5 == 0 or i == len(tickers) - 1:
            print(f"    北向进度: {i + 1}/{len(tickers)}")
        time.sleep(0.4)

    if not holdings:
        print("    无北向数据，跳过")
        return panel

    hsgt_panel = pd.concat(holdings, ignore_index=True)
    hsgt_panel = hsgt_panel.rename(columns={"date": "hsgt_date"})
    # 与日频 panel 按 ticker + 日期 merge
    panel = panel.merge(
        hsgt_panel[["hsgt_date", "ticker", "holding_pct", "fund_change", "value_change", "holding_value"]],
        left_on=["date", "ticker"],
        right_on=["hsgt_date", "ticker"],
        how="left",
    )
    if "hsgt_date" in panel.columns:
        panel = panel.drop(columns=["hsgt_date"])
    return panel


def fetch_and_merge_fund_flow(
    panel: pd.DataFrame,
    tickers: list[str],
    ff: FundFlowFetcher | None = None,
) -> pd.DataFrame:
    """批量拉个股资金流（2024 年至今可用，现代情绪因子源）。

    数据优先从 SQLite `fund_flow` 表批量取（增量），缺失 ticker 走网络补齐并落库。
    """
    print("\n[Step 4.5] 批量抓取个股资金流（现代情绪因子源，SQLite 增量）...")
    from fetcher.fund_flow import load_fund_flow_panel
    flow_panel = load_fund_flow_panel(tickers, market="ashare")
    if flow_panel.empty:
        print("    无资金流数据，跳过")
        return panel

    keep_cols = [c for c in ["date", "ticker", "main_net_inflow",
                              "super_big_net_inflow", "big_net_inflow",
                              "mid_net_inflow", "small_net_inflow"]
                 if c in flow_panel.columns]
    flow_panel = flow_panel[keep_cols]
    panel = panel.merge(flow_panel, on=["date", "ticker"], how="left")
    cov = panel["main_net_inflow"].notna().mean() if "main_net_inflow" in panel.columns else 0
    print(f"    资金流合并: {flow_panel['ticker'].nunique()} 只, "
          f"main_net_inflow 覆盖率 {cov:.1%}")
    return panel


def ensure_fund_flow_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """若 panel 缺 MainFlow/SuperBig 的 raw/z（如从旧 factor_panel 加载），
    用已合并的资金流原始列补算这两个因子，使 --from-panel 也能用上资金流。
    标准化与 compute_all_factors 保持一致（缩尾 + 行业/市值中性化 + zscore）。
    """
    from factors.sentiment import MainFlowFactor, SuperBigFlowFactor
    from processor.normalize import standardize_factor, winsorize_cross_section, zscore_cross_section

    do_neut = "industry" in panel.columns and "ln_market_cap" in panel.columns
    for fcls in (MainFlowFactor, SuperBigFlowFactor):
        f = fcls()
        raw_col = f"{f.name}_raw"
        if raw_col in panel.columns:
            continue
        req = f.required_columns()[0]
        if req not in panel.columns:
            print(f"    [跳过] 缺 {req}，无法补算 {f.name}")
            continue
        panel[raw_col] = f.compute(panel)
        try:
            std = standardize_factor(panel, raw_col, do_winsorize=True,
                                     do_neutralize=do_neut, method="zscore")
            panel[f"{f.name}_z"] = std
        except Exception:
            w = winsorize_cross_section(panel, raw_col, n_sigma=3.0)
            panel[f"{f.name}_z"] = zscore_cross_section(w, panel["date"], min_count=3)
        print(f"    补算因子 {f.name}: 有效 {panel[raw_col].notna().sum()}")
    return panel


def compute_all_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """计算全部 22 个因子。"""
    print("\n[Step 5] 计算 22 个因子...")
    for factor_cls in ALL_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        raw = factor.compute(panel)
        panel[f"{factor.name}_raw"] = raw
        valid = raw.notna().sum()
        print(f"    {factor.name:8s} 有效: {valid:5d}/{len(raw)} ({valid / len(raw):.1%})")
    return panel


def standardize_all_factors(panel: pd.DataFrame, do_neutralize: bool = True) -> pd.DataFrame:
    """对所有因子做标准化。"""
    print("\n[Step 6] 截面标准化...")
    # 先添加对数市值列（用于中性化）
    if "market_cap" in panel.columns and "ln_market_cap" not in panel.columns:
        panel["ln_market_cap"] = np.log(
            pd.to_numeric(panel["market_cap"], errors="coerce").replace(0, np.nan)
        )

    # 添加行业列
    if "industry" not in panel.columns:
        try:
            ind_fetcher = IndustryFetcher()
            panel = ind_fetcher.attach_industry(panel)
        except Exception as e:
            print(f"    行业分类失败: {e}，跳过中性化")
            do_neutralize = False

    for factor_cls in ALL_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        raw_col = f"{factor.name}_raw"
        if raw_col not in panel.columns:
            continue

        # 财报因子（PIT）做中性化，技术/情绪因子可跳过，但统一做更稳健
        neutralize = do_neutralize
        if factor.need_pit and "industry" in panel.columns and "ln_market_cap" in panel.columns:
            try:
                std = standardize_factor(
                    panel, raw_col,
                    do_winsorize=True,
                    do_neutralize=neutralize,
                    method="zscore",
                )
                panel[f"{factor.name}_z"] = std
                continue
            except Exception as e:
                print(f"    {factor.name} 中性化失败: {e}")

        # 简化路径：只做缩尾+zscore
        w = winsorize_cross_section(panel, raw_col, n_sigma=3.0)
        panel[f"{factor.name}_z"] = zscore_cross_section(w, panel["date"], min_count=3)

    return panel


def evaluate_all_factors(panel: pd.DataFrame, periods: list[int] = None) -> dict:
    """对所有因子做 IC/IR 评估。"""
    print("\n[Step 7] 计算 forward return...")
    panel = compute_forward_returns(panel, periods=periods or [1, 5, 10, 21])
    print(f"    forward 1d:  {panel['forward_1d_return'].notna().sum()}")
    print(f"    forward 21d: {panel['forward_21d_return'].notna().sum()}")

    print("\n[Step 8] 横截面 IC/IR 评估（全部 22 因子）...")
    summary_rows = []
    for factor_cls in ALL_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        z_col = f"{factor.name}_z"
        if z_col not in panel.columns:
            continue
        df_eval = panel.dropna(subset=[z_col]).copy()
        if len(df_eval) < 30:
            continue
        # 与合成口径一致：按 direction 调整后再算 IC（负向因子乘 -1）。
        # 否则 direction=-1 的因子（Lev/Vol60/LnMV/Rev1m/Turn/Beta）原始 z 的 IC 恒为负，
        # 会被误判为"无效因子"。调整后 IC 恒表示"因子越强 → 未来收益越高"。
        eval_col = f"{factor.name}_dz_eval"
        df_eval[eval_col] = df_eval[z_col] * factor.direction
        results = evaluate_factor(df_eval, eval_col)
        if not results:
            continue

        # 取 21 天持有期的 IC/IR
        r21 = results.get("forward_21d_return", {})
        ic_21 = r21.get("ic_series", pd.DataFrame())
        if ic_21.empty or "ic" not in ic_21.columns or ic_21["ic"].dropna().empty:
            continue
        s = r21.get("summary", {})
        summary_rows.append({
            "factor": factor.name,
            "category": factor.category,
            "direction": factor.direction,
            "need_pit": factor.need_pit,
            "ic_21d": s.get("ic_mean", np.nan),
            "ir_21d": s.get("ir", np.nan),
            "ic_pos_rate": s.get("ic_positive_rate", np.nan),
            "n_ic": s.get("n", 0),
        })

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values("ir_21d", ascending=False).reset_index(drop=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description="全量22因子端到端评估")
    parser.add_argument("--index", default="000300", help="指数代码（默认沪深300）")
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=None)
    parser.add_argument("--max-stocks", type=int, default=5, help="最多下载几只（默认5，可扩至300）")
    parser.add_argument("--no-neutralize", action="store_true", help="关闭行业/市值中性化")
    args = parser.parse_args()

    print("=" * 60)
    print(f" 全量22因子端到端评估 | 基准: {args.index}")
    print(f" 区间: {args.start} ~ {args.end or '最新'} | 股票数: {args.max_stocks}")
    print("=" * 60)

    # 1. 成分股
    print("\n[Step 1] 获取成分股...")
    u = Universe(mode="A", start=args.start, end=args.end, index_symbol=args.index)
    cons = u.constituents()
    tickers = cons["ticker"].tolist()
    print(f"    成分数: {len(tickers)}")
    if args.max_stocks > 0:
        tickers = tickers[:args.max_stocks]

    # 2. 日频行情
    print(f"\n[Step 2] 下载日频行情（后复权）...")
    panel = download_constituent_prices(
        tickers, args.start, args.end or "", market="A", max_stocks=args.max_stocks
    )
    if panel.empty:
        print("ERROR: 无行情数据")
        return 1
    print(f"    Panel: {panel.shape[0]} rows × {panel.shape[1]} cols")
    print(f"    股票数: {panel['ticker'].nunique()}")
    print(f"    日期范围: {panel['date'].min().date()} ~ {panel['date'].max().date()}")

    # 2.5. Spot 数据（市场总值/PE/PB）
    print("\n[Step 2.5] 获取 spot 行情（市值/PE/PB）...")
    try:
        sf = SpotFetcher()
        panel = sf.attach_to_panel(panel, tickers)
        if "circ_market_cap" in panel.columns:
            print(f"    流通市值: {panel['circ_market_cap'].notna().sum()}")
        if "pe_ttm" in panel.columns:
            print(f"    PE: {panel['pe_ttm'].notna().sum()}")
    except Exception as e:
        print(f"    Spot 获取失败: {e}")

    # 2.6. 基准指数（用于 Beta）
    print(f"\n[Step 2.6] 获取基准指数: {args.index}...")
    try:
        pf = PriceFetcher()
        bm = pf.get_benchmark_daily(args.index, start_date=args.start, end_date=args.end or "")
        if not bm.empty:
            bm["bench_ret"] = bm["close"].pct_change()
            bm = bm[["date", "bench_ret"]].copy()
            panel = panel.merge(bm, on="date", how="left")
            print(f"    基准 rows: {len(bm)}, 合并后 panel: {panel.shape}")
    except Exception as e:
        print(f"    基准获取失败: {e}")

    # 3. 财报
    ff = FinancialFetcher()
    panel = fetch_and_merge_financial(panel, tickers, ff)

    # 4. 北向（仅历史段）
    hf = HSGTFetcher()
    panel = fetch_and_merge_hsgt(panel, tickers, hf)

    # 4.5 资金流（现代情绪源）
    try:
        fflow = FundFlowFetcher()
        panel = fetch_and_merge_fund_flow(panel, tickers, fflow)
    except Exception as e:
        print(f"    资金流获取失败: {e}")

    # 5. 因子
    panel = compute_all_factors(panel)

    # 6. 标准化
    panel = standardize_all_factors(panel, do_neutralize=not args.no_neutralize)

    # 7. 评估
    summary = evaluate_all_factors(panel)

    print("\n" + "=" * 60)
    print(" 22 因子 IC/IR 排名（21日持有期）")
    print("=" * 60)
    if summary.empty:
        print(" 无有效评估结果")
    else:
        print(summary.to_string(index=False, float_format="%.4f"))

    # 8. 分位组合（取有效因子中 IR 最高的一个）
    best_factor = summary.iloc[0]["factor"] if not summary.empty else None
    if best_factor:
        print(f"\n[Step 9] 分位组合收益示例（{best_factor} 因子，5组，21日持有）...")
        z_col = f"{best_factor}_z"
        if z_col in panel.columns and "forward_21d_return" in panel.columns:
            q_df = quantile_portfolio_returns(
                panel, z_col, return_col="forward_21d_return", n_groups=5
            )
            if not q_df.empty:
                q_sum = summarize_quantile_returns(q_df, n_groups=5)
                print_quantile_summary(q_sum, factor_name=best_factor)

    # 保存结果
    out_path = FACTOR_DIR / f"all_factors_{args.max_stocks}stocks.parquet"
    panel.to_parquet(out_path)
    print(f"\n因子面板已保存: {out_path}")
    print(f"\n{'=' * 60}\n 评估完成\n{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
