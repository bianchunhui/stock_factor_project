"""Build GGT eligibility list by testing HSI constituents via stock_hsgt_individual_em.

Strategy:
1. Start with hardcoded HSI constituents (~84 stocks)
2. For each, check if stock_hsgt_individual_em returns data (=> GGT eligible)
3. Save the cross-referenced list

Also try: the hsgt_hist_em daily data contains 领涨股-代码 column
which gives us GGT-eligible stock codes as a side effect.
"""
import akshare as ak
import pandas as pd
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# HSI constituents (hardcoded, update quarterly)
HSI_CODES = [
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

print(f"HSI constituents to test: {len(HSI_CODES)}")
print("Checking GGT eligibility via stock_hsgt_individual_em...")
print()

ggt_eligible = []
ggt_ineligible = []

for i, code in enumerate(HSI_CODES):
    try:
        df = ak.stock_hsgt_individual_em(symbol=code)
        if df is not None and len(df) > 0:
            ggt_eligible.append(code)
            status = "GGT ✅"
        else:
            ggt_ineligible.append(code)
            status = "GGT ❌"
    except Exception as e:
        ggt_ineligible.append(code)
        status = f"ERROR: {e}"
    
    if (i + 1) % 10 == 0 or i == len(HSI_CODES) - 1:
        print(f"  [{i+1}/{len(HSI_CODES)}] {code}: {status}  "
              f"(eligible: {len(ggt_eligible)}, ineligible: {len(ggt_ineligible)})")
    time.sleep(0.2)

print()
print("=" * 60)
print(f"Result: {len(ggt_eligible)} GGT-eligible out of {len(HSI_CODES)} HSI stocks")
print("=" * 60)

if ggt_ineligible:
    print(f"\nNot in GGT: {ggt_ineligible}")

# Save final list
result = pd.DataFrame({
    "ticker": ggt_eligible,
    "in_hsi": True,
    "in_ggt": True,
    "source": "hsi_ggt_intersection",
})
out_path = Path("data/hk_universe.csv")
result.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\nSaved to {out_path}")
print(f"Final HK universe: {len(result)} stocks")
