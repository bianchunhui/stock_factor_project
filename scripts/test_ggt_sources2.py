"""Get GGT stocks via southbound holding data (stock_hsgt_individual_em reverse approach).

If we can get the list of stocks that have southbound holdings, 
those are by definition GGT-eligible stocks.

Also try stock_hsgt_hold_stock_em for the ranking.
"""
import akshare as ak
import pandas as pd
import time

# Approach O: stock_hsgt_hold_stock_em - 沪深港通持股个股排行
print("=" * 60)
print("O. stock_hsgt_hold_stock_em (个股排行)")
print("=" * 60)
try:
    df = ak.stock_hsgt_hold_stock_em(market="南向", indicator="今日排行")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(5).to_string(index=False))
    if len(df) > 0:
        df.to_csv("data/ggt_from_hold_rank.csv", index=False, encoding="utf-8-sig")
        print(f"\n  Saved to data/ggt_from_hold_rank.csv")
        codes = df.iloc[:, 1].astype(str).tolist()  # code column
        print(f"  Unique codes: {len(set(codes))}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach P: stock_hsgt_stock_statistics_em (no args)
print()
print("=" * 60)
print("P. stock_hsgt_stock_statistics_em (default args)")
print("=" * 60)
try:
    df = ak.stock_hsgt_stock_statistics_em(indicator="今日排行")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(5).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

# Approach Q: Try with different parameter combos
print()
print("=" * 60)
print("Q. stock_hsgt_stock_statistics_em (various params)")
print("=" * 60)
for ind in ["今日排行", "5日排行", "10日排行"]:
    try:
        df = ak.stock_hsgt_stock_statistics_em(indicator=ind)
        print(f"  indicator={ind}: Rows={len(df)}, Cols={list(df.columns)[:5]}")
        if len(df) > 0:
            print(df.head(2).to_string(index=False))
            break
    except Exception as e:
        print(f"  indicator={ind}: {e}")

# Approach R: Web scrape港股通名单 from HKEX
print()
print("=" * 60)
print("R. HKEX southbound eligible list")
print("=" * 60)
try:
    import requests
    url = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{}.json".format("2026/07/09")
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    print(f"  Status: {resp.status_code}")
    print(f"  Content[:300]: {resp.text[:300]}")
except Exception as e:
    print(f"  FAILED: {e}")

# Approach S: Use akshare stock_hk_spot (all 2797 HK stocks) 
# and filter by typical GGT criteria:
# - Main board (not GEM)
# - Not a derivative (no letters in code for regular stocks)
# - Price > 0.5 HKD (not a仙股)
# - Has volume
print()
print("=" * 60)
print("S. Alternative: Use stock_hsgt_hist_em + stock_hsgt_individual_em")
print("=" * 60)
# The individual_em API takes a stock code and returns southbound holding data
# If it returns data, the stock IS in GGT
# We can use this to verify our HSI list against GGT eligibility
try:
    # Test a few HSI stocks
    test_codes = ["00700", "00001", "00005", "00388", "01810", "09988"]
    for code in test_codes:
        df = ak.stock_hsgt_individual_em(symbol=code)
        if len(df) > 0:
            print(f"  {code}: GGT eligible (has southbound data, {len(df)} days)")
        else:
            print(f"  {code}: No southbound data")
        time.sleep(0.3)
except Exception as e:
    print(f"  FAILED: {e}")

print("\nDONE")
