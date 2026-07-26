"""Try multiple approaches to get HSI constituents."""
import akshare as ak
import pandas as pd

# Approach 1: stock_hk_spot (sina) - get all HK stocks, then we need to filter
print("=" * 60)
print("Approach 1: stock_hk_spot (sina) - all HK stocks")
print("=" * 60)
try:
    df = ak.stock_hk_spot()
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

# Approach 2: Try stock_hk_ggt_components_em with retry
print()
print("=" * 60)
print("Approach 2: stock_hk_ggt_components_em (retry)")
print("=" * 60)
import time
for attempt in range(3):
    try:
        df = ak.stock_hk_ggt_components_em()
        print(f"  Rows: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        print(df.head(5).to_string(index=False))
        print(f"\n  Unique codes: {df.iloc[:, 2].nunique() if len(df) > 0 else 0}")
        break
    except Exception as e:
        print(f"  Attempt {attempt+1} failed: {e}")
        time.sleep(2)

# Approach 3: Try stock_zh_ah_name (A+H shares)
print()
print("=" * 60)
print("Approach 3: stock_zh_ah_name (A+H shares)")
print("=" * 60)
try:
    df = ak.stock_zh_ah_name()
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(5).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

# Approach 4: Try stock_hk_hot_rank_em (hot stocks, might give us some HSI members)
print()
print("=" * 60)
print("Approach 4: stock_hk_hot_rank_em (hot rank)")
print("=" * 60)
try:
    df = ak.stock_hk_hot_rank_em()
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(5).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

# Approach 5: Try stock_individual_basic_info_hk_xq (xueqiu HK info)
print()
print("=" * 60)
print("Approach 5: stock_individual_basic_info_hk_xq (00700)")
print("=" * 60)
try:
    df = ak.stock_individual_basic_info_hk_xq(symbol="00700")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

# Approach 6: Try eastmoney web API directly for HSI constituents
print()
print("=" * 60)
print("Approach 6: Eastmoney web - HSI constituents")
print("=" * 60)
try:
    import requests
    # Eastmoney API for HSI constituents
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "sortColumns": "SECURITY_CODE",
        "sortTypes": "1",
        "pageSize": "100",
        "pageNumber": "1",
        "reportName": "RPT_INDEX_HSI_DETAIL",
        "columns": "ALL",
        "source": "WEB",
        "client": "WEB",
    }
    resp = requests.get(url, params=params, timeout=10, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.eastmoney.com/",
    })
    print(f"  Status: {resp.status_code}")
    data = resp.json()
    if data.get("result"):
        rows = data["result"].get("data", [])
        print(f"  Got {len(rows)} rows")
        if rows:
            print(f"  Columns: {list(rows[0].keys())}")
            for r in rows[:3]:
                print(f"    {r}")
    else:
        print(f"  Response: {data}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach 7: Try fetching from HKEX directly
print()
print("=" * 60)
print("Approach 7: HKEX - HSI constituents via stock_hk_index_spot_em")
print("=" * 60)
try:
    df = ak.stock_hk_index_spot_em()
    hsi_rows = df[df['名称'].str.contains('恒生指数', na=False)]
    print(f"  HSI related indices: {len(hsi_rows)}")
    print(hsi_rows[['代码', '名称']].to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print("\nDONE")
