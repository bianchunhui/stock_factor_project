"""扫描所有 parquet 缓存，检查 report_date/announcement_date 的 dtype。"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\chunh\ZCodeProject\stock_factor_project")

import pandas as pd

CACHE_DIR = Path(r"C:\Users\chunh\ZCodeProject\stock_factor_project\data\cache")
print(f"Cache dir: {CACHE_DIR}")
files = sorted(CACHE_DIR.glob("*.parquet"))
print(f"Total parquet files: {len(files)}")

found_financial = []
found_bad = []

for p in files:
    try:
        # 只读前几行来检查 columns
        df = pd.read_parquet(p)
    except Exception as e:
        continue
    
    cols = set(df.columns)
    has_report = "report_date" in cols or "report_period" in cols
    has_ann = "announcement_date" in cols
    
    if has_report or has_ann:
        found_financial.append(p.name)
        # 检查每列的 dtype
        for col in ["report_date", "announcement_date", "report_period"]:
            if col in df.columns:
                dt = str(df[col].dtype)
                sample = df[col].dropna().head(2).tolist()
                status = "OK" if "datetime" in dt else "BAD(int/float)"
                print(f"  {p.name}: {col} dtype={dt} {status} sample={sample}")
                if "datetime" not in dt:
                    found_bad.append((p.name, col, dt, sample))

print(f"\n--- Summary ---")
print(f"Financial cache files: {len(found_financial)}")
print(f"Bad dtype files: {len(found_bad)}")

if found_bad:
    print("\nBad files detail:")
    for fname, col, dt, sample in found_bad[:10]:
        print(f"  {fname}: {col} = {dt}, sample = {sample}")
        # 尝试判断 epoch 单位
        val = sample[0] if sample else None
        if val is not None and isinstance(val, (int, float)):
            for unit, label in [("ns", "ns"), ("us", "us"), ("ms", "ms")]:
                try:
                    ts = pd.to_datetime(val, unit=unit)
                    print(f"    as {label}: {ts}")
                except:
                    pass
