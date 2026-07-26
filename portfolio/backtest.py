"""向量化回测引擎（月度调仓）。

核心约定（与 cta_project 一致）：
    月末 t 生成信号 → shift(1) → t+1 持有至下月末
    成本模型：换仓时计算 turnover × cost_model.round_trip

流程：
    1. 从 panel 的 weight 列读取组合权重（已由 builder 生成）
    2. 计算每日持仓收益 = Σ(weight_i × return_i)
    3. 换仓日计算交易成本
    4. 累积净值曲线
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.costs import CostModel, A_COST


@dataclass
class BacktestResult:
    """回测结果容器。"""
    strategy_name: str
    daily_returns: pd.Series
    equity: pd.Series
    turnover: pd.Series
    benchmark_returns: pd.Series | None = None
    n_days: int = 0
    cost_model: CostModel | None = None

    def __post_init__(self):
        if self.n_days == 0:
            self.n_days = len(self.daily_returns)


def run_backtest(
    panel: pd.DataFrame,
    rebalance_dates: list[pd.Timestamp] | None = None,
    cost_model: CostModel = A_COST,
    return_col: str = "daily_return",
    weight_col: str = "weight",
    date_col: str = "date",
    benchmark_col: str | None = None,
    strategy_name: str = "multi_factor",
) -> BacktestResult:
    """向量化回测。

    Parameters
    ----------
    panel : 含 date/ticker/daily_return/weight 列的 DataFrame。
    rebalance_dates : 调仓日列表（月末日）。若为 None，则每天重新读取 weight。
    cost_model : 交易成本模型。
    """
    df = panel.copy()
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()

    # 日收益率
    if return_col not in df.columns:
        if "close" in df.columns:
            df[return_col] = df.groupby("ticker")["close"].pct_change()
        else:
            raise KeyError(f"缺 {return_col} 或 close 列")

    # 确定调仓日集合
    if rebalance_dates is not None:
        rebal_set = set(pd.to_datetime(rebalance_dates).normalize())
    else:
        # 退化为：weight 非零的日子即为有持仓
        rebal_set = None

    # 按日期聚合组合收益
    df["weighted_ret"] = df[weight_col] * df[return_col]
    daily = df.groupby(date_col).apply(
        lambda g: pd.Series({
            "portfolio_ret": (g[weight_col] * g[return_col]).sum(),
            "n_holdings": (g[weight_col] > 0).sum(),
        })
    )

    # 换手率 = 调仓日权重变化量
    # 近似：在调仓日计算新旧权重差异
    if rebalance_dates is not None and len(rebalance_dates) > 0:
        # 在调仓日，前一日权重 → 新权重，差异即为换手
        weight_pivot = df.pivot_table(index=date_col, columns="ticker", values=weight_col, fill_value=0)
        weight_pivot = weight_pivot.sort_index()
        rebal_series = pd.Series(weight_pivot.index.isin(rebal_set), index=weight_pivot.index)
        turnover = weight_pivot.diff().abs().sum(axis=1)
        turnover = turnover * rebal_series  # 仅在调仓日计换手
        turnover = turnover.reindex(daily.index).fillna(0)
    else:
        turnover = pd.Series(0, index=daily.index)

    # 成本
    cost = turnover * cost_model.round_trip

    # 净收益
    net_ret = daily["portfolio_ret"] - cost
    net_ret = net_ret.fillna(0)

    # 净值曲线
    equity = (1 + net_ret).cumprod()

    # 基准收益
    bench_ret = None
    if benchmark_col and benchmark_col in df.columns:
        bench_ret = df.groupby(date_col)[benchmark_col].mean().reindex(daily.index).fillna(0)

    return BacktestResult(
        strategy_name=strategy_name,
        daily_returns=net_ret,
        equity=equity,
        turnover=turnover,
        benchmark_returns=bench_ret,
        cost_model=cost_model,
    )
