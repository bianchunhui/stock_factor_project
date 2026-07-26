"""Try to get HSI constituents from multiple real-time sources.

Strategy: Use Python requests to find working APIs.
"""
import requests
import json
import re

# 1. Try hsi.com.hk public API endpoints
print("=" * 60)
print("1. HSI.com.hk public endpoints")
print("=" * 60)
endpoints = [
    "https://www.hsi.com.hk/data/chi/index/constituents/HSI.js",
    "https://www.hsi.com.hk/static/data/index/HSI.json",
    "https://www.hsi.com.hk/chi/indexes/all-indexes/hsi",
]
for url in endpoints:
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        print(f"  {url}: status={resp.status_code}, len={len(resp.text)}")
        if resp.status_code == 200:
            text = resp.text[:500]
            print(f"    {text[:300]}")
            # Try to extract stock codes
            codes = re.findall(r'"code":\s*"(\d{5})"', resp.text)
            if codes:
                print(f"    Found {len(codes)} codes: {codes[:10]}...")
    except Exception as e:
        print(f"  {url}: {e}")

# 2. Try Sina finance HSI constituents API
print()
print("=" * 60)
print("2. Sina finance - HSI constituents")
print("=" * 60)
try:
    # Sina's component API
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        "page": "1",
        "num": "100",
        "sort": "symbol",
        "asc": "1",
        "node": "hsi",  # might work
        "symbol": "",
        "_s_r_a": "init",
    }
    resp = requests.get(url, params=params, timeout=10, 
                       headers={"User-Agent": "Mozilla/5.0"})
    print(f"  Status: {resp.status_code}, len={len(resp.text)}")
    print(f"  Content[:300]: {resp.text[:300]}")
except Exception as e:
    print(f"  FAILED: {e}")

# 3. Try using the stock_hk_spot (already works) + market cap filter
# All HSI stocks are large-cap, filter by top 100 HK stocks by market cap
print()
print("=" * 60)
print("3. Smart approach: use akshare stock_hk_spot + filter")
print("=" * 60)
import akshare as ak
import pandas as pd

try:
    df = ak.stock_hk_spot()
    print(f"  Total HK stocks: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    
    # Filter: HSI stocks are typically:
    # 1. Main board (codes 00001-09999, not 08xxx)
    # 2. Not derivative/structured products (no letters in code)
    # 3. Top by market cap + liquidity
    
    # Clean: keep only stocks with numeric codes
    df['code_numeric'] = df['代码'].astype(str).str.zfill(5)
    numeric_mask = df['code_numeric'].str.match(r'^\d{5}$')
    numeric_stocks = df[numeric_mask].copy()
    print(f"  Numeric-coded stocks: {len(numeric_stocks)}")
    
    # Calculate estimated market cap from price and volume
    # stock_hk_spot doesn't have outstanding shares, so use成交额/turnover as liquidity proxy
    numeric_stocks['成交额'] = pd.to_numeric(numeric_stocks['成交额'], errors='coerce')
    numeric_stocks['最新价'] = pd.to_numeric(numeric_stocks['最新价'], errors='coerce')
    numeric_stocks['成交量'] = pd.to_numeric(numeric_stocks['成交量'], errors='coerce')
    
    # Sort by成交额 (liquidity proxy) descending, take top 100
    top_by_amount = numeric_stocks.nlargest(100, '成交额')
    print(f"  Top 100 by turnover: sample codes = {top_by_amount['code_numeric'].head(20).tolist()}")
    
    # Cross-reference with known HSI codes
    known_hsi = {
        "00001", "00002", "00003", "00005", "00006", "00011", "00012", "00016",
        "00019", "00027", "00066", "00083", "00101", "00175", "00241", "00267",
        "00268", "00270", "00285", "00288", "00291", "00293", "00388", "00688",
        "00700", "00762", "00763", "00823", "00868", "00883", "00939", "00941",
        "00992", "01038", "01044", "01088", "01099", "01109", "01113", "01177",
        "01211", "01288", "01398", "01658", "01766", "01810", "01876", "01928",
        "01997", "02007", "02013", "02018", "02313", "02318", "02328", "02331",
        "02382", "02388", "02628", "02688", "02888", "03328", "03690",
        "03888", "03968", "06098", "06185", "06862", "06888", "09618", "09633",
        "09668", "09888", "09988", "09999", "01024", "02020", "02359", "06618",
        "01896", "02196", "02269", "03833",
        # 2025+ additions
        "09901", "02015",
    }
    
    hsi_found = top_by_amount[top_by_amount['code_numeric'].isin(known_hsi)]
    print(f"\n  Known HSI in top 100: {len(hsi_found)}/{len(known_hsi)}")
    
    # Show top 90 by turnover - these should approximate HSI
    top90 = top_by_amount.head(90)
    top90_codes = set(top90['code_numeric'].tolist())
    
    known_set = known_hsi
    intersection = top90_codes & known_set
    missing_known = known_set - top90_codes
    extra_new = top90_codes - known_set
    
    print(f"  Intersection: {len(intersection)}")
    if missing_known:
        print(f"  Known HSI not in top 90 (missing): {sorted(missing_known)[:20]}")
    if extra_new:
        print(f"  Extra in top 90 not in known list: {sorted(extra_new)[:20]}")
    
    # Save for inspection
    top90[['code_numeric', '中文名称', '最新价', '成交额']].to_csv(
        "data/top90_hk_by_turnover.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\n  Saved top 90 to data/top90_hk_by_turnover.csv")
    
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback
    traceback.print_exc()

print("\nDONE")
