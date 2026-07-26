"""Fetch outstanding shares via baostock for all HS300 stocks.

baostock query_stock_basic returns: code, code_name, IPOdate, outDate, type, status
But for shares we need query_stock_industry or use the financial reports.

Actually, baostock's balance sheet has 'totalShare' field.
Alternative: use the already-downloaded financial data which has total_assets.
We can approximate market_cap = close * total_shares.

Another approach: baostock query_history_k_data_plus with 'turn' field.
From turn rate and volume we can infer outstanding shares:
  outstanding_share = volume / (turn / 100)

This is the simplest approach since we already have volume and turn data.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from config import CACHE_DIR, FACTOR_DIR


def infer_outstanding_shares_from_cache() -> dict[str, float]:
    """Infer outstanding shares from volume / turnover ratio.
    
    turnover = volume / outstanding_share * 100
    => outstanding_share = volume / (turnover / 100)
    
    Use median across all dates for stability.
    """
    print("  Inferring outstanding shares from volume/turnover...")
    cache_dir = CACHE_DIR
    files = list(cache_dir.glob('*.parquet'))
    
    shares = {}
    for f in files:
        try:
            df = pd.read_parquet(f)
            if 'close' not in df.columns or 'ticker' not in df.columns:
                continue
            if 'volume' not in df.columns or 'turnover' not in df.columns:
                continue
            
            for ticker, g in df.groupby('ticker'):
                t = pd.to_numeric(g['turnover'], errors='coerce')
                v = pd.to_numeric(g['volume'], errors='coerce')
                # outstanding = volume / (turn/100) = volume * 100 / turn
                ratio = v * 100.0 / t.where(t > 0.001, np.nan)
                ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
                if len(ratio) > 10:
                    # Use median for robustness
                    shares[str(ticker)] = float(ratio.median())
        except Exception:
            continue
    
    print(f"  Inferred shares for {len(shares)} tickers")
    return shares


def main():
    print("=" * 60)
    print(" Infer Outstanding Shares from Volume/Turnover")
    print("=" * 60)
    
    shares = infer_outstanding_shares_from_cache()
    
    if not shares:
        print("  ERROR: Could not infer any shares")
        return 1
    
    # Save
    df = pd.DataFrame([
        {"ticker": k, "outstanding_share": v} for k, v in shares.items()
    ])
    df = df.sort_values("ticker").reset_index(drop=True)
    
    out_path = FACTOR_DIR / "hs300_outstanding_shares.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n  Saved: {out_path}")
    print(f"  Coverage: {len(df)} tickers")
    
    # Stats
    print(f"\n  Share count stats:")
    print(df['outstanding_share'].describe().to_string())
    
    # Sample
    print(f"\n  Sample (first 10):")
    print(df.head(10).to_string(index=False))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
