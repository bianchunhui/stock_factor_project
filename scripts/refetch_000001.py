"""Re-download 000001 price data, force overwrite bad cache."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.price import PriceFetcher

pf = PriceFetcher()
# use_cache=False -> force re-download and overwrite bad cache file
df = pf.get_a_share_daily("000001", start_date="20210101", use_cache=False)
print(f"Result: {len(df)} rows")
print(f"Date range: {df['date'].min()} ~ {df['date'].max()}")
print(f"Columns: {list(df.columns)}")
print(f"Sample:")
print(df.tail(3).to_string(index=False))
