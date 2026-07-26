"""成长因子：营收增长率 / 净利润增长率 / EPS 增长率。

数据来源：FinancialFetcher 从东方财富 EM 利润表提取
  - revenue_yoy        营业收入同比 (%)
  - net_profit_yoy     净利润同比 (%)
  - parent_net_profit_yoy  归母净利润同比 (%)

所有因子 direction=+1（增长越高越好）。
need_pit=True（依赖财报，需 PIT 对齐防未来函数）。

异常值处理（关键）
------------------
YoY 同比在"亏转盈"或"小基数"时会爆炸（分母≈0 或为负，数据源给出 +800%~
+1000% 量级的伪信号）。仅靠截面 winsorize(3σ) 无法压住——异常点被 clip 到
+3σ 上限后 z-score 仍≈+3，等于直接给满分，污染复合因子排名。

处理方式（在因子层，A/港股共用）：
  1. 若上一报告期归母净利润 ≤ 0（亏损/为零），同比经济上无意义 → 置 NaN
     （需 PIT merge 提供 prev_parent_net_profit / prev_net_profit 列）
  2. 兜底硬裁剪 ±200%，挡住小正基数残余极端值
缺 prev 列时 graceful degrade：仅做硬裁剪（不破坏现有 A 股 panel）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FactorBase


# YoY 硬裁剪上下界（%）。超出即视为数据伪信号。
YOY_CLIP_LOWER = -200.0
YOY_CLIP_UPPER = 200.0


def _sanitize_yoy(
    yoy: pd.Series,
    panel: pd.DataFrame,
    prev_col: str | None = None,
) -> pd.Series:
    """小分母/亏转盈中性化 + 硬裁剪。

    Parameters
    ----------
    yoy : 原始同比序列（%）
    panel : 含 prev_* 列的面板（可选）
    prev_col : 上一报告期利润列名；存在且该值 ≤ 0 时把 yoy 置 NaN
    """
    yoy = pd.to_numeric(yoy, errors="coerce")

    # 1) 亏转盈 / 负分母中性化
    if prev_col is not None and prev_col in panel.columns:
        prev = pd.to_numeric(panel[prev_col], errors="coerce")
        # 上一报告期亏损或为零 → 同比无意义
        yoy = yoy.where(prev > 0, np.nan)

    # 2) 兜底硬裁剪
    yoy = yoy.clip(lower=YOY_CLIP_LOWER, upper=YOY_CLIP_UPPER)
    return yoy


class RevGFactor(FactorBase):
    """营业收入同比增长率（YoY）。

    需要列: revenue_yoy（来自财报利润表的 OPERATE_INCOME_YOY）
    营收恒正无符号问题，仅做硬裁剪挡小基数极端值。
    """
    name = "RevG"
    category = "growth"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "revenue_yoy" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        return _sanitize_yoy(panel["revenue_yoy"], panel, prev_col=None)

    def required_columns(self):
        return ["revenue_yoy"]


class NetGFactor(FactorBase):
    """净利润同比增长率（YoY）。"""
    name = "NetG"
    category = "growth"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "net_profit_yoy" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        # prev_net_profit 可选；缺则仅硬裁剪
        return _sanitize_yoy(panel["net_profit_yoy"], panel, prev_col="prev_net_profit")

    def required_columns(self):
        return ["net_profit_yoy"]


class EpGFactor(FactorBase):
    """归母净利润同比增长率（YoY），近似 EPS 增长。"""
    name = "EpG"
    category = "growth"
    direction = +1
    need_pit = True

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        # 优先用归母净利润同比
        if "parent_net_profit_yoy" in panel.columns:
            yoy = panel["parent_net_profit_yoy"]
            return _sanitize_yoy(yoy, panel, prev_col="prev_parent_net_profit")
        # 回退到净利润同比
        if "net_profit_yoy" in panel.columns:
            yoy = panel["net_profit_yoy"]
            return _sanitize_yoy(yoy, panel, prev_col="prev_net_profit")
        return pd.Series(np.nan, index=panel.index)

    def required_columns(self):
        return ["parent_net_profit_yoy", "net_profit_yoy"]


# 注册表
GROWTH_FACTORS = [RevGFactor, NetGFactor, EpGFactor]
