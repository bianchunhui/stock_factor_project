"""Supplement outstanding_share for all 300 stocks.

Uses akshare stock_individual_info_em to get total share capital per stock.
Saves to a single lookup file, then we attach it to the panel.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from config import CACHE_DIR, FACTOR_DIR
from universe import Universe


def fetch_all_shares(tickers: list[str]) -> dict[str, float]:
    """Fetch outstanding_share for all tickers via akshare."""
    import akshare as ak
    
    # Try bulk method first: stock_zh_a_spot_em has all A-shares
    try:
        print("  Trying bulk spot data (stock_zh_a_spot_em)...")
        spot = ak.stock_zh_a_spot_em()
        if spot is not None and len(spot) > 0:
            code_col = [c for c in spot.columns if c in ('代码', 'code')][0]
            # Look for total share column
            share_cols = [c for c in spot.columns if '股本' in c or 'share' in c.lower()]
            print(f"  Available columns: {list(spot.columns)}")
            if share_cols:
                print(f"  Share columns found: {share_cols}")
            # Also look for market cap
            mc_cols = [c for c in spot.columns if '市值' in c or 'cap' in c.lower()]
            print(f"  Market cap columns: {mc_cols}")
            
            result = {}
            for _, row in spot.iterrows():
                code = str(row[code_col]).zfill(6)
                if code in tickers:
                    # Try to get total shares
                    for sc in share_cols:
                        try:
                            val = float(row[sc])
                            if val > 0:
                                result[code] = val
                                break
                        except:
                            pass
            if result:
                print(f"  Got shares for {len(result)} stocks from bulk spot")
                return result
    except Exception as e:
        print(f"  Bulk spot failed: {e}")
    
    # Fallback: individual query
    print("  Falling back to individual stock info...")
    result = {}
    for i, code in enumerate(tickers):
        try:
            info = ak.stock_individual_info_em(symbol=code)
            # info has columns: item, value
            for _, row in info.iterrows():
                item = str(row['item'])
                if '总股本' in item or '总股' in item:
                    val = float(row['value'])
                    if val > 0:
                        result[code] = val
                        break
            if (i + 1) % 50 == 0:
                print(f"    Progress: {i+1}/{len(tickers)}, got {len(result)}")
        except Exception as e:
            pass
        time.sleep(0.1)
    
    print(f"  Got shares for {len(result)} stocks from individual queries")
    return result


def fetch_all_market_caps(tickers: list[str]) -> dict[str, float]:
    """Fetch latest market cap for all tickers via akshare spot."""
    import akshare as ak
    
    try:
        print("  Fetching latest market caps from spot...")
        spot = ak.stock_zh_a_spot_em()
        if spot is None or len(spot) == 0:
            return {}
        
        code_col = [c for c in spot.columns if c in ('代码', 'code')][0]
        mc_cols = [c for c in spot.columns if '总市值' in c or '市值' in c]
        print(f"  Market cap columns: {mc_cols}")
        
        if not mc_cols:
            print(f"  Available columns: {list(spot.columns)}")
            return {}
        
        mc_col = mc_cols[0]  # 总市值
        result = {}
        for _, row in spot.iterrows():
            code = str(row[code_col]).zfill(6)
            if code in tickers:
                try:
                    val = float(row[mc_col])
                    if val > 0:
                        result[code] = val
                except:
                    pass
        print(f"  Got market caps for {len(result)} stocks")
        return result
    except Exception as e:
        print(f"  Market cap fetch failed: {e}")
        return {}


def main():
    print("=" * 60)
    print(" Supplement outstanding_share / market_cap for HS300")
    print("=" * 60)
    
    # Get HS300 constituents
    u = Universe(mode="A", index_symbol="000300")
    cons = u.constituents()
    tickers = sorted(cons["ticker"].tolist())
    print(f"  HS300 constituents: {len(tickers)}")
    
    # Try to get shares
    shares = fetch_all_shares(tickers)
    
    # Also get latest market caps
    mcaps = fetch_all_market_caps(tickers)
    
    # Save
    out = []
    for code in tickers:
        out.append({
            "ticker": code,
            "outstanding_share": shares.get(code, np.nan),
            "latest_market_cap": mcaps.get(code, np.nan),
        })
    df = pd.DataFrame(out)
    
    out_path = FACTOR_DIR / "hs300_shares_marketcap.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n  Saved: {out_path}")
    print(f"  Shares coverage: {df['outstanding_share'].notna().sum()}/{len(df)}")
    print(f"  MarketCap coverage: {df['latest_market_cap'].notna().sum()}/{len(df)}")
    
    if df['outstanding_share'].notna().sum() > 0:
        print(f"\n  Sample:")
        print(df.dropna(subset=['outstanding_share']).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
