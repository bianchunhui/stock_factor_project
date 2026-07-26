"""美股复合因子构建 + 回测 + 选股（道指 30）。

选用 5 个低相关有效因子（价值 + 反转 + 动量 + 低波）：
  BP    (value, 市净率倒数)
  EP    (value, 市盈率倒数)
  Rev1m (reversal, 1月反转，负向)
  Mom12m(momentum, 12月动量剔除近1月)
  Vol60 (low-vol, 60日波动率，负向)

复合方式：等权 z-score + 滚动 IC 加权（动态权重）
回测：全样本 5 分位 + Top10 等权净值曲线
选股：最新截面前 10 名

产出：
  data/factors/us_composite_factor.parquet
  data/factors/us_top10_equal_weight.csv
  data/factors/us_top10_ic_weight.csv
  data/factors/us_nav_equal_weight.csv
  data/factors/us_nav_ic_weight.csv
"""
from __future__ import annotations

import sys, time, warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from scipy import stats
from report_utils import save_csv_html, save_panel

warnings.filterwarnings("ignore")

from fetcher.store.db import load_factor_panel, load_universe

UNIVERSE = "data/dj_universe_20260710.csv"
PANEL = "data/us_full_factor_panel.parquet"
SELECTED_FACTORS = ["BP", "EP", "Rev1m", "Mom12m", "Vol60"]
# 方向：raw z 越高不代表越好，合成前必须乘方向（越高=越好）。
# 修复：原等权/IC 加权均未乘方向，导致 Rev1m/Vol60 被用反。
FACTOR_DIRECTION = {"BP": 1, "EP": 1, "Rev1m": -1, "Mom12m": 1, "Vol60": -1}
FACTOR_WEIGHTS_EQUAL = {f: 1.0 / len(SELECTED_FACTORS) for f in SELECTED_FACTORS}
N_GROUPS = 5
TOP_N = 10
FORWARD_PERIOD = 21
ROLLING_IC_WINDOW = 60


def _build_us_name_map() -> dict:
    try:
        uni = load_universe("us")
        if uni is not None and not uni.empty:
            uni["ticker"] = uni["ticker"].astype(str).str.upper()
            mp = dict(zip(uni["ticker"], uni["name"].astype(str)))
            print(f"  [OK] 名称映射来自 db(ref_universe): {len(mp)} 只")
            return mp
    except Exception as e:
        print(f"  [WARN] ref_universe 名称加载失败: {e}")
    try:
        df = pd.read_csv(UNIVERSE, dtype={"ticker": str})
        df["ticker"] = df["ticker"].astype(str).str.upper()
        return dict(zip(df["ticker"], df["name"].astype(str)))
    except Exception as e:
        print(f"  [WARN] 名称映射加载失败: {e}")
        return {}
    return {}


def load_panel() -> pd.DataFrame:
    print("Loading US panel from us.db (factor_panel)...", end=" ", flush=True)
    name_map = _build_us_name_map()
    panel = load_factor_panel("us")
    if panel.empty:
        print("EMPTY")
        return panel
    panel["ticker"] = panel["ticker"].astype(str).str.upper()
    if "name" not in panel.columns:
        panel["name"] = panel["ticker"].map(name_map)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.normalize()
    # SQLite 全 NULL 列读回为 object 类型，强制转 float 避免合成时报 dtype 错
    for c in panel.columns:
        if c.endswith("_z") or c.endswith("_raw") or c.startswith("forward_"):
            panel[c] = pd.to_numeric(panel[c], errors="coerce")
    keep = ["date", "ticker"]
    if "name" in panel.columns:
        keep.append("name")
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
    print(f"{panel.shape}")
    miss = panel["name"].isna().sum() if "name" in panel.columns else len(panel)
    if miss:
        print(f"  [WARN] {miss} 行未匹配名称")
    return panel


def build_equal_weight_composite(panel: pd.DataFrame) -> pd.DataFrame:
    print("\n=== Equal-Weight Composite ===")
    z_cols = [f"{f}_z" for f in SELECTED_FACTORS if f"{f}_z" in panel.columns]

    def composite_row(g):
        vals = g[z_cols].copy()
        for c in z_cols:
            f = c.replace("_z", "")
            vals[c] = vals[c] * FACTOR_DIRECTION.get(f, 1)  # 方向调整：越高越好
            if vals[c].isna().any():
                vals[c] = vals[c].fillna(vals[c].mean())
        return vals.mean(axis=1)

    panel["composite_eq"] = np.nan
    for d, g in panel.groupby("date"):
        panel.loc[g.index, "composite_eq"] = composite_row(g)

    valid = panel["composite_eq"].notna().sum()
    print(f"  Composite (equal): {valid}/{len(panel)} ({valid/len(panel):.1%})")
    print(f"  Weights: {FACTOR_WEIGHTS_EQUAL}")
    return panel


def build_rolling_ic_weight_composite(panel: pd.DataFrame) -> pd.DataFrame:
    print("\n=== Rolling-IC-Weight Composite ===")
    z_cols = [f"{f}_z" for f in SELECTED_FACTORS if f"{f}_z" in panel.columns]
    s_cols = [f"{c}_signed" for c in z_cols]
    for c, sc in zip(z_cols, s_cols):
        f = c.replace("_z", "")
        panel[sc] = panel[c] * FACTOR_DIRECTION.get(f, 1)  # 方向调整：越高越好
    ret_col = f"forward_{FORWARD_PERIOD}d_return"
    dates = sorted(panel["date"].unique())

    ic_dict = {c: {} for c in z_cols}
    for i, d in enumerate(dates):
        g = panel.loc[panel["date"] == d, s_cols + [ret_col]].dropna(subset=[ret_col])
        if len(g) < 5:
            continue
        for c, sc in zip(z_cols, s_cols):
            g2 = g.dropna(subset=[sc])
            if len(g2) < 5 or g2[sc].std() < 1e-12:
                continue
            r, _ = stats.spearmanr(g2[sc].values, g2[ret_col].values)
            if np.isfinite(r):
                ic_dict[c][i] = r

    ic_df = pd.DataFrame(ic_dict)
    rolling_ic = ic_df.rolling(window=ROLLING_IC_WINDOW, min_periods=20).mean()
    weights_df = rolling_ic.div(
        rolling_ic.abs().sum(axis=1).replace(0, np.nan), axis=0
    ).fillna(1.0 / len(z_cols))

    print(f"  Rolling IC window: {ROLLING_IC_WINDOW} days")

    panel["composite_ic"] = np.nan
    for i, d in enumerate(dates):
        g = panel.loc[panel["date"] == d]
        if len(g) < 5:
            continue
        w = weights_df.iloc[i].dropna() if i < len(weights_df) else pd.Series(
            {c: 1.0/len(z_cols) for c in z_cols})
        if w.empty or w.abs().sum() < 1e-12:
            w = pd.Series({c: 1.0/len(z_cols) for c in z_cols})
        composite = np.zeros(len(g))
        weight_sum = 0.0
        for c, sc in zip(z_cols, s_cols):
            if c in w.index:
                wi = w[c]
                vals = g[sc].values.copy()  # 用方向调整后的 signed z
                if np.isnan(vals).any():
                    mask = ~np.isnan(vals)
                    if mask.sum() > 0:
                        vals[~mask] = vals[mask].mean()
                    else:
                        continue
                composite += wi * vals
                weight_sum += abs(wi)
        if weight_sum > 1e-12:
            composite /= weight_sum
            panel.loc[g.index, "composite_ic"] = composite

    valid = panel["composite_ic"].notna().sum()
    print(f"  Composite (IC): {valid}/{len(panel)} ({valid/len(panel):.1%})")
    if not weights_df.empty:
        last_w = weights_df.iloc[-1].dropna()
        print("\n  Latest IC weights:")
        for c, v in last_w.items():
            print(f"    {c.replace('_z',''):<8s} {v:>+8.4f}")
    # 清理临时 signed 列
    panel.drop(columns=[c for c in s_cols if c in panel.columns], inplace=True)
    return panel


def backtest_composite(panel: pd.DataFrame, composite_col: str = "composite_eq"):
    print(f"\n=== Backtest: {composite_col} ===")
    ret_col = f"forward_{FORWARD_PERIOD}d_return"
    ret1d = "forward_1d_return"
    if composite_col not in panel.columns or ret_col not in panel.columns:
        print("  Missing columns")
        return None
    dates = sorted(panel["date"].unique())

    q_means = {i: [] for i in range(1, N_GROUPS + 1)}
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

    print("\n  Quantile Portfolio (21d holding):")
    for qi in range(1, N_GROUPS + 1):
        avg = np.mean(q_means[qi]) if q_means[qi] else np.nan
        print(f"    Q{qi}: {avg:+.4f}")
    ls_arr = np.array([x for x in ls_list if np.isfinite(x)])
    ls_mean = ls_arr.mean()
    ls_std = ls_arr.std()
    ls_ir = ls_mean / ls_std if ls_std > 1e-12 else np.nan
    qs = [np.mean(q_means[i]) if q_means[i] else np.nan for i in range(1, 6)]
    valid = [(i+1, m) for i, m in enumerate(qs) if np.isfinite(m)]
    mono = float(np.corrcoef([v[0] for v in valid], [v[1] for v in valid])[0, 1]) \
        if len(valid) >= 2 else np.nan
    print(f"    Long-Short: {ls_mean:+.4f}  IR: {ls_ir:+.3f}  Mono: {mono:+.2f}")

    if ret1d not in panel.columns:
        return None
    print(f"\n  Top{TOP_N} Equal-Weight Portfolio:")
    nav_dates, nav_values, nav = [], [], 1.0
    for d in dates:
        g = panel.loc[panel["date"] == d, [composite_col, ret1d]].dropna()
        if len(g) < 2:
            continue
        top = g.nlargest(min(TOP_N, len(g)), composite_col)  # 小股票池也能回测
        daily_ret = top[ret1d].mean()
        if np.isfinite(daily_ret):
            nav *= (1 + daily_ret)
            nav_dates.append(d)
            nav_values.append(nav)
    nav_series = pd.Series(nav_values, index=nav_dates)
    if nav_series.empty:
        print("    [WARN] 无足够有效股票构建净值（有效数 < TOP_N）")
        return None
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
    return nav_series


def select_latest_stocks(panel: pd.DataFrame, composite_col: str = "composite_eq"):
    print(f"\n=== Latest Selection (Top {TOP_N}) ===")
    if composite_col not in panel.columns:
        print("  Composite column not found")
        return None
    latest_date = panel["date"].max()
    g = panel.loc[panel["date"] == latest_date].copy().dropna(subset=[composite_col])
    if len(g) < TOP_N:
        print(f"  Only {len(g)} stocks available")
    top = g.nlargest(TOP_N, composite_col)

    out_cols = ["ticker", "name", composite_col]
    for f in SELECTED_FACTORS:
        z = f"{f}_z"
        if z in top.columns:
            out_cols.append(z)
    print(f"\n  Date: {latest_date.date()}")
    print(f"  Candidates: {len(g)}")
    print(f"\n  {'Rank':<5}{'Ticker':<8}{'Name':<14}{'Composite':>10}", end="")
    for f in SELECTED_FACTORS:
        print(f" {f:>8}", end="")
    print()
    print("  " + "-" * 82)
    for rank, (_, row) in enumerate(top.iterrows(), 1):
        name = str(row.get("name", ""))
        print(f"  {rank:<5}{row['ticker']:<8}{name:<14s}{row[composite_col]:>+10.3f}", end="")
        for f in SELECTED_FACTORS:
            v = row.get(f"{f}_z", np.nan)
            print(f" {v:>+8.3f}", end="")
        print()
    return top


def main():
    t0 = time.time()
    print("=" * 70)
    print(" US Composite Factor + Backtest + Selection (Dow Jones 30)")
    print("=" * 70)
    panel = load_panel()
    panel = build_equal_weight_composite(panel)
    panel = build_rolling_ic_weight_composite(panel)
    backtest_composite(panel, "composite_eq")
    backtest_composite(panel, "composite_ic")
    top_eq = select_latest_stocks(panel, "composite_eq")
    top_ic = select_latest_stocks(panel, "composite_ic")

    print("\n=== Saving to report/ ===")
    # 完整因子面板（parquet 快照 + csv）
    save_cols = ["date", "ticker"]
    if "name" in panel.columns:
        save_cols.append("name")
    save_cols += ["composite_eq", "composite_ic"]
    for f in SELECTED_FACTORS:
        z = f"{f}_z"
        if z in panel.columns:
            save_cols.append(z)
    save_panel("us", "composite_factor", panel[save_cols])

    # 选股结果（等权 / IC加权）
    if top_eq is not None:
        save_csv_html("us", "top10_equal_weight", top_eq,
                      title="美股 Top10 等权选股",
                      subtitle="composite_eq 前10名（含各因子z值）")
    if top_ic is not None:
        save_csv_html("us", "top10_ic_weight", top_ic,
                      title="美股 Top10 IC加权选股",
                      subtitle="composite_ic 前10名（含各因子z值）")
    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
