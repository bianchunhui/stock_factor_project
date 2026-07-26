import pandas as pd
h = pd.read_parquet("data/hk_panel_hsgt.parquet")
print("columns:", list(h.columns))
print()
# rename garbled cols
for c in h.columns:
    if "变化" in c or "鍙" in c:
        print(f"  garbled: '{c}'")
print()
# check financial cols
f = pd.read_parquet("data/hk_panel_financial.parquet")
print("financial cols:", list(f.columns))
print()
print("financial sample (00700):")
s = f[f["ticker"]=="00700"].head(3)
for c in f.columns:
    print(f"  {c}: {s[c].tolist()}")
