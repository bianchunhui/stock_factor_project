"""Build definitive HSI 90 list and validate 港股通 membership.

From tracked adjustments:
- 2024-05: 82 stocks (base from public article)
- 2024-06: +比亚迪电子(00285) replacing碧桂园服务(06098)? No,碧桂园服务 was still in.
  Let me trace more carefully from news:

Key adjustments:
- 2023-06: 76→80: +华润电力, +紫金矿业, +京东健康, +携程集团
- 2023-09: -碧桂园 +国药控股  
- 2023-12: +理想汽车, +药明康德 → 82
- 2024-03: no change
- 2024-06: -碧桂园服务 +比亚迪电子 (82 stays)
- 2024-09: +中国宏桥(01378) +中升集团(00881)? Wait
- 2024-12: -新世界发展(00017), +快手(01024), +新东方(09901) → 83
- 2025-03: +…… let me search
- 2025-06: +…… 
- 2025-09: +……
- 2025-12: 
- 2026-03: +宁德时代(03750) +洛阳钼业(03993) +老铺黄金(06181), -中升集团(00881) → 88→90

Between 2024-05(82) and 2025-12(88), +6 net: I need to identify which 6.

Let me just work with the verified "top 90 by turnover" approach and
cross-reference with known HSI from authoritative sources.
"""

# The 2024-05-05 toutiao article listed exactly 82 stocks. Let me rebuild from that.
# The article had: (names extracted from search results)
hsi_82_202405 = [
    "00700",  # 腾讯控股
    "09988",  # 阿里巴巴-SW
    "01398",  # 工商银行
    "00941",  # 中国移动
    "00005",  # 汇丰控股
    "00857",  # 中国石油股份
    "00939",  # 建设银行
    "03988",  # 中国银行
    "00883",  # 中国海洋石油
    "03968",  # 招商银行
    "03690",  # 美团-W
    "02318",  # 中国平安
    "01299",  # 友邦保险
    "01088",  # 中国神华
    "01211",  # 比亚迪股份
    "00386",  # 中国石油化工股份
    "09999",  # 网易-S
    "09633",  # 农夫山泉
    "02899",  # 紫金矿业
    "01810",  # 小米集团-W
    "09618",  # 京东集团-SW
    "00388",  # 香港交易所
    "02628",  # 中国人寿
    "09888",  # 百度集团-SW
    "06690",  # 海尔智家
    "02020",  # 安踏体育
    "09961",  # 携程集团-S
    "02388",  # 中银香港
    "02015",  # 理想汽车-W
    "00267",  # 中信股份
    "00016",  # 新鸿基地产
    "01109",  # 华润置地
    "00011",  # 恒生银行
    "00669",  # 创科实业
    "00762",  # 中国联通
    "00688",  # 中国海外发展
    "00066",  # 港铁公司
    "00027",  # 银河娱乐
    "02359",  # 药明康德
    "02382",  # 舜宇光学科技
    "01876",  # 百威亚太
    "00288",  # 万洲国际
    "00291",  # 华润啤酒
    "01928",  # 金沙中国有限公司
    "00002",  # 中电控股
    "00006",  # 电能实业
    "00001",  # 长和
    "00003",  # 香港中华煤气
    "02331",  # 李宁
    "00083",  # 信和置业
    "00012",  # 恒基地产
    "01929",  # 周大福
    "01044",  # 恒安国际
    "00823",  # 领展房产基金
    "00836",  # 华润电力
    "01099",  # 国药控股
    "00019",  # 太古股份公司A
    "00992",  # 联想集团
    "00101",  # 恒隆地产
    "00175",  # 吉利汽车
    "02688",  # 新奥能源
    "02007",  # 碧桂园服务
    "00285",  # 比亚迪电子
    "01177",  # 中国生物制药
    "01378",  # 中国宏桥
    "01997",  # 九龙仓置业
    "00960",  # 龙湖集团
    "02269",  # 药明生物
    "09696",  # 天齐锂业
    "02313",  # 申洲国际
    "01038",  # 长江基建集团
    "01833",  # 平安好医生
    "03328",  # 交通银行
    "01288",  # 农业银行
    "02618",  # 京东物流
    "00270",  # 粤海投资
    "00322",  # 康师傅控股
    "01658",  # 邮储银行
    "00017",  # 新世界发展 (removed 2024-12)
    "00868",  # 信义光能
    "06098",  # 碧桂园服务? No this is different
]

# Let me just check: the 2024-05 article had 82. After all adjustments to 2026-03:
# Known changes from search:
additions = [
    "01024",  # 快手-W (2024-12)
    "09901",  # 新东方-S (2024-12)
    "03750",  # 宁德时代 (2026-03)
    "03993",  # 洛阳钼业 (2026-03)
    "06181",  # 老铺黄金 (2026-03)
]
removals = [
    "00017",  # 新世界发展 (2024-12)
    "00881",  # 中升集团 (2026-03) - actually was this ever added? 
]

# But: 82 - 1 + 2 = 83... and the news said 88→90. So there were 5 more additions
# between May 2024 and Feb 2026 that I'm missing.

# Let me just verify what we have. First, let me just use the approach:
# 1. Use stock_hk_spot (Sina source) to get all HK stocks sorted by market cap
# 2. Cross-check known HSI codes
# 3. Also try stock_hk_index_spot (Sina source) for HSI info

print("=" * 60)
print("Strategy: Verify HSI via Sina API + known baseline")
print("=" * 60)

# Let's also try fetching HSI constituent names from a simpler source
# Wikipedia often has the list
import requests
print("\n1. Try Wikipedia HSI constituent list...")
try:
    resp = requests.get(
        "https://en.wikipedia.org/wiki/Hang_Seng_Index",
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    if resp.status_code == 200:
        # Extract stock codes (5-digit HK codes)
        import re
        codes = re.findall(r'SEHK:\s*(\d{4,5})', resp.text)
        if codes:
            codes = [c.zfill(5) for c in codes]
            print(f"  Found {len(codes)} codes from Wikipedia")
            print(f"  Sample: {codes[:20]}")
        else:
            # Try another pattern
            codes = re.findall(r'(\d{4,5})\s*\.HK', resp.text, re.IGNORECASE)
            if codes:
                codes = [c.zfill(5) for c in codes]
                print(f"  Found {len(codes)} codes (\.HK pattern)")
            else:
                print(f"  No codes found. Content len: {len(resp.text)}")
    else:
        print(f"  Status: {resp.status_code}")
except Exception as e:
    print(f"  FAILED: {e}")

# 2. Try akshare stock_hk_index_spot for HSI (Sina source)
print("\n2. Try Sina-based index spot...")
import akshare as ak
try:
    df = ak.stock_hk_index_spot()
    print(f"  Got {len(df)} indices")
    print(f"  Columns: {list(df.columns)}")
    hsi_row = df[df['名称'].str.contains('恒生', na=False)]
    print(f"  HSI rows: {len(hsi_row)}")
    for _, r in hsi_row.iterrows():
        print(f"    {r.to_dict()}")
except Exception as e:
    print(f"  FAILED: {e}")

# 3. Use the approach that WORKS: put together a thorough HSI 90 list
print("\n3. Now let's build the definitive 90 list...")
print("(This will be the canonical reference for the project)")

# Let me read the top90 file to see actual HK market leaders
import pandas as pd
top90 = pd.read_csv("data/top90_hk_by_turnover.csv")
print(f"\n  Top 5 by turnover: {top90[['code_numeric', '中文名称', '最新价']].head(10).to_string(index=False)}")

print("\nDONE - will build final HSI list from combined sources")
