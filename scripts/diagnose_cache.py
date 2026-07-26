"""诊断 parquet 缓存中财务数据的 dtype 问题。

检查 profit/balance/cashflow/indicators 缓存文件里
report_date 和 announcement_date 列的实际 dtype 和样本值。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fetcher.base import cache_key, BaseFetcher

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def inspect_parquet(code: str, label: str):
    """检查某个 cache_key 对应的 parquet 文件。"""
    ck = cache_key(label, code)
    p = CACHE_DIR / f"{ck}.parquet"
    if not p.exists():
        print(f"  [{label}] {code}: 缓存文件不存在 ({ck}.parquet)")
        return
    df = pd.read_parquet(p)
    print(f"\n  [{label}] {code} ({ck}.parquet)")
    print(f"    shape: {df.shape}")
    print(f"    columns: {list(df.columns[:15])}")

    for col in ["report_date", "announcement_date", "report_period"]:
        if col in df.columns:
            dtype = df[col].dtype
            sample = df[col].dropna().head(3).tolist()
            print(f"    {col}: dtype={dtype}, sample={sample}")
            # 如果是 int64，尝试判断是否是 epoch 微秒
            if "int" in str(dtype):
                val = df[col].dropna().iloc[0] if df[col].notna().any() else None
                if val is not None:
                    # 尝试不同单位
                    for unit, name in [("ns", "nanoseconds"), ("us", "microseconds"),
                                       ("ms", "milliseconds"), ("s", "seconds")]:
                        try:
                            ts = pd.to_datetime(val, unit=unit)
                            print(f"      → 如果是 {name}: {ts}")
                        except Exception:
                            pass
        # else:
        #     print(f"    {col}: NOT IN COLUMNS")


def main():
    # 检查几只常见股票的缓存
    test_codes = ["000001", "600036", "000858"]
    for code in test_codes:
        print(f"\n{'='*60}")
        print(f"股票: {code}")
        print(f"{'='*60}")
        for label in ["profit", "balance", "cashflow", "indicators"]:
            inspect_parquet(code, label)

    # 额外检查：用 pit_merge 的角度看数据
    print(f"\n{'='*60}")
    print("模拟 pit_merge 视角：取 000001 的 indicators 缓存")
    print(f"{'='*60}")
    ck = cache_key("indicators", "000001")
    p = CACHE_DIR / f"{ck}.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        print(f"  shape: {df.shape}")
        print(f"  columns: {list(df.columns)}")
        for col in ["report_date", "announcement_date"]:
            if col in df.columns:
                print(f"\n  {col} dtype: {df[col].dtype}")
                if "int" in str(df[col].dtype) or "float" in str(df[col].dtype):
                    print(f"    raw values: {df[col].dropna().head(5).tolist()}")
                    # 模拟 pit_merge 的转换
                    converted = pd.to_datetime(df[col], errors="coerce")
                    print(f"    pd.to_datetime (default ns): {converted.dropna().head(3).tolist()}")
                    # 尝试微秒
                    converted_us = pd.to_datetime(df[col], errors="coerce", unit="us")
                    print(f"    pd.to_datetime (us): {converted_us.dropna().head(3).tolist()}")
                    # 尝试毫秒
                    converted_ms = pd.to_datetime(df[col], errors="coerce", unit="ms")
                    print(f"    pd.to_datetime (ms): {converted_ms.dropna().head(3).tolist()}")
                elif "datetime" in str(df[col].dtype):
                    print(f"    values: {df[col].dropna().head(5).tolist()}")
                    print("    ✓ 已经是 datetime 类型")
                else:
                    print(f"    values: {df[col].dropna().head(5).tolist()}")


if __name__ == "__main__":
    main()
