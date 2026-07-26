"""因子库。

公开：
    FactorBase        —— 因子基类
    VALUE_FACTORS     —— 价值因子 (EP/BP/SP/CFP/DP)
    GROWTH_FACTORS    —— 成长因子 (RevG/NetG/EpG)
    QUALITY_FACTORS   —— 质量因子 (ROE/ROA/GPM/Lev/CFO)
    MOMENTUM_FACTORS  —— 动量因子 (Mom12m/Rev1m)
    TECH_FACTORS      —— 技术/规模/流动性因子 (LnMV/Turn/Vol60/Beta)
    SENTIMENT_FACTORS —— 情绪因子 (HSGT/Flow/FUp/MainFlow/SuperBig)
    ALL_FACTORS       —— 全部 24 个因子类（便于批量实例化）

⚠️ HSGT/Flow/FUp 仅支持 2014-11 ~ 2024-08 历史段；
   MainFlow/SuperBig 基于 2024 年至今可用的资金流数据。
"""
from .base import FactorBase
from .value import (
    EPFactor, BPFactor, SPFactor, CFPFactor, DPFactor, VALUE_FACTORS,
)
from .growth import RevGFactor, NetGFactor, EpGFactor, GROWTH_FACTORS
from .quality import ROEFactor, ROAFactor, GPMFactor, LevFactor, CFOFactor, QUALITY_FACTORS
from .momentum import Mom12mFactor, Rev1mFactor, MOMENTUM_FACTORS
from .technical import (
    LnMVFactor, TurnFactor, Vol60Factor, BetaFactor, TECH_FACTORS,
)
from .sentiment import (
    HSGTFactor, FlowFactor, FUpFactor,
    MainFlowFactor, SuperBigFlowFactor, SENTIMENT_FACTORS,
)

# 全部因子类（24 个，便于批量实例化 / 遍历评估）
ALL_FACTORS = (
    VALUE_FACTORS
    + GROWTH_FACTORS
    + QUALITY_FACTORS
    + MOMENTUM_FACTORS
    + TECH_FACTORS
    + SENTIMENT_FACTORS
)

# 便于代码中按 name 查找因子类
FACTOR_CLASS_MAP = {cls.name: cls for cls in ALL_FACTORS}

__all__ = [
    "FactorBase",
    # 价值
    "EPFactor", "BPFactor", "SPFactor", "CFPFactor", "DPFactor", "VALUE_FACTORS",
    # 成长
    "RevGFactor", "NetGFactor", "EpGFactor", "GROWTH_FACTORS",
    # 质量
    "ROEFactor", "ROAFactor", "GPMFactor", "LevFactor", "CFOFactor", "QUALITY_FACTORS",
    # 动量
    "Mom12mFactor", "Rev1mFactor", "MOMENTUM_FACTORS",
    # 技术/规模/流动性
    "LnMVFactor", "TurnFactor", "Vol60Factor", "BetaFactor", "TECH_FACTORS",
    # 情绪
    "HSGTFactor", "FlowFactor", "FUpFactor",
    "MainFlowFactor", "SuperBigFlowFactor", "SENTIMENT_FACTORS",
    # 汇总
    "ALL_FACTORS", "FACTOR_CLASS_MAP",
]
