"""沪深港通（北向资金）数据抓取器。

⚠️ 重要：港交所于 2024-08-16 起停止披露沪深股通实时买卖额与每日成交总额，
   `stock_hsgt_individual_em` 个股级持股数据**不再更新**。
   本模块数据仅覆盖 2014-11-17 ~ 2024-08-16，适合历史回测，不可用于实时选股。

数据源：东方财富 EM
  - stock_hsgt_hist_em              市场级历史汇总（每日净买额/余额）
  - stock_hsgt_individual_em(symbol) 个股级持股历史（逐日变动）⚠️ 截至 2024-08-16
  - stock_hsgt_fund_flow_summary_em  资金流向实时汇总

用于构建 Sentiment 类因子（仅历史段）：
  HSGT — 北向持股占比 / 持股变化
  Flow — 个股资金净流入
  FUp  — 北向增持幅度
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .base import BaseFetcher, cache_key

logger = logging.getLogger(__name__)

# 北向资金个股级数据的截止日期（港交所 2024-08-16 停报）
HSGT_DATA_END_DATE = pd.Timestamp("2024-08-16")


class HSGTFetcher(BaseFetcher):
    """沪深港通数据抓取器。

    用法
    ----
    >>> hf = HSGTFetcher()
    >>> hist = hf.get_market_history()        # 市场级汇总
    >>> holding = hf.get_stock_holding("000001") # 个股持股历史
    >>> flow = hf.get_fund_flow_summary()     # 实时资金流向
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        import akshare as ak
        self._ak = ak

    # ── 市场级：北向资金历史 ────────────────────────────────────────
    def get_market_history(self, symbol: str = "沪股通", use_cache: bool = True) -> pd.DataFrame:
        """获取沪深港通市场级历史数据。

        Parameters
        ----------
        symbol : str
            '沪股通' | '深股通' | '港股通(沪)' | '港股通(深)'
        use_cache : bool

        Returns
        -------
        DataFrame columns:
            date, net_buy_amount, buy_amount, sell_amount,
            cumulative_net_buy, capital_inflow, daily_quota,
            market_value, ...
        """
        ck = cache_key("hsgt_market", symbol)
        if use_cache:
            cached = self._load_cache(ck)
            if cached is not None:
                return cached

        logger.info("获取港股通市场历史: %s", symbol)
        df = self._call_with_retry(self._ak.stock_hsgt_hist_em, symbol=symbol)

        if df is None or len(df) == 0:
            return pd.DataFrame()

        # 标准化列名
        col_map = {
            "日期":           "date",
            "当日成交净买额":   "net_buy_amount",
            "买入成交额":      "buy_amount",
            "卖出成交额":      "sell_amount",
            "历史累计净买额":   "cumulative_net_buy",
            "当日资金流入":     "capital_inflow",
            "当日余额":        "daily_quota",
            "持股市值":       "market_value",
            "上证指数":       "index_close",
            "上证指数-涨跌幅":  "index_change_pct",
        }
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        # 数值列转 float
        for col in ["net_buy_amount", "buy_amount", "sell_amount",
                     "cumulative_net_buy", "capital_inflow", "daily_quota",
                     "market_value", "index_close", "index_change_pct"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if use_cache:
            self._save_cache(df, ck)
        return df

    # ── 个股级：北向持股历史（核心） ────────────────────────────────
    def get_stock_holding(
        self,
        code: str,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取个股的北向资金持股历史。

        这是构建 HSGT / Flow / FUp 因子的**核心数据源**。

        Parameters
        ----------
        code : str
            股票代码，如 '000001', '600519'
        use_cache : bool

        Returns
        -------
        DataFrame columns:
            date, close_price, change_pct,
            holding_shares, holding_value,
            holding_pct,          # 持股数量占A股百分比
            share_change,        # 今日增持股数
            fund_change,         # 今日增持资金（万元）
            value_change         # 今日持股市值变化
        """
        ck = cache_key("hsgt_stock", code)
        if use_cache:
            cached = self._load_cache(ck)
            if cached is not None:
                return cached

        logger.info("获取北向持股: %s", code)
        df = self._call_with_retry(self._ak.stock_hsgt_individual_em, symbol=code)

        if df is None or len(df) == 0:
            return pd.DataFrame()

        # 标准化列名
        col_map = {
            "持股日期":          "date",
            "当日收盘价":        "close_price",
            "当日涨跌幅":        "change_pct",
            "持股数量":          "holding_shares",
            "持股市值":          "holding_value",
            "持股数量占A股百分比": "holding_pct",
            "今日增持股数":       "share_change",
            "今日增持资金":       "fund_change",
            "今日持股市值变化":    "value_change",
        }
        df = df.rename(columns=col_map)

        # 类型转换
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        numeric_cols = [
            "close_price", "change_pct", "holding_shares", "holding_value",
            "holding_pct", "share_change", "fund_change", "value_change",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 添加 ticker 列
        df["ticker"] = code

        if use_cache:
            self._save_cache(df, ck)
        return df

    # ── 实时：资金流向汇总 ─────────────────────────────────────────
    def get_fund_flow_summary(self, use_cache: bool = False) -> pd.DataFrame:
        """获取最新资金流向汇总（通常不缓存，因为实时数据）。"""
        logger.info("获取资金流向汇总")
        try:
            df = self._call_with_retry(
                self._ak.stock_hsgt_fund_flow_summary_em,
                interval=0.1,  # 实时数据请求间隔短
            )
        except Exception as e:
            logger.warning("资金流向汇总获取失败: %s", e)
            return pd.DataFrame()

        if df is None or len(df) == 0:
            return pd.DataFrame()

        col_map = {
            "交易日":      "trade_date",
            "类型":        "market_type",
            "板块":        "sector",
            "资金方向":     "direction",
            "交易状态":     "status",
            "成交净买额":   "net_buy",
            "资金净流入":   "net_flow",
            "当日资金余额": "daily_balance",
            "上涨数":      "up_count",
            "持平数":      "flat_count",
            "下跌数":      "down_count",
            "相关指数":    "index_name",
            "指数涨跌幅":  "index_chg",
        }
        df = df.rename(columns=col_map)
        return df

    # ── 批量抓取多只股票的北向持股 ──────────────────────────────────
    def batch_holdings(
        self,
        codes: List[str],
        use_cache: bool = True,
        progress_every: int = 10,
    ) -> Dict[str, pd.DataFrame]:
        """批量获取多只股票的北向持股历史。

        Returns
        -------
        dict[str, DataFrame]  {code: holding_df}
        """
        results: Dict[str, pd.DataFrame] = {}
        total = len(codes)
        for i, code in enumerate(codes):
            try:
                h = self.get_stock_holding(code, use_cache=use_cache)
                results[code] = h
            except Exception as e:
                logger.warning("获取 %s 北向持股失败: %s", code, e)
                results[code] = pd.DataFrame()

            if (i + 1) % progress_every == 0 or i == total - 1:
                logger.info("北向持股进度: %d/%d (%.0f%%)",
                            i + 1, total, (i + 1) / total * 100)
            time.sleep(0.4)  # 避免限流

        return results

    # ── 合并为宽表（供因子计算使用） ────────────────────────────────
    def merge_holdings_to_panel(
        self,
        holdings_dict: Dict[str, pd.DataFrame],
        dates: Optional[pd.DatetimeIndex] = None,
    ) -> pd.DataFrame:
        """将多股票的持股数据合并为长格式 panel。

        Parameters
        ----------
        holdings_dict : {code: DataFrame}
            batch_holdings 的返回值
        dates : DatetimeIndex, optional
            截面日期范围（用于对齐）

        Returns
        -------
        DataFrame: [date, ticker, close_price, holding_pct, share_change, fund_change, ...]
        """
        panels = []
        for code, df in holdings_dict.items():
            if df.empty:
                continue
            sub = df[["date", "ticker", "holding_pct", "share_change",
                      "fund_change", "value_change"]].copy()
            panels.append(sub)

        if not panels:
            return pd.DataFrame()

        panel = pd.concat(panels, ignore_index=True)
        panel = panel.dropna(subset=["date", "ticker"])

        if dates is not None:
            panel = panel[panel["date"].isin(dates)]

        return panel.sort_values(["date", "ticker"]).reset_index(drop=True)
