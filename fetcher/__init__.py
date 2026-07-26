"""数据抓取包。

公开 API：
    BaseFetcher        —— 公共基类（节流/重试/缓存）
    CalendarFetcher    —— 交易日历
    PriceFetcher       —— A 股 / 港股 / 指数日频行情
    FinancialFetcher   —— 三大报表 + 财务指标（东方财富 EM）
    HSGTFetcher        —— 沪深港通北向持股（⚠️ 2024-08-16 后停报）
    FundFlowFetcher    —— 个股资金流（替代北向的现代情绪因子源）
    IndustryFetcher    —— 申万行业分类映射
    SpotFetcher        —— 东财实时行情（市值/PE/PB）

⚠️ 北向资金数据自 2024-08-16 起港交所停止披露个股级实时数据。
   HSGTFetcher 仅支持历史回测（2017-03 ~ 2024-08）；
   实时情绪因子建议改用 FundFlowFetcher。
"""
from .base import BaseFetcher, cache_key, today_str, to_datetime_safe
from .calendar import CalendarFetcher
from .price import PriceFetcher
from .financial import FinancialFetcher
from .hsgt import HSGTFetcher, HSGT_DATA_END_DATE
from .fund_flow import FundFlowFetcher
from .industry import IndustryFetcher
from .spot import SpotFetcher

__all__ = [
    "BaseFetcher",
    "CalendarFetcher",
    "PriceFetcher",
    "FinancialFetcher",
    "HSGTFetcher",
    "FundFlowFetcher",
    "IndustryFetcher",
    "SpotFetcher",
    "HSGT_DATA_END_DATE",
    "cache_key",
    "today_str",
    "to_datetime_safe",
]
