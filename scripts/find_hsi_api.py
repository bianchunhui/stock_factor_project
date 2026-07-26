"""Find Eastmoney push2 API filter string for HSI constituents.

The grid page #hsi_large_components loads data via:
  push2.eastmoney.com/api/qt/clist/get
with a specific fs= parameter.

We try common patterns for HK indices.
"""
import requests
import json
import time

BASE = "https://push2.eastmoney.com/api/qt/clist/get"
FIELDS = "f2,f3,f12,f14,f15,f16,f17,f18,f20"

# Candidates for HSI constituents
# m: market (128=HK), t: board type
candidates = [
    # HSI related
    "b:BK0524",   # 恒生指数板块
    "b:BK0248",   # 可能也是恒生
    # HK large cap
    "m:128+t:1",  # HK main board
    "m:128+t:23", # possibly HSI
    "m:128+s:204", # another guess
    # HSI specific fs strings
    "m:128+b:BK0524",
    "m:128+f:!50",
    # Try specific HSI fs patterns
    "b:BK0484",
    "b:BK0551",
    "b:BK0552", 
]

for fs in candidates:
    try:
        params = {
            "pn": "1", "pz": "5", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": fs, "fields": FIELDS,
        }
        resp = requests.get(BASE, params=params, timeout=10, 
                          headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
        if data.get("data") and data["data"].get("diff"):
            items = data["data"]["diff"]
            total = data["data"].get("total", len(items))
            if total > 30:
                print(f"✅ fs={fs}: total={total}, sample={items[:3]}")
        else:
            print(f"❌ fs={fs}: empty/failed")
    except Exception as e:
        print(f"❌ fs={fs}: {e}")
    time.sleep(0.3)

# Also try to get the "恒生大型股" classification directly
print("\n" + "=" * 60)
print("Try getting HSI via stock_hk_index_spot_em detailed data")
print("=" * 60)
try:
    import akshare as ak
    df = ak.stock_hk_index_spot_em()
    print(f"Total indices: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    # Check if there's a code pattern for HSI
    hsi = df[df['名称'] == '恒生指数']
    print(f"HSI row: {hsi.to_string(index=False) if len(hsi) > 0 else 'Not found'}")
except Exception as e:
    print(f"Failed: {e}")

print("\nDONE")
