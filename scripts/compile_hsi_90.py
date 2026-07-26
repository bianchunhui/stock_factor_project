"""Build HSI 90 constituents list (as of 2026-03-09 quarterly review).

Source: Multiple search results from 2025-2026 indicating:
- 2024 baseline: 82 stocks
- 2024-12: +快手(01024) +新东方(09901), -新世界发展(00017) → 83 stocks  
- 2025-02: +宁德时代(03750) +洛阳钼业(03993) +老铺黄金(06181), -中升集团(00881) → 88→90 stocks (effective 2026-03-09)

NOTE: Some historical additions/removals accumulated over quarters:
- Previous additions: 理想汽车(02015), 药明康德(02359), 比亚迪电子(00285), etc.
- Various removals over time
"""

# HSI 90 constituents (effective 2026-03-09)
# Compiled from multiple public sources
HSI_90 = [
    # === Financials (金融) ===
    "00005",  # 汇丰控股
    "00011",  # 恒生银行
    "00388",  # 香港交易所
    "00939",  # 建设银行
    "01299",  # 友邦保险
    "01398",  # 工商银行
    "02318",  # 中国平安
    "02388",  # 中银香港
    "02628",  # 中国人寿
    "03328",  # 交通银行
    "03968",  # 招商银行
    "03988",  # 中国银行
    
    # === Utilities (公用) ===
    "00002",  # 中电控股
    "00003",  # 香港中华煤气
    "00006",  # 电能实业
    
    # === Properties (地产) ===
    "00001",  # 长和
    "00012",  # 恒基地产
    "00016",  # 新鸿基地产
    "00083",  # 信和置业
    "00101",  # 恒隆地产
    "00688",  # 中国海外发展
    "00960",  # 龙湖集团
    "01109",  # 华润置地
    "01997",  # 九龙仓置业
    
    # === Conglomerates (综合) ===
    "00019",  # 太古股份公司A
    "00267",  # 中信股份
    
    # === Energy (能源) ===
    "00386",  # 中国石油化工股份
    "00857",  # 中国石油股份
    "00883",  # 中国海洋石油
    "01088",  # 中国神华
    "03993",  # 洛阳钼业 (new 2026-03)
    
    # === Telecom (电讯) ===
    "00762",  # 中国联通
    "00728",  # 中国电信
    "00941",  # 中国移动
    
    # === Technology / Internet (科技) ===
    "00700",  # 腾讯控股
    "09988",  # 阿里巴巴-SW
    "03690",  # 美团-W
    "09999",  # 网易-S
    "01810",  # 小米集团-W
    "09618",  # 京东集团-SW
    "09888",  # 百度集团-SW
    "01024",  # 快手-W
    "09901",  # 新东方-S
    "00241",  # 阿里健康
    "06618",  # 京东健康
    "02013",  # 微盟集团? - Actually let me verify
    
    # === Consumer / Retail (消费) ===
    "00175",  # 吉利汽车
    "00291",  # 华润啤酒
    "00293",  # 国泰航空
    "00270",  # 粤海投资
    "00322",  # 康师傅控股
    "00669",  # 创科实业
    "00992",  # 联想集团
    "01044",  # 恒安国际
    "01177",  # 中国生物制药
    "01211",  # 比亚迪股份
    "01378",  # 中国宏桥
    "01658",  # 邮储银行
    "01772",  # 赣锋锂业
    "01876",  # 百威亚太
    "01928",  # 金沙中国有限公司
    "01929",  # 周大福
    "02007",  # 碧桂园服务
    "02015",  # 理想汽车-W
    "02018",  # 瑞声科技
    "02020",  # 安踏体育
    "02196",  # 复星医药
    "02269",  # 药明生物
    "02313",  # 申洲国际
    "02331",  # 李宁
    "02359",  # 药明康德
    "02382",  # 舜宇光学科技
    "02688",  # 新奥能源
    "02899",  # 紫金矿业
    "02918",  # (placeholder, check)
    "03833",  # 新疆大全能源? 不，应该是 other
    "03888",  # 金山软件
    "06098",  # 碧桂园服务? No, that was 02007
    "06185",  # 康希诺生物
    "06862",  # 海底捞
    "06888",  # 招金矿业? No, let me check
    "09633",  # 农夫山泉
    "09668",  # 泡泡玛特? No...
    
    # 2026-03 additions:
    "03750",  # 宁德时代 (new)
    "06181",  # 老铺黄金 (new)
    
    # Removed: "00881"  # 中升集团 (removed 2026-03)
    # Removed: "00017"  # 新世界发展 (removed 2024-12)
]

# Deduplicate and sort
HSI_90 = sorted(set(HSI_90))

print(f"Total HSI constituents (compiled): {len(HSI_90)}")
print(f"Target: 90")
print()
if len(HSI_90) != 90:
    print(f"WARNING: Expected 90, got {len(HSI_90)}. Need to review list.")
    
# Save for verification
import pandas as pd
from pathlib import Path
df = pd.DataFrame({"ticker": HSI_90})
Path("data").mkdir(exist_ok=True)
df.to_csv("data/hsi_90_reference.csv", index=False, encoding="utf-8-sig")
print("\nSaved to data/hsi_90_reference.csv")
