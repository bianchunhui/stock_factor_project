"""回测指标计算。

沿袭 cta_project/backtest/metrics 的约定，增加相对基准的指标。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RF_ANNUAL = 0.02


def _safe_series(x) -> pd.Series:
    s = pd.Series(x).dropna()
    return s


def annualized_return(returns: pd.Series) -> float:
    s = _safe_series(returns)
    if s.empty:
        return 0.0
    return (1 + s).prod() ** (TRADING_DAYS / len(s)) - 1


def annualized_vol(returns: pd.Series) -> float:
    s = _safe_series(returns)
    if s.empty or s.std() == 0:
        return 0.0
    return s.std() * np.sqrt(TRADING_DAYS)


def sharpe_ratio(returns: pd.Series, rf: float = RF_ANNUAL) -> float:
    vol = annualized_vol(returns)
    if vol < 1e-10:
        return 0.0
    return (annualized_return(returns) - rf) / vol


def max_drawdown(equity: pd.Series) -> tuple[float, int, int]:
    """返回 (最大回撤, 峰位索引, 谷位索引)。"""
    eq = _safe_series(equity)
    if eq.empty:
        return 0.0, 0, 0
    cummax = eq.cummax()
    dd = (eq - cummax) / cummax
    mdd = dd.min()
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    return mdd, peak, trough


def calmar_ratio(returns: pd.Series, equity: pd.Series) -> float:
    mdd, _, _ = max_drawdown(equity)
    if abs(mdd) < 1e-10:
        return 0.0
    return annualized_return(returns) / abs(mdd)


def information_ratio(excess_returns: pd.Series) -> float:
    """跟踪误差信息比率 = mean(超额) / std(超额)。"""
    s = _safe_series(excess_returns)
    if s.empty:
        return 0.0
    te = s.std() * np.sqrt(TRADING_DAYS)
    if te < 1e-10:
        return 0.0
    return annualized_return(s) / te


def win_rate(returns: pd.Series) -> float:
    s = _safe_series(returns)
    if s.empty:
        return 0.0
    return (s > 0).mean()


def turnover_pa(turnover: pd.Series) -> float:
    """年化换手率。"""
    s = _safe_series(turnover)
    if s.empty:
        return 0.0
    return s.mean() * TRADING_DAYS


def summarize(
    returns: pd.Series,
    equity: pd.Series,
    turnover: pd.Series | None = None,
    bench_returns: pd.Series | None = None,
) -> dict:
    """汇总所有回测指标。"""
    ret = annualized_return(returns)
    vol = annualized_vol(returns)
    sr = sharpe_ratio(returns)
    mdd_val, _, _ = max_drawdown(equity)
    cal = calmar_ratio(returns, equity)
    wr = win_rate(returns)

    out = {
        "年化收益": ret,
        "年化波动": vol,
        "夏普比率": sr,
        "最大回撤": mdd_val,
        "卡玛比率": cal,
        "胜率": wr,
    }
    if turnover is not None:
        out["年化换手"] = turnover_pa(turnover)
    if bench_returns is not None:
        excess = returns - bench_returns.reindex(returns.index).fillna(0)
        out["超额收益"] = annualized_return(excess)
        out["信息比率"] = information_ratio(excess)
    return out


def print_summary(m: dict, title: str = "") -> None:
    title = title or "回测指标"
    print(f"\n{'=' * 44}")
    print(f" {title}")
    print(f"{'=' * 44}")
    for k, v in m.items():
        if isinstance(v, float):
            if abs(v) < 1:
                print(f"  {k:<10}: {v:.4f}")
            else:
                print(f"  {k:<10}: {v:.2f}")
    print(f"{'=' * 44}")
