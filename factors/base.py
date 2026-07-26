"""因子基类。

所有因子继承 FactorBase，实现 compute() 返回与 panel 同索引的因子值 Series。

与 cta_project 的 StrategyBase 区别：
- 输入是 panel（多标的×日期），而非单标的的时间序列
- 输出是横截面因子值（连续值），而非方向信号 {-1,0,+1}
- 引入 direction：+1 越大越好，-1 越小越好，用于统一排序方向

panel 约定（长表 long format）：
    必备列: date, ticker, close
    可选列: open, high, low, volume, amount, turnover,
            market_cap, circ_market_cap, pe, pb, eps, ...
    index 为默认 RangeIndex（不要用 date×ticker 做索引，便于 groupby）
"""
from __future__ import annotations

import pandas as pd


class FactorBase:
    """因子基类。

    子类需设置类属性 name / category / direction，并实现 compute()。
    """

    name: str = "base"
    category: str = "abstract"
    direction: int = +1       # +1 越大越好；-1 越小越好
    need_pit: bool = False    # 是否依赖财报（True 则需 PIT 对齐）

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        """计算因子值。

        Parameters
        ----------
        panel : pd.DataFrame
            长表，含 date / ticker 列及其他所需列。

        Returns
        -------
        pd.Series
            与 panel 同索引的因子值；缺失返回 NaN。Series.name 设为因子名。
        """
        raise NotImplementedError

    def compute_aligned(self, panel: pd.DataFrame) -> pd.Series:
        """计算并按 direction 调整方向（统一为"越大越好"）。

        direction=-1 的因子返回值取负，使下游排序/合成逻辑统一。
        """
        values = self.compute(panel)
        if self.direction == -1:
            values = -values
        values.name = self.name
        return values

    def required_columns(self) -> list[str]:
        """子类可覆盖，声明所需列（用于数据预检与文档）。"""
        return []
