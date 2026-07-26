"""修复 parquet 缓存中 report_date/announcement_date 的 dtype。

问题：AKShare EM 接口返回的 REPORT_DATE/NOTICE_DATE 是 epoch 微秒 (int64)，
      pd.to_datetime() 不带 unit 参数默认按纳秒解析，导致日期被误译为 1970 年。
      旧缓存直接保存了原始 int64 值。

修复：读取每个缓存文件，将 int64 微秒正确转为 datetime64[ns] 后回写。
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\chunh\ZCodeProject\stock_factor_project")

import pandas as pd
import numpy as np

CACHE_DIR = Path(r"C:\Users\chunh\ZCodeProject\stock_factor_project\data\cache")

DATE_COLS = ["report_date", "announcement_date", "report_period"]


def fix_one(p: Path) -> bool:
    """修复单个 parquet 文件。返回是否做了修改。"""
    try:
        df = pd.read_parquet(p)
    except Exception as e:
        print(f"  跳过 {p.name}: 读取失败 {e}")
        return False

    changed = False
    for col in DATE_COLS:
        if col not in df.columns:
            continue
        dt = str(df[col].dtype)
        if "datetime" in dt:
            continue  # 已经是 datetime，无需修复

        # int64/float64 → 判断是否 epoch 微秒
        non_null = df[col].dropna()
        if len(non_null) == 0:
            continue

        sample_val = non_null.iloc[0]
        if not isinstance(sample_val, (int, float, np.integer, np.floating)):
            # 可能是字符串日期，直接 to_datetime
            df[col] = pd.to_datetime(df[col], errors="coerce")
            changed = True
            continue

        # 数值型：判断单位
        # 微秒范围: ~1.7e15 (2020年代), 毫秒: ~1.7e12, 纳秒: ~1.7e18
        abs_val = abs(sample_val)
        if abs_val > 1e17:
            unit = "ns"
        elif abs_val > 1e14:
            unit = "us"   # 微秒
        elif abs_val > 1e11:
            unit = "ms"   # 毫秒
        else:
            unit = "s"

        df[col] = pd.to_datetime(df[col], errors="coerce", unit=unit)
        changed = True
        print(f"  {p.name}: {col} int64->datetime64 (unit={unit}), sample: {df[col].dropna().head(2).tolist()}")

    if changed:
        df.to_parquet(p)
        print(f"  [OK] 已回写: {p.name}")
    return changed


def main():
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"扫描 {len(files)} 个 parquet 文件...")

    fixed_count = 0
    for p in files:
        try:
            # 先检查是否含日期列
            df = pd.read_parquet(p, columns=None)
        except Exception:
            continue
        cols = set(df.columns)
        has_date = any(c in cols for c in DATE_COLS)
        if not has_date:
            continue
        if fix_one(p):
            fixed_count += 1

    print(f"\n完成: 修复了 {fixed_count} 个文件")

    # 验证
    print("\n--- 验证 ---")
    bad = 0
    for p in files:
        try:
            df = pd.read_parquet(p, columns=None)
        except:
            continue
        for col in DATE_COLS:
            if col in df.columns and "datetime" not in str(df[col].dtype):
                print(f"  仍为坏 dtype: {p.name}: {col} = {df[col].dtype}")
                bad += 1
    if bad == 0:
        print("  所有日期列均为 datetime 类型 [OK]")
    else:
        print(f"  仍有 {bad} 个坏列")


if __name__ == "__main__":
    main()
