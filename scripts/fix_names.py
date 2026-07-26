"""补全选股结果的股票名称。"""
import pandas as pd

uni = pd.read_csv("data/hsi_hkgt_universe_20260709.csv")
name_map = dict(zip(uni["ticker"].astype(str).str.zfill(5), uni["name"]))

for f in ["hk_top20_equal_weight.csv", "hk_top20_ic_weight.csv"]:
    path = f"data/factors/{f}"
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["ticker"] = df["ticker"].astype(str).str.zfill(5)
    df["name"] = df["ticker"].map(name_map).fillna("")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    
    comp_col = "composite_eq" if "composite_eq" in df.columns else "composite_ic"
    print(f"=== {f} ===")
    for rank, (_, r) in enumerate(df.iterrows(), 1):
        print(f"  {rank:>2}. {r['ticker']}  {r['name']:<12s}  {comp_col}={r[comp_col]:+.3f}")
    print()
