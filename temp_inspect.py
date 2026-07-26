"""Inspect cache file structure for user explanation."""
import pandas as pd
import hashlib
import os

# Price cache file
f1 = 'data/cache/0071ea6de0ab.parquet'
df1 = pd.read_parquet(f1)
print("=== 行情缓存文件示例 (一只股票的多年日线) ===")
print(f"文件名: {os.path.basename(f1)}")
print(f"格式: Parquet (Apache列式存储，压缩率高，读取快)")
print(f"行数: {len(df1)}  (交易日数)")
print(f"列名: {list(df1.columns)}")
print(f"时间范围: {df1['date'].min()} ~ {df1['date'].max()}")
print(f"股票: {df1['ticker'].unique()}")
print()
print(df1.head(5).to_string(index=False))
print()

# Find a financial cache file
for f in os.listdir('data/cache'):
    df = pd.read_parquet(f'data/cache/{f}')
    if 'report_date' in df.columns and 'ticker' in df.columns:
        print("=== 财务缓存文件示例 ===")
        print(f"文件名: {f}")
        print(f"格式: Parquet")
        print(f"行数: {len(df)}  (报告期数)")
        print(f"列名: {list(df.columns)}")
        print(f"股票: {df['ticker'].unique()}")
        print()
        print(df.head(5).to_string(index=False))
        break

print()
print("=== cache_key 生成规则 (决定文件名) ===")

def cache_key(*parts):
    raw = '_'.join(str(p) for p in parts)
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]

examples = [
    ("ashare", "600519", "20210101", "20260709", "hfq"),
    ("balance", "600519"),
    ("profit", "000001"),
    ("cashflow", "000001"),
    ("indicator", "600519"),
]
for e in examples:
    ck = cache_key(*e)
    print(f"  cache_key{e}")
    print(f"       -> {ck}.parquet")
    print()
