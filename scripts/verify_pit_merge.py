"""验证 PIT merge 修复后财务因子不再全 panel 常数填充。

用缓存的 indicators 数据 + 构造的小型日频 panel 做 pit_merge，
检查同一股票在不同日期是否拿到不同的财报值。
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\chunh\ZCodeProject\stock_factor_project")

import pandas as pd
import numpy as np
from fetcher.base import cache_key, to_datetime_safe
from processor.pit_align import pit_merge

CACHE_DIR = Path(r"C:\Users\chunh\ZCodeProject\stock_factor_project\data\cache")


def main():
    # 找一个有 indicators 缓存的股票
    # 扫描所有缓存文件找含 roe 列的
    test_file = None
    test_code = None
    for p in sorted(CACHE_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(p, columns=None)
        except:
            continue
        if "roe" in df.columns and "announcement_date" in df.columns:
            test_file = p
            test_df = df
            break

    if test_file is None:
        print("找不到 indicators 缓存文件")
        return

    print(f"使用缓存文件: {test_file.name}")
    print(f"  shape: {test_df.shape}")
    print(f"  columns: {list(test_df.columns)}")
    print(f"  report_date dtype: {test_df.get('report_date', pd.Series()).dtype}")
    print(f"  announcement_date dtype: {test_df.get('announcement_date', pd.Series()).dtype}")

    # 确保有 ticker 列
    if "ticker" not in test_df.columns:
        print("  缺 ticker 列，跳过")
        return

    code = test_df["ticker"].iloc[0]
    print(f"  ticker: {code}")

    # 构造一个小型日频 panel（2023-01-01 到 2026-07-01，每月第一天）
    dates = pd.date_range("2023-01-01", "2026-07-01", freq="MS")
    panel = pd.DataFrame({
        "date": np.tile(dates, 1),
        "ticker": code,
        "close": 100.0,
    })
    print(f"\n构造 panel: {len(panel)} 行, 日期范围 {dates[0].date()} ~ {dates[-1].date()}")

    # 准备 report_df
    rep = test_df.copy()
    rep = rep.rename(columns={"report_date": "report_period"})
    print(f"\nReport DF:")
    print(f"  report_period dtype: {rep['report_period'].dtype}")
    print(f"  announcement_date dtype: {rep['announcement_date'].dtype}")
    print(f"  report_period 样本: {rep['report_period'].dropna().head(3).tolist()}")
    print(f"  announcement_date 样本: {rep['announcement_date'].dropna().head(3).tolist()}")

    # 选择要合并的列
    value_cols = [c for c in ["revenue_yoy", "net_profit_yoy", "roe", "roa",
                               "gross_margin", "debt_ratio"]
                  if c in rep.columns]
    print(f"  value_cols: {value_cols}")

    # 执行 pit_merge
    merged = pit_merge(panel, rep, value_cols)

    print(f"\n--- PIT Merge 结果 ---")
    print(f"  shape: {merged.shape}")
    print(f"\n  各日期对应的财报值:")
    for _, row in merged.iterrows():
        date_str = str(row["date"].date())
        values = {c: row.get(c, np.nan) for c in value_cols}
        pit_rp = row.get("pit_report_period", None)
        pit_rp_str = str(pit_rp.date()) if pd.notna(pit_rp) else "N/A"
        print(f"  {date_str} | pit_report_period={pit_rp_str} | " +
              " | ".join(f"{c}={v:.4f}" if pd.notna(v) else f"{c}=NaN" for c, v in values.items()))

    # 检查是否常数填充
    print(f"\n--- 常数填充检查 ---")
    for c in value_cols:
        unique_vals = merged[c].dropna().nunique()
        total_vals = merged[c].notna().sum()
        if unique_vals <= 1 and total_vals > 1:
            print(f"  [BAD] {c}: 只有 {unique_vals} 个唯一值 ({total_vals} 个非空) -> 常数填充!")
        elif unique_vals > 1:
            print(f"  [OK]  {c}: {unique_vals} 个唯一值 ({total_vals} 个非空) -> 正常变化")
        else:
            print(f"  [?]   {c}: {total_vals} 个非空值")


if __name__ == "__main__":
    main()
