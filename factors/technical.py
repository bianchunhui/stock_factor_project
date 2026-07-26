"""规模 / 流动性 / 波动因子（纯行情）。

LnMV  : 对数流通市值（小市值效应，负向）
Turn  : 换手率（低换手溢价，负向）
Vol60 : 60 日已实现波动率（低波动溢价，负向）
Beta  : 个股对基准指数的 Beta（低 Beta 异象，负向）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FactorBase


class LnMVFactor(FactorBase):
    name = "LnMV"
    category = "size"
    direction = -1
    need_pit = False

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        col = "circ_market_cap" if "circ_market_cap" in panel.columns else (
            "market_cap" if "market_cap" in panel.columns else None
        )
        if col is None:
            return pd.Series(np.nan, index=panel.index)
        mc = pd.to_numeric(panel[col], errors="coerce")
        return np.log(mc.where(mc > 0, np.nan))

    def required_columns(self):
        return ["circ_market_cap", "market_cap"]


class TurnFactor(FactorBase):
    """换手率（取近 window 日均值）。"""
    name = "Turn"
    category = "liquidity"
    direction = -1
    need_pit = False

    def __init__(self, window: int = 20):
        self.window = window

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "turnover" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        t = pd.to_numeric(panel["turnover"], errors="coerce")
        return t.groupby(panel["ticker"]).transform(
            lambda s: s.rolling(self.window, min_periods=self.window // 2).mean()
        )

    def required_columns(self):
        return ["turnover"]


class Vol60Factor(FactorBase):
    """60 日已实现波动率（日收益标准差 × sqrt(252)）。"""
    name = "Vol60"
    category = "volatility"
    direction = -1
    need_pit = False

    def __init__(self, window: int = 60, annualize: int = 252):
        self.window = window
        self.annualize = annualize

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "close" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        ret = pd.to_numeric(panel["close"], errors="coerce").groupby(
            panel["ticker"]
        ).pct_change()
        vol = ret.groupby(panel["ticker"]).transform(
            lambda s: s.rolling(self.window, min_periods=self.window // 2).std()
        ) * np.sqrt(self.annualize)
        return vol

    def required_columns(self):
        return ["close"]


class BetaFactor(FactorBase):
    """个股对基准指数的 Beta。

    需要 panel 中有 bench_ret 列（基准日收益率）。若缺失返回 NaN。
    """
    name = "Beta"
    category = "volatility"
    direction = -1
    need_pit = False

    def __init__(self, window: int = 60):
        self.window = window

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "close" not in panel.columns or "bench_ret" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        stock_ret = pd.to_numeric(panel["close"], errors="coerce").groupby(
            panel["ticker"]
        ).pct_change()
        bench = pd.to_numeric(panel["bench_ret"], errors="coerce")

        def _beta(s):
            x = bench.loc[s.index].values
            y = s.values
            mask = ~(np.isnan(x) | np.isnan(y))
            if mask.sum() < self.window // 2:
                return np.nan
            xv, yv = x[mask], y[mask]
            var = xv.var()
            if var < 1e-12:
                return np.nan
            return np.cov(xv, yv)[0, 1] / var

        return stock_ret.groupby(panel["ticker"]).transform(
            lambda s: s.rolling(self.window, min_periods=self.window // 2).apply(
                _beta, raw=False
            )
        )

    def required_columns(self):
        return ["close", "bench_ret"]


TECH_FACTORS = [LnMVFactor, TurnFactor, Vol60Factor, BetaFactor]
