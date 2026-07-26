"""情绪因子。

⚠️ 数据源说明（重要）：
   2024-08-16 港交所停止披露个股级北向资金实时数据。本模块采用双源设计：
   - HSGT/Flow/FUp：北向持股类，仅适用于 2014-11 ~ 2024-08 历史回测
   - MainFlow/SuperBigFlow：东财个股资金流，2024 年至今可用，作为现代情绪源

因子定义：
  HSGT       北向持股占比（%，仅历史段）
  Flow       北向今日增持资金（仅历史段）
  FUp        北向近 20 日增持幅度（仅历史段）
  MainFlow   主力资金净流入（元，westock 数据源）
  SuperBig   超大单净流入（元，westock 数据源）

所有因子 direction=+1（资金净流入越高，看多情绪越强）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FactorBase


# ============================================================
# 北向资金类（仅历史段 2014-11 ~ 2024-08）
# ============================================================
class HSGTFactor(FactorBase):
    """北向持股占比（%）。

    ⚠️ 2024-08-16 后无数据，仅历史回测有效。
    需要列: holding_pct（来自 HSGTFetcher.get_stock_holding）
    """
    name = "HSGT"
    category = "sentiment"
    direction = +1
    need_pit = False

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "holding_pct" in panel.columns:
            return pd.to_numeric(panel["holding_pct"], errors="coerce")
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["holding_pct"]


class FlowFactor(FactorBase):
    """北向今日增持资金（万元，仅历史段）。"""
    name = "Flow"
    category = "sentiment"
    direction = +1
    need_pit = False

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "fund_change" in panel.columns:
            return pd.to_numeric(panel["fund_change"], errors="coerce")
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["fund_change"]


class FUpFactor(FactorBase):
    """北向近 20 日增持幅度：累计增持资金 / 持股市值（仅历史段）。"""
    name = "FUp"
    category = "sentiment"
    direction = +1
    need_pit = False

    def __init__(self, window: int = 20):
        self.window = window

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "holding_value" not in panel.columns or "fund_change" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)

        if "ticker" not in panel.columns or "date" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)

        panel_sorted = panel.sort_values(["ticker", "date"])
        rolling_fc = (
            panel_sorted.groupby("ticker")["fund_change"]
            .transform(lambda x: x.rolling(self.window, min_periods=1).sum())
        )
        rolling_hv = panel_sorted["holding_value"]

        ratio = rolling_fc / rolling_hv.abs().where(rolling_hv.abs() > 1e-8, np.nan)
        ratio.index = panel_sorted.index
        return ratio.reindex(panel.index)

    def required_columns(self):
        return ["holding_value", "fund_change"]


# ============================================================
# 资金流类（现代数据源，2024 年起可用）
# ============================================================
class MainFlowFactor(FactorBase):
    """主力资金净流入（元，近 window 日均值）。

    数据源：东财 stock_individual_fund_flow
    现代可用的情绪因子，覆盖 2024 年至今。
    """
    name = "MainFlow"
    category = "sentiment"
    direction = +1
    need_pit = False

    def __init__(self, window: int = 5):
        self.window = window

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "main_net_inflow" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        if "ticker" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)

        flow = pd.to_numeric(panel["main_net_inflow"], errors="coerce")
        return flow.groupby(panel["ticker"]).transform(
            lambda s: s.rolling(self.window, min_periods=1).mean()
        )

    def required_columns(self):
        return ["main_net_inflow"]


class SuperBigFlowFactor(FactorBase):
    """超大单净流入（元，近 window 日均值）。

    超大单代表机构资金动向，是机构情绪的代理变量。
    """
    name = "SuperBig"
    category = "sentiment"
    direction = +1
    need_pit = False

    def __init__(self, window: int = 5):
        self.window = window

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "super_big_net_inflow" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        if "ticker" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)

        flow = pd.to_numeric(panel["super_big_net_inflow"], errors="coerce")
        return flow.groupby(panel["ticker"]).transform(
            lambda s: s.rolling(self.window, min_periods=1).mean()
        )

    def required_columns(self):
        return ["super_big_net_inflow"]


# 注册表（5 个情绪因子：3 个历史 + 2 个现代）
SENTIMENT_FACTORS = [HSGTFactor, FlowFactor, FUpFactor, MainFlowFactor, SuperBigFlowFactor]
