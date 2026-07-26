"""财报 PIT (Point-in-Time) 对齐 —— 防未来函数的核心。

财报数据有披露滞后：
    一季报：4 月 30 日前披露
    半年报：8 月 31 日前披露
    三季报：10 月 31 日前披露
    年  报：4 月 30 日前披露

为避免回测时"偷看"未来才公布的财报，必须用 announcement_date（公告日）
而非 report_period（报告期）做对齐：对每个交易日 t，只能使用
announcement_date <= t 的最新一期财报。

实现：pd.merge_asof 按 (ticker 分组) announcement_date 取 as-of 最新。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from fetcher.base import to_datetime_safe


def pit_merge(
    panel: pd.DataFrame,
    report_df: pd.DataFrame,
    value_cols: list[str],
    date_col: str = "date",
    ticker_col: str = "ticker",
    ann_col: str = "announcement_date",
    report_period_col: str = "report_period",
) -> pd.DataFrame:
    """把财报字段按 PIT 合并到日频 panel 上。

    Parameters
    ----------
    panel : 日频 panel，含 date / ticker。
    report_df : 财报，含 ticker / announcement_date / report_period / value_cols。
                若无 announcement_date 列，退化为按 report_period + 固定滞后估算
                （由 report_lag_map 提供，仅作兜底）。
    value_cols : 要合并的财报字段。

    Returns
    -------
    panel 追加 value_cols 列后的 DataFrame（不改变行数与顺序）。
    """
    need = {ticker_col, ann_col}
    if not need.issubset(report_df.columns):
        raise KeyError(
            f"report_df 缺少列: {need - set(report_df.columns)}；"
            "PIT 对齐需要 announcement_date。"
        )

    # 预处理 panel
    df = panel.copy()
    df[date_col] = to_datetime_safe(df[date_col]).dt.tz_localize(None).dt.normalize()
    df[date_col] = df[date_col].astype("datetime64[ns]")

    # 预处理 report_df：按 ticker 排序、去重（同公告日取最新报告期）
    rep = report_df[[ticker_col, ann_col, report_period_col] + value_cols].copy()
    rep[ann_col] = to_datetime_safe(rep[ann_col]).dt.tz_localize(None).dt.normalize()
    rep[ann_col] = rep[ann_col].astype("datetime64[ns]")
    rep = rep.sort_values([ticker_col, ann_col, report_period_col])
    rep = rep.drop_duplicates(subset=[ticker_col, ann_col], keep="last")
    # 剔除公告日为 null 的行：无法做 PIT 对齐，且 merge_asof 不允许
    # right key 含 null（会抛 "Merge keys contain null values"）。这些财报
    # 不参与对齐，对应股票该期财务退化为 NaN，不影响整体流程。
    if rep[ann_col].isna().any():
        rep = rep.dropna(subset=[ann_col])

    out_parts = []
    for tk, g_panel in df.groupby(ticker_col, sort=False):
        g_rep = rep[rep[ticker_col] == tk]
        if g_rep.empty:
            for c in value_cols:
                g_panel[c] = np.nan
            out_parts.append(g_panel)
            continue
        # merge_asof 要求两侧按 key 排序
        g_panel_sorted = g_panel.sort_values(date_col)
        merged = pd.merge_asof(
            g_panel_sorted,
            g_rep,
            left_on=date_col,
            right_on=ann_col,
            direction="backward",
            suffixes=("", "_rep"),
        )
        # merge_asof 会带入 ann_col，删除避免污染
        drop_extra = [c for c in (ann_col, report_period_col) if c in merged.columns]
        # 保留 report_period 便于回看，但重命名
        if report_period_col in drop_extra:
            merged = merged.rename(columns={report_period_col: "pit_report_period"})
            drop_extra.remove(report_period_col)
        if drop_extra:
            merged = merged.drop(columns=drop_extra)
        out_parts.append(merged)

    result = pd.concat(out_parts, ignore_index=False)
    # 恢复原顺序
    result = result.loc[df.index] if df.index.equals(result.index) else result
    return result.reset_index(drop=True)


def estimate_announcement_date(
    report_period: pd.Period | str,
    lag_days_map: dict | None = None,
) -> pd.Timestamp:
    """无公告日时，按报告期估算法定披露截止日（兜底，不推荐用于精确回测）。

    Parameters
    ----------
    lag_days_map : {1: 120, 2: 90, 3: 30, 4: 120}
        各季度的法定披露窗口（天数近似）。
    """
    if lag_days_map is None:
        lag_days_map = {1: 120, 2: 90, 3: 30, 4: 120}
    p = pd.Period(report_period, freq="Q") if not isinstance(report_period, pd.Period) else report_period
    quarter = p.quarter
    lag = lag_days_map.get(quarter, 120)
    return (p.end_time + pd.Timedelta(days=lag)).normalize()
