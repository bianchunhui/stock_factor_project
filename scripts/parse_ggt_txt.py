"""Parse Eastmoney-exported 沪港通/深港通 TXT files and build the 港股通 universe.

Files are GBK-encoded, tab-separated but mangled into a single column.
We extract stock codes (5-digit HK codes) via regex from the raw text.

Output:
  data/hkgt_sh.csv  (沪港通标的, ~615)
  data/hkgt_sz.csv  (深港通标的, ~615)
  data/hkgt_all.csv (并集, unique)
  data/hsi_and_hkgt_20260709.csv (HSI 93 + is_hkgt_sh / is_hkgt_sz / is_hkgt flags)
  data/hsi_hkgt_universe_20260709.csv (HSI ∩ 港股通, for factor model)
"""
import pandas as pd
import re

SH_FILE = r"C:\Users\chunh\Downloads\Table沪港通.txt"
SZ_FILE = r"C:\Users\chunh\Downloads\Table深港通.txt"

def parse_ggt_txt(path, label):
    """Extract (code, name) pairs from Eastmoney GBK tab file."""
    with open(path, "r", encoding="gbk") as f:
        lines = f.readlines()
    
    # Header is line 0 (merged). Data starts from line 1.
    # Each data line: "  1      03986    兆易创新            945.000  ..."
    # Code is a 5-digit number; name follows after code.
    records = []
    for line in lines[1:]:
        # Match: optional serial number, then 5-digit code, then Chinese name
        m = re.match(r"\s*\d+\s+(\d{5})\s+(\S+)", line)
        if m:
            code = m.group(1)
            name = m.group(2).strip()
            records.append({"ticker": code, "name": name, "source": label})
    return pd.DataFrame(records)

sh = parse_ggt_txt(SH_FILE, "sh")
sz = parse_ggt_txt(SZ_FILE, "sz")
print(f"沪港通: {len(sh)} stocks")
print(f"深港通: {len(sz)} stocks")

# Union
all_ggt = pd.concat([sh, sz]).drop_duplicates(subset="ticker").sort_values("ticker").reset_index(drop=True)
# Mark which connect
all_ggt["in_sh"] = all_ggt["ticker"].isin(set(sh["ticker"]))
all_ggt["in_sz"] = all_ggt["ticker"].isin(set(sz["ticker"]))

print(f"港股通 union (unique): {len(all_ggt)}")
print(f"  only in 沪: { (~all_ggt['in_sz'] & all_ggt['in_sh']).sum()}")
print(f"  only in 深: { (all_ggt['in_sz'] & ~all_ggt['in_sh']).sum()}")
print(f"  in both:    { (all_ggt['in_sz'] & all_ggt['in_sh']).sum()}")

sh.to_csv("data/hkgt_sh.csv", index=False, encoding="utf-8-sig")
sz.to_csv("data/hkgt_sz.csv", index=False, encoding="utf-8-sig")
all_ggt.to_csv("data/hkgt_all.csv", index=False, encoding="utf-8-sig")
print(f"Saved data/hkgt_sh.csv, data/hkgt_sz.csv, data/hkgt_all.csv")

# --- Cross with HSI 93 ---
hsi = pd.read_csv("data/hsi_constituents_20260709.csv", dtype={"ticker": str})
sh_set = set(sh["ticker"])
sz_set = set(sz["ticker"])
all_set = set(all_ggt["ticker"])

hsi["is_hkgt_sh"] = hsi["ticker"].isin(sh_set)
hsi["is_hkgt_sz"] = hsi["ticker"].isin(sz_set)
hsi["is_hkgt"] = hsi["ticker"].isin(all_set)

hsi.to_csv("data/hsi_and_hkgt_20260709.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved data/hsi_and_hkgt_20260709.csv ({len(hsi)} rows)")
print(f"HSI ∩ 港股通: {hsi['is_hkgt'].sum()}/93")
print(f"HSI ∩ 沪港通: {hsi['is_hkgt_sh'].sum()}")
print(f"HSI ∩ 深港通: {hsi['is_hkgt_sz'].sum()}")

# HSI not in 港股通
not_in = hsi[~hsi["is_hkgt"]][["ticker", "name"]]
if len(not_in) > 0:
    print(f"\nHSI stocks NOT in 港股通 ({len(not_in)}):")
    print(not_in.to_string(index=False))
else:
    print("\nAll 93 HSI stocks are in 港股通!")

# Save the final universe for the factor model
universe = hsi[hsi["is_hkgt"]][["ticker", "name", "industry"]].copy()
universe.to_csv("data/hsi_hkgt_universe_20260709.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved data/hsi_hkgt_universe_20260709.csv ({len(universe)} stocks)")
