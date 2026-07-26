"""Try more sources for GGT constituents and HSI constituents."""
import requests
import pandas as pd
import time

# Approach G: Eastmoney - 港股通成分股 (correct board codes)
print("=" * 60)
print("G. Eastmoney - 港股通成分股 (push2 API)")
print("=" * 60)
# 港股通板块: b_hkconnect
for fs_code in ["b_hkconnect", "b:HKCONNECT", "m:128,t:23"]:
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "1000", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": fs_code,
            "fields": "f12,f14",
        }
        resp = requests.get(url, params=params, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
        if data.get("data") and data["data"].get("diff"):
            items = data["data"]["diff"]
            print(f"  fs={fs_code}: Got {len(items)} items")
            if items:
                print(f"    Sample: {items[:3]}")
        else:
            print(f"  fs={fs_code}: empty or failed")
    except Exception as e:
        print(f"  fs={fs_code}: {e}")
    time.sleep(0.5)

# Approach H: Try direct eastmoney datacenter for 港股通
print()
print("=" * 60)
print("H. Eastmoney datacenter - 港股通标的")
print("=" * 60)
try:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "sortColumns": "SECURITY_CODE",
        "sortTypes": "1",
        "pageSize": "500",
        "pageNumber": "1",
        "reportName": "RPT_MUTUAL_DEALINGDETAILS",
        "columns": "ALL",
        "source": "WEB",
        "client": "WEB",
        "filter": '(MARKET_TYPE="港股通")',
    }
    resp = requests.get(url, params=params, timeout=10, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.eastmoney.com/",
    })
    data = resp.json()
    print(f"  Success: {data.get('success')}")
    if data.get("result") and data["result"].get("data"):
        rows = data["result"]["data"]
        print(f"  Got {len(rows)} rows")
        print(f"  Sample: {rows[:2]}")
    else:
        print(f"  Message: {data.get('message')}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach I: Wikipedia HSI constituents
print()
print("=" * 60)
print("I. Wikipedia - HSI constituents")
print("=" * 60)
try:
    url = "https://en.wikipedia.org/wiki/Hang_Seng_Index"
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    print(f"  Status: {resp.status_code}")
    tables = pd.read_html(resp.text)
    print(f"  Found {len(tables)} tables")
    for i, t in enumerate(tables):
        cols = list(t.columns)
        # Look for table with stock codes
        if any('code' in str(c).lower() or 'ticker' in str(c).lower() or 'symbol' in str(c).lower() for c in cols):
            print(f"  Table {i}: {t.shape}, columns={cols}")
            print(t.head(5).to_string(index=False))
        elif any('0000' in str(c) or '00700' in str(t.iloc[0].values) for c in cols for t_row in [t]):
            pass
    # Try broader search
    for i, t in enumerate(tables):
        if len(t) > 50 and len(t) < 100:
            print(f"  Table {i}: {t.shape}, columns={list(t.columns)[:5]}")
            print(t.head(3).to_string(index=False))
            print()
except Exception as e:
    print(f"  FAILED: {e}")

# Approach J: Use sina stock_hk_spot (already have 2797 stocks) 
# and cross-reference with hardcoded HSI list
print()
print("=" * 60)
print("J. Cross-reference: sina HK stocks vs HSI hardcoded list")
print("=" * 60)
import akshare as ak
try:
    all_hk = ak.stock_hk_spot()
    # HSI hardcoded list
    hsi_codes = [
        "00001", "00002", "00003", "00005", "00006", "00011", "00012", "00016",
        "00017", "00019", "00027", "00066", "00101", "00175", "00241", "00267",
        "00268", "00270", "00285", "00288", "00291", "00293", "00388", "00688",
        "00700", "00762", "00763", "00823", "00868", "00883", "00939", "00941",
        "00992", "01038", "01044", "01088", "01099", "01109", "01113", "01177",
        "01211", "01288", "01398", "01658", "01766", "01810", "01876", "01928",
        "01997", "02007", "02013", "02018", "02313", "02318", "02328", "02331",
        "02382", "02388", "02628", "02688", "02888", "02918", "03328", "03690",
        "03888", "03968", "06098", "06185", "06862", "06888", "09618", "09633",
        "09668", "09888", "09988", "09999", "01024", "02020", "02359", "06618",
        "01896", "02196", "02269", "03833",
    ]
    # all_hk 'code' column format
    print(f"  All HK stocks: {len(all_hk)}")
    print(f"  all_hk columns: {list(all_hk.columns)}")
    # Check code format
    print(f"  all_hk code sample: {all_hk['代码'].head(5).tolist()}")
    
    # Match
    all_hk['code_5'] = all_hk['代码'].astype(str).str.zfill(5)
    matched = all_hk[all_hk['code_5'].isin(hsi_codes)]
    print(f"\n  HSI matched: {len(matched)} / {len(hsi_codes)}")
    print(matched[['code_5', '中文名称']].head(10).to_string(index=False))
    
    # Find missing
    found = set(matched['code_5'].tolist())
    missing = set(hsi_codes) - found
    if missing:
        print(f"\n  Missing codes: {sorted(missing)}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\nDONE")
