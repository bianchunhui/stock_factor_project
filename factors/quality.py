"""质量因子：ROE / ROA / 毛利率 / 杠杆率 / 经营现金流比率。

数据来源：FinancialFetcher 衍生指标
  - roe            净资产收益率（归母净利润 / 归母权益）
  - roa            总资产收益率（净利润 / 总资产）
  - gross_margin   毛利率（营业利润 / 营收，近似）
  - debt_ratio     资产负债率（总负债 / 总资产，越小越好 → direction=-1）
  - ocf_ratio      经营现金流/营收比

ROE / ROA / GPM / CFO 方向=+1（越大越好），Lev 方向=-1（越小越好）。
need_pit=True。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FactorBase


class ROEFactor(FactorBase):
    """净资产收益率 ROE = 归母净利润 / 归母权益。"""
    name = "ROE"
    category = "quality"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "roe" in panel.columns:
            return pd.to_numeric(panel["roe"], errors="coerce")
        # 回退：用 panel 中已有的 parent_net_profit / (total_assets - total_liabilities)
        if {"parent_net_profit", "total_assets", "total_liabilities"}.issubset(panel.columns):
            pnp = pd.to_numeric(panel["parent_net_profit"], errors="coerce")
            ta = pd.to_numeric(panel["total_assets"], errors="coerce")
            tl = pd.to_numeric(panel["total_liabilities"], errors="coerce")
            equity = ta.sub(tl, fill_value=np.nan)
            return pnp.div(equity.where(equity.abs() > 1e-8), fill_value=np.nan)
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["roe"]


class ROAFactor(FactorBase):
    """总资产收益率 ROA = 净利润 / 总资产。"""
    name = "ROA"
    category = "quality"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "roa" in panel.columns:
            return pd.to_numeric(panel["roa"], errors="coerce")
        if {"net_profit", "total_assets"}.issubset(panel.columns):
            np_ = pd.to_numeric(panel["net_profit"], errors="coerce")
            ta = pd.to_numeric(panel["total_assets"], errors="coerce")
            return np_.div(ta.where(ta.abs() > 1e-8), fill_value=np.nan)
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["roa"]


class GPMFactor(FactorBase):
    """毛利率 GPM = 营业利润 / 营业收入（近似）。"""
    name = "GPM"
    category = "quality"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "gross_margin" in panel.columns:
            return pd.to_numeric(panel["gross_margin"], errors="coerce")
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["gross_margin"]


class LevFactor(FactorBase):
    """资产负债率 Lev = 总负债 / 总资产。

    direction=-1：负债率越低越好（公司更稳健）。
    """
    name = "Lev"
    category = "quality"
    direction = -1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "debt_ratio" in panel.columns:
            return pd.to_numeric(panel["debt_ratio"], errors="coerce")
        if {"total_liabilities", "total_assets"}.issubset(panel.columns):
            tl = pd.to_numeric(panel["total_liabilities"], errors="coerce")
            ta = pd.to_numeric(panel["total_assets"], errors="coerce")
            return tl.div(ta.where(ta.abs() > 1e-8), fill_value=np.nan)
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["debt_ratio"]


class CFOFactor(FactorBase):
    """经营现金流比率 CFO = 经营现金流净额 / 营业收入。

    反映盈利的现金含量，越高说明盈利质量越好。
    """
    name = "CFO"
    category = "quality"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "ocf_ratio" in panel.columns:
            return pd.to_numeric(panel["ocf_ratio"], errors="coerce")
        if {"operating_cash_flow", "total_revenue"}.issubset(panel.columns):
            ocf = pd.to_numeric(panel["operating_cash_flow"], errors="coerce")
            rev = pd.to_numeric(panel["total_revenue"], errors="coerce")
            return ocf.div(rev.where(abs(rev) > 1e-6), fill_value=np.nan)
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["ocf_ratio"]


# 注册表
QUALITY_FACTORS = [ROEFactor, ROAFactor, GPMFactor, LevFactor, CFOFactor]
