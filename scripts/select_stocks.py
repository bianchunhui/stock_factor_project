"""多因子选股脚本 — 从因子评估到实际选股组合 + 月度调仓回测。

流程：
  1. 获取沪深300成分股 + 下载行情 + 财报PIT合并 + 资金流合并
  2. 计算24因子 + 截面标准化（缩尾+行业/市值中性化+zscore）
  3. 评估IC/IR → 确定有效因子 + IC加权权重
  4. 方向调整(direction×z) → IC加权合成多因子得分
  5. 最新日期：选Top-N% → 风控约束 → 输出推荐持仓
  6. 月度调仓回测 → 年化/夏普/回撤/信息比率

用法：
  # 用已有缓存快速测试（5股）
  python scripts/select_stocks.py --max-stocks 5

  # 沪深300全量（首次较慢，后续走缓存）
  python scripts/select_stocks.py --max-stocks 0 --start 20230101

  # 从已保存的 panel parquet 加载（跳过数据拉取）
  python scripts/select_stocks.py --from-panel data/factors/all_factors_5stocks.parquet

  # 自定义参数
  python scripts/select_stocks.py --max-stocks 50 --top-pct 10 --holding-months 1
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from config import FACTOR_DIR
from report_utils import save_csv_html, save_panel
from fetcher import (
    CalendarFetcher, PriceFetcher, FinancialFetcher, HSGTFetcher,
    IndustryFetcher, SpotFetcher, FundFlowFetcher, HSGT_DATA_END_DATE,
)
from universe import Universe
from factors import ALL_FACTORS, FACTOR_CLASS_MAP
from processor.pit_align import pit_merge
from processor.normalize import standardize_factor, zscore_cross_section, winsorize_cross_section
from processor.align import compute_forward_returns
from evaluator.ic_ir import evaluate_factor
from portfolio.combine import combine_ic_weight
from portfolio.builder import select_top_n_pct, assign_weights
from portfolio.backtest import run_backtest
from backtest.metrics import summarize, print_summary
from backtest.costs import A_COST
from risk.controls import apply_constraints

# 复用 eval_all_factors 的数据准备函数
from scripts.eval_all_factors import (
    download_constituent_prices,
    fetch_and_merge_financial,
    fetch_and_merge_hsgt,
    fetch_and_merge_fund_flow,
    ensure_fund_flow_factors,
    compute_all_factors,
    standardize_all_factors,
)


def add_direction_adjusted_z(panel: pd.DataFrame) -> None:
    """在 panel 上追加 _dz 列（方向调整后 z-score），不计算IC。
    用于滚动窗口IC加权流程。
    """
    for cls in ALL_FACTORS:
        f = cls() if isinstance(cls, type) else cls
        z_col = f"{f.name}_z"
        if z_col in panel.columns:
            panel[f"{f.name}_dz"] = panel[z_col] * f.direction


def evaluate_factors_for_ic(panel: pd.DataFrame, holding_period: int = 21) -> pd.DataFrame:
    """评估各因子IC，返回汇总表（用于确定IC加权权重）。

    关键：先对 z-score 做方向调整（乘以 direction），
    使得"方向调整后的z"越大=越好，IC应为正。
    副作用：在原 panel 上追加 _dz 列（方向调整后 z-score）。
    """
    # 计算forward return（如果还没有）— 直接在原panel上添加列，不重新赋值panel
    return_col = f"forward_{holding_period}d_return"
    if return_col not in panel.columns:
        tmp = compute_forward_returns(panel, periods=[holding_period])
        if return_col in tmp.columns:
            panel[return_col] = tmp[return_col].values

    rows = []
    for cls in ALL_FACTORS:
        f = cls() if isinstance(cls, type) else cls
        z_col = f"{f.name}_z"
        if z_col not in panel.columns:
            continue
        # 方向调整
        dz = panel[z_col] * f.direction
        panel[f"{f.name}_dz"] = dz

        df_eval = panel.dropna(subset=[z_col, return_col])
        if len(df_eval) < 30:
            continue
        results = evaluate_factor(df_eval.assign(_eval_z=dz), "_eval_z")
        if not results or return_col not in results:
            continue
        s = results[return_col].get("summary", {})
        rows.append({
            "factor": f.name,
            "category": f.category,
            "direction": f.direction,
            "ic_mean": s.get("ic_mean", 0),
            "ir": s.get("ir", 0),
            "ic_pos_rate": s.get("ic_positive_rate", 0),
            "n": s.get("n", 0),
        })
    return pd.DataFrame(rows)


def combine_factors_ic_weighted(
    panel: pd.DataFrame,
    ic_summary: pd.DataFrame,
    ir_threshold: float = 0.05,
) -> tuple[pd.Series, dict]:
    """用IC加权合成多因子得分。

    只用IR超过阈值的因子（避免噪音因子）。
    返回 (composite_score, weight_dict)。
    """
    # 筛选有效因子
    effective = ic_summary[ic_summary["ir"].abs() >= ir_threshold].copy()
    if effective.empty:
        print("    [WARN] 无有效因子(IR>=阈值)，退化为全部等权")
        effective = ic_summary.copy()

    # 构造IC均值字典：{factor_dz_col: ic_mean}
    ic_means = {}
    for _, row in effective.iterrows():
        col = f"{row['factor']}_dz"
        if col in panel.columns:
            # IC应为正（方向已调整），负的直接跳过
            ic = row["ic_mean"]
            if ic > 0:
                ic_means[col] = ic

    if not ic_means:
        print("    [WARN] 无正IC因子，退化为等权")
        factor_cols = [f"{r['factor']}_dz" for _, r in effective.iterrows()
                       if f"{r['factor']}_dz" in panel.columns]
        if not factor_cols:
            return pd.Series(np.nan, index=panel.index), {}
        return panel[factor_cols].mean(axis=1), {}

    factor_cols = list(ic_means.keys())
    # NaN-tolerant IC加权：缺失因子的权重自动重分配给可用因子
    # 不用 combine_ic_weight（它用 sum() 传播 NaN），而是手动计算加权均值
    w_arr = np.array([ic_means[c] for c in factor_cols])
    w_arr = w_arr / w_arr.sum()  # 归一化
    fdata = panel[factor_cols]
    mask = fdata.notna().values  # (n_rows, n_cols)
    vals = fdata.values
    weighted_sum = np.nansum(vals * w_arr, axis=1)  # sum(w_i * x_i) for non-NaN
    weight_used = np.nansum(mask * w_arr, axis=1)    # sum(w_i) for non-NaN
    composite_arr = np.where(weight_used > 1e-10, weighted_sum / weight_used, np.nan)
    composite = pd.Series(composite_arr, index=panel.index)

    # 打印权重
    total = sum(ic_means.values())
    print(f"    IC加权因子数: {len(ic_means)}")
    for col, ic in sorted(ic_means.items(), key=lambda x: -x[1]):
        fname = col.replace("_dz", "")
        w = ic / total
        print(f"      {fname:12s} IC={ic:+.4f} weight={w:.1%}")

    return composite, ic_means


def combine_factors_rolling_ic(
    panel: pd.DataFrame,
    ir_threshold: float = 0.05,
    rolling_window_months: int = 12,
    holding_period: int = 21,
    min_history_months: int = 3,
) -> tuple[pd.Series, dict]:
    """滚动窗口IC加权合成（walk-forward，无前视偏差）。

    每个调仓月只用过去N个月的IC确定权重，然后给当月打分。
    前 min_history_months 个月无足够历史，退化为等权。
    """
    return_col = f"forward_{holding_period}d_return"
    if return_col not in panel.columns:
        tmp = compute_forward_returns(panel, periods=[holding_period])
        if return_col in tmp.columns:
            panel[return_col] = tmp[return_col].values

    # 收集所有 _dz 列
    dz_cols = [c for c in panel.columns if c.endswith("_dz")]
    if not dz_cols:
        return pd.Series(np.nan, index=panel.index), {}

    # 月末调仓日期
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    monthly_last = dates.to_series().groupby(dates.to_period("M")).last().tolist()
    rebal_dates = [pd.Timestamp(d).normalize() for d in monthly_last]

    composite = pd.Series(np.nan, index=panel.index)
    out = np.full(len(panel), np.nan)  # pandas 3.0 安全的后备数组
    weight_log = {}  # {date_str: {factor: weight}}

    print(f"    滚动窗口: {rolling_window_months}个月, 调仓月数: {len(rebal_dates)}")

    for i, d in enumerate(rebal_dates):
        # 窗口：过去N个月的数据。
        # 上界不能只排除当月(< d)：窗口末尾行的 forward_{holding_period}d_return
        # 会用到 d 之后的收益 → 前视。故上界收紧到 d 之前第 holding_period 个交易日，
        # 保证窗口内每个 t 都满足 t+holding_period <= d，无前视泄漏。
        window_start = d - pd.DateOffset(months=rolling_window_months)
        _pos = dates.searchsorted(d)
        _cut = _pos - holding_period
        window_cutoff = dates[_cut] if _cut > 0 else window_start
        window_data = panel[(panel["date"] >= window_start) & (panel["date"] < window_cutoff)]

        # 当月截面数据
        month_data = panel[panel["date"] == d]

        if len(window_data) < 30 or i < min_history_months:
            # 历史不足，等权
            month_scores = month_data[dz_cols].mean(axis=1)
            pos = panel.index.get_indexer(month_scores.index)
            out[pos] = month_scores.to_numpy()
            weight_log[d.strftime("%Y-%m")] = {c: 1.0/len(dz_cols) for c in dz_cols}
            continue

        # 计算窗口内各因子IC
        ic_means = {}
        for col in dz_cols:
            df_eval = window_data.dropna(subset=[col, return_col])
            if len(df_eval) < 20:
                continue
            # 简单Spearman IC
            ic = df_eval[col].corr(df_eval[return_col], method="spearman")
            if not np.isnan(ic) and ic > 0:
                # IR近似：IC均值/IC标准差（按月分组算IC序列）
                monthly_ics = df_eval.groupby(df_eval["date"].dt.to_period("M")).apply(
                    lambda g: g[col].corr(g[return_col], method="spearman")
                    if len(g) > 5 and g[col].notna().sum() > 3 else np.nan
                ).dropna()
                ir = ic / monthly_ics.std() if len(monthly_ics) > 1 and monthly_ics.std() > 0 else 0
                if abs(ir) >= ir_threshold:
                    ic_means[col] = ic

        if not ic_means:
            # 无有效因子，等权
            month_scores = month_data[dz_cols].mean(axis=1)
            pos = panel.index.get_indexer(month_scores.index)
            out[pos] = month_scores.to_numpy()
            weight_log[d.strftime("%Y-%m")] = {c: 1.0/len(dz_cols) for c in dz_cols}
            continue

        # NaN-tolerant加权
        factor_cols = list(ic_means.keys())
        w_arr = np.array([ic_means[c] for c in factor_cols])
        w_arr = w_arr / w_arr.sum()
        fdata = month_data[factor_cols]
        mask = fdata.notna().values
        vals = fdata.values
        weighted_sum = np.nansum(vals * w_arr, axis=1)
        weight_used = np.nansum(mask * w_arr, axis=1)
        scores = np.where(weight_used > 1e-10, weighted_sum / weight_used, np.nan)
        pos = panel.index.get_indexer(month_data.index)
        out[pos] = scores
        weight_log[d.strftime("%Y-%m")] = {c: ic_means[c]/sum(ic_means.values()) for c in factor_cols}

    # 打印最末期权重
    if weight_log:
        last_key = sorted(weight_log.keys())[-1]
        last_w = weight_log[last_key]
        print(f"    最新月({last_key}) IC加权因子数: {len(last_w)}")
        for col, w in sorted(last_w.items(), key=lambda x: -x[1]):
            print(f"      {col.replace('_dz',''):12s} weight={w:.1%}")

    composite = pd.Series(out, index=panel.index)
    return composite, weight_log


def build_monthly_portfolio(
    panel: pd.DataFrame,
    score_col: str,
    top_pct: float = 0.10,
    weight_method: str = "equal",
    min_stocks: int = 5,
) -> pd.DataFrame:
    """月度调仓组合：月末选股，权重前填充至下月末。

    返回 panel 追加 selected/weight 列。
    """
    df = panel.copy()
    df["selected"] = False
    df["weight"] = 0.0

    # 月末日期
    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    rebal_dates = dates.to_series().groupby(dates.to_period("M")).last().tolist()
    rebal_set = set(pd.Timestamp(d).normalize() for d in rebal_dates)

    # 只在调仓日选股 + 分配权重
    for d in rebal_dates:
        d = pd.Timestamp(d).normalize()
        mask = df["date"] == d
        g = df[mask]
        valid = g[g[score_col].notna()]
        if len(valid) < min_stocks:
            continue
        n_select = max(int(len(valid) * top_pct), min_stocks)
        top_idx = valid.nlargest(n_select, score_col).index
        df.loc[top_idx, "selected"] = True
        if weight_method == "equal":
            df.loc[top_idx, "weight"] = 1.0 / n_select

    # 权重前填充：pivot → 仅调仓日有值 → ffill → 转回长格式
    wp = df.pivot_table(index="date", columns="ticker", values="weight", fill_value=0)
    wp = wp.sort_index()
    rebal_mask = wp.index.isin(rebal_set)
    # 非调仓日设为NaN，然后ffill
    wp_ff = wp.copy()
    wp_ff.loc[~rebal_mask] = np.nan
    wp_ff = wp_ff.ffill().fillna(0)

    wl = wp_ff.stack().reset_index()
    wl.columns = ["date", "ticker", "weight_ff"]
    df = df.drop(columns=["weight"]).merge(wl, on=["date", "ticker"], how="left")
    df["weight"] = df["weight_ff"].fillna(0)
    df = df.drop(columns=["weight_ff"])
    # selected 也前填充
    sp = df.pivot_table(index="date", columns="ticker", values="selected", fill_value=False)
    sp = sp.sort_index()
    sp_ff = sp.astype(object).copy()
    sp_ff.loc[~rebal_mask] = np.nan
    sp_ff = sp_ff.ffill().fillna(False)
    sl = sp_ff.stack().reset_index()
    sl.columns = ["date", "ticker", "sel_ff"]
    df = df.drop(columns=["selected"]).merge(sl, on=["date", "ticker"], how="left")
    df["selected"] = df["sel_ff"].fillna(False)
    df = df.drop(columns=["sel_ff"])

    return df, rebal_dates


def get_stock_names(tickers: list[str]) -> dict[str, str]:
    """获取股票名称（用于输出）。"""
    try:
        import akshare as ak
        info = ak.stock_info_a_code_name()
        name_map = dict(zip(info["code"], info["name"]))
        return {t: name_map.get(t, t) for t in tickers}
    except Exception:
        return {t: t for t in tickers}


def main():
    parser = argparse.ArgumentParser(description="多因子选股 + 月度调仓回测")
    parser.add_argument("--index", default="000300", help="指数代码（默认沪深300）")
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default=None)
    parser.add_argument("--max-stocks", type=int, default=5, help="最多下载几只（0=全部）")
    parser.add_argument("--top-pct", type=float, default=10, help="选股比例%%（如10=Top10%%）")
    parser.add_argument("--from-panel", default=None, help="从已保存的panel parquet加载")
    parser.add_argument("--ir-threshold", type=float, default=0.03, help="IR阈值，低于此值的因子不参与合成")
    parser.add_argument("--no-backtest", action="store_true", help="跳过回测，只输出选股")
    parser.add_argument("--skip-em", action="store_true", help="跳过东财源，直走新浪（东财不通时有用）")
    parser.add_argument("--with-hsgt", action="store_true",
                        help="启用北向持股因子（默认关闭：stock_hsgt 数据仅至2024-08-16，已停更，对当前选股无效）")
    parser.add_argument("--skip-hsgt", action="store_true",
                        help="[已弃用] 北向默认即跳过，此开关保留仅为向后兼容")
    parser.add_argument("--skip-fund-flow", action="store_true",
                        help="跳过个股资金流获取（当前网络不通时避免长重试超时）")
    parser.add_argument("--rolling-months", type=int, default=12, help="滚动IC窗口月数（0=全样本IC，有前视偏差；默认12=walk-forward）")
    args = parser.parse_args()

    top_pct = args.top_pct / 100.0
    print("=" * 60)
    print(f" 多因子选股 | 基准: {args.index} | Top: {args.top_pct}%")
    print(f" 区间: {args.start} ~ {args.end or '最新'} | 股票数: {args.max_stocks or '全部'}")
    print(f" IC加权: {'滚动' + str(args.rolling_months) + '月' if args.rolling_months > 0 else '全样本(有前视偏差)'}")
    print("=" * 60)

    # ── 1. 数据准备 ──────────────────────────────────────────────
    if args.from_panel:
        print("\n[Step 1] 加载 panel...")
        p = Path(args.from_panel)
        if p.exists():
            panel = pd.read_parquet(p)
            print(f"    从 parquet 加载: {panel.shape[0]} rows")
        else:
            # 回退：从 SQLite 因子面板加载（run_factor_calc 已写入 ashare.db.factor_panel）
            from fetcher.store.db import load_factor_panel
            print(f"    parquet 不存在，从 SQLite(ashare.db.factor_panel) 加载 (start={args.start})...")
            panel = load_factor_panel("ashare", start=args.start)
            if panel.empty:
                print("ERROR: SQLite 因子面板为空，请先跑 scripts/run_factor_calc.py")
                return 1
            panel["date"] = pd.to_datetime(panel["date"], format="ISO8601").dt.normalize()
            print(f"    从 SQLite 加载: {panel.shape[0]} rows")
        print(f"    Panel: {panel.shape[0]} rows x {panel.shape[1]} cols")
        print(f"    股票数: {panel['ticker'].nunique()}")
        print(f"    日期范围: {panel['date'].min().date()} ~ {panel['date'].max().date()}")

        # 资金流补合：旧 factor_panel 可能缺资金流列，从 db 合并并补算因子
        if "main_net_inflow" not in panel.columns:
            try:
                from fetcher.fund_flow import load_fund_flow_panel
                ff_tickers = panel["ticker"].astype(str).str.zfill(6).unique().tolist()
                flow_panel = load_fund_flow_panel(ff_tickers, market="ashare")
                if not flow_panel.empty:
                    keep_cols = [c for c in ["date", "ticker", "main_net_inflow",
                                            "super_big_net_inflow", "big_net_inflow",
                                            "mid_net_inflow", "small_net_inflow"]
                                 if c in flow_panel.columns]
                    panel = panel.merge(flow_panel[keep_cols], on=["date", "ticker"], how="left")
                    print(f"    资金流从 db 补合: {flow_panel['ticker'].nunique()} 只")
            except Exception as e:
                print(f"    资金流补合失败: {e}")
        try:
            panel = ensure_fund_flow_factors(panel)
        except Exception as e:
            print(f"    资金流因子补算失败: {e}")
    else:
        print("\n[Step 1] 获取成分股 + 下载数据...")
        u = Universe(mode="A", start=args.start, end=args.end, index_symbol=args.index)
        cons = u.constituents()
        tickers = cons["ticker"].tolist()
        if args.max_stocks > 0:
            tickers = tickers[:args.max_stocks]
        print(f"    成分数: {len(tickers)}")

        # 行情
        panel = download_constituent_prices(tickers, args.start, args.end or "", "A", args.max_stocks, skip_em=args.skip_em)
        if panel.empty:
            print("ERROR: 无行情数据")
            return 1
        print(f"    Panel: {panel.shape[0]} rows, 股票: {panel['ticker'].nunique()}")

        # 基准
        try:
            pf = PriceFetcher()
            bm = pf.get_benchmark_daily(args.index, start_date=args.start, end_date=args.end or "")
            if not bm.empty:
                bm["bench_ret"] = bm["close"].pct_change()
                panel = panel.merge(bm[["date", "bench_ret"]], on="date", how="left")
        except Exception as e:
            print(f"    基准失败: {e}")

        # 财报（先于Spot，因为Spot需要财报数据算PE/PB）
        ff = FinancialFetcher()
        panel = fetch_and_merge_financial(panel, tickers, ff)

        # Spot（市值/PE/PB）—— 从 close×outstanding_share + 财报数据计算
        try:
            sf = SpotFetcher()
            panel = sf.attach_to_panel(panel, tickers)
            print(f"    Spot(计算)完成: market_cap/pe_ttm/pb")
        except Exception as e:
            print(f"    Spot 失败: {e}")

        # 北向：默认退役（stock_hsgt 数据仅至 2024-08-16 已停更，对当前截面为 NaN，白拉且拖慢）
        # 仅在显式 --with-hsgt 且未 --skip-hsgt 时才拉取（用于历史回溯研究）
        if args.with_hsgt and not args.skip_hsgt:
            hf = HSGTFetcher()
            panel = fetch_and_merge_hsgt(panel, tickers, hf)
        else:
            print("\n[Step 4] 北向持股默认退役（数据仅至 2024-08-16 停更；如需历史回溯用 --with-hsgt 启用）")

        # 资金流
        if not args.skip_fund_flow:
            try:
                fflow = FundFlowFetcher()
                panel = fetch_and_merge_fund_flow(panel, tickers, fflow)
            except Exception as e:
                print(f"    资金流失败: {e}")
        else:
            print("\n[Step 4.5] 跳过个股资金流（--skip-fund-flow）")

    # ── 2. 因子计算 + 标准化 ─────────────────────────────────────
    if "EP_z" not in panel.columns:
        print("\n[Step 2] 计算24因子 + 标准化...")
        panel = compute_all_factors(panel)
        panel = standardize_all_factors(panel, do_neutralize=True)
    else:
        print("\n[Step 2] 因子已标准化（从parquet加载）")

    z_cols = [c for c in panel.columns if c.endswith("_z") and not c.endswith("_dz")]
    print(f"    z-score 列数: {len(z_cols)}")

    # ── 3. IC评估 + 因子合成 ─────────────────────────────────────
    if args.rolling_months > 0:
        # 滚动窗口IC（walk-forward，无前视偏差）
        print(f"\n[Step 3] 滚动IC加权合成（窗口={args.rolling_months}月, IR阈值={args.ir_threshold}）...")
        add_direction_adjusted_z(panel)
        composite, weight_log = combine_factors_rolling_ic(
            panel, ir_threshold=args.ir_threshold,
            rolling_window_months=args.rolling_months, holding_period=21,
        )
    else:
        # 全样本IC（有前视偏差，仅作对比）
        print("\n[Step 3] 全样本IC评估（21日持有期）[注意: 有前视偏差]...")
        ic_summary = evaluate_factors_for_ic(panel, holding_period=21)
        if ic_summary.empty:
            print("ERROR: 无有效因子评估结果")
            return 1
        ic_summary = ic_summary.sort_values("ir", ascending=False)
        print(ic_summary.to_string(index=False, float_format="%.4f"))

        print(f"\n[Step 4] IC加权合成（IR阈值={args.ir_threshold}）...")
        composite, weight_dict = combine_factors_ic_weighted(
            panel, ic_summary, ir_threshold=args.ir_threshold
        )
    panel["composite_score"] = composite
    valid = composite.notna().sum()
    print(f"    合成得分有效值: {valid}/{len(composite)}")

    # ── 5. 最新持仓 ──────────────────────────────────────────────
    print(f"\n[Step 5] 最新推荐持仓（Top {args.top_pct}%）...")
    latest_date = panel["date"].max()
    latest = panel[panel["date"] == latest_date].copy()
    latest_valid = latest[latest["composite_score"].notna()]

    if len(latest_valid) == 0:
        print(f"    [WARN] 最新日期 {latest_date.date()} 无有效合成得分")
        print(f"    (可能原因：部分因子数据已到期，如北向资金于 2024.08 停更)")
        # 回退：用最近一个有有效得分的日期
        for d in sorted(panel["date"].unique(), reverse=True)[1:]:
            t = panel[panel["date"] == d]
            tv = t[t["composite_score"].notna()]
            if len(tv) > 0:
                latest_date = d
                latest_valid = tv
                print(f"    回退至: {latest_date.date()} ({len(latest_valid)} 有效)")
                break

    if len(latest_valid) == 0:
        print("    ERROR: 整个 panel 无有效合成得分，无法选股")
    else:
        n_select = max(int(len(latest_valid) * top_pct), 5)
        holdings = latest_valid.nlargest(n_select, "composite_score").copy()

        # 获取股票名称
        name_map = get_stock_names(holdings["ticker"].tolist())

        # 等权
        holdings["weight"] = 1.0 / len(holdings)
        holdings["name"] = holdings["ticker"].map(name_map)

        print(f"    日期: {latest_date.date()}")
        print(f"    选股数: {len(holdings)} / {len(latest_valid)} 有效")
        print(f"\n    {'代码':8s} {'名称':10s} {'权重':>6s} {'得分':>8s}")
        print(f"    {'-'*8} {'-'*10} {'-'*6} {'-'*8}")
        for _, r in holdings.iterrows():
            print(f"    {r['ticker']:8s} {str(r['name']):10s} {r['weight']:5.1%} {r['composite_score']:+8.4f}")

        # 保存持仓 → report/<运行日期>/ashare_holdings.csv + .html
        # 不包含数据日期在文件名中（避免不同数据日期产生不同文件堆积）
        save_csv_html(
            "ashare", "holdings",
            holdings[["ticker", "name", "weight", "composite_score"]],
            title=f"A股 推荐持仓 {latest_date.strftime('%Y%m%d')}",
            subtitle=f"基准 {args.index} Top {args.top_pct}% 等权",
        )

    # ── 6. 回测 ──────────────────────────────────────────────────
    if not args.no_backtest:
        print(f"\n[Step 6] 月度调仓回测（Top {args.top_pct}%, 等权, A股成本）...")
        panel_bt, rebal_dates = build_monthly_portfolio(
            panel, "composite_score", top_pct=top_pct, weight_method="equal"
        )

        # 风控约束
        if "industry" in panel_bt.columns:
            panel_bt = apply_constraints(panel_bt, "weight", "date", "industry",
                                         max_stock_weight=0.05, max_industry_weight=0.30)
        else:
            print("    (无行业列，跳过行业约束)")

        # 日收益率
        if "daily_return" not in panel_bt.columns:
            panel_bt["daily_return"] = panel_bt.groupby("ticker")["close"].pct_change()

        result = run_backtest(
            panel_bt,
            rebalance_dates=rebal_dates,
            cost_model=A_COST,
            return_col="daily_return",
            weight_col="weight",
            date_col="date",
            benchmark_col="bench_ret" if "bench_ret" in panel_bt.columns else None,
            strategy_name=f"multi_factor_top{args.top_pct}",
        )

        m = summarize(
            result.daily_returns,
            result.equity,
            result.turnover,
            result.benchmark_returns,
        )
        print_summary(m, title=f"多因子选股 Top{args.top_pct}% 月度调仓")

        # 保存净值曲线 → report/<运行日期>/ashare_equity_<idx>_<pct>pct.csv + .html
        save_csv_html(
            "ashare", f"equity_{args.index}_{args.top_pct}pct",
            result.equity.rename("equity"),
            title=f"A股 净值曲线 {args.index} Top{args.top_pct}%",
            subtitle="月度调仓等权（含 A股交易成本）",
        )

        # 调仓统计
        print(f"\n    调仓次数: {len(rebal_dates)}")
        print(f"    平均换手率: {result.turnover.mean():.2%}")
        print(f"    年化换手率: {result.turnover.mean() * 252:.1%}")

    # 保存完整 panel → report/<运行日期>/ashare_select_panel_<n>stocks.parquet (+csv)
    save_panel("ashare", f"select_panel_{args.max_stocks}stocks", panel)
    print(f"\n    完整 panel 已保存至 report/")

    print(f"\n{'='*60}")
    print(" 选股完成")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
