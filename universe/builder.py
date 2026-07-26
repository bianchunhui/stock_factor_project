"""Universe 构建：成分获取 + 过滤。

支持三种模式：
    mode="A"    : 沪深京 A 股（含科创/创业/北交所）
    mode="HK"   : 港股通成分
    mode="A_HK" : 两者合并

过滤规则（可配置）：
    - drop_st        : 去除 ST /*ST
    - min_list_days  : 上市满 N 个交易日（去新股）
    - min_amount_20d : 近 20 日日均成交额下限（流动性）
    - drop_paused    : 调仓日停牌剔除

注意：成分股随时间变动，本实现先以"当前成分 + 历史成分"近似。
退市股通过 stock_info_*_delist 补充，缓解幸存者偏差。
"""
from __future__ import annotations

import logging
from typing import Optional

import akshare as ak
import pandas as pd

from config import UNIVERSE_FILTERS, BENCHMARK, SH_PREFIX, SZ_PREFIX, BJ_PREFIX
from fetcher import BaseFetcher, cache_key, today_str

logger = logging.getLogger(__name__)


def detect_market(code: str) -> str:
    """根据 A 股代码判定市场：SH / SZ / BJ。

    >>> detect_market("600519")  -> "SH"
    >>> detect_market("000001")  -> "SZ"
    >>> detect_market("300750")  -> "SZ"
    >>> detect_market("688981")  -> "SH"
    >>> detect_market("835174")  -> "BJ"
    """
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj")):
        return code[:2].upper()
    if code.startswith(SH_PREFIX):
        return "SH"
    if code.startswith(BJ_PREFIX):
        return "BJ"
    if code.startswith(SZ_PREFIX):
        return "SZ"
    # 兜底按深市处理
    return "SZ"


def full_code(code: str) -> str:
    """返回带市场前缀的全代码（如 sh600519）。"""
    code = str(code).strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code
    return detect_market(code).lower() + code


class Universe:
    """选股池构建器。

    Parameters
    ----------
    mode : {"A", "HK", "A_HK"}
    start, end : str
        回测区间，形如 "20210101"。
    index_symbol : str or None
        若指定（如 "000300"），则 A 股侧限定为该指数成分，而非全市场。
    filters : dict or None
        覆盖默认过滤参数。
    """

    def __init__(
        self,
        mode: str = "A",
        start: str = "20210101",
        end: Optional[str] = None,
        index_symbol: Optional[str] = None,
        filters: Optional[dict] = None,
        fetcher: Optional[BaseFetcher] = None,
    ):
        self.mode = mode.upper()
        if self.mode not in ("A", "HK", "A_HK"):
            raise ValueError(f"未知 mode: {mode}")
        self.start = start
        self.end = end or today_str()
        self.index_symbol = index_symbol
        self._fetcher = fetcher or BaseFetcher()
        self.filters = self._merge_filters(filters)

    def _merge_filters(self, override: Optional[dict]) -> dict:
        base = {}
        if self.mode == "A" or self.mode == "A_HK":
            base.update(UNIVERSE_FILTERS["A"])
        if self.mode == "HK" or self.mode == "A_HK":
            base.update(UNIVERSE_FILTERS["HK"])
        if override:
            base.update(override)
        return base

    def benchmark(self) -> str:
        return BENCHMARK[self.mode]

    # --------------------------------------------------
    # A 股成分
    # --------------------------------------------------
    def _a_constituents(self, use_cache: bool = True) -> pd.DataFrame:
        """获取 A 股成分（全市场 或 指定指数成分）。

        返回列: ticker, name, market
        """
        if self.index_symbol:
            return self._a_index_constituents(self.index_symbol, use_cache)

        key = cache_key("a_all_cons", today_str())
        if use_cache:
            cached = self._fetcher._load_cache(key)
            if cached is not None:
                return cached

        # 东财实时行情含全部沪深京 A 股
        try:
            raw = self._fetcher._call_with_retry(ak.stock_zh_a_spot_em, interval=0.8)
            df = pd.DataFrame({
                "ticker": raw["代码"].astype(str).str.zfill(6),
                "name": raw.get("名称", pd.NA),
            })
            df["market"] = df["ticker"].apply(detect_market)
            self._fetcher._save_cache(df, key)
            return df
        except Exception as e:
            logger.warning("东财全市场成分获取失败，回退交易所接口: %s", e)
            return self._a_constituents_fallback(use_cache)

    def _a_constituents_fallback(self, use_cache: bool) -> pd.DataFrame:
        """交易所代码接口兜底（沪/深/京）。"""
        frames = []
        for fn, mkt in [
            (ak.stock_info_sh_name_code, "SH"),
            (ak.stock_info_sz_name_code, "SZ"),
            (ak.stock_info_bj_name_code, "BJ"),
        ]:
            try:
                raw = self._fetcher._call_with_retry(fn, interval=0.6)
                # 列名可能是 证券代码/代码 等
                code_col = [c for c in raw.columns if "代码" in c][0]
                name_col = [c for c in raw.columns if "简称" in c or "名称" in c][0]
                frames.append(pd.DataFrame({
                    "ticker": raw[code_col].astype(str).str.zfill(6),
                    "name": raw[name_col],
                    "market": mkt,
                }))
            except Exception as e:
                logger.warning("%s 成分获取失败: %s", mkt, e)
        if not frames:
            return pd.DataFrame(columns=["ticker", "name", "market"])
        df = pd.concat(frames, ignore_index=True)
        return df

    def _a_index_constituents(self, symbol: str, use_cache: bool) -> pd.DataFrame:
        """获取指数成分（如沪深300=000300）。
        主用中证指数公司官方源（300只完整 + 权重），回退新浪源。
        """
        key = cache_key("a_idx_cons_v2", symbol, today_str())
        if use_cache:
            cached = self._fetcher._load_cache(key)
            if cached is not None:
                return cached

        # ---- 主源：中证指数公司（官方，完整300只 + 权重）----
        try:
            raw = self._fetcher._call_with_retry(
                ak.index_stock_cons_weight_csindex, symbol=symbol, interval=0.6
            )
            if raw is not None and len(raw) > 0:
                df = pd.DataFrame({
                    "ticker": raw["成分券代码"].astype(str).str.zfill(6),
                    "name": raw.get("成分券名称", pd.NA),
                    "weight": pd.to_numeric(raw.get("权重", pd.NA), errors="coerce"),
                })
                df["market"] = df["ticker"].apply(detect_market)
                self._fetcher._save_cache(df, key)
                return df
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "中证指数公司成分股失败 %s: %s，回退新浪源", symbol, type(e).__name__
            )

        # ---- 备源：新浪（可能不完整）----
        raw = self._fetcher._call_with_retry(ak.index_stock_cons, symbol=symbol, interval=0.6)
        df = pd.DataFrame({
            "ticker": raw["品种代码"].astype(str).str.zfill(6),
            "name": raw.get("品种名称", pd.NA),
        })
        df["market"] = df["ticker"].apply(detect_market)
        self._fetcher._save_cache(df, key)
        return df

    def _a_st_codes(self, use_cache: bool = True) -> set[str]:
        """获取 ST/*ST 代码集合。失败返回空集（不阻塞）。"""
        key = cache_key("a_st", today_str())
        if use_cache:
            cached = self._fetcher._load_cache(key)
            if cached is not None:
                return set(cached["ticker"].astype(str).str.zfill(6))
        try:
            raw = self._fetcher._call_with_retry(ak.stock_zh_a_st_em, interval=0.8)
            codes = set(raw["代码"].astype(str).str.zfill(6))
            self._fetcher._save_cache(
                pd.DataFrame({"ticker": list(codes)}), key
            )
            return codes
        except Exception as e:
            logger.warning("ST 板块获取失败（跳过 ST 过滤）: %s", e)
            return set()

    # --------------------------------------------------
    # 港股通成分
    # --------------------------------------------------
    def _hk_connect_constituents(self, use_cache: bool = True) -> pd.DataFrame:
        """获取港股通成分股。失败返回空 DataFrame。"""
        key = cache_key("hk_ggt", today_str())
        if use_cache:
            cached = self._fetcher._load_cache(key)
            if cached is not None:
                return cached
        try:
            raw = self._fetcher._call_with_retry(
                ak.stock_hk_ggt_components_em, interval=0.8
            )
            code_col = [c for c in raw.columns if "代码" in c][0]
            name_col = [c for c in raw.columns if "名称" in c or "简称" in c][0]
            df = pd.DataFrame({
                "ticker": raw[code_col].astype(str).str.zfill(5),
                "name": raw[name_col],
                "market": "HK",
            })
            self._fetcher._save_cache(df, key)
            return df
        except Exception as e:
            logger.warning("港股通成分获取失败（港股 universe 不可用）: %s", e)
            return pd.DataFrame(columns=["ticker", "name", "market"])

    # --------------------------------------------------
    # 成分汇总
    # --------------------------------------------------
    def constituents(self, use_cache: bool = True) -> pd.DataFrame:
        """返回合并后的成分表 [ticker, name, market]。

        重复 ticker 保留首次出现（A 股优先）。
        """
        frames = []
        if self.mode in ("A", "A_HK"):
            a = self._a_constituents(use_cache)
            if len(a):
                frames.append(a.assign(board="A"))
        if self.mode in ("HK", "A_HK"):
            hk = self._hk_connect_constituents(use_cache)
            if len(hk):
                frames.append(hk.assign(board="HK"))
        if not frames:
            return pd.DataFrame(columns=["ticker", "name", "market", "board"])
        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(subset=["ticker"], keep="first").reset_index(drop=True)
        return df

    def is_st(self, ticker: str, st_set: Optional[set[str]] = None) -> bool:
        """判断是否为 ST（仅 A 股有效）。"""
        if not st_set:
            st_set = self._a_st_codes()
        return ticker in st_set

    def describe(self, use_cache: bool = True) -> dict:
        """返回 universe 概况（用于日志/报告）。"""
        cons = self.constituents(use_cache)
        return {
            "mode": self.mode,
            "start": self.start,
            "end": self.end,
            "benchmark": self.benchmark(),
            "index_symbol": self.index_symbol,
            "n_constituents": len(cons),
            "filters": self.filters,
        }
