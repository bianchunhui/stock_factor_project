"""Try official sources for HSI constituents and GGT list."""
import requests
import pandas as pd

# Approach A: Hang Seng Indexes Company - HSI constituents
print("=" * 60)
print("A. Hang Seng Indexes Company - HSI constituents")
print("=" * 60)
try:
    url = "https://www.hsi.com.hk/eng/indexes/all-indexes/hsi/constituents"
    resp = requests.get(url, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    })
    print(f"  Status: {resp.status_code}")
    # Check if there are tables
    tables = pd.read_html(resp.text)
    if tables:
        print(f"  Found {len(tables)} tables")
        for i, t in enumerate(tables):
            print(f"  Table {i}: shape={t.shape}, columns={list(t.columns)}")
            if len(t) > 0:
                print(t.head(3).to_string(index=False))
    else:
        print("  No tables found (likely JS-rendered)")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach B: SSE/SHSE港股通名单
print()
print("=" * 60)
print("B. SSE港股通名单 (沪港通)")
print("=" * 60)
try:
    url = "https://query.sse.com.cn/commonSoaQuery.do"
    params = {
        "jsonCallBack": "",
        "isPagination": "true",
        "sqlId": "GZGL_GGT_GGTXXPL",
        "pageHelp.pageSize": "1000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.endPage": "1000",
    }
    resp = requests.get(url, params=params, timeout=10, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.sse.com.cn/",
    })
    print(f"  Status: {resp.status_code}")
    print(f"  Content[:500]: {resp.text[:500]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach C: SZSE港股通名单
print()
print("=" * 60)
print("C. SZSE港股通名单 (深港通)")
print("=" * 60)
try:
    url = "https://www.szse.cn/api/disc/announcement/annList"
    data = {"channelCode": ["fixed_disc"], "pageSize": 5, "pageNum": 1,
            "seDate": ["2024-01-01", "2026-07-09"],
            "searchkey": "港股通"}
    resp = requests.post(url, json=data, timeout=10, headers={
        "User-Agent": "Mozilla/5.0",
    })
    print(f"  Status: {resp.status_code}")
    print(f"  Content[:500]: {resp.text[:500]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach D: Eastmoney - 港股通成分 (alternative endpoint)
print()
print("=" * 60)
print("D. Eastmoney - 港股通成分 (alternative)")
print("=" * 60)
try:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "1000",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",  # 港股通板块
        "fields": "f12,f14",  # code, name
    }
    resp = requests.get(url, params=params, timeout=10, headers={
        "User-Agent": "Mozilla/5.0",
    })
    print(f"  Status: {resp.status_code}")
    data = resp.json()
    if data.get("data") and data["data"].get("diff"):
        items = data["data"]["diff"]
        print(f"  Got {len(items)} items")
        print(f"  Sample: {items[:3]}")
    else:
        print(f"  Response: {str(data)[:300]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach E: Eastmoney - HSI constituents via datacenter
print()
print("=" * 60)
print("E. Eastmoney datacenter - HSI constituents")
print("=" * 60)
try:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "sortColumns": "SECURITY_CODE",
        "sortTypes": "1",
        "pageSize": "100",
        "pageNumber": "1",
        "reportName": "RPT_HSI_CONSTITUENTS",
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
    print(f"  Success: {data.get('success')}")
    if data.get("result") and data["result"].get("data"):
        rows = data["result"]["data"]
        print(f"  Got {len(rows)} rows")
        print(f"  Sample: {rows[:2]}")
    else:
        print(f"  Message: {data.get('message')}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach F: Use akshare stock_hk_spot data we already got
# HSI constituents are well-known ~80 stocks, we can hardcode
print()
print("=" * 60)
print("F. HSI constituents - hardcoded list approach")
print("=" * 60)
# From HKEX / Hang Seng Indexes Company official website
# As of 2025, HSI has ~82 constituents
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
print(f"  Hardcoded HSI list: {len(hsi_codes)} stocks")
print(f"  First 10: {hsi_codes[:10]}")
print(f"  Note: This needs periodic update (HSI reviews quarterly)")

print("\nDONE")
