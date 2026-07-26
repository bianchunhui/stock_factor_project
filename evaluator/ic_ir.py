"""横截面 IC / IR 评估。

IC (Information Coefficient) = 每个截面上因子值与 forward return 的相关系数。
    - 默认 Spearman（rank IC），对极端值稳健
    - 按日 groupby → 得到 IC 时序 → 汇总统计

IR (Information Ratio) = mean(IC) / std(IC)
IC_IR = 同 IR，强调显著性；t_stat = mean(IC)/std(IC)*sqrt(N)

输出列名约定：forward_{N}d_return（与 align.compute_forward_returns 一致）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def cross_sectional_ic(
    df: pd.DataFrame,
    factor_col: str,
    return_col: str = "forward_21d_return",
    date_col: str = "date",
    method: str = "spearman",
    min_count: int = 3,
) -> pd.DataFrame:
    """逐日计算横截面 IC，返回 IC 时序。

    Returns
    -------
    DataFrame[date, ic, n]
    """
    if factor_col not in df.columns or return_col not in df.columns:
        raise KeyError(f"缺列 {factor_col} 或 {return_col}")

    rows = []
    for d, g in df.groupby(date_col):
        g = g.dropna(subset=[factor_col, return_col])
        if len(g) < min_count:
            continue
        x = g[factor_col].astype(float).values
        y = g[return_col].astype(float).values
        if method == "spearman":
            r, _ = stats.spearmanr(x, y)
        else:
            r, _ = stats.pearsonr(x, y)
        rows.append({"date": d, "ic": r, "n": len(g)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("date").reset_index(drop=True)


def summarize_ic(ic_series: pd.DataFrame | pd.Series) -> dict:
    """汇总 IC 时序的统计量。

    Parameters
    ----------
    ic_series : 含 ic 列的 DataFrame，或纯 ic 的 Series。
    """
    if isinstance(ic_series, pd.DataFrame):
        if ic_series.empty or "ic" not in ic_series.columns:
            return {"ic_mean": np.nan, "ic_std": np.nan, "ir": np.nan,
                    "t_stat": np.nan, "ic_positive_rate": np.nan, "n": 0}
        s = ic_series["ic"].dropna()
    else:
        s = ic_series.dropna() if ic_series is not None else pd.Series(dtype=float)
    n = len(s)
    if n == 0:
        return {"ic_mean": np.nan, "ic_std": np.nan, "ir": np.nan,
                "t_stat": np.nan, "ic_positive_rate": np.nan, "n": 0}
    mean = s.mean()
    std = s.std()
    ir = mean / std if std > 1e-12 else np.nan
    t_stat = ir * np.sqrt(n) if np.isfinite(ir) else np.nan
    pos_rate = (s > 0).mean()
    return {
        "ic_mean": mean,
        "ic_std": std,
        "ir": ir,                         # 信息比率 = mean/std
        "t_stat": t_stat,
        "ic_positive_rate": pos_rate,     # IC>0 的天数占比（胜率代理）
        "n": int(n),
    }


def evaluate_factor(
    df: pd.DataFrame,
    factor_col: str,
    return_cols: list[str] | None = None,
    method: str = "spearman",
) -> dict:
    """对单因子在多个持有期上评估 IC/IR。

    Returns
    -------
    {return_col: {ic_series, summary}}
    """
    if return_cols is None:
        return_cols = [c for c in df.columns if c.startswith("forward_") and c.endswith("_return")]
    results = {}
    for rc in return_cols:
        ic_ts = cross_sectional_ic(df, factor_col, rc, method=method)
        if ic_ts.empty:
            results[rc] = {"ic_series": ic_ts, "summary": summarize_ic(ic_ts)}
            continue
        results[rc] = {"ic_series": ic_ts, "summary": summarize_ic(ic_ts)}
    return results


def print_ic_summary(results: dict, factor_name: str = "") -> None:
    """打印 IC/IR 评估表格。"""
    title = f"因子 {factor_name} IC/IR 评估" if factor_name else "IC/IR 评估"
    print(f"\n{'=' * 56}")
    print(f" {title}")
    print(f"{'=' * 56}")
    print(f"{'持有期':<16}{'IC均值':>10}{'IC标准差':>11}{'IR':>9}{'t值':>9}{'胜率':>8}{'样本':>8}")
    print("-" * 56)
    for rc, r in results.items():
        s = r["summary"]
        print(
            f"{rc:<16}{s['ic_mean']:>10.4f}{s['ic_std']:>11.4f}"
            f"{(s['ir'] if np.isfinite(s['ir']) else float('nan')):>9.3f}"
            f"{(s['t_stat'] if np.isfinite(s['t_stat']) else float('nan')):>9.2f}"
            f"{s['ic_positive_rate']:>8.1%}{s['n']:>8}"
        )
    print("=" * 56)
