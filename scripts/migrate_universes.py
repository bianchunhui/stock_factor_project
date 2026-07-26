"""将港股/美股选股池 universe CSV 迁入 SQLite（ref_universe 表）。

- 港股: data/hsi_hkgt_universe_20260709.csv (ticker,name,industry)
        -> hk.db.ref_universe (market='HK', sector=industry 列)
- 美股: data/dj_universe_20260710.csv       (ticker,name,sector)
        -> us.db.ref_universe (market='US', sector=sector 列)

A 股 300 成分股已在 ref_index_weight，无需此脚本处理。

写入方式：upsert (market, ticker) 主键去重，可重复运行。
离线脚本，不联网。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.store.db import save_ref, init_dbs

ROOT = Path(__file__).resolve().parent.parent
HK_UNIVERSE = ROOT / "data" / "hsi_hkgt_universe_20260709.csv"
US_UNIVERSE = ROOT / "data" / "dj_universe_20260710.csv"


def load_hk() -> pd.DataFrame:
    if not HK_UNIVERSE.exists():
        print(f"[WARN] 港股 universe 缺失: {HK_UNIVERSE}")
        return pd.DataFrame()
    df = pd.read_csv(HK_UNIVERSE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(5)
    # 行业列：优先 industry，回退 board/sector
    sector_col = None
    for c in ("industry", "board", "sector", "行业", "东财行业"):
        if c in df.columns:
            sector_col = c
            break
    if sector_col is None:
        print(f"[WARN] 港股 universe 无行业列，默认 Other。列: {list(df.columns)}")
        df["sector"] = "Other"
    else:
        df["sector"] = df[sector_col].astype(str)
    out = pd.DataFrame({
        "market": "HK",
        "ticker": df["ticker"],
        "name": df["name"].astype(str) if "name" in df.columns else "",
        "sector": df["sector"],
    })
    return out


def load_us() -> pd.DataFrame:
    if not US_UNIVERSE.exists():
        print(f"[WARN] 美股 universe 缺失: {US_UNIVERSE}")
        return pd.DataFrame()
    df = pd.read_csv(US_UNIVERSE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.upper()
    out = pd.DataFrame({
        "market": "US",
        "ticker": df["ticker"],
        "name": df["name"].astype(str) if "name" in df.columns else "",
        "sector": df["sector"].astype(str) if "sector" in df.columns else "Other",
    })
    return out


def main():
    # 预建核心表（含 ref_universe）
    init_dbs()

    hk = load_hk()
    us = load_us()

    if not hk.empty:
        n = save_ref(hk, "ref_universe", "hk", ["market", "ticker"])
        print(f"[OK] hk.db.ref_universe: 写入 {n} 行 (HK universe)")
    else:
        print("[SKIP] HK universe 无数据")

    if not us.empty:
        n = save_ref(us, "ref_universe", "us", ["market", "ticker"])
        print(f"[OK] us.db.ref_universe: 写入 {n} 行 (US universe)")
    else:
        print("[SKIP] US universe 无数据")

    print("[DONE] migrate_universes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
