"""行业分类与中性化工具。

为截面因子提供申万行业分类列，用于 processor.normalize.neutralize 中
进行 OLS 行业 + 市值中性化。

数据源（按优先级）：
  1. 东方财富行业板块成分 (stock_board_industry_cons_em) — primary，push2 接口稳定、覆盖全 A
  2. 申万行业成分 (index_component_sw) — fallback（swsresearch 近年常不稳定，易报
     "invalid error value specified"），仅作兜底
结果按 EM 源缓存；中性化对行业分类口径不敏感，东财行业即可。

输出：
  DataFrame [ticker, industry_name] 或长表 panel 带 industry 列
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import pandas as pd

from fetcher import BaseFetcher, cache_key
from fetcher.store.db import query, save_ref

logger = logging.getLogger(__name__)


# 申万一级行业经典代码（从 empirical 测试得到的有效子集）
# 注意：部分 801xxx 代码 index_component_sw 返回 KeyError，会在运行时跳过
SW_LEVEL1_CODES = [
    "801010",   # 农林牧渔
    "801030",   # 钢铁
    "801040",   # 有色金属
    "801050",   # 煤炭
    "801080",   # 机械设备
    "801110",   # 汽车
    "801120",   # 家用电器
    "801130",   # 食品饮料
    "801140",   # 纺织服饰
    "801150",   # 医药生物
    "801160",   # 商贸零售
    "801170",   # 社会服务
    "801180",   # 计算机
    "801200",   # 通信
    "801210",   # 电子
    "801230",   # 非银金融
    "801250",   # 综合
    "801260",   # 建筑材料/建筑装饰
    "801270",   # 公用事业
    "801280",   # 交通运输
]


class IndustryFetcher(BaseFetcher):
    """行业分类抓取器。

    用法：
    >>> ind = IndustryFetcher()
    >>> mapping = ind.get_ticker_to_industry()  # {ticker: industry_name}
    >>> panel = ind.attach_industry(panel, mapping)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        import akshare as ak
        self._ak = ak

    # ── 获取申万行业树（仅用于信息） ────────────────────────────────
    def get_industry_tree(self, use_cache: bool = True) -> pd.DataFrame:
        """获取申万行业三级分类树（缓存走 db ref_industry_tree）。"""
        if use_cache:
            try:
                df = query("SELECT * FROM ref_industry_tree", market="ashare")
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass

        df = self._call_with_retry(self._ak.sw_index_third_info)
        if use_cache and df is not None and not df.empty:
            keys = ["行业代码"] if "行业代码" in df.columns else (
                ["代码"] if "代码" in df.columns else None)
            if keys:
                save_ref(df, "ref_industry_tree", "ashare", keys)
        return df

    # ── 构建 ticker -> 行业映射 ─────────────────────────────────────
    def get_ticker_to_industry(self, use_cache: bool = True) -> Dict[str, str]:
        """获取股票代码 -> 行业名称 映射字典。

        数据源优先级（任一成功即用）：
          1. 东方财富行业板块成分 stock_board_industry_cons_em（稳定，覆盖全 A）
          2. 申万成分 index_component_sw（swsresearch，近年常不稳定，作兜底）

        命中缓存则跳过所有网络请求。
        """
        ck = cache_key("industry_map_em")
        if use_cache:
            try:
                df = query("SELECT ticker, industry FROM ref_industry_map", market="ashare")
                if df is not None and not df.empty:
                    return df.set_index("ticker")["industry"].to_dict()
            except Exception:
                pass

        mapping = self._fetch_em_industry_map()
        if not mapping:
            logger.warning("东方财富行业映射为空，尝试申万兜底源")
            mapping = self._fetch_sw_industry_map()

        if not mapping:
            logger.warning(
                "行业映射获取失败（东财+申万均不可用）。因子中性化将退化为仅市值中性化。"
            )
            return {}

        map_df = pd.DataFrame.from_dict(mapping, orient="index", columns=["industry"])
        map_df.index.name = "ticker"
        map_df = map_df.reset_index()
        if use_cache:
            save_ref(map_df, "ref_industry_map", "ashare", ["ticker"])
        logger.info("行业映射构建完成: %d 只股票", len(map_df))
        return mapping

    def _fetch_em_industry_map(self) -> Dict[str, str]:
        """东方财富行业板块 -> {ticker: 板块名称}（primary）。"""
        mapping: Dict[str, str] = {}
        try:
            boards = self._call_with_retry(self._ak.stock_board_industry_name_em)
        except Exception as e:
            logger.warning("东方财富行业板块列表获取失败: %s", e)
            return mapping
        if boards is None or boards.empty:
            return mapping

        # 预建 板块名称 -> 板块代码(BKxxxx) 映射，避免每只板块重复拉列表
        name_to_code = dict(
            zip(boards["板块名称"].astype(str), boards["板块代码"].astype(str))
        )
        for name, bk in name_to_code.items():
            try:
                cons = self._call_with_retry(
                    self._ak.stock_board_industry_cons_em, symbol=bk
                )
            except Exception as e:
                logger.debug("东财板块 %s 成分获取失败: %s", name, e)
                continue
            if cons is None or cons.empty or "代码" not in cons.columns:
                continue
            for t in cons["代码"].astype(str).str[-6:].str.zfill(6):
                mapping[t] = name
            time.sleep(0.05)
        return mapping

    def _fetch_sw_industry_map(self) -> Dict[str, str]:
        """申万一级行业成分 -> {ticker: 行业名称}（fallback）。"""
        mapping: Dict[str, str] = {}
        for code in SW_LEVEL1_CODES:
            try:
                df = self._call_with_retry(
                    self._ak.index_component_sw, symbol=code, interval=0.3
                )
            except Exception as e:
                logger.debug("申万行业 %s 获取失败: %s", code, e)
                continue
            if df is None or len(df) == 0:
                continue

            tree = self.get_industry_tree(use_cache=True)
            industry_name = self._industry_name_for_code(code, tree)
            ticker_col = "证券代码" if "证券代码" in df.columns else "代码"
            for raw in df[ticker_col]:
                digs = "".join(ch for ch in str(raw) if ch.isdigit())[-6:]
                if len(digs) == 6:
                    mapping[digs] = industry_name
            time.sleep(0.2)
        return mapping

    @staticmethod
    def _industry_name_for_code(code: str, tree_df: pd.DataFrame) -> str:
        """根据行业代码从 sw_index_third_info 中推断行业名。"""
        # 801010 对应 8501xx 组
        # 简单映射前缀：801010 -> 8501, 801030 -> 8503, ...
        prefix = code[2:4] if len(code) >= 4 else ""
        # 在 tree 中找行业代码以 8501 开头且上级行业为空（或行业代码就是 8501xx）的行
        # 这里简化：返回 code 本身
        if not tree_df.empty and "行业代码" in tree_df.columns and "行业名称" in tree_df.columns:
            # 模糊匹配：801030 -> 8503 开头，取第一个行业名
            matches = tree_df[tree_df["行业代码"].str.startswith(f"85{prefix}", na=False)]
            if not matches.empty:
                return str(matches.iloc[0]["行业名称"])
        return f"行业_{code}"

    # ── 附加到 panel ──────────────────────────────────────────────
    def attach_industry(
        self,
        panel: pd.DataFrame,
        mapping: Optional[Dict[str, str]] = None,
        fill_na: str = "其他",
    ) -> pd.DataFrame:
        """把行业列附加到 panel（长表）。"""
        if mapping is None:
            mapping = self.get_ticker_to_industry(use_cache=True)

        panel = panel.copy()
        panel["industry"] = panel["ticker"].map(mapping).fillna(fill_na)
        return panel


# ── 便捷函数 ────────────────────────────────────────────────────
def attach_industry_to_panel(
    panel: pd.DataFrame,
    fetcher: Optional[IndustryFetcher] = None,
) -> pd.DataFrame:
    """一键给 panel 添加行业列。"""
    fetcher = fetcher or IndustryFetcher()
    return fetcher.attach_industry(panel)
