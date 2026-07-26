"""港股复合因子构建 + 回测 + 选股。

选用 5 个低相关有效因子（21d IR > 0.05）：
  BP    (IR=0.256, value)
  EP    (IR=0.183, value)
  EpG   (IR=0.116, growth)
  GPM   (IR=0.087, quality)
  Rev1m (IR=0.073, reversal)

复合方式：
  1. 等权 z-score 合成
  2. 滚动 IC 加权（动态权重）

回测：
  - 全样本 5 分位组合
  - Top 20 等权组合净值曲线
  - 年化收益/夏普/最大回撤/胜率

选股：
  - 最新截面前 20 名
"""
from __future__ import annotations

import sys, time, warnings, gc
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from scipy import stats
from report_utils import save_csv_html, save_panel
warnings.filterwarnings("ignore")

from fetcher.store.db import load_factor_panel, query, load_universe

# ================================================================
# 配置
# ================================================================
SELECTED_FACTORS = ["BP", "EP", "EpG", "GPM", "Rev1m"]
FACTOR_WEIGHTS_EQUAL = {f: 1.0 / len(SELECTED_FACTORS) for f in SELECTED_FACTORS}
N_GROUPS = 5
TOP_N = 20
FORWARD_PERIOD = 21
ROLLING_IC_WINDOW = 60  # 滚动IC窗口（交易日）


def _build_hk_name_map():
    """从 hk.db.ref_universe(name 列) 取 ticker->名称 映射，回退 financial_indicator。"""
    try:
        uni = load_universe("hk")
        if uni is not None and not uni.empty:
            uni["ticker"] = uni["ticker"].astype(str)
            mp = dict(zip(uni["ticker"], uni["name"].astype(str)))
            print(f"  [OK] 名称映射来自 db(ref_universe): {len(mp)} 只")
            return mp
    except Exception as e:
        print(f"  [WARN] ref_universe 名称加载失败: {e}")
    # 回退：financial_indicator 的 SECURITY_NAME_ABBR + ticker_code
    try:
        fin = query(
            "SELECT ticker_code, SECURITY_NAME_ABBR FROM financial_indicator",
            market="hk",
        ).dropna()
        fin = fin.drop_duplicates("ticker_code")
        return dict(zip(fin["ticker_code"].astype(str), fin["SECURITY_NAME_ABBR"]))
    except Exception as e:
        print(f"  [WARN] 名称映射回退也失败: {e}")
        return {}


def _enrich_names(panel, name_map):
    """给 panel 补 name 列（若已有则跳过）。"""
    if "name" in panel.columns:
        return panel
    if not name_map:
        return panel
    panel["name"] = panel["ticker"].astype(str).map(name_map)
    miss = panel["name"].isna().sum()
    if miss:
        print(f"  [WARN] {miss} 只股票未能匹配名称")
    else:
        print(f"  [OK] 已补 {len(name_map)} 个港股名称")
    return panel


def load_panel():
    """从 hk.db.factor_panel 加载 panel，只保留需要的列。"""
    print("Loading panel from hk.db (factor_panel)...", end=" ", flush=True)
    name_map = _build_hk_name_map()
    panel = load_factor_panel("hk")
    if panel.empty:
        print("EMPTY")
        return panel
    panel["ticker"] = panel["ticker"].astype(str)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.normalize()
    keep = ["date", "ticker"]
    for f in SELECTED_FACTORS:
        z = f"{f}_z"
        if z in panel.columns:
            keep.append(z)
    for p in [1, 5, FORWARD_PERIOD]:
        c = f"forward_{p}d_return"
        if c in panel.columns:
            keep.append(c)
    if "industry" in panel.columns:
        keep.append("industry")
    panel = panel[keep].copy()
    panel = _enrich_names(panel, name_map)
    if "name" in panel.columns and "name" not in keep:
        keep.append("name")
        panel = panel[keep].copy()
    # SQLite 全 NULL 列读回为 object 类型，强制转 float 避免合成时报 dtype 错
    for c in panel.columns:
        if c.endswith("_z") or c.endswith("_raw") or c.startswith("forward_"):
            panel[c] = pd.to_numeric(panel[c], errors="coerce")
    print(f"{panel.shape}")
    return panel


def build_equal_weight_composite(panel):
    """等权 z-score 合成。"""
    print("\n=== Building Equal-Weight Composite ===")
    z_cols = [f"{f}_z" for f in SELECTED_FACTORS if f"{f}_z" in panel.columns]
    
    # 逐日截面均值合成
    def composite_row(group):
        vals = group[z_cols].copy()
        # 缺失因子用截面均值填充（不丢股票）
        for c in z_cols:
            if vals[c].isna().any():
                vals[c] = vals[c].fillna(vals[c].mean())
        return vals.mean(axis=1)
    
    panel["composite_eq"] = np.nan
    for d, g in panel.groupby("date"):
        idx = g.index
        panel.loc[idx, "composite_eq"] = composite_row(g)
    
    valid = panel["composite_eq"].notna().sum()
    print(f"  Composite (equal weight): {valid}/{len(panel)} ({valid/len(panel):.1%})")
    print(f"  Factors used: {z_cols}")
    print(f"  Weights: {FACTOR_WEIGHTS_EQUAL}")
    return panel


def build_rolling_ic_weight_composite(panel):
    """滚动 IC 加权合成。"""
    print("\n=== Building Rolling-IC-Weight Composite ===")
    z_cols = [f"{f}_z" for f in SELECTED_FACTORS if f"{f}_z" in panel.columns]
    ret_col = f"forward_{FORWARD_PERIOD}d_return"
    
    dates = sorted(panel["date"].unique())
    n_dates = len(dates)
    
    # 预计算每个因子的逐日 IC
    ic_dict = {c: {} for c in z_cols}
    for i, d in enumerate(dates):
        g = panel.loc[panel["date"] == d, z_cols + [ret_col]].dropna(subset=[ret_col])
        if len(g) < 5:
            continue
        for c in z_cols:
            g2 = g.dropna(subset=[c])
            if len(g2) < 5 or g2[c].std() < 1e-12:
                continue
            r, _ = stats.spearmanr(g2[c].values, g2[ret_col].values)
            if np.isfinite(r):
                ic_dict[c][i] = r
    
    # 滚动窗口均值作为权重
    ic_df = pd.DataFrame(ic_dict)
    rolling_ic = ic_df.rolling(window=ROLLING_IC_WINDOW, min_periods=20).mean()
    
    # 标准化权重（绝对值归一，保留方向）
    weights_df = rolling_ic.div(rolling_ic.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(1.0 / len(z_cols))
    
    print(f"  Rolling IC window: {ROLLING_IC_WINDOW} days")
    print(f"  IC history: {ic_df.shape}")
    
    # 逐日合成
    panel["composite_ic"] = np.nan
    for i, d in enumerate(dates):
        g = panel.loc[panel["date"] == d]
        if len(g) < 5:
            continue
        
        if i < len(weights_df):
            w = weights_df.iloc[i].dropna()
        else:
            w = pd.Series({c: 1.0/len(z_cols) for c in z_cols})
        
        if w.empty or w.abs().sum() < 1e-12:
            w = pd.Series({c: 1.0/len(z_cols) for c in z_cols})
        
        # 加权合成
        composite = np.zeros(len(g))
        weight_sum = 0
        for c in z_cols:
            if c in w.index:
                wi = w[c]
                vals = g[c].values
                # 填缺失为截面均值
                if np.isnan(vals).any():
                    mask = ~np.isnan(vals)
                    if mask.sum() > 0:
                        vals = vals.copy()
                        vals[~mask] = vals[mask].mean()
                    else:
                        continue
                composite += wi * vals
                weight_sum += abs(wi)
        
        if weight_sum > 1e-12:
            composite /= weight_sum
            panel.loc[g.index, "composite_ic"] = composite
    
    valid = panel["composite_ic"].notna().sum()
    print(f"  Composite (IC weight): {valid}/{len(panel)} ({valid/len(panel):.1%})")
    
    # 打印最新一期权重
    if not weights_df.empty:
        last_w = weights_df.iloc[-1].dropna()
        print(f"\n  Latest IC weights:")
        for c, v in last_w.items():
            print(f"    {c.replace('_z',''):<8s} {v:>+8.4f}")
    
    return panel


def backtest_composite(panel, composite_col="composite_eq"):
    """回测复合因子：分位组合 + Top20 净值曲线。"""
    print(f"\n=== Backtest: {composite_col} ===")
    ret_col = f"forward_{FORWARD_PERIOD}d_return"
    ret1d = "forward_1d_return"
    
    if composite_col not in panel.columns or ret_col not in panel.columns:
        print("  Missing columns")
        return
    
    dates = sorted(panel["date"].unique())
    
    # --- 分位组合 ---
    q_means = {1: [], 2: [], 3: [], 4: [], 5: []}
    ls_list = []
    
    for d in dates:
        g = panel.loc[panel["date"] == d, [composite_col, ret_col]].dropna()
        if len(g) < N_GROUPS:
            continue
        try:
            ranks = g[composite_col].rank(method="first")
            q = pd.qcut(ranks, N_GROUPS, labels=False) + 1
        except ValueError:
            continue
        for qi in range(1, N_GROUPS + 1):
            mask = q == qi
            if mask.sum() > 0:
                q_means[qi].append(g.loc[mask, ret_col].mean())
        ls_list.append(g.loc[q == N_GROUPS, ret_col].mean() - g.loc[q == 1, ret_col].mean())
    
    print(f"\n  Quantile Portfolio (21d holding):")
    for qi in range(1, N_GROUPS + 1):
        avg = np.mean(q_means[qi]) if q_means[qi] else np.nan
        print(f"    Q{qi}: {avg:+.4f}")
    
    ls_arr = np.array([x for x in ls_list if np.isfinite(x)])
    ls_mean = ls_arr.mean()
    ls_std = ls_arr.std()
    ls_ir = ls_mean / ls_std if ls_std > 1e-12 else np.nan
    
    qs = [np.mean(q_means[i]) if q_means[i] else np.nan for i in range(1, 6)]
    valid = [(i+1, m) for i, m in enumerate(qs) if np.isfinite(m)]
    mono = float(np.corrcoef([v[0] for v in valid], [v[1] for v in valid])[0, 1]) if len(valid) >= 2 else np.nan
    
    print(f"    Long-Short: {ls_mean:+.4f}  IR: {ls_ir:+.3f}  Mono: {mono:+.2f}")
    
    # --- Top20 等权组合净值曲线 ---
    if ret1d not in panel.columns:
        print("  No 1d return for NAV curve")
        return
    
    print(f"\n  Top{TOP_N} Equal-Weight Portfolio (daily rebalance proxy):")
    
    # 逐日选 Top N，用 forward_1d_return 做净值
    nav_dates = []
    nav_values = []
    nav = 1.0
    
    for i, d in enumerate(dates):
        g = panel.loc[panel["date"] == d, [composite_col, ret1d]].dropna()
        if len(g) < TOP_N:
            continue
        
        # 选 Top N
        top = g.nlargest(TOP_N, composite_col)
        daily_ret = top[ret1d].mean()
        if np.isfinite(daily_ret):
            nav *= (1 + daily_ret)
            nav_dates.append(d)
            nav_values.append(nav)
    
    nav_series = pd.Series(nav_values, index=nav_dates)
    
    # 统计
    daily_rets = nav_series.pct_change().dropna()
    ann_ret = daily_rets.mean() * 252
    ann_vol = daily_rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    max_dd = ((nav_series / nav_series.cummax()) - 1).min()
    win_rate = (daily_rets > 0).mean()
    
    print(f"    Period: {nav_dates[0].date()} ~ {nav_dates[-1].date()}")
    print(f"    Final NAV: {nav_series.iloc[-1]:.4f}")
    print(f"    Ann Return: {ann_ret:+.2%}")
    print(f"    Ann Vol:    {ann_vol:.2%}")
    print(f"    Sharpe:     {sharpe:.3f}")
    print(f"    Max DD:     {max_dd:.2%}")
    print(f"    Win Rate:   {win_rate:.1%}")
    
    # --- Bottom20 对比 ---
    nav_b = 1.0
    for d in dates:
        g = panel.loc[panel["date"] == d, [composite_col, ret1d]].dropna()
        if len(g) < TOP_N:
            continue
        bottom = g.nsmallest(TOP_N, composite_col)
        daily_ret = bottom[ret1d].mean()
        if np.isfinite(daily_ret):
            nav_b *= (1 + daily_ret)
    
    print(f"\n    Bottom{TOP_N} NAV: {nav_b:.4f} (对比)")
    print(f"    Top-Bottom spread: {nav_series.iloc[-1] - nav_b:+.4f}")
    
    return nav_series


def select_latest_stocks(panel, composite_col="composite_eq"):
    """最新截面前 TOP_N 名。"""
    print(f"\n=== Latest Selection (Top {TOP_N}) ===")
    
    if composite_col not in panel.columns:
        print("  Composite column not found")
        return
    
    latest_date = panel["date"].max()
    g = panel.loc[panel["date"] == latest_date].copy()
    g = g.dropna(subset=[composite_col])
    
    if len(g) < TOP_N:
        print(f"  Only {len(g)} stocks available")
    
    top = g.nlargest(TOP_N, composite_col)
    
    # 整理输出
    out_cols = ["ticker", "name", composite_col]
    for f in SELECTED_FACTORS:
        z = f"{f}_z"
        if z in top.columns:
            out_cols.append(z)
    
    # 添加原始因子值
    
    print(f"\n  Date: {latest_date.date()}")
    print(f"  Total candidates: {len(g)}")
    print(f"\n  {'Rank':<5} {'Ticker':<8} {'Name':<12} {'Composite':>10}", end="")
    for f in SELECTED_FACTORS:
        print(f" {f:>8}", end="")
    print()
    print("  " + "-" * 80)
    
    for rank, (_, row) in enumerate(top.iterrows(), 1):
        name = row.get("name", "")
        print(f"  {rank:<5} {row['ticker']:<8} {str(name):<12s} {row[composite_col]:>+10.3f}", end="")
        for f in SELECTED_FACTORS:
            z = f"{f}_z"
            v = row.get(z, np.nan)
            print(f" {v:>+8.3f}", end="")
        print()
    
    return top


def main():
    t0 = time.time()
    print("=" * 70)
    print(" HK Composite Factor + Backtest + Selection")
    print("=" * 70)
    
    panel = load_panel()
    
    # 1. 等权复合
    panel = build_equal_weight_composite(panel)
    
    # 2. 滚动IC加权复合
    panel = build_rolling_ic_weight_composite(panel)
    
    # 3. 回测等权复合
    nav_eq = backtest_composite(panel, "composite_eq")
    
    # 4. 回测IC加权复合
    nav_ic = backtest_composite(panel, "composite_ic")
    
    # 5. 选股（等权）
    top_eq = select_latest_stocks(panel, "composite_eq")
    
    # 6. 选股（IC加权）
    top_ic = select_latest_stocks(panel, "composite_ic")
    
    # 7. 保存 → report/<运行日期>/ (CSV + HTML)
    print("\n=== Saving to report/ ===")
    # 完整因子面板（parquet 快照 + csv；大表不生成 HTML）
    save_cols = ["date", "ticker"]
    if "name" in panel.columns:
        save_cols.append("name")
    save_cols += ["composite_eq", "composite_ic"]
    for f in SELECTED_FACTORS:
        z = f"{f}_z"
        if z in panel.columns:
            save_cols.append(z)
    save_panel("hk", "composite_factor", panel[save_cols])

    # 选股结果（等权 / IC加权）
    if top_eq is not None:
        save_csv_html("hk", "top20_equal_weight", top_eq,
                      title="港股 Top20 等权选股",
                      subtitle="composite_eq 前20名（含各因子z值）")
    if top_ic is not None:
        save_csv_html("hk", "top20_ic_weight", top_ic,
                      title="港股 Top20 IC加权选股",
                      subtitle="composite_ic 前20名（含各因子z值）")

    # 净值曲线（等权 / IC加权）
    if nav_eq is not None:
        save_csv_html("hk", "nav_equal_weight", nav_eq,
                      title="港股 Top20 等权净值曲线",
                      subtitle="每日再平衡代理净值（forward_1d_return）")
    if nav_ic is not None:
        save_csv_html("hk", "nav_ic_weight", nav_ic,
                      title="港股 Top20 IC加权净值曲线",
                      subtitle="每日再平衡代理净值（forward_1d_return）")

    elapsed = time.time() - t0
    print(f"\nTotal elapsed: {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
