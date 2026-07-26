import pandas as pd

# Price
p = pd.read_parquet("data/hk_panel_price.parquet")
print("=== PRICE ===")
print(f"  shape: {p.shape}, tickers: {p.ticker.nunique()}")
print(f"  date range: {p.date.min()} ~ {p.date.max()}")
sizes = p.groupby("ticker").size()
print(f"  rows per ticker: min={sizes.min()}, max={sizes.max()}, median={sizes.median():.0f}")
print(f"  NaN: close={p.close.isna().sum()}, volume={p.volume.isna().sum()}")
print(f"  cols: {list(p.columns)}")

# Financial
f = pd.read_parquet("data/hk_panel_financial.parquet")
print("\n=== FINANCIAL ===")
print(f"  shape: {f.shape}, tickers: {f.ticker.nunique()}")
print(f"  report_date range: {f.report_date.min()} ~ {f.report_date.max()}")
fsizes = f.groupby("ticker").size()
print(f"  rows per ticker: min={fsizes.min()}, max={fsizes.max()}")
avail = [c for c in ["basic_eps","bps","revenue_yoy","gross_margin","holder_profit","eps_ttm"] if c in f.columns]
print(f"  key cols: {avail}")

# HSGT
h = pd.read_parquet("data/hk_panel_hsgt.parquet")
print("\n=== SOUTHBOUND HOLDING ===")
print(f"  shape: {h.shape}, tickers: {h.ticker.nunique()}")
print(f"  date range: {h.date.min()} ~ {h.date.max()}")
hsizes = h.groupby("ticker").size()
print(f"  rows per ticker: min={hsizes.min()}, max={hsizes.max()}, median={hsizes.median():.0f}")
print(f"  holding_pct: mean={h.holding_pct.mean():.2f}%, max={h.holding_pct.max():.2f}%")
print(f"  cols: {list(h.columns)}")

# Cache size
import os
cache_dir = "data/cache"
files = os.listdir(cache_dir)
total_size = sum(os.path.getsize(os.path.join(cache_dir, f)) for f in files)
print(f"\n=== CACHE ===")
print(f"  files: {len(files)}, total: {total_size/1024/1024:.1f} MB")
hk_files = [f for f in files if f.startswith("hkprice") or f.startswith("hkfin") or f.startswith("hkgthold") or f.startswith("hkindex")]
print(f"  HK cache files: {len(hk_files)}")
