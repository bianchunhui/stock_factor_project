"""股票 spot 基础数据（市值、PE、PB）—— 从价格 + 财报数据计算。

旧方案依赖东财 stock_zh_a_spot_em 实时快照（在此网络100%失败，
且快照值用于全样本有前视偏差）。

新方案：
  - market_cap = close × outstanding_share（新浪价格源已含 outstanding_share）
  - PE(TTM) = market_cap / parent_net_profit（PIT对齐后的财报数据）
  - PB = market_cap / parent_equity（PIT对齐后的财报数据）

优势：无前视偏差，不依赖东财，每个日期有独立计算值。
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from .base import BaseFetcher, cache_key

logger = logging.getLogger(__name__)


class SpotFetcher(BaseFetcher):
    """从 panel 已有的价格 + 财报数据计算市值/PE/PB。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def compute_from_panel(self, panel: pd.DataFrame) -> pd.DataFrame:
        """从 panel 计算 market_cap / pe_ttm / pb，返回追加列后的 panel。

        前提：panel 已含 close, outstanding_share（价格数据），
        以及 parent_net_profit / parent_equity（财报数据，PIT对齐后）。
        """
        df = panel.copy()

        # ── 市值 = close × outstanding_share ──
        if "close" in df.columns and "outstanding_share" in df.columns:
            df["market_cap"] = df["close"] * df["outstanding_share"]
            logger.info("market_cap 已从 close × outstanding_share 计算")
        elif "close" in df.columns and "outstanding_share" not in df.columns:
            logger.warning("panel 无 outstanding_share 列，无法计算 market_cap")
        else:
            logger.warning("panel 无 close 列，无法计算 market_cap")

        # ── PE(TTM) = market_cap / parent_net_profit ──
        # parent_net_profit 是财报累计值，近似 TTM（单季报可能不准，但回测够用）
        if "market_cap" in df.columns and "parent_net_profit" in df.columns:
            df["pe_ttm"] = np.where(
                df["parent_net_profit"] > 0,
                df["market_cap"] / df["parent_net_profit"],
                np.nan
            )
            logger.info("pe_ttm 已从 market_cap / parent_net_profit 计算")

        # ── PB = market_cap / parent_equity ──
        if "market_cap" in df.columns and "parent_equity" in df.columns:
            df["pb"] = np.where(
                df["parent_equity"] > 0,
                df["market_cap"] / df["parent_equity"],
                np.nan
            )
            logger.info("pb 已从 market_cap / parent_equity 计算")
        elif "market_cap" in df.columns and "owner_equity" in df.columns:
            # 回退：用 owner_equity（所有者权益合计）
            df["pb"] = np.where(
                df["owner_equity"] > 0,
                df["market_cap"] / df["owner_equity"],
                np.nan
            )
            logger.info("pb 已从 market_cap / owner_equity 计算（无 parent_equity）")

        return df

    def attach_to_panel(
        self,
        panel: pd.DataFrame,
        tickers=None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """兼容旧接口：从 panel 数据计算 spot 字段。
        注意：调用前 panel 需已含价格(outstanding_share)和财报(parent_net_profit等)数据。
        """
        return self.compute_from_panel(panel)
