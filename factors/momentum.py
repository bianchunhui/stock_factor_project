"""动量因子（纯行情，无需 PIT）。

Mom12m : 12 个月动量，剔除最近 1 个月（避免短期反转污染）
          = close[t-21] / close[t-252] - 1
Rev1m  : 1 个月反转（短期反转效应，负向因子）
          = close[t-1] / close[t-21] - 1
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FactorBase


class Mom12mFactor(FactorBase):
    name = "Mom12m"
    category = "momentum"
    direction = +1
    need_pit = False

    def __init__(self, long_window: int = 252, skip: int = 21):
        self.long_window = long_window
        self.skip = skip

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "close" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        g = panel.groupby("ticker")["close"]
        end = g.shift(self.skip)
        start = g.shift(self.long_window + self.skip)
        mom = end / start - 1.0
        return mom

    def required_columns(self):
        return ["close"]


class Rev1mFactor(FactorBase):
    name = "Rev1m"
    category = "momentum"
    direction = -1   # 短期反转：近期跌幅大的后续反弹
    need_pit = False

    def __init__(self, window: int = 21):
        self.window = window

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "close" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        g = panel.groupby("ticker")["close"]
        ret = g.shift(1) / g.shift(1 + self.window) - 1.0
        return ret

    def required_columns(self):
        return ["close"]


MOMENTUM_FACTORS = [Mom12mFactor, Rev1mFactor]
