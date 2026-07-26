"""价值因子：EP / BP / SP / CFP / DP。

EP = 1/PE = 归母净利润 / 总市值
BP = 1/PB = 归母净资产 / 总市值
SP = 1/PS = 营业收入 / 总市值
CFP = 1/PCF = 经营现金流 / 总市值
DP = 股息率 = 近 12 月每股分红 / 股价

注意：第一版先用 panel 中已带的估值列（pe/pb/...）或从基本面数据合并得到的
净利润/净资产等字段。完整的 PIT 财报对齐在 processor.pit_align 中处理。
本模块只做"给定 panel 中的字段 → 因子值"的纯计算。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FactorBase


def _safe_inverse(series: pd.Series, eps: float = 1e-8) -> pd.Series:
    """安全取倒数，避免除零。返回 pd.Series。"""
    series = pd.to_numeric(series, errors="coerce")
    mask = series.abs() < eps
    return series.where(~mask, np.nan).pow(-1, fill_value=np.nan)


class EPFactor(FactorBase):
    """市盈率倒数 EP = 1 / PE_TTM。

    需要列: pe_ttm（或 pe）。若直接有 pe 列取倒数；否则用 net_profit / market_cap。
    """
    name = "EP"
    category = "value"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "pe_ttm" in panel.columns:
            return _safe_inverse(panel["pe_ttm"])
        if "pe" in panel.columns:
            return _safe_inverse(panel["pe"])
        if {"net_profit", "market_cap"}.issubset(panel.columns):
            mc = pd.to_numeric(panel["market_cap"], errors="coerce")
            np_ = pd.to_numeric(panel["net_profit"], errors="coerce")
            safe_mc = mc.where(mc.abs() > 1e-8, np.nan)
            return np_ / safe_mc
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["pe_ttm"]


class BPFactor(FactorBase):
    """市净率倒数 BP = 1 / PB。"""
    name = "BP"
    category = "value"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "pb" in panel.columns:
            return _safe_inverse(panel["pb"])
        if {"net_assets", "market_cap"}.issubset(panel.columns):
            mc = pd.to_numeric(panel["market_cap"], errors="coerce")
            na = pd.to_numeric(panel["net_assets"], errors="coerce")
            return na / mc.where(mc.abs() > 1e-8, np.nan)
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["pb"]


class SPFactor(FactorBase):
    """市销率倒数 SP = 1 / PS。"""
    name = "SP"
    category = "value"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "ps_ttm" in panel.columns:
            return _safe_inverse(panel["ps_ttm"])
        if "ps" in panel.columns:
            return _safe_inverse(panel["ps"])
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["ps_ttm"]


class CFPFactor(FactorBase):
    """市现率倒数 CFP = 1 / PCF（经营现金流口径）。"""
    name = "CFP"
    category = "value"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "pcf" in panel.columns:
            return _safe_inverse(panel["pcf"])
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["pcf"]


class DPFactor(FactorBase):
    """股息率 DP = 近 12 月每股分红 / 股价。

    需要 dividend_ttm（近 12 月每股分红）与 close。
    """
    name = "DP"
    category = "value"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "dividend_yield" in panel.columns:
            return pd.to_numeric(panel["dividend_yield"], errors="coerce")
        if {"dividend_ttm", "close"}.issubset(panel.columns):
            d = pd.to_numeric(panel["dividend_ttm"], errors="coerce")
            c = pd.to_numeric(panel["close"], errors="coerce")
            return d / c.where(c.abs() > 1e-8, np.nan)
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["dividend_ttm", "close"]


# 便于批量调用的注册表
VALUE_FACTORS = [EPFactor, BPFactor, SPFactor, CFPFactor, DPFactor]
