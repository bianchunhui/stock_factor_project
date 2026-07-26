"""Check 000001 price data completeness."""
import pandas as pd
from pathlib import Path

cache_dir = Path('data/cache')
total_rows = 0
files_found = []

for f in sorted(cache_dir.glob('*.parquet')):
    try:
        df = pd.read_parquet(f)
        if 'ticker' in df.columns and 'date' in df.columns:
            tickers = df['ticker'].astype(str).str.zfill(6).unique()
            if '000001' in tickers:
                files_found.append(f.name)
                total_rows += len(df)
                dmin = df['date'].min()
                dmax = df['date'].max()
                cols = [c for c in df.columns if c != 'ticker']
                print(f"  {f.name}: {len(df)} rows, {len(cols)} cols, {dmin} ~ {dmax}")
                print(f"            columns: {cols}")
    except Exception as e:
        pass

print(f"\nFiles found: {len(files_found)}")
print(f"Total rows: {total_rows}")

if not files_found:
    print("\n*** NO DATA FOUND for 000001! ***")
else:
    print(f"\n=== Expected: ~1330 trading days (2021-01 ~ 2026-07) ===")
    print(f"=== Actual:   {total_rows} rows ===")
