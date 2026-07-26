"""横截面预处理：去极值 + 行业/市值中性化 + 标准化。

所有操作按日期 groupby（横截面），不跨期泄漏。

winsorize  : 截面内缩尾到 [mean-3σ, mean+3σ]
neutralize : 对行业哑变量 + ln(市值) 做 OLS，取残差（去行业/规模暴露）
zscore     : 截面内 (x - mean) / std
rank       : 截面内百分位排名 [0, 1]
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize_cross_section(
    panel: pd.DataFrame,
    col: str,
    date_col: str = "date",
    n_sigma: float = 3.0,
) -> pd.Series:
    """截面缩尾到 ±nσ。返回处理后的 Series（同索引）。"""
    s = panel[col].copy()

    def _clip(g: pd.Series) -> pd.Series:
        mu, sd = g.mean(), g.std()
        if not np.isfinite(sd) or sd < 1e-12:
            return g
        return g.clip(lower=mu - n_sigma * sd, upper=mu + n_sigma * sd)

    return s.groupby(panel[date_col]).transform(_clip)


def neutralize(
    panel: pd.DataFrame,
    factor_col: str,
    date_col: str = "date",
    industry_col: str = "industry",
    size_col: str = "ln_market_cap",
) -> pd.Series:
    """截面回归中性化：factor ~ industry_dummies + size，取残差。

    若缺 industry/size 列，则原样返回（跳过中性化）。
    需要 statsmodels；缺失则用 numpy OLS 兜底。
    """
    need = {industry_col, size_col}
    if not need.issubset(panel.columns):
        return panel[factor_col].copy()

    def _resid(g: pd.DataFrame) -> pd.Series:
        y = g[factor_col].astype(float).values
        mask = ~np.isnan(y)
        if mask.sum() < len(need) + 2:  # 样本太少
            return pd.Series(np.nan, index=g.index)
        yv = y[mask]
        # 行业哑变量
        dummies = pd.get_dummies(g[industry_col], prefix="ind", dtype=float)
        X = pd.concat([dummies, g[[size_col]].astype(float)], axis=1).values
        Xv = X[mask]
        # 加截距
        Xv = np.column_stack([np.ones(len(Xv)), Xv])
        try:
            coef, *_ = np.linalg.lstsq(Xv, yv, rcond=None)
            resid = yv - Xv @ coef
        except np.linalg.LinAlgError:
            return pd.Series(np.nan, index=g.index)
        out = np.full(len(g), np.nan)
        out[mask] = resid
        return pd.Series(out, index=g.index)

    parts = []
    for _, g in panel.groupby(date_col):
        parts.append(_resid(g))
    return pd.concat(parts).sort_index()


def zscore_cross_section(
    series: pd.Series, date_col: pd.Series, min_count: int = 3
) -> pd.Series:
    """截面 z-score。样本少于 min_count 返回 NaN。"""
    def _z(g: pd.Series) -> pd.Series:
        if g.notna().sum() < min_count:
            return pd.Series(np.nan, index=g.index)
        mu, sd = g.mean(), g.std()
        if not np.isfinite(sd) or sd < 1e-12:
            return pd.Series(0.0, index=g.index)
        return (g - mu) / sd
    return series.groupby(date_col).transform(_z)


def rank_cross_section(series: pd.Series, date_col: pd.Series, pct: bool = True) -> pd.Series:
    """截面百分位排名 ∈ [0, 1]。"""
    return series.groupby(date_col).rank(pct=pct, method="average")


def standardize_factor(
    panel: pd.DataFrame,
    factor_col: str,
    date_col: str = "date",
    industry_col: str = "industry",
    size_col: str = "ln_market_cap",
    do_winsorize: bool = True,
    do_neutralize: bool = True,
    method: str = "zscore",
) -> pd.Series:
    """因子标准化全流程：缩尾 → 中性化 → zscore/rank。

    返回处理后的 Series，列名加 _std 后缀的语义由调用方负责。
    """
    if factor_col not in panel.columns:
        raise KeyError(f"panel 缺少因子列: {factor_col}")

    s = panel[factor_col].copy()
    if do_winsorize:
        s = winsorize_cross_section(panel, factor_col, date_col)
        panel = panel.assign(_tmp=s)
        # 中性化基于缩尾后的值
        if do_neutralize:
            s = neutralize(panel, "_tmp", date_col, industry_col, size_col)

    if method == "zscore":
        s = zscore_cross_section(s, panel[date_col])
    elif method == "rank":
        s = rank_cross_section(s, panel[date_col])
    else:
        raise ValueError(f"未知 method: {method}")
    return s
