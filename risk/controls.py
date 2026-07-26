"""风控约束。

集中度上限、行业暴露上限、个股最大权重。
用于回测和实盘信号后处理。
"""
from __future__ import annotations

import pandas as pd


def apply_constraints(
    panel: pd.DataFrame,
    weight_col: str = "weight",
    date_col: str = "date",
    industry_col: str = "industry",
    max_stock_weight: float = 0.05,
    max_industry_weight: float = 0.30,
) -> pd.DataFrame:
    """对组合权重施加约束并重新归一化。

    1. 个股权重不超过 max_stock_weight
    2. 行业权重不超过 max_industry_weight
    3. 重新归一化使权重之和为 1
    """
    df = panel.copy()
    df[weight_col] = df[weight_col].clip(upper=max_stock_weight)

    if industry_col in df.columns:
        for d, g in df.groupby(date_col):
            ind_w = g.groupby(industry_col)[weight_col].sum()
            over = ind_w[ind_w > max_industry_weight]
            for ind, w in over.items():
                mask = (df[date_col] == d) & (df[industry_col] == ind)
                scale = max_industry_weight / w
                df.loc[mask, weight_col] *= scale

    # 归一化
    for d, g in df.groupby(date_col):
        total = g[weight_col].sum()
        if total > 1e-10:
            df.loc[g.index, weight_col] = g[weight_col] / total
    return df
