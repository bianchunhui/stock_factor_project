"""财报数据抓取器。

数据源：东方财富 EM 三大报表接口（按报告期）
  - stock_profit_sheet_by_report_em      利润表
  - stock_balance_sheet_by_report_em     资产负债表
  - stock_cash_flow_sheet_by_report_em   现金流量表

输出标准化列名，供 Growth / Quality 因子使用。
支持逐股票抓取 + parquet 缓存。
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .base import BaseFetcher, cache_key, to_datetime_safe

logger = logging.getLogger(__name__)

# ── 东方财富报表原始列名 → 标准英文字段映射 ────────────────────────
# 只映射因子计算所需的核心字段；其余保留原列名
PROFIT_MAP = {
    "SECURITY_CODE":       "ticker",
    "REPORT_DATE":         "report_date",
    "NOTICE_DATE":         "announcement_date",
    "REPORT_TYPE":         "report_type",
    "OPERATE_INCOME":      "total_revenue",          # 营业总收入
    "OPERATE_INCOME_YOY":  "revenue_yoy",            # 营收同比
    "OPERATE_PROFIT":      "operating_profit",        # 营业利润
    "TOTAL_PROFIT":        "total_profit",            # 利润总额
    "NETPROFIT":           "net_profit",              # 净利润
    "NETPROFIT_YOY":       "net_profit_yoy",          # 净利润同比
    "PARENT_NETPROFIT":    "parent_net_profit",        # 归母净利润
    "PARENT_NETPROFIT_YOY":"parent_net_profit_yoy",   # 归母净利润同比
    "BASIC_EPS":           "basic_eps",               # 基本每股收益
    "DILUTED_EPS":        "diluted_eps",             # 稀释每股收益
    "DEDUCT_PARENT_NETPROFIT": "deduct_parent_net_profit",  # 扣非归母净利润
}

BALANCE_MAP = {
    "SECURITY_CODE":       "ticker",
    "REPORT_DATE":         "report_date",
    "NOTICE_DATE":         "announcement_date",
    "REPORT_TYPE":         "report_type",
    "TOTAL_ASSETS":        "total_assets",            # 总资产
    "TOTAL_LIABILITIES":   "total_liabilities",        # 总负债
    "OWNER_EQUITY":        "owner_equity",             # 所有者权益(或归母权益)
    "EQUITY_LESS_MINORITY":"parent_equity",            # 归母权益(若存在)
}

CASHFLOW_MAP = {
    "SECURITY_CODE":               "ticker",
    "REPORT_DATE":                 "report_date",
    "NOTICE_DATE":                 "announcement_date",
    "REPORT_TYPE":                 "report_type",
    "NETCASH_OPERATE":             "operating_cash_flow",   # 经营活动现金流净额
    "NETCASH_INVEST":              "investing_cash_flow",   # 投资活动现金流净额
    "NETCASH_FINANCE":             "financing_cash_flow",   # 筹资活动现金流净额
    "CCE_ADD":                     "net_cash_increase",      # 现金及等价物净增加额
}


class FinancialFetcher(BaseFetcher):
    """财报数据抓取器：三大报表 + 指标衍生。

    用法
    ----
    >>> ff = FinancialFetcher()
    >>> profit_df = ff.get_profit_sheet("000001")   # 利润表
    >>> balance_df = ff.get_balance_sheet("000001") # 资产负债表
    >>> cash_df = ff.get_cashflow_sheet("000001")   # 现金流量表
    >>> indicators = ff.get_indicators("000001")    # 衍生财务指标
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        import akshare as ak
        self._ak = ak

    # ── 内部：统一 ticker 格式 ─────────────────────────────────────
    @staticmethod
    def _to_em_symbol(code: str) -> str:
        """000001 → SZ000001, 600001 → SH600001"""
        code = str(code).strip()
        if code.startswith("6"):
            return f"SH{code}"
        elif code.startswith(("0", "3")):
            return f"SZ{code}"
        elif code.startswith(("4", "8")):
            return f"BJ{code}"
        return code

    # ── 单股票抓取 + 标准化 ────────────────────────────────────────
    def _fin_is_fresh(self, table: str, ticker: str,
                      max_gap_days: int = 120) -> bool:
        """Check if cached financial data covers recent quarters.

        Financial reports are quarterly; 120-day gap means we're within
        one quarter + typical filing delay (30-60 days).
        """
        from fetcher.store.db import query
        r = query(
            f'SELECT MAX(report_date) AS mx FROM "{table}" WHERE ticker=?',
            [ticker], market="ashare",
        )
        if r.empty or r["mx"].iloc[0] is None:
            return False
        try:
            last = pd.to_datetime(str(r["mx"].iloc[0])).date()
        except Exception:
            return False
        return (date.today() - last).days <= max_gap_days

    def get_profit_sheet(self, code: str, use_cache: bool = True) -> pd.DataFrame:
        """获取个股利润表（按报告期），返回标准列名 DataFrame。"""
        TABLE, KEYS = "financial_income", ["ticker", "report_date"]
        if use_cache and self._fin_is_fresh(TABLE, code):
            return self.load_table(TABLE, market="ashare", ticker=code)

        sym = self._to_em_symbol(code)
        logger.info("获取利润表: %s (%s)", code, sym)
        df = self._call_with_retry(self._ak.stock_profit_sheet_by_report_em, symbol=sym)

        if df is None or len(df) == 0:
            return pd.DataFrame()

        # 重命名已知列
        df = df.rename(columns=PROFIT_MAP)
        # 类型转换
        for col in ["report_date", "announcement_date"]:
            if col in df.columns:
                df[col] = to_datetime_safe(df[col])
        # 数值列转 float
        numeric_cols = [c for c in df.columns if c in PROFIT_MAP.values()]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # EM 原始 ticker 为 int（如 1），统一为 6 位字符串以匹配价格表/下游
        if "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)

        if use_cache:
            self.save_table(df, TABLE, KEYS, market="ashare")
        return df

    def get_balance_sheet(self, code: str, use_cache: bool = True) -> pd.DataFrame:
        """获取个股资产负债表。"""
        TABLE, KEYS = "financial_balance", ["ticker", "report_date"]
        if use_cache and self._fin_is_fresh(TABLE, code):
            return self.load_table(TABLE, market="ashare", ticker=code)

        sym = self._to_em_symbol(code)
        logger.info("获取资产负债表: %s (%s)", code, sym)
        df = self._call_with_retry(self._ak.stock_balance_sheet_by_report_em, symbol=sym)

        if df is None or len(df) == 0:
            return pd.DataFrame()

        df = df.rename(columns=BALANCE_MAP)
        for col in ["report_date", "announcement_date"]:
            if col in df.columns:
                df[col] = to_datetime_safe(df[col])
        numeric_cols = [c for c in df.columns if c in BALANCE_MAP.values()]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)

        if use_cache:
            self.save_table(df, TABLE, KEYS, market="ashare")
        return df

    def get_cashflow_sheet(self, code: str, use_cache: bool = True) -> pd.DataFrame:
        """获取个股现金流量表。"""
        TABLE, KEYS = "financial_cashflow", ["ticker", "report_date"]
        if use_cache and self._fin_is_fresh(TABLE, code):
            return self.load_table(TABLE, market="ashare", ticker=code)

        sym = self._to_em_symbol(code)
        logger.info("获取现金流量表: %s (%s)", code, sym)
        df = self._call_with_retry(self._ak.stock_cash_flow_sheet_by_report_em, symbol=sym)

        if df is None or len(df) == 0:
            return pd.DataFrame()

        df = df.rename(columns=CASHFLOW_MAP)
        for col in ["report_date", "announcement_date"]:
            if col in df.columns:
                df[col] = to_datetime_safe(df[col])
        numeric_cols = [c for c in df.columns if c in CASHFLOW_MAP.values()]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)

        if use_cache:
            self.save_table(df, TABLE, KEYS, market="ashare")
        return df

    # ── 衍生指标（从三表合并计算） ─────────────────────────────────
    def get_indicators(self, code: str, use_cache: bool = True) -> pd.DataFrame:
        """合并三表，计算因子所需的财务指标。

        返回 DataFrame，每行一个报告期，包含：
          report_date, announcement_date,
          revenue_yoy, net_profit_yoy, parent_net_profit_yoy,   ← 成长
          roe, roa, gross_margin, debt_ratio,                    ← 质量
          ocf_ratio,                                              ← 现金流质量
          eps                                                    ← 价值辅助
        """
        if use_cache and self._fin_is_fresh("financial_indicator", code):
            return self.load_table("financial_indicator", market="ashare", ticker=code)

        profit = self.get_profit_sheet(code, use_cache=use_cache)
        balance = self.get_balance_sheet(code, use_cache=use_cache)
        cashflow = self.get_cashflow_sheet(code, use_cache=use_cache)

        if profit.empty and balance.empty and cashflow.empty:
            return pd.DataFrame()

        # 以利润表为基准 merge
        base_cols = ["ticker", "report_date", "announcement_date"]
        result = profit[base_cols].copy() if not profit.empty else pd.DataFrame()

        # 先把利润表中因子计算需要的字段都带进来
        profit_cols = ["revenue_yoy", "net_profit_yoy", "parent_net_profit_yoy",
                       "basic_eps", "total_revenue", "parent_net_profit",
                       "net_profit", "operating_profit"]
        for col in profit_cols:
            if col in profit.columns:
                result[col] = pd.to_numeric(profit[col].values, errors="coerce")

        # ── 质量类（需要资产负债表） ──
        if not balance.empty and not result.empty:
            balance_sub = balance[["report_date", "total_assets",
                                   "total_liabilities"]].copy()
            for c in ["total_assets", "total_liabilities"]:
                if c in balance_sub.columns:
                    balance_sub[c] = pd.to_numeric(balance_sub[c], errors="coerce")
            result = result.merge(balance_sub, on="report_date", how="left")

            ta = pd.to_numeric(result.get("total_assets"), errors="coerce")
            tlv = pd.to_numeric(result.get("total_liabilities"), errors="coerce")
            pnp = pd.to_numeric(result.get("parent_net_profit"), errors="coerce")
            np_ = pd.to_numeric(result.get("net_profit"), errors="coerce")

            # ROE = 归母净利润 / 归母权益（近似用 总资产-总负债）
            equity = ta.sub(tlv, fill_value=0)
            result["roe"] = pnp / equity.where(equity > 0, np.nan)

            # ROA = 净利润 / 总资产
            result["roa"] = np_ / ta.where(ta > 0, np.nan)

            # 资产负债率
            result["debt_ratio"] = tlv / ta.where(ta > 0, np.nan)

        # ── 毛利率（从利润表推算） ──
        if "total_revenue" in result.columns and "operating_profit" in result.columns:
            rev = pd.to_numeric(result["total_revenue"], errors="coerce")
            op = pd.to_numeric(result["operating_profit"], errors="coerce")
            result["gross_margin"] = op / rev.where(rev > 0, np.nan)

        # ── 经营现金流比率 ──
        if not cashflow.empty and not result.empty:
            cf_cols = ["report_date", "operating_cash_flow"]
            available = [c for c in cf_cols if c in cashflow.columns]
            if "operating_cash_flow" in cashflow.columns:
                cf_sub = cashflow[available].copy()
                cf_sub["operating_cash_flow"] = pd.to_numeric(
                    cf_sub["operating_cash_flow"], errors="coerce"
                )
                result = result.merge(cf_sub, on="report_date", how="left")
                rev = pd.to_numeric(result.get("total_revenue"), errors="coerce")
                ocf = pd.to_numeric(result.get("operating_cash_flow"), errors="coerce")
                result["ocf_ratio"] = ocf / rev.where(abs(rev) > 1e6, np.nan)

        # ── 上一报告期利润（供成长因子亏转盈/小分母中性化）──
        # 按报告期排序后 shift(1)，得到上一期的归母/净利润
        if "report_date" in result.columns:
            result = result.sort_values("report_date").reset_index(drop=True)
            if "parent_net_profit" in result.columns:
                result["prev_parent_net_profit"] = pd.to_numeric(
                    result["parent_net_profit"], errors="coerce"
                ).shift(1)
            if "net_profit" in result.columns:
                result["prev_net_profit"] = pd.to_numeric(
                    result["net_profit"], errors="coerce"
                ).shift(1)

        # 清理
        for c in ["ticker_x", "ticker_y"]:
            if c in result.columns:
                result = result.drop(columns=[c])

        # 公告日兜底：东财对未知公告日返回 int64 哨兵(-2^63)，
        # to_datetime_safe 会将其转为 NaT。若留 null，下游 pit_merge 的
        # merge_asof 会因 right key 含 null 直接崩溃。此处用"报告期 + 法定
        # 披露窗口"估算补齐（project 已有 estimate_announcement_date）。
        if "announcement_date" in result.columns and "report_date" in result.columns:
            from processor.pit_align import estimate_announcement_date
            ann = to_datetime_safe(result["announcement_date"])
            rep_period = to_datetime_safe(result["report_date"])
            null_mask = ann.isna()
            if null_mask.any():
                est = rep_period.apply(
                    lambda p: estimate_announcement_date(p) if pd.notna(p) else pd.NaT
                )
                ann = ann.mask(null_mask, est)
                result["announcement_date"] = ann

        if use_cache and not result.empty:
            if "ticker" in result.columns:
                result["ticker"] = result["ticker"].astype(str).str.zfill(6)
            self.save_table(result, "financial_indicator",
                            ["ticker", "report_date"], market="ashare")
        return result

    # ── 批量抓取（多股票循环） ─────────────────────────────────────
    def batch_indicators(
        self,
        codes: List[str],
        use_cache: bool = True,
        progress_every: int = 10,
    ) -> Dict[str, pd.DataFrame]:
        """批量获取多只股票的财务指标。

        Parameters
        ----------
        codes : list[str]
            股票代码列表
        use_cache : bool
            是否使用缓存
        progress_every : int
            每 N 只打印一次进度

        Returns
        -------
        dict[str, DataFrame]
            {code: indicators_df}
        """
        results: Dict[str, pd.DataFrame] = {}
        total = len(codes)
        for i, code in enumerate(codes):
            try:
                ind = self.get_indicators(code, use_cache=use_cache)
                results[code] = ind
            except Exception as e:
                logger.warning("获取 %s 财报失败: %s", code, e)
                results[code] = pd.DataFrame()

            if (i + 1) % progress_every == 0 or i == total - 1:
                logger.info("财报进度: %d/%d (%.0f%%)",
                            i + 1, total, (i + 1) / total * 100)
            time.sleep(0.3)  # 避免限流

        return results
