"""美股因子计算脚本（道指 30 成分股）。

数据源：data/us_panel_price.parquet, data/us_panel_valuation.parquet
        （由 scripts/download_us_data.py 生成）

因子清单（7 个，均基于可得数据，无需 PIT 财报对齐）：
  价值 (3): EP(1/PE_TTM), BP(1/PB), CFP(1/PCF)
  规模 (1): LnMV(对数总市值，负向)
  动量 (2): Mom12m(12m动量剔除近1m), Rev1m(1m反转，负向)
  波动 (1): Vol60(60日波动率，负向)

说明：
  - 估值列(pe_ttm/pb/pcf/market_cap)来自百度股市通时间序列，已按交易日向后填充对齐
    （仅用历史已知值，无前视偏差）
  - 美股财务报表接口（stock_us_fundamental）在当前 akshare 版本不可用，故
    成长(RevG/NetG/EpG)与质量(ROE/ROA/GPM/Lev/CFO)类因子暂缺；若后续 akshare
    提供美股财报，可在此补充 PIT 合并并加入对应因子
  - 行业中性化使用 universe 的 sector 列

产出：data/us_full_factor_panel.parquet
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from factors.base import FactorBase
from factors.value import EPFactor, BPFactor, CFPFactor
from factors.technical import LnMVFactor, Vol60Factor
from factors.momentum import Mom12mFactor, Rev1mFactor
from processor.normalize import (
    standardize_factor, zscore_cross_section, winsorize_cross_section,
)
from processor.align import compute_forward_returns
from fetcher.store.db import query, save_factor_panel, load_universe

UNIVERSE = "data/dj_universe_20260710.csv"  # 回退行业/名称用

US_FACTORS = [
    EPFactor, BPFactor, CFPFactor,     # value 3
    LnMVFactor,                         # size 1
    Mom12mFactor, Rev1mFactor,          # momentum 2
    Vol60Factor,                        # volatility 1
]


def load_price() -> pd.DataFrame:
    print("  Loading US prices from us.db (daily_price)...")
    p = query("SELECT * FROM daily_price", market="us")
    if p.empty:
        return p
    p["date"] = pd.to_datetime(p["date"], format="ISO8601").dt.normalize()
    p["ticker"] = p["ticker"].astype(str).str.upper()
    for c in ("open", "high", "low", "close", "volume", "amount"):
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  Prices: {p['ticker'].nunique()} tickers, {len(p)} rows")
    print(f"  Date range: {p['date'].min().date()} ~ {p['date'].max().date()}")
    return p


def load_valuation() -> pd.DataFrame:
    print("  Loading US valuation from us.db (valuation)...")
    f = query("SELECT * FROM valuation", market="us")
    if f.empty:
        return f
    f["date"] = pd.to_datetime(f["date"], format="ISO8601").dt.normalize()
    f["ticker"] = f["ticker"].astype(str).str.upper()
    for c in ("market_cap", "pe_ttm", "pb", "pcf"):
        if c in f.columns:
            f[c] = pd.to_numeric(f[c], errors="coerce")
    f = f.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  Valuation: {f['ticker'].nunique()} tickers, {len(f)} rows")
    return f


def merge_valuation(panel: pd.DataFrame, val: pd.DataFrame) -> pd.DataFrame:
    """把估值时间序列对齐到价格面板（向后填充，按 ticker，无前视）。"""
    print("  Merging valuation onto price panel (ffill per ticker)...")
    # 估值按 [date, ticker] 精确合并
    merged = panel.merge(val, on=["date", "ticker"], how="left")
    # 逐 ticker 向后填充（只用历史已知估值，避免前视）
    ffill_cols = [c for c in ("market_cap", "pe_ttm", "pb", "pcf") if c in merged.columns]
    merged[ffill_cols] = (
        merged.groupby("ticker")[ffill_cols].ffill()
    )
    for c in ffill_cols:
        valid = merged[c].notna().sum()
        print(f"    {c}: {valid}/{len(merged)} ({valid/len(merged):.1%})")
    return merged


def load_industry() -> dict:
    try:
        uni = load_universe("us")
        if uni is not None and not uni.empty:
            uni["ticker"] = uni["ticker"].astype(str).str.upper()
            mapping = dict(zip(uni["ticker"], uni["sector"]))
            print(f"  Industry mapping: {len(mapping)} tickers from db(ref_universe)")
            return mapping
    except Exception as e:
        print(f"  db ref_universe load failed: {e}")
    # 回退 CSV
    df = pd.read_csv(UNIVERSE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.upper()
    ind_col = "sector" if "sector" in df.columns else (
        "industry" if "industry" in df.columns else None
    )
    if ind_col is None:
        return {}
    return dict(zip(df["ticker"], df[ind_col]))


def main():
    t0 = time.time()
    print("=" * 65)
    print(" US Stock Factor Calculation (Dow Jones 30)")
    print("=" * 65)

    panel = load_price()
    val = load_valuation()
    panel = merge_valuation(panel, val)

    # ln_market_cap 供行业/规模中性化使用
    mc = pd.to_numeric(panel.get("market_cap"), errors="coerce")
    panel["ln_market_cap"] = np.log(mc.where(mc > 0, np.nan))

    # 行业
    ind_map = load_industry()
    panel["industry"] = panel["ticker"].map(ind_map).fillna("Other")
    print(f"\n  Industries: {panel['industry'].nunique()}, "
          f"coverage {panel['industry'].notna().sum()}/{len(panel)}")

    # 计算因子
    print(f"\n[Step] Computing {len(US_FACTORS)} factors...")
    for fc in US_FACTORS:
        factor = fc() if isinstance(fc, type) else fc
        raw = factor.compute(panel)
        if isinstance(raw, np.ndarray):
            raw = pd.Series(raw, index=panel.index)
        panel[f"{factor.name}_raw"] = raw
        valid = raw.notna().sum()
        print(f"  {factor.name:8s} cat={factor.category:10s} dir={factor.direction:+d} "
              f"valid={valid:6d}/{len(raw)} ({valid/len(raw):.1%})")

    # 标准化
    print(f"\n[Step] Standardize (winsorize + neutralize + zscore)...")
    for fc in US_FACTORS:
        factor = fc() if isinstance(fc, type) else fc
        raw_col = f"{factor.name}_raw"
        if raw_col not in panel.columns:
            continue
        try:
            std = standardize_factor(
                panel, raw_col, do_winsorize=True, do_neutralize=True, method="zscore",
            )
            panel[f"{factor.name}_z"] = std
        except Exception as e:
            print(f"  WARN: {factor.name} standardize failed: {e}")
            w = winsorize_cross_section(panel, raw_col, n_sigma=3.0)
            panel[f"{factor.name}_z"] = zscore_cross_section(w, panel["date"], min_count=3)

    z_cols = [c for c in panel.columns if c.endswith("_z")]
    print(f"  z-score columns: {len(z_cols)}")

    # 前向收益
    print(f"\n[Step] Computing forward returns...")
    panel = compute_forward_returns(panel, periods=[1, 5, 10, 21])
    for p in [1, 5, 10, 21]:
        col = f"forward_{p}d_return"
        if col in panel.columns:
            print(f"  {col}: {panel[col].notna().sum()} valid")

    n_saved = save_factor_panel(panel, "us")
    print(f"\n[Done] Panel saved to SQLite (us.db.factor_panel): {n_saved} rows")
    print(f"  Shape: {panel.shape}  Elapsed: {time.time()-t0:.1f}s")

    # 因子摘要
    print(f"\n{'='*60}\n Factor Summary\n{'='*60}")
    print(f"{'Factor':<10}{'Category':<12}{'Dir':>5}{'Raw':>10}{'Z':>10}")
    print("-" * 47)
    for fc in US_FACTORS:
        factor = fc() if isinstance(fc, type) else fc
        rc, zc = f"{factor.name}_raw", f"{factor.name}_z"
        rv = panel[rc].notna().sum() if rc in panel.columns else 0
        zv = panel[zc].notna().sum() if zc in panel.columns else 0
        print(f"{factor.name:<10}{factor.category:<12}{factor.direction:>+5}{rv:>10}{zv:>10}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
