"""多因子合成。

支持三种加权方式：
    equal     : 等权（默认）
    ic_weight : 用历史 IC 均值加权（IC 越大权重越高）
    inv_var   : 逆方差加权（IC 波动越小权重越高）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def combine_equal(factor_df: pd.DataFrame, factor_cols: list[str] | None = None) -> pd.Series:
    """等权合成：各因子 z-score 简单取均值。"""
    cols = factor_cols or [c for c in factor_df.columns if c.endswith("_z")]
    if not cols:
        raise ValueError("无可用因子列（需 _z 后缀）")
    return factor_df[cols].mean(axis=1)


def combine_ic_weight(
    factor_df: pd.DataFrame,
    ic_means: dict[str, float],
    factor_cols: list[str] | None = None,
) -> pd.Series:
    """IC 加权合成：用各因子历史 IC 均值作为权重。

    Parameters
    ----------
    ic_means : {factor_col: mean_ic}
    """
    cols = factor_cols or [c for c in factor_df.columns if c.endswith("_z")]
    weights = np.array([max(ic_means.get(c, 0.0), 0.0) for c in cols])
    total = weights.sum()
    if total < 1e-10:
        return combine_equal(factor_df, cols)
    weights = weights / total
    return sum(factor_df[c] * w for c, w in zip(cols, weights))


def combine_inv_var(
    factor_df: pd.DataFrame,
    ic_vars: dict[str, float],
    factor_cols: list[str] | None = None,
) -> pd.Series:
    """逆方差加权：IC 方差越小的因子权重越高。"""
    cols = factor_cols or [c for c in factor_df.columns if c.endswith("_z")]
    inv = np.array([1.0 / max(ic_vars.get(c, 1e-6), 1e-10) for c in cols])
    total = inv.sum()
    if total < 1e-10:
        return combine_equal(factor_df, cols)
    weights = inv / total
    return sum(factor_df[c] * w for c, w in zip(cols, weights))


def combine_factors(
    factor_df: pd.DataFrame,
    method: str = "equal",
    ic_stats: dict | None = None,
    factor_cols: list[str] | None = None,
) -> pd.Series:
    """统一合成入口。"""
    if method == "equal":
        return combine_equal(factor_df, factor_cols)
    elif method == "ic_weight":
        ic_means = ic_stats.get("ic_mean", {}) if ic_stats else {}
        return combine_ic_weight(factor_df, ic_means, factor_cols)
    elif method == "inv_var":
        ic_vars = ic_stats.get("ic_var", {}) if ic_stats else {}
        return combine_inv_var(factor_df, ic_vars, factor_cols)
    else:
        raise ValueError(f"未知合成方法: {method}")
