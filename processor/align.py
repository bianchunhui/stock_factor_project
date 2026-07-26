"""forward return 对齐与信号对齐。

防前视约定（与 cta_project/news_event_project 一致）：
    信号在 t 生成 → t+1 开盘建仓 → 持有至 t+N 收盘平仓
    forward_N_return = (close[t+N] - open[t+1]) / open[t+1]

注意：akshare 日频未必有可靠 open 字段（腾讯源无 open、东财有）。
为稳健起见，默认用 close[t+N] / close[t] - 1 作为 forward return 近似
（即 t 日收盘信号，t+1 持有到 t+N），并在文档中标注。若 open 可用，
可切换 use_open=True 用 open[t+1]。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_forward_returns(
    panel: pd.DataFrame,
    periods: list[int] | None = None,
    price_col: str = "close",
    open_col: str = "open",
    use_open: bool = False,
) -> pd.DataFrame:
    """为 panel 追加 forward_N_return 列。

    Parameters
    ----------
    periods : list[int]
        持有期（交易日）。默认 [1, 5, 10, 21]。
    use_open : bool
        True: 用 open[t+1] 作为买入价（更精确）。
        False: 用 close[t] 近似（更稳健，腾讯源也能用）。
    """
    if periods is None:
        periods = [1, 5, 10, 21]
    df = panel.copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    for n in periods:
        if use_open and open_col in df.columns:
            buy = df.groupby("ticker")[open_col].shift(-1)
            sell = df.groupby("ticker")[price_col].shift(-n)
            df[f"forward_{n}d_return"] = sell / buy - 1.0
        else:
            # close[t] 信号 → close[t+N] 平仓（近似 t+1 持有）
            future = df.groupby("ticker")[price_col].shift(-n)
            df[f"forward_{n}d_return"] = future / df[price_col] - 1.0
    return df


def align_factor_to_return(
    panel: pd.DataFrame,
    factor_col: str,
    return_col: str = "forward_21d_return",
    shift: int = 1,
) -> pd.DataFrame:
    """把因子值与对应 forward return 对齐到同一行（防前视）。

    即 factor[t] 对应 forward_return[t]（已在 compute_forward_returns 中 shift）。
    若 factor 用 t 日数据预测 t+1 起 N 日收益，shift=1 表示因子延迟 1 日生效。

    返回含 [date, ticker, factor_col, return_col] 且均非空的 DataFrame。
    """
    df = panel[["date", "ticker", factor_col, return_col]].copy()
    df[factor_col] = df.groupby("ticker")[factor_col].shift(shift)
    df = df.dropna(subset=[factor_col, return_col])
    return df
