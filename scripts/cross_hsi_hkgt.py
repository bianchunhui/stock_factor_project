"""Cross-validate HSI 93 constituents vs 港股通 (Southbound) eligible list.

1. Load HSI 93 from data/hsi_constituents_20260709.csv
2. Get 港股通 constituents via stock_hk_ggt_components_em (now working)
3. Intersect -> HSI stocks that are also Southbound-eligible
4. Output: data/hsi_and_hkgt_20260709.csv
"""
import pandas as pd
import akshare as ak

# 1. HSI 93
hsi = pd.read_csv("data/hsi_constituents_20260709.csv", dtype={"ticker": str})
hsi_tickers = set(hsi["ticker"])
print(f"HSI constituents: {len(hsi_tickers)}")

# 2. 港股通 constituents (沪港通+深港通)
try:
    ggt = ak.stock_hk_ggt_components_em()
    # normalize ticker
    ggt["ticker"] = ggt["代码"].astype(str).str.zfill(5)
    ggt_tickers = set(ggt["ticker"])
    print(f"港股通 constituents: {len(ggt_tickers)}")
    print(f"  ggt columns: {list(ggt.columns)}")
except Exception as e:
    print(f"stock_hk_ggt_components_em FAILED: {e}")
    # fallback: build ggt eligible set by probing each HSI ticker via stock_hsgt_individual_em
    print("Falling back to individual probe (slower)...")
    ggt_tickers = set()
    import time
    for t in hsi_tickers:
        try:
            d = ak.stock_hsgt_individual_em(symbol=t)
            if d is not None and len(d) > 0:
                ggt_tickers.add(t)
        except Exception:
            pass
        time.sleep(0.1)
    print(f"  Probed eligible: {len(ggt_tickers)}")

# 3. Intersect
both = hsi_tickers & ggt_tickers
hsi_only = hsi_tickers - ggt_tickers
ggt_only_not_hsi = ggt_tickers - hsi_tickers

print(f"\n=== Result ===")
print(f"HSI ∩ 港股通 (both): {len(both)}")
print(f"HSI only (not 港股通): {len(hsi_only)} -> {sorted(hsi_only)}")
print(f"港股通 only (not HSI): {len(ggt_only_not_hsi)}")

# 4. Output merged file
hsi["is_hkgt"] = hsi["ticker"].isin(ggt_tickers)
out = hsi.copy()
out.to_csv("data/hsi_and_hkgt_20260709.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved -> data/hsi_and_hkgt_20260709.csv ({len(out)} rows, {out['is_hkgt'].sum()} in 港股通)")

# Also dump the pure intersection list for universe module
both_df = out[out["is_hkgt"]][["ticker", "name", "industry"]]
both_df.to_csv("data/hsi_hkgt_universe_20260709.csv", index=False, encoding="utf-8-sig")
print(f"Saved -> data/hsi_hkgt_universe_20260709.csv ({len(both_df)} stocks)")
