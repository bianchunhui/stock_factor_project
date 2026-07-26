"""数据处理层。

公开：
    normalize.*        —— 截面去极值/中性化/zscore/rank
    align.*            —— forward return 与因子对齐
    pit_align.*        —— 财报 PIT 合并（防未来函数）
"""
from . import normalize, align, pit_align

__all__ = ["normalize", "align", "pit_align"]
