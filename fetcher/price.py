"""股票与指数日频行情抓取器。

数据源策略：
- A 股日频：主用新浪 stock_zh_a_daily（含 volume/turnover/outstanding_share，字段完整）；
             失败回退东财 stock_zh_a_hist（东财在此网络环境基本不通）
- A 股指数：新浪 stock_zh_index_daily（东财偶发限流，新浪稳定）
- 港股日频：新浪 stock_hk_daily（前复权）
- 港股指数：新浪 stock_hk_index_daily_sina

输出统一英文列名：
    date, ticker, open, high, low, close, volume, amount, turnover(换手率%)
"""
from __future__ import annotations

import time
from typing import Optional

import akshare as ak
import pandas as pd

from .base import BaseFetcher, cache_key, today_str


def _to_a_em_symbol(code: str) -> str:
    """东财 stock_zh_a_hist 接受 6 位代码（不带市场前缀）。"""
    return code.strip().lower().replace("sh", "").replace("sz", "").replace("bj", "")


def _to_a_tx_symbol(code: str) -> str:
    """腾讯接口需要带 sh/sz/bj 前缀。"""
    code = code.strip()
    if code.startswith(("sh", "sz", "bj")):
        return code.lower()
    if code.startswith(("60", "68")):
        return "sh" + code
    if code.startswith(("83", "87", "92", "43", "88")):
        return "bj" + code
    return "sz" + code


def _to_a_sina_symbol(code: str) -> str:
    """新浪 stock_zh_a_daily 需要带 sh/sz 前缀。"""
    code = code.strip()
    if code.startswith(("sh", "sz")):
        return code.lower()
    if code.startswith(("60", "68")):
        return "sh" + code
    return "sz" + code


def _to_index_sina_symbol(code: str) -> str:
    """新浪指数代码：sh000300 / sz399006 / hkHSI。"""
    code = str(code).strip().lower()
    if code.startswith(("sh", "sz")):
        return code
    if code in ("hsi",):
        return "hkHSI"
    if code.startswith("hk"):
        return "hk" + code[2:]
    if code.startswith(("000", "950")):
        return "sh" + code
    return "sz" + code


class PriceFetcher(BaseFetcher):
    """股票与指数日频行情抓取器。"""

    # 东财 A 股列名 -> 标准英文
    _EM_COL_MAP = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_chg",
        "涨跌额": "chg",
        "换手率": "turnover",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # --------------------------------------------------
    # A 股个股日频
    # --------------------------------------------------
    def _normalize_em(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        df = df.rename(columns=self._EM_COL_MAP)
        keep = [c for c in ("date", "open", "close", "high", "low",
                            "volume", "amount", "turnover", "pct_chg") if c in df.columns]
        df = df[keep].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df["ticker"] = ticker
        for c in ("open", "close", "high", "low", "volume", "amount", "turnover"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    def _normalize_sina(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        # 新浪源列: date open high low close volume amount outstanding_share turnover
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df["ticker"] = ticker
        for c in ("open", "close", "high", "low", "volume", "amount",
                   "turnover", "outstanding_share"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        keep = [c for c in ("date", "ticker", "open", "close", "high", "low",
                            "volume", "amount", "turnover",
                            "outstanding_share") if c in df.columns]
        return df[keep].copy()

    def get_a_share_daily(
        self,
        code: str,
        start_date: str = "20200101",
        end_date: Optional[str] = None,
        adjust: str = "hfq",
        use_cache: bool = True,
        skip_em: bool = False,
    ) -> pd.DataFrame:
        """获取 A 股个股日频行情。

        Parameters
        ----------
        code : str
            6 位股票代码（可带 sh/sz/bj 前缀）。
        adjust : {"hfq", "qfq", ""}
            后复权（默认，回测用）/ 前复权 / 不复权。回测用后复权避免历史失真。
        skip_em : bool
            跳过东财备源（东财在此网络环境基本不通，默认走新浪主源即可）。
        """
        end_date = end_date or today_str()
        em_code = _to_a_em_symbol(code)
        TABLE, KEYS = "daily_price", ["ticker", "date"]
        if use_cache:
            cached = self.load_table(TABLE, market="ashare", ticker=em_code,
                                     date_ge=start_date)
            if cached is not None and len(cached) > 0:
                return cached

        # ---- 主源：新浪（有 volume + turnover + outstanding_share）----
        sina_code = _to_a_sina_symbol(code)
        try:
            raw = self._call_with_retry(
                ak.stock_zh_a_daily,
                symbol=sina_code, start_date=start_date, end_date=end_date, adjust=adjust,
                interval=1.0,
            )
            if raw is not None and len(raw) > 0:
                df = self._normalize_sina(raw, em_code)
                df["date"] = pd.to_datetime(df["date"]).dt.normalize()
                df = df[(df["date"] >= pd.to_datetime(start_date)) &
                        (df["date"] <= pd.to_datetime(end_date))]
                df = df.sort_values("date").reset_index(drop=True)
                self.save_table(df, TABLE, KEYS, market="ashare")
                return df
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "新浪日频失败 %s: %s，回退东财源", em_code, type(e).__name__
            )

        # ---- 备源：东财（新浪失败时才尝试）----
        if not skip_em:
            try:
                raw = self._call_with_retry(
                    ak.stock_zh_a_hist,
                    symbol=em_code, period="daily",
                    start_date=start_date, end_date=end_date, adjust=adjust,
                    interval=0.6,
                )
                if raw is not None and len(raw) > 0:
                    df = self._normalize_em(raw, em_code)
                    df = df.sort_values("date").reset_index(drop=True)
                    self.save_table(df, TABLE, KEYS, market="ashare")
                    return df
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "东财日频失败 %s: %s", em_code, type(e).__name__
                )

        # 两个源都失败
        return pd.DataFrame()

    # --------------------------------------------------
    # A 股指数日频
    # --------------------------------------------------
    def get_a_index_daily(
        self,
        symbol: str = "000300",
        start_date: str = "20200101",
        end_date: Optional[str] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取 A 股指数日频（基准用）。新浪源稳定。"""
        end_date = end_date or today_str()
        TABLE, KEYS = "daily_price", ["ticker", "date"]
        if use_cache:
            cached = self.load_table(TABLE, market="ashare", ticker=symbol)
            if cached is not None and len(cached) > 0:
                return cached

        sina_code = _to_index_sina_symbol(symbol)
        raw = self._call_with_retry(ak.stock_zh_index_daily, symbol=sina_code, interval=0.5)
        df = raw.rename(columns={"date": "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[(df["date"] >= pd.to_datetime(start_date)) &
                (df["date"] <= pd.to_datetime(end_date))]
        df["ticker"] = symbol
        df = df.sort_values("date").reset_index(drop=True)
        self.save_table(df, TABLE, KEYS, market="ashare")
        return df

    # --------------------------------------------------
    # 港股个股日频
    # --------------------------------------------------
    def get_hk_daily(
        self,
        code: str,
        start_date: str = "20200101",
        end_date: Optional[str] = None,
        adjust: str = "qfq",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取港股个股日频（新浪源，前复权）。"""
        end_date = end_date or today_str()
        TABLE, KEYS = "daily_price", ["ticker", "date"]
        if use_cache:
            cached = self.load_table(TABLE, market="hk", ticker=code, date_ge=start_date)
            if cached is not None and len(cached) > 0:
                return cached

        raw = self._call_with_retry(ak.stock_hk_daily, symbol=code, adjust=adjust, interval=0.6)
        df = raw.rename(columns={
            "date": "date", "open": "open", "close": "close",
            "high": "high", "low": "low", "volume": "volume", "amount": "amount",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        for c in ("open", "close", "high", "low", "volume", "amount"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[(df["date"] >= pd.to_datetime(start_date)) &
                (df["date"] <= pd.to_datetime(end_date))]
        df["ticker"] = code
        df = df.sort_values("date").reset_index(drop=True)
        self.save_table(df, TABLE, KEYS, market="hk")
        return df

    # --------------------------------------------------
    # 港股指数日频
    # --------------------------------------------------
    def get_hk_index_daily(
        self,
        symbol: str = "HSI",
        start_date: str = "20200101",
        end_date: Optional[str] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取港股指数日频（恒生指数基准）。"""
        end_date = end_date or today_str()
        TABLE, KEYS = "daily_price", ["ticker", "date"]
        if use_cache:
            cached = self.load_table(TABLE, market="hk", ticker=symbol)
            if cached is not None and len(cached) > 0:
                return cached

        sina_code = _to_index_sina_symbol(symbol)
        raw = self._call_with_retry(
            ak.stock_hk_index_daily_sina, symbol=sina_code, interval=0.6
        )
        df = raw.rename(columns={
            "date": "date", "open": "open", "close": "close",
            "high": "high", "low": "low", "volume": "volume",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        for c in ("open", "close", "high", "low", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[(df["date"] >= pd.to_datetime(start_date)) &
                (df["date"] <= pd.to_datetime(end_date))]
        df["ticker"] = symbol
        df = df.sort_values("date").reset_index(drop=True)
        self.save_table(df, TABLE, KEYS, market="hk")
        return df

    # --------------------------------------------------
    # 统一入口（按市场路由）
    # --------------------------------------------------
    def get_daily(
        self,
        code: str,
        market: str = "A",
        start_date: str = "20200101",
        end_date: Optional[str] = None,
        adjust: str = "hfq",
        use_cache: bool = True,
        skip_em: bool = False,
    ) -> pd.DataFrame:
        """统一日频行情入口，按 market 路由。

        Parameters
        ----------
        market : {"A", "HK"}
            A 股或港股。
        skip_em : bool
            跳过东财备源（仅 A 股有效；新浪主源失败时不再尝试东财）。
        """
        if market.upper() == "A":
            return self.get_a_share_daily(code, start_date, end_date, adjust, use_cache, skip_em=skip_em)
        elif market.upper() == "HK":
            return self.get_hk_daily(code, start_date, end_date, adjust, use_cache)
        else:
            raise ValueError(f"未知 market: {market}")

    def get_benchmark_daily(
        self,
        benchmark: str,
        market: str = "A",
        start_date: str = "20200101",
        end_date: Optional[str] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取基准指数日频（用于超额收益与 Beta）。"""
        if market.upper() == "A":
            return self.get_a_index_daily(benchmark, start_date, end_date, use_cache)
        elif market.upper() == "HK":
            return self.get_hk_index_daily(benchmark, start_date, end_date, use_cache)
        else:
            raise ValueError(f"未知 market: {market}")
