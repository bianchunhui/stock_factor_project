"""HS300 full factor calculation v2 - with outstanding_share inference.

Flow:
  1. Load price data from cache -> panel
  2. Infer outstanding_share from volume/turnover -> merge to panel
  3. Load benchmark (HS300) -> merge bench_ret
  4. Load financial indicators from cache -> PIT merge
  5. Compute market_cap/PE/PB from close * outstanding_share + financials
  6. Get industry classification -> attach industry column
  7. Compute 24 factors
  8. Cross-section standardize (winsorize + industry/size neutralize + zscore)
  9. Compute forward returns
  10. Save full factor panel to parquet
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from config import FACTOR_DIR, CACHE_DIR
from fetcher import (
    PriceFetcher, FinancialFetcher, IndustryFetcher, SpotFetcher,
)
from fetcher.base import cache_key, to_datetime_safe
from fetcher.store.db import query, save_ref, save_factor_panel, load_universe, init_dbs
from universe import Universe
from factors import ALL_FACTORS
from processor.pit_align import pit_merge
from processor.normalize import (
    standardize_factor, zscore_cross_section, winsorize_cross_section,
)
from processor.align import compute_forward_returns


def load_all_prices_from_cache(start: str = "20210101", market: str = "ashare") -> pd.DataFrame:
    """从 SQLite 读取全部个股日频行情（替代扫描散落 parquet）。

    指数（000300 等）与个股同存 daily_price 表，按 ticker 区分，此处排除指数。
    """
    from fetcher.store.db import query
    print("  Loading prices from SQLite (daily_price)...")
    sql = 'SELECT * FROM daily_price WHERE date >= ? AND ticker != ?'
    panel = query(sql, [str(start), "000300"], market=market)
    if panel.empty:
        return pd.DataFrame()

    panel["ticker"] = panel["ticker"].astype(str).str.zfill(6)
    panel["date"] = pd.to_datetime(panel["date"], format="ISO8601").dt.normalize()
    panel = panel[panel["date"] >= pd.to_datetime(start)]

    # 数值列统一数值化（含迁移遗留的非数值）
    for c in ("open", "high", "low", "close", "volume", "amount",
              "turnover", "pct_chg", "outstanding_share"):
        if c in panel.columns:
            panel[c] = pd.to_numeric(panel[c], errors="coerce")

    panel = panel.drop_duplicates(subset=["ticker", "date"], keep="last")
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)

    print(f"  Prices: {panel['ticker'].nunique()} tickers, {len(panel)} rows")
    print(f"  Date range: {panel['date'].min().date()} ~ {panel['date'].max().date()}")
    return panel


def infer_and_attach_shares(panel: pd.DataFrame) -> pd.DataFrame:
    """Infer outstanding_share from volume/turnover and attach to panel.

    已推断的股本优先从 SQLite (ashare.db.ref_shares) 读取；缺失时从 panel 推断并回写 db。
    """
    print("  Inferring outstanding_share from volume/turnover...")

    # 1) 尝试从 db 读取已存股本
    shares_map: dict = {}
    try:
        shares_df = query(
            "SELECT ticker, outstanding_share FROM ref_shares", market="ashare"
        )
        if not shares_df.empty:
            shares_df["ticker"] = shares_df["ticker"].astype(str).str.zfill(6)
            shares_map = dict(zip(shares_df["ticker"], shares_df["outstanding_share"]))
            print(f"  Loaded shares from db(ref_shares): {len(shares_map)} tickers")
    except Exception as e:
        print(f"  db ref_shares read failed: {e}")

    if not shares_map:
        # Infer from panel
        v = pd.to_numeric(panel['volume'], errors='coerce')
        t = pd.to_numeric(panel['turnover'], errors='coerce')
        ratio = v * 100.0 / t.where(t > 0.001, np.nan)
        ratio = ratio.replace([np.inf, -np.inf], np.nan)
        panel['_tmp_share'] = ratio
        shares_map = panel.groupby('ticker')['_tmp_share'].median().dropna().to_dict()
        panel = panel.drop(columns=['_tmp_share'])
        print(f"  Inferred shares: {len(shares_map)} tickers")
        # 回写 db
        if shares_map:
            df = pd.DataFrame({
                "ticker": [str(k).zfill(6) for k in shares_map.keys()],
                "outstanding_share": list(shares_map.values()),
            })
            save_ref(df, "ref_shares", "ashare", ["ticker"])
            print(f"  Saved shares to db(ref_shares): {len(df)} tickers")

    panel['outstanding_share'] = panel['ticker'].map(shares_map)
    valid = panel['outstanding_share'].notna().sum()
    total = len(panel)
    print(f"  outstanding_share coverage: {valid}/{total} ({valid/total:.1%})")
    return panel


def load_benchmark(start: str = "20210101") -> pd.DataFrame:
    """Load HS300 benchmark index."""
    pf = PriceFetcher()
    bm = pf.get_benchmark_daily("000300", start_date=start)
    if bm.empty:
        return pd.DataFrame()
    bm["date"] = pd.to_datetime(bm["date"], format="ISO8601").dt.normalize()
    bm["bench_ret"] = bm["close"].pct_change()
    return bm[["date", "bench_ret"]].copy()


def load_all_financials(tickers: list[str]) -> pd.DataFrame:
    """Load financial indicators from cache for all tickers."""
    print("  Loading financial data from cache...")
    ff = FinancialFetcher()
    reports = []
    for code in tickers:
        try:
            ind = ff.get_indicators(code, use_cache=True)
            if not ind.empty:
                ind = ind.copy()
                ind["ticker"] = code
                if "announcement_date" not in ind.columns:
                    ind["announcement_date"] = ind["report_date"]
                reports.append(ind)
        except Exception as e:
            print(f"    {code} financial load failed: {e}")

    if not reports:
        return pd.DataFrame()

    rep_df = pd.concat(reports, ignore_index=True)
    rep_df = rep_df.rename(columns={"report_date": "report_period"})
    for c in ["report_period", "announcement_date"]:
        if c in rep_df.columns:
            rep_df[c] = to_datetime_safe(rep_df[c])

    # Fix NaN announcement_date
    if "announcement_date" in rep_df.columns:
        mask = rep_df["announcement_date"].isna()
        if mask.any():
            print(f"  WARN: {mask.sum()} rows announcement_date is null, fallback to report_period")
            rep_df.loc[mask, "announcement_date"] = rep_df.loc[mask, "report_period"]
        before = len(rep_df)
        rep_df = rep_df.dropna(subset=["announcement_date"])
        if len(rep_df) < before:
            print(f"  Dropped {before - len(rep_df)} rows without announcement_date")

    print(f"  Financials: {rep_df['ticker'].nunique()} tickers, {len(rep_df)} reports")
    return rep_df


def get_industry_mapping(tickers: list[str]) -> dict[str, str]:
    """Get industry mapping - try db first, then akshare."""
    ticker_set = set(tickers)
    # Try loading from db
    try:
        df = query("SELECT ticker, industry FROM ref_industry_map", market="ashare")
        if not df.empty:
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)
            mapping = {k: v for k, v in zip(df["ticker"], df["industry"]) if k in ticker_set}
            if mapping:
                print(f"  Loaded industry mapping from db(ref_industry_map): {len(mapping)} tickers")
                return mapping
    except Exception as e:
        print(f"  db ref_industry_map read failed: {e}")

    # Try akshare - use stock_board_industry_cons_em for each board
    try:
        import akshare as ak
        print("  Fetching industry classification via akshare...")

        # Get all industry boards
        boards = ak.stock_board_industry_name_em()
        mapping = {}
        for _, board_row in boards.iterrows():
            board_name = board_row['板块名称']
            try:
                cons = ak.stock_board_industry_cons_em(symbol=board_name)
                code_col = [c for c in cons.columns if '代码' in c][0]
                for code in cons[code_col].astype(str).str.zfill(6):
                    if code in tickers:
                        mapping[code] = board_name
            except Exception:
                pass
            time.sleep(0.1)

        if mapping:
            # Save to db
            df = pd.DataFrame(list(mapping.items()), columns=['ticker', 'industry'])
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)
            save_ref(df, "ref_industry_map", "ashare", ["ticker"])
            print(f"  Got industry mapping: {len(mapping)} tickers, saved to db")
            return mapping
    except Exception as e:
        print(f"  Industry fetch via akshare failed: {e}")

    # Fallback: use SW level1 via baostock or just assign "Other"
    print("  WARN: Using 'Other' for all tickers")
    return {t: "Other" for t in tickers}


def main():
    parser = argparse.ArgumentParser(description="HS300 full factor calculation v2")
    parser.add_argument("--start", default="20210101", help="Start date")
    parser.add_argument("--no-neutralize", action="store_true", help="Disable neutralization")
    args = parser.parse_args()

    t0 = time.time()
    # 预建核心表（含 ref_shares / ref_industry_map 等参考表）
    init_dbs()
    print("=" * 65)
    print(f" HS300 Full Factor Calculation v2 | Start: {args.start}")
    print("=" * 65)

    # Step 1: Load prices
    print("\n[Step 1] Loading price data from cache...")
    panel = load_all_prices_from_cache(start=args.start)
    if panel.empty:
        print("ERROR: No price data")
        return 1

    tickers = sorted(panel['ticker'].unique().tolist())
    print(f"  Ticker count: {len(tickers)}")

    # 限定到沪深300成分股（db: ref_index_weight），确保严格 300 只
    hs300 = load_universe("ashare")
    hs300_set = set(hs300["ticker"].astype(str).str.zfill(6))
    before_n = len(tickers)
    tickers = [t for t in tickers if t in hs300_set]
    print(f"  Restricted to HS300 universe: {len(tickers)}/{before_n} tickers")
    panel = panel[panel["ticker"].isin(tickers)].copy()
    panel = panel.reset_index(drop=True)

    # Step 2: Infer outstanding_share
    print("\n[Step 2] Inferring outstanding_share...")
    panel = infer_and_attach_shares(panel)

    # Step 3: Merge benchmark
    print("\n[Step 3] Merging benchmark (HS300)...")
    bm = load_benchmark(start=args.start)
    if not bm.empty:
        panel = panel.merge(bm, on="date", how="left")
        print(f"  bench_ret: {panel['bench_ret'].notna().sum()} valid")
    else:
        print("  WARN: Benchmark load failed")
        panel["bench_ret"] = np.nan

    # Step 4: PIT merge financials
    print("\n[Step 4] PIT merging financial data...")
    rep_df = load_all_financials(tickers)
    if not rep_df.empty:
        value_cols = [
            "revenue_yoy", "net_profit_yoy", "parent_net_profit_yoy",
            "basic_eps", "roe", "roa", "gross_margin", "debt_ratio", "ocf_ratio",
            "total_assets", "total_liabilities", "parent_net_profit", "net_profit",
            "operating_cash_flow", "total_revenue",
            "owner_equity", "parent_equity",
            # 上一报告期利润：供 EpG/NetG 亏转盈/小分母中性化
            "prev_parent_net_profit", "prev_net_profit",
        ]
        value_cols = [c for c in value_cols if c in rep_df.columns]
        print(f"  Merging fields: {value_cols}")
        panel = pit_merge(panel, rep_df, value_cols)
        print(f"  Panel after PIT merge: {panel.shape}")
    else:
        print("  WARN: No financial data")

    # Step 4.5: Merge fund flow (SQLite 增量; 缺失走网络补齐并落库)
    print("\n[Step 4.5] Merging fund flow (MainFlow/SuperBig 因子源)...")
    try:
        from fetcher.fund_flow import load_fund_flow_panel
        ff_tickers = panel["ticker"].astype(str).str.zfill(6).unique().tolist()
        flow_panel = load_fund_flow_panel(ff_tickers, market="ashare")
        if not flow_panel.empty:
            keep_cols = [c for c in ["date", "ticker", "main_net_inflow",
                                      "super_big_net_inflow", "big_net_inflow",
                                      "mid_net_inflow", "small_net_inflow"]
                         if c in flow_panel.columns]
            flow_panel = flow_panel[keep_cols]
            panel = panel.merge(flow_panel, on=["date", "ticker"], how="left")
            print(f"  Fund flow merged: {flow_panel['ticker'].nunique()} tickers, "
                  f"main_net_inflow 覆盖率 {panel['main_net_inflow'].notna().mean():.1%}")
        else:
            print("  WARN: No fund flow data (MainFlow/SuperBig 将为 NaN)")
    except Exception as e:
        print(f"  Fund flow merge failed: {e}")

    # Step 5: Compute market_cap/PE/PB
    print("\n[Step 5] Computing market_cap/PE/PB...")
    sf = SpotFetcher()
    panel = sf.attach_to_panel(panel, tickers)
    for col in ("market_cap", "pe_ttm", "pb"):
        if col in panel.columns:
            print(f"  {col}: {panel[col].notna().sum()} valid")

    if "market_cap" in panel.columns:
        panel["ln_market_cap"] = np.log(
            pd.to_numeric(panel["market_cap"], errors="coerce").replace(0, np.nan)
        )

    # Step 6: Industry classification
    print("\n[Step 6] Getting industry classification...")
    ind_map = get_industry_mapping(tickers)
    panel["industry"] = panel["ticker"].map(ind_map).fillna("Other")
    n_ind = panel["industry"].nunique()
    print(f"  Industries: {n_ind}, coverage: {panel['industry'].notna().sum()}/{len(panel)}")

    # Step 7: Compute 24 factors
    print(f"\n[Step 7] Computing {len(ALL_FACTORS)} factors...")
    for factor_cls in ALL_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        raw = factor.compute(panel)
        if isinstance(raw, np.ndarray):
            raw = pd.Series(raw, index=panel.index)
        panel[f"{factor.name}_raw"] = raw
        valid = raw.notna().sum()
        pct = valid / len(raw) if len(raw) > 0 else 0
        print(f"  {factor.name:8s} cat={factor.category:10s} dir={factor.direction:+d}  "
              f"valid={valid:6d}/{len(raw)} ({pct:.1%})")

    # Step 8: Standardize
    do_neut = not args.no_neutralize
    neut_str = "neutralize + " if do_neut else ""
    print(f"\n[Step 8] Standardize (winsorize + {neut_str}zscore)...")
    for factor_cls in ALL_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        raw_col = f"{factor.name}_raw"
        if raw_col not in panel.columns:
            continue

        if do_neut and "industry" in panel.columns and "ln_market_cap" in panel.columns:
            try:
                std = standardize_factor(
                    panel, raw_col,
                    do_winsorize=True,
                    do_neutralize=True,
                    method="zscore",
                )
                panel[f"{factor.name}_z"] = std
                continue
            except Exception as e:
                print(f"  WARN: {factor.name} neutralize failed: {e}")

        w = winsorize_cross_section(panel, raw_col, n_sigma=3.0)
        panel[f"{factor.name}_z"] = zscore_cross_section(w, panel["date"], min_count=3)

    z_cols = [c for c in panel.columns if c.endswith("_z") and not c.endswith("_dz")]
    print(f"  z-score columns: {len(z_cols)}")

    # Step 9: Forward returns
    print("\n[Step 9] Computing forward returns...")
    panel = compute_forward_returns(panel, periods=[1, 5, 10, 21])
    for p in [1, 5, 10, 21]:
        col = f"forward_{p}d_return"
        if col in panel.columns:
            print(f"  {col}: {panel[col].notna().sum()} valid")

    # Step 10: Save factor panel to SQLite (ashare.db.factor_panel)
    n_saved = save_factor_panel(panel, "ashare")
    elapsed = time.time() - t0
    print(f"\n[Done] Panel saved to SQLite (ashare.db.factor_panel): {n_saved} rows")
    print(f"  Shape: {panel.shape}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Columns: {len(panel.columns)}")
    print(f"  Factor raw cols: {len([c for c in panel.columns if c.endswith('_raw')])}")
    print(f"  Factor z cols: {len(z_cols)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
