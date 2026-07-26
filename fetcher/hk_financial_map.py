"""港股财务字段映射（统一管理，消除分散硬编码）。

背景
----
港股财务来自 akshare ``stock_financial_hk_analysis_indicator_em``，其列名与
A 股 ``stock_profit_sheet_by_report_em`` 不同：

  - 港股: HOLDER_PROFIT / HOLDER_PROFIT_YOY / ROE_AVG / ROA / ...
  - A股:  PARENT_NETPROFIT / PARENT_NETPROFIT_YOY / ROE / ...

历史问题
--------
- ``download_hk_data.py`` 把 EM 原始列转成可读中间名（holder_profit 等），
  部分列（ROE_AVG/ROA/DEBT_ASSET_RATIO/OCF_SALES）未改名直接进 parquet。
- ``run_hk_factor_calc.py`` 再把"parquet 中实际出现的列名"映射到 A 股因子
  模块统一字段名（parent_net_profit 等），原先写死在脚本里。

本模块
------
集中维护"parquet 实际列名 → A 股因子字段名"的映射，供
``run_hk_factor_calc.py`` 引用。新增字段只改这里一处，避免静默 NaN。
"""
from __future__ import annotations

# parquet(hk_panel_financial.parquet) 实际列名 → A 股因子模块统一字段名
# key 必须与 download_hk_data.py 产出/保留的列名一致
HK_FINANCIAL_MAP = {
    # 归母净利润及同比（download 已改名 holder_profit*）
    "HOLDER_PROFIT":      "parent_net_profit",
    "HOLDER_PROFIT_YOY":  "parent_net_profit_yoy",
    # 营收及同比（download 已改名）
    "OPERATE_INCOME":     "total_revenue",
    "OPERATE_INCOME_YOY": "revenue_yoy",
    # 每股指标
    "BASIC_EPS":          "basic_eps",
    "DILUTED_EPS":        "diluted_eps",
    "EPS_TTM":            "eps_ttm",
    "BPS":                "bps",
    # 质量指标（download 未改名，保留 EM 原始列名）
    "ROE_AVG":            "roe",
    "ROA":                "roa",
    "DEBT_ASSET_RATIO":   "debt_ratio",
    "OCF_SALES":          "ocf_ratio",
    # 毛利率（download 已改名）
    "GROSS_PROFIT_RATIO": "gross_margin",
}

# 注意：download_hk_data.py 的 col_map 把部分列改成了可读名（holder_profit/
# revenue_yoy/gross_margin/eps_ttm/bps/basic_eps/total_revenue），这些可读名
# 与本表 value 同名，属于 no-op；ROE_AVG/ROA/DEBT_ASSET_RATIO/OCF_SALES 在
# download 中未改名，故此处仍用 EM 原始列名作为 key。
# 下方提供"可读名优先"的兼容映射，确保两种 parquet 命名都能命中。


def resolve_hk_financial_map(columns) -> dict:
    """根据 panel 实际存在的列，返回生效的映射子集。

    同时兼容 download 改名后的可读名与未改名的 EM 原始列名。
    """
    colset = set(columns)
    resolved = {}
    # 先按 EM 原始列名命中
    for k, v in HK_FINANCIAL_MAP.items():
        if k in colset:
            resolved[k] = v
    # 再按 download 产出的可读名命中（holder_profit 等）
    readable_aliases = {
        "holder_profit":      "parent_net_profit",
        "holder_profit_yoy":  "parent_net_profit_yoy",
        "total_revenue":      "total_revenue",
        "revenue_yoy":        "revenue_yoy",
        "gross_margin":       "gross_margin",
        "eps_ttm":            "eps_ttm",
        "bps":                "bps",
        "basic_eps":          "basic_eps",
        "diluted_eps":        "diluted_eps",
        "ocf_per_share":      "ocf_per_share",
    }
    for k, v in readable_aliases.items():
        if k in colset and v not in resolved.values():
            resolved[k] = v
    return resolved
