"""组合构建：Top-N% 选股 + 加权。

纯多头策略：每月末根据合成因子得分选 Top N% 的股票，
等权或市值加权持有至下月末。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def select_top_n_pct(
    panel: pd.DataFrame,
    score_col: str,
    date_col: str = "date",
    top_pct: float = 0.10,
    min_stocks: int = 5,
) -> pd.DataFrame:
    """逐日选取因子得分 Top N% 的股票。

    Returns
    -------
    panel 追加 selected 列（bool）。
    """
    df = panel.copy()
    df["selected"] = False

    for d, g in df.groupby(date_col):
        valid = g[g[score_col].notna()]
        if len(valid) < min_stocks:
            continue
        n_select = max(int(len(valid) * top_pct), min_stocks)
        top_idx = valid.nlargest(n_select, score_col).index
        df.loc[top_idx, "selected"] = True
    return df


def assign_weights(
    panel: pd.DataFrame,
    method: str = "equal",
    weight_col: str = "weight",
    market_cap_col: str = "market_cap",
) -> pd.DataFrame:
    """为选中的股票分配权重。

    Parameters
    ----------
    method : {"equal", "market_cap"}
        等权 或 市值加权。
    """
    df = panel.copy()
    df[weight_col] = 0.0
    sel = df[df["selected"]].copy()

    if method == "equal":
        counts = sel.groupby("date").size()
        for d, n in counts.items():
            mask = (df["date"] == d) & (df["selected"])
            df.loc[mask, weight_col] = 1.0 / n
    elif method == "market_cap":
        if market_cap_col not in df.columns:
            # 无市值列则退化为等权
            return assign_weights(panel, method="equal", weight_col=weight_col)
        for d, g in sel.groupby("date"):
            mc = g[market_cap_col].astype(float)
            w = mc / mc.sum()
            idx = g.index
            df.loc[idx, weight_col] = w.values
    return df


def build_portfolio(
    panel: pd.DataFrame,
    score_col: str,
    top_pct: float = 0.10,
    weight_method: str = "equal",
    date_col: str = "date",
    min_stocks: int = 5,
) -> pd.DataFrame:
    """选股 + 加权一步到位。

    Returns panel 追加 selected / weight 列。
    """
    df = select_top_n_pct(panel, score_col, date_col, top_pct, min_stocks)
    df = assign_weights(df, method=weight_method)
    return df
