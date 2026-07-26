"""Try to get GGT (港股通) constituent list from SHSE/SZSE official."""
import requests
import pandas as pd

# Approach K: SHSE 沪股通名单
print("=" * 60)
print("K. SHSE 沪港通下港股通名单")
print("=" * 60)
try:
    url = "http://query.sse.com.cn/commonSoaQuery.do"
    params = {
        "sqlId": "GZGL_GGT_GGTXXPL",
        "isPagination": "true",
        "pageHelp.pageSize": "1000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.endPage": "1000",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "http://www.sse.com.cn/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    resp = requests.get(url, params=params, timeout=10, headers=headers)
    print(f"  Status: {resp.status_code}")
    print(f"  Content[:500]: {resp.text[:500]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach L: SZSE 深港通名单 - sector list
print()
print("=" * 60)
print("L. SZSE 深港通名单")
print("=" * 60)
try:
    # Try SZSE API for 港股通标的
    url = "https://www.szse.cn/api/disc/announcement/annList"
    # Search for latest 港股通调整 announcement
    data = {
        "channelCode": ["fixed_disc"],
        "pageSize": 5,
        "pageNum": 1,
        "seDate": ["2025-01-01", "2026-07-09"],
        "searchkey": "港股通名单",
    }
    resp = requests.post(url, json=data, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    print(f"  Status: {resp.status_code}")
    import json
    j = resp.json()
    if j.get("data"):
        for item in j["data"][:3]:
            print(f"    Title: {item.get('title')}, Date: {item.get('publishTime')}")
            print(f"    Attach: {item.get('attachPath')}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach M: Eastmoney - 港股通 through akshare with retries
print()
print("=" * 60)
print("M. akshare stock_hk_ggt_components_em (5 retries)")
print("=" * 60)
import akshare as ak
import time
for i in range(5):
    try:
        df = ak.stock_hk_ggt_components_em()
        print(f"  Success! Rows: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        print(df.head(5).to_string(index=False))
        # Save to CSV for later use
        df.to_csv("data/ggt_constituents.csv", index=False, encoding="utf-8-sig")
        print(f"\n  Saved to data/ggt_constituents.csv")
        break
    except Exception as e:
        print(f"  Attempt {i+1}: {e}")
        time.sleep(3)
else:
    print("  All retries failed")

# Approach N: Use sina all HK stocks + filter by known GGT features
# 港股通标的通常代码为4-5位数字
# 可以通过东财个股页面判断是否属于港股通
print()
print("=" * 60)
print("N. Alternative: stock_hsgt_stock_statistics_em")
print("=" * 60)
try:
    df = ak.stock_hsgt_stock_statistics_em(market="南向持股", indicator="今日排行")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(5).to_string(index=False))
    # This gives us stocks with southbound holding = GGT stocks
    if len(df) > 0:
        df.to_csv("data/ggt_from_hsgt.csv", index=False, encoding="utf-8-sig")
        print(f"\n  Saved to data/ggt_from_hsgt.csv")
except Exception as e:
    print(f"  FAILED: {e}")

print("\nDONE")
