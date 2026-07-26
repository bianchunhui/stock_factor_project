"""深度分析 06160 百济神州 EpG 爆炸 + 全市场 EpG 异常值扫描。"""
import pandas as pd
import numpy as np

panel = pd.read_parquet("data/hk_full_factor_panel.parquet")

# ====== 1. 06160 Q1 报告 PIT merge 时间点 ======
print("=== 06160 Q1-2026 报告 PIT merge ===")
d = panel[panel["ticker"] == "06160"].copy()
d["date"] = pd.to_datetime(d["date"])

# 2026-03-31 Q1 报告什么时候进入 panel？
# PIT: announcement_date + 90 天
fin = pd.read_parquet("data/hk_panel_financial.parquet")
q1 = fin[(fin["ticker"] == "06160") & (fin["report_date"] == "2026-03-31")]
print(f"Q1-2026 报告:")
print(f"  holder_profit: {q1['holder_profit'].values[0]/1e8:.2f}亿")
print(f"  holder_profit_yoy: {q1['holder_profit_yoy'].values[0]:.2f}%")

# PIT merge 后什么时候开始生效？
sub = d[["date", "parent_net_profit_yoy"]].dropna()
sub["prev"] = sub["parent_net_profit_yoy"].shift(1)
jump = sub[sub["parent_net_profit_yoy"] > 1000]
print(f"  EpG 爆炸起始日: {jump['date'].iloc[0].date()}")
print(f"  之前 yoy: {sub.loc[jump.index[0]-1,'parent_net_profit_yoy']:.2f}")
print(f"  爆炸后 yoy: {jump['parent_net_profit_yoy'].iloc[0]:.2f}")
print()

# ====== 2. 全市场 EpG 异常值扫描 ======
print("=== 全市场 EpG_raw 极端值 ===")
latest_date = pd.to_datetime(panel["date"]).max()
latest = panel[pd.to_datetime(panel["date"]) == latest_date]
epg = latest[["ticker", "EpG_raw"]].dropna()
epg = epg.sort_values("EpG_raw")

print(f"最新截面 ({latest_date.date()}):")
print(f"  全市场覆盖: {len(epg)}/88")
print(f"  EpG_raw 分位数:")
for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
    print(f"    {p:>2}%: {np.percentile(epg.EpG_raw, p):.1f}")

print(f"\n  Top 10 最高:")
top10 = epg.nlargest(10, "EpG_raw")
for _, r in top10.iterrows():
    print(f"    {r['ticker']}  EpG={r['EpG_raw']:.1f}")

print(f"\n  Bottom 10 最低:")
bottom10 = epg.nsmallest(10, "EpG_raw")
for _, r in bottom10.iterrows():
    print(f"    {r['ticker']}  EpG={r['EpG_raw']:.1f}")

# ====== 3. 小基数问题检测 ======
print("\n=== 小基数 YoY 检测（全市场） ===")
# 对于每个 ticker，检查 parent_net_profit 接近零的天
panel["date"] = pd.to_datetime(panel["date"])
for t in ["06160"]:
    dp = panel[panel["ticker"] == t][["date", "parent_net_profit", "parent_net_profit_yoy"]].dropna()
    near_zero = dp[dp["parent_net_profit"].abs() < 5e7]  # < 5000万
    if len(near_zero) > 0:
        print(f"\n  {t} 净利润<5000万的时期:")
        print(f"    天数: {len(near_zero)}")
        for _, r in near_zero.iterrows():
            print(f"    {r['date'].date()}  profit={r['parent_net_profit']/1e4:.0f}万  yoy={r['parent_net_profit_yoy']:.1f}%")

# ====== 4. 查看 EpG 因子在打分中的贡献 ======
print("\n=== 06160 在各因子上的得分分解 ===")
d_latest = d[d["date"] == d["date"].max()]
for f in ["BP_z", "EP_z", "EpG_z", "GPM_z", "Rev1m_z", "composite_eq"]:
    if f in d_latest.columns:
        print(f"  {f}: {d_latest[f].values[0]:+.3f}")
