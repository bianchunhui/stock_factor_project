"""Get GGT lists from SHSE/SZSE official APIs.

SSE eligible list: https://www.sse.com.cn/services/hkexsc/disclo/eligible/
SZSE underlying list: https://www.szse.cn/szhk/hkbussiness/underlylist/index.html
Both are JS-rendered but likely have JSON API backing.
"""
import requests
import json
import re

# Try SSE JSON endpoint for 港股通标的
print("=" * 60)
print("A. SSE 港股通标的 - JSON API")
print("=" * 60)
try:
    # SSE uses a query pattern: query.sse.com.cn
    url = "https://query.sse.com.cn/commonQuery.do"
    params = {
        "jsonCallBack": "jsonpCallback",
        "isPagination": "true",
        "sqlId": "GZGL_GGT_GGTXXPL",  # This might need different params
        "pageHelp.pageSize": "1000",
        "pageHelp.pageNo": "1",
    }
    headers = {
        "Referer": "https://www.sse.com.cn/",
        "User-Agent": "Mozilla/5.0",
    }
    resp = requests.get(url, params=params, timeout=10, headers=headers)
    print(f"  Status: {resp.status_code}")
    print(f"  Content[:500]: {resp.text[:500]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Try SSE homepage GGT API
print()
print("=" * 60)
print("B. SSE 港股通标的 - alternative endpoint")
print("=" * 60)
try:
    url = "https://query.sse.com.cn/security/stock/queryGgtList.do"
    params = {
        "jsonCallBack": "jsonpCallback",
        "isPagination": "true",
        "pageHelp.pageSize": "1000",
        "pageHelp.pageNo": "1",
    }
    headers = {
        "Referer": "https://www.sse.com.cn/",
        "User-Agent": "Mozilla/5.0",
    }
    resp = requests.get(url, params=params, timeout=10, headers=headers)
    print(f"  Status: {resp.status_code}")
    print(f"  Content[:500]: {resp.text[:500]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Try SZSE JSON endpoint
print()
print("=" * 60)
print("C. SZSE 港股通标的 - JSON API")
print("=" * 60)
try:
    # SZSE uses these pattern endpoints
    url = "https://www.szse.cn/api/disc/announcement/annList"
    data = {
        "channelCode": ["fixed_disc"],
        "pageSize": 1,
        "pageNum": 1,
        "seDate": ["2026-01-01", "2026-07-09"],
        "searchkey": "港股通标的证券名单",
    }
    resp = requests.post(url, json=data, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"})
    print(f"  Status: {resp.status_code}")
    j = resp.json()
    print(f"  Count: {j.get('announceCount', 'N/A')}")
    if j.get("data"):
        for item in j["data"][:3]:
            print(f"  Title: {item.get('title')}")
            print(f"  Date: {item.get('publishTime')}")
except Exception as e:
    print(f"  FAILED: {e}")

# Try SZSE underlying list API
print()
print("=" * 60)
print("D. SZSE 标的证券名单 - spreadsheet API")
print("=" * 60)
try:
    url = "https://www.szse.cn/api/report/szhk/hkbussiness/underlylist/index/query"
    headers = {
        "Referer": "https://www.szse.cn/szhk/hkbussiness/underlylist/index.html",
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, timeout=10, headers=headers)
    print(f"  Status: {resp.status_code}")
    print(f"  Content[:1000]: {resp.text[:1000]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Try a practical approach: get HSI constituents from hsi.com.hk JSON
print()
print("=" * 60)
print("E. hsi.com.hk - HSI constituents API")
print("=" * 60)
try:
    url = "https://www.hsi.com.hk/data/chi/index/constituents/HSI"
    resp = requests.get(url, timeout=15,
                       headers={"User-Agent": "Mozilla/5.0"})
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        if isinstance(data, list):
            print(f"  Got {len(data)} constituents")
            for item in data[:3]:
                print(f"    {item}")
        else:
            print(f"  Type: {type(data)}, Keys: {list(data.keys())[:5] if isinstance(data, dict) else 'N/A'}")
            print(f"  Content[:500]: {json.dumps(data)[:500]}")
    else:
        print(f"  Content[:300]: {resp.text[:300]}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\nDONE")
