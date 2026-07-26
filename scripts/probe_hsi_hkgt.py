"""Build HSI ∩ 港股通 universe via per-ticker Southbound holding probe.

stock_hk_ggt_components_em is intermittently unavailable (EM connection aborts),
so we probe each HSI ticker with stock_hsgt_individual_em:
  - if it returns non-empty data -> stock IS in 港股通 (has southbound holdings)
  - empty/exception -> not in 港股通 (or network blip, flagged separately)

Save:
  data/hsi_and_hkgt_20260709.csv   (all 93, with is_hkgt + probe_status)
  data/hsi_hkgt_universe_20260709.csv  (intersection only)
"""
import pandas as pd
import akshare as ak
import time
import sys

hsi = pd.read_csv("data/hsi_constituents_20260709.csv", dtype={"ticker": str})
hsi_tickers = hsi["ticker"].tolist()

print(f"Probing {len(hsi_tickers)} HSI tickers for 港股通 eligibility...", flush=True)

results = {}  # ticker -> (is_hkgt: bool, status: str)
probe_ok = 0
probe_fail = 0
for i, t in enumerate(hsi_tickers, 1):
    try:
        d = ak.stock_hsgt_individual_em(symbol=t)
        if d is not None and len(d) > 0:
            results[t] = (True, "eligible")
            probe_ok += 1
        else:
            results[t] = (False, "empty")
    except Exception as e:
        results[t] = (False, f"err:{type(e).__name__}")
        probe_fail += 1
    # throttle a bit to avoid hammering
    time.sleep(0.15)
    if i % 10 == 0 or i == len(hsi_tickers):
        print(f"  [{i}/{len(hsi_tickers)}] ok={probe_ok} empty/fail={probe_fail}", flush=True)

print(f"\nDone. eligible={probe_ok}, not_eligible/err={probe_fail}", flush=True)

# Merge
hsi["is_hkgt"] = hsi["ticker"].map(lambda x: results[x][0])
hsi["probe_status"] = hsi["ticker"].map(lambda x: results[x][1])
hsi.to_csv("data/hsi_and_hkgt_20260709.csv", index=False, encoding="utf-8-sig")
print(f"Saved data/hsi_and_hkgt_20260709.csv ({len(hsi)} rows)", flush=True)

both = hsi[hsi["is_hkgt"]][["ticker", "name", "industry"]]
both.to_csv("data/hsi_hkgt_universe_20260709.csv", index=False, encoding="utf-8-sig")
print(f"Saved data/hsi_hkgt_universe_20260709.csv ({len(both)} stocks)", flush=True)

# List the non-eligible ones for review
not_elig = hsi[~hsi["is_hkgt"]][["ticker", "name", "probe_status"]]
print(f"\nNot in 港股通 ({len(not_elig)}):", flush=True)
print(not_elig.to_string(index=False), flush=True)
