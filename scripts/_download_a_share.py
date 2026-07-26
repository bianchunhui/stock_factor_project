"""A-share (HS300) incremental download - standalone script for Streamlit streaming.

Usage: python scripts/_download_a_share.py <start_date> <end_date>
Example: python scripts/_download_a_share.py 2026-07-10 2026-07-17

Downloads price data (300 stocks + 000300 index) and financial data,
saving to ashare.db via existing fetcher paths.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime


def main():
    if len(sys.argv) < 3:
        print("Usage: python _download_a_share.py <start_date> <end_date>")
        sys.exit(1)

    start_date = sys.argv[1]
    end_date = sys.argv[2]

    from fetcher import PriceFetcher, FinancialFetcher
    from fetcher.store.db import query

    uni = query("SELECT ticker FROM ref_index_weight", [], market="ashare")
    if uni.empty:
        print("ERROR: ref_index_weight is empty")
        sys.exit(1)

    tickers = sorted(uni["ticker"].astype(str).str.zfill(6).tolist())
    total = len(tickers)
    print(f"Universe: {total} tickers")
    print(f"Range: {start_date} ~ {end_date}")
    print()

    # 1. Prices
    pf = PriceFetcher()
    p_ok = 0
    p_fail = 0
    t0 = datetime.now()
    for i, t in enumerate(tickers, 1):
        try:
            df = pf.get_a_share_daily(t, start_date, end_date, use_cache=True)
            if df is not None and not df.empty:
                p_ok += 1
            else:
                p_fail += 1
        except Exception as e:
            p_fail += 1
            if p_fail <= 5:
                print(f"  [price] {t}: {type(e).__name__}")
        if i % 10 == 0 or i == total:
            elapsed = (datetime.now() - t0).total_seconds()
            eta = elapsed / i * (total - i) if i < total else 0
            print(f"  [price] {i}/{total} (ok={p_ok}, fail={p_fail})  "
                  f"elapsed={elapsed:.0f}s  ETA={eta:.0f}s")
    print(f"Price done: {p_ok} ok, {p_fail} fail\n")

    # 1b. Index
    try:
        pf.get_a_index_daily("000300", start_date, end_date, use_cache=False)
        print("Index (000300) OK")
    except Exception as e:
        print(f"Index (000300) FAILED: {type(e).__name__}: {e}")

    # 2. Financials
    ff = FinancialFetcher()
    fin_ops = [
        ("profit_sheet", lambda t: ff.get_profit_sheet(t)),
        ("balance_sheet", lambda t: ff.get_balance_sheet(t)),
        ("indicators", lambda t: ff.get_indicators(t)),
    ]
    for label, fn in fin_ops:
        ok = 0
        fail = 0
        t0 = datetime.now()
        for i, t in enumerate(tickers, 1):
            try:
                fn(t)
                ok += 1
            except Exception:
                fail += 1
            if i % 30 == 0 or i == total:
                elapsed = (datetime.now() - t0).total_seconds()
                eta = elapsed / i * (total - i) if i < total else 0
                print(f"  [{label}] {i}/{total} (ok={ok}, fail={fail})  "
                      f"elapsed={elapsed:.0f}s  ETA={eta:.0f}s")
        print(f"{label}: {ok} OK, {fail} failed")

    print("\n[DONE] A-share download complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
