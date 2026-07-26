"""交易成本模型。

A 股：佣金 0.025%（双边）+ 卖出印花税 0.05%（2023降后）+ 滑点 0.1%（双边）
港股通：佣金 0.05%（双边）+ 印花税 0.13%（卖出）+ 汇率损益 0.05% + 滑点 0.15%
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostModel:
    """交易成本模型。"""
    commission: float = 0.00025   # 单边佣金率
    stamp_tax: float = 0.0005     # 卖出印花税率（仅卖出）
    slippage: float = 0.001       # 单边滑点率
    fx_cost: float = 0.0          # 汇率损益（港股通）

    @property
    def buy_side(self) -> float:
        return self.commission + self.slippage

    @property
    def sell_side(self) -> float:
        return self.commission + self.stamp_tax + self.slippage + self.fx_cost

    @property
    def round_trip(self) -> float:
        return self.buy_side + self.sell_side


# 预定义
A_COST = CostModel(commission=0.00025, stamp_tax=0.0005, slippage=0.001, fx_cost=0.0)
HK_COST = CostModel(commission=0.0005, stamp_tax=0.0013, slippage=0.0015, fx_cost=0.0005)
