"""交易日历与调仓日工具。

数据源：akshare tool_trade_date_hist_sina（新浪财经-交易日历）
"""
from __future__ import annotations

import akshare as ak
import pandas as pd

from .base import BaseFetcher, cache_key, today_str


class CalendarFetcher(BaseFetcher):
    """交易日历抓取器。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def trade_dates(self, use_cache: bool = True) -> pd.Series:
        """获取历史所有交易日（升序），返回 pd.Series[date]。

        date 为 tz-naive 的 Timestamp（归一化到午夜）。
        """
        key = cache_key("calendar_all", today_str())
        if use_cache:
            cached = self._load_cache(key)
            if cached is not None:
                return pd.to_datetime(cached["trade_date"]).dt.normalize()

        raw = self._call_with_retry(ak.tool_trade_date_hist_sina)
        # akshare 返回列名 "trade_date"
        df = raw.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
        df = df.sort_values("trade_date").reset_index(drop=True)
        self._save_cache(df, key)
        return df["trade_date"]

    def trade_dates_between(self, start: str, end: str | None = None) -> list[pd.Timestamp]:
        """[start, end] 闭区间内的交易日列表。"""
        end = end or today_str()
        dates = self.trade_dates()
        s = pd.to_datetime(start).normalize()
        e = pd.to_datetime(end).normalize()
        return [d for d in dates if s <= d <= e]

    def month_end_dates(self, start: str, end: str | None = None) -> list[pd.Timestamp]:
        """月度调仓日：每月最后一个交易日。

        Parameters
        ----------
        start, end : str
            形如 "20210101" 的日期串。
        """
        dates = self.trade_dates_between(start, end)
        if not dates:
            return []
        s = pd.Series(dates)
        # 按年月分组取每组最大日期
        ym = s.dt.to_period("M")
        month_ends = s.groupby(ym).max()
        return sorted(month_ends.tolist())

    def rebalance_dates(
        self, start: str, end: str | None = None, freq: str = "M"
    ) -> list[pd.Timestamp]:
        """调仓日序列。

        Parameters
        ----------
        freq : {"M", "W", "Q"}
            月度 / 周度 / 季度。
        """
        dates = self.trade_dates_between(start, end)
        if not dates:
            return []
        s = pd.Series(dates)
        if freq == "M":
            period = s.dt.to_period("M")
        elif freq == "W":
            period = s.dt.to_period("W")
        elif freq == "Q":
            period = s.dt.to_period("Q")
        else:
            raise ValueError(f"未知 freq: {freq}")
        return sorted(s.groupby(period).max().tolist())
