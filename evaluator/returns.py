"""分位组合收益分析（单调性诊断）。

把每个截面的股票按因子值分 N 组（如 5 组），计算各组 forward return 均值，
观察是否单调（有效因子的分组收益应单调）。

多空组合 = Top 组 - Bottom 组（纯多头策略中用作诊断指标，不实际交易）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def quantile_portfolio_returns(
    df: pd.DataFrame,
    factor_col: str,
    return_col: str = "forward_21d_return",
    date_col: str = "date",
    n_groups: int = 5,
    ascending: bool = True,
) -> pd.DataFrame:
    """逐日分 N 组，返回每组平均 forward return 的时间序列。

    Parameters
    ----------
    ascending : bool
        True: 组 1 = 因子值最小。False: 组 1 = 因子值最大（Top）。
        约定 ascending=True，组 n_groups 为 Top（因子大者）。

    Returns
    -------
    DataFrame[date, q1, q2, ..., qN, long_short]
        long_short = qN - q1（Top - Bottom）
    """
    if factor_col not in df.columns or return_col not in df.columns:
        raise KeyError(f"缺列 {factor_col} 或 {return_col}")

    rows = []
    for d, g in df.groupby(date_col):
        g = g.dropna(subset=[factor_col, return_col])
        if len(g) < n_groups:
            continue
        try:
            g = g.assign(
                _q=pd.qcut(g[factor_col].rank(method="first"), n_groups, labels=False) + 1
            )
        except ValueError:
            continue
        grp_mean = g.groupby("_q")[return_col].mean()
        row = {"date": d}
        for q in range(1, n_groups + 1):
            row[f"q{q}"] = grp_mean.get(q, np.nan)
        row["long_short"] = row.get(f"q{n_groups}", np.nan) - row.get("q1", np.nan)
        rows.append(row)
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return out


def summarize_quantile_returns(q_df: pd.DataFrame, n_groups: int = 5) -> dict:
    """汇总各分位组的平均收益、单调性、多空。"""
    if q_df.empty:
        return {}
    out = {}
    for q in range(1, n_groups + 1):
        col = f"q{q}"
        if col in q_df.columns:
            out[col] = q_df[col].mean()
    if "long_short" in q_df.columns:
        ls = q_df["long_short"].dropna()
        out["long_short_mean"] = ls.mean()
        out["long_short_std"] = ls.std()
        out["long_short_ir"] = (
            ls.mean() / ls.std() if ls.std() > 1e-12 else np.nan
        )
    # 单调性得分：分组均值与组序号的相关性（+1 完美单调）
    means = [out.get(f"q{q}", np.nan) for q in range(1, n_groups + 1)]
    valid = [(i + 1, m) for i, m in enumerate(means) if np.isfinite(m)]
    if len(valid) >= 2:
        xs = np.array([v[0] for v in valid])
        ys = np.array([v[1] for v in valid])
        out["monotonicity"] = float(np.corrcoef(xs, ys)[0, 1])
    else:
        out["monotonicity"] = np.nan
    return out


def print_quantile_summary(q_summary: dict, n_groups: int = 5, factor_name: str = "") -> None:
    """打印分位组合收益表格。"""
    title = f"因子 {factor_name} 分位组合收益" if factor_name else "分位组合收益"
    print(f"\n{'=' * 56}")
    print(f" {title}")
    print(f"{'=' * 56}")
    print(f"{'组别':<8}{'平均收益':>12}")
    print("-" * 56)
    for q in range(1, n_groups + 1):
        v = q_summary.get(f"q{q}", np.nan)
        print(f"q{q:<7}{v:>12.4f}")
    print("-" * 56)
    print(f"{'多空均值':<8}{q_summary.get('long_short_mean', np.nan):>12.4f}")
    print(f"{'多空IR':<8}{q_summary.get('long_short_ir', np.nan):>12.3f}")
    print(f"{'单调性':<8}{q_summary.get('monotonicity', np.nan):>12.3f}")
    print("=" * 56)
