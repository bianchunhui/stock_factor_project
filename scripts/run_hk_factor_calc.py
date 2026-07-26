"""港股 88 只标的因子计算脚本。

与 A 股 run_factor_calc.py 并行，独立运行。
数据源: data/hk_panel_price.parquet, data/hk_panel_financial.parquet, data/hk_panel_hsgt.parquet

因子清单 (16 个):
  价值 (4): EP, BP, SP, CFP
  成长 (3): RevG, NetG, EpG (holder_profit_yoy)
  质量 (5): ROE, ROA, GPM, Lev, CFO
  动量 (2): Mom12m, Rev1m
  规模/波动 (2): LnMV, Vol60
  南向资金流 (2): SBHolding (南向持股比例), SBFlow (南向持股比例20日变化率)

注意:
  - 港股无 turnover 列 → 不计算 Turn 因子
  - 港股无 bench_ret → 不计算 Beta 因子（用 HSI proxy 可后补）
  - 币种: 港币，与 A 股人民币独立
  - 行业: 使用 universe 文件中的行业分类（中文），后续映射英文
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from factors.base import FactorBase
from factors.value import EPFactor, BPFactor, SPFactor, CFPFactor
from factors.growth import RevGFactor, NetGFactor, EpGFactor
from factors.quality import ROEFactor, ROAFactor, GPMFactor, LevFactor, CFOFactor
from factors.momentum import Mom12mFactor, Rev1mFactor
from factors.technical import LnMVFactor, Vol60Factor
from processor.normalize import (
    standardize_factor, zscore_cross_section, winsorize_cross_section,
)
from processor.align import compute_forward_returns
from fetcher.hk_financial_map import resolve_hk_financial_map
from fetcher.store.db import query, save_factor_panel, load_universe

# ================================================================
# 1. 南向资金流因子（港股独有）
# ================================================================
class SBHoldingFactor(FactorBase):
    """南向持股比例因子。

    holding_pct 越高 → 南向资金越看好。
    direction=+1 (越高越好)
    """
    name = "SBHolding"
    category = "southbound"
    direction = +1
    need_pit = False

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "holding_pct" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        return pd.to_numeric(panel["holding_pct"], errors="coerce")

    def required_columns(self):
        return ["holding_pct"]


class SBFlowFactor(FactorBase):
    """南向资金流入因子。

    = holding_pct 的 20 日变化率 (当前 vs 20日前)
    > 0 表示南向近期加仓，< 0 表示减仓。
    direction=+1
    """
    name = "SBFlow"
    category = "southbound"
    direction = +1
    need_pit = False

    def __init__(self, window: int = 20):
        self.window = window

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        if "holding_pct" not in panel.columns:
            return pd.Series(np.nan, index=panel.index)
        h = pd.to_numeric(panel["holding_pct"], errors="coerce")
        # 20 日变化率 = 当前 / shift(20) - 1
        past = h.groupby(panel["ticker"]).shift(self.window)
        flow = h / past.where(past.abs() > 1e-6, np.nan) - 1.0
        return flow

    def required_columns(self):
        return ["holding_pct"]


SOUTHBOUND_FACTORS = [SBHoldingFactor, SBFlowFactor]

# 全部港股因子 (16 个)
HK_FACTORS = (
    [EPFactor, BPFactor, SPFactor, CFPFactor]      # value 4
    + [RevGFactor, EpGFactor]                        # growth 2 (NetG 数据不全跳过)
    + [ROEFactor, ROAFactor, GPMFactor, LevFactor, CFOFactor]  # quality 5
    + [Mom12mFactor, Rev1mFactor]                    # momentum 2
    + [LnMVFactor, Vol60Factor]                      # size/vol 2
    + SOUTHBOUND_FACTORS                              # southbound 2
)

# ================================================================
# 2. 数据加载（全部走 hk.db）
# ================================================================
def load_hk_prices() -> pd.DataFrame:
    """从 SQLite(hk.db.daily_price) 加载港股行情 panel，排除指数。"""
    print("  Loading HK prices from hk.db (daily_price)...")
    p = query(
        "SELECT * FROM daily_price WHERE ticker != ? AND ticker != ?",
        ["HSI", "HSI_PROXY_02800"], market="hk",
    )
    if p.empty:
        return p
    p["date"] = pd.to_datetime(p["date"], format="ISO8601").dt.normalize()
    p["ticker"] = p["ticker"].astype(str)
    for c in ("open", "high", "low", "close", "volume", "amount"):
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  Prices: {p['ticker'].nunique()} tickers, {len(p)} rows")
    print(f"  Date range: {p['date'].min().date()} ~ {p['date'].max().date()}")
    return p


def load_hk_benchmark() -> pd.DataFrame:
    """加载 HSI 基准（hk.db.daily_price ticker='HSI'）。缺失则 bench_ret 置 NaN。"""
    print("  Loading HSI benchmark from hk.db (daily_price ticker='HSI')...")
    bm = query("SELECT * FROM daily_price WHERE ticker=?", ["HSI"], market="hk")
    if bm.empty:
        print("  WARN: no HSI benchmark in db, bench_ret will be NaN")
        return pd.DataFrame()
    bm["date"] = pd.to_datetime(bm["date"], format="ISO8601").dt.normalize()
    bm["bench_ret"] = pd.to_numeric(bm["close"], errors="coerce").pct_change()
    print(f"  HSI benchmark: {bm['date'].min().date()} ~ {bm['date'].max().date()}")
    return bm[["date", "bench_ret"]].copy()


def load_hk_financials() -> pd.DataFrame:
    """从 SQLite(hk.db.financial_indicator) 加载港股财务指标。

    列名映射统一走 fetcher.hk_financial_map（兼容 EM 原始列名与 download
    改名后的可读名）。同时产出 prev_parent_net_profit 供成长因子符号中性化。
    """
    print("  Loading HK financials from hk.db (financial_indicator)...")
    f = query("SELECT * FROM financial_indicator", market="hk")
    if f.empty:
        print("  WARN: no financial data in db")
        return f
    f["ticker"] = f["ticker"].astype(str)
    f["report_date"] = pd.to_datetime(f["report_date"], errors="coerce")

    # 重命名: 走中央映射（兼容 EM 原始列名与可读名）
    rename_map = resolve_hk_financial_map(f.columns)
    f = f.rename(columns=rename_map)
    print(f"  HK financial field map applied: {rename_map}")

    # 构建 announcement_date (港股年报通常在报告期后 3 个月披露)
    if "announcement_date" not in f.columns:
        f["announcement_date"] = f["report_date"] + pd.Timedelta(days=90)

    # report_period for PIT merge
    f = f.rename(columns={"report_date": "report_period"})

    # 上一报告期归母利润（per ticker 按报告期 shift），供成长因子符号中性化
    if "parent_net_profit" in f.columns:
        f = f.sort_values(["ticker", "report_period"]).reset_index(drop=True)
        f["prev_parent_net_profit"] = (
            pd.to_numeric(f["parent_net_profit"], errors="coerce")
            .groupby(f["ticker"]).shift(1)
        )

    print(f"  Financials: {f['ticker'].nunique()} tickers, {len(f)} reports")
    return f


def load_southbound() -> pd.DataFrame:
    """从 SQLite(hk.db.ref_hsgt) 加载南向持股，清理乱码列名。"""
    print("  Loading southbound holdings from hk.db (ref_hsgt)...")
    h = query("SELECT * FROM ref_hsgt", market="hk")
    if h.empty:
        print("  WARN: no southbound data in db")
        return h
    h["date"] = pd.to_datetime(h["date"], format="ISO8601").dt.normalize()
    h["ticker"] = h["ticker"].astype(str)

    # 删除乱码列（迁移遗留）
    drop_cols = [c for c in h.columns if "鍙" in c or "变化" in c]
    h = h.drop(columns=drop_cols, errors="ignore")

    for c in ("holding_shares", "holding_value", "holding_pct", "close_price", "change_pct"):
        if c in h.columns:
            h[c] = pd.to_numeric(h[c], errors="coerce")

    h = h.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  Southbound: {h['ticker'].nunique()} tickers, {len(h)} rows")
    return h


def load_industry() -> dict:
    """从 hk.db.ref_universe(sector 列) 加载行业分类，回退 CSV。"""
    try:
        uni = load_universe("hk")
        if uni is not None and not uni.empty:
            uni["ticker"] = uni["ticker"].astype(str)
            mapping = dict(zip(uni["ticker"], uni["sector"]))
            print(f"  Industry mapping: {len(mapping)} tickers from db(ref_universe)")
            return mapping
    except Exception as e:
        print(f"  db ref_universe load failed: {e}")

    # 回退 CSV
    df = pd.read_csv("data/hsi_hkgt_universe_20260709.csv", dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str)
    ind_col = None
    for c in ["industry", "board", "sector", "东财行业", "行业"]:
        if c in df.columns:
            ind_col = c
            break
    if ind_col is None:
        print(f"  WARN: No industry column found. Columns: {list(df.columns)}")
        return {}
    mapping = dict(zip(df["ticker"], df[ind_col]))
    print(f"  Industry mapping: {len(mapping)} tickers from CSV, {df[ind_col].nunique()} industries")
    return mapping


# ================================================================
# 3. 港股市值/估值计算
# ================================================================
def compute_hk_market_cap(panel: pd.DataFrame, fin: pd.DataFrame) -> pd.DataFrame:
    """计算港股市值和估值指标。

    market_cap = close * outstanding_share
    outstanding_share 从财务数据中获取 (total_revenue / basic_eps 近似，或直接用 holder_profit / eps)

    PE_TTM = close / eps_ttm
    PB = close / bps
    PS = close / (total_revenue / outstanding_share)  -- 需要股本
    """
    print("  Computing market_cap and valuation ratios...")

    # 从财务数据估算 outstanding_share
    # outstanding_share ≈ holder_profit / basic_eps (归母净利润 / 每股收益)
    fin_latest = fin.copy()
    fin_latest = fin_latest.sort_values(["ticker", "report_period"])
    # 取每只股票最新的财务数据
    fin_latest = fin_latest.groupby("ticker").last().reset_index()

    shares_map = {}
    for _, row in fin_latest.iterrows():
        t = row["ticker"]
        hp = pd.to_numeric(row.get("parent_net_profit"), errors="coerce")
        eps = pd.to_numeric(row.get("basic_eps"), errors="coerce")
        if pd.notna(hp) and pd.notna(eps) and abs(eps) > 1e-6:
            shares_map[t] = hp / eps

    print(f"  Inferred outstanding_share: {len(shares_map)}/{len(fin_latest)} tickers")

    # merge outstanding_share to panel
    panel["outstanding_share"] = panel["ticker"].map(shares_map)

    # market_cap (港币, 单位: 股 * 港币)
    panel["market_cap"] = panel["close"] * panel["outstanding_share"]

    # PE_TTM = close / eps_ttm (需要 PIT merge 后才有 eps_ttm)
    # 这里先标记，PIT merge 后再算
    panel["circ_market_cap"] = panel["market_cap"]  # 港股没有流通/限售区分

    # ln_market_cap
    mc = pd.to_numeric(panel["market_cap"], errors="coerce")
    panel["ln_market_cap"] = np.log(mc.where(mc > 0, np.nan))

    valid_mc = panel["market_cap"].notna().sum()
    print(f"  market_cap valid: {valid_mc}/{len(panel)} ({valid_mc/len(panel):.1%})")

    return panel


def compute_valuation_ratios(panel: pd.DataFrame) -> pd.DataFrame:
    """计算 PE_TTM, PB, PS（在 PIT merge 之后调用）。"""
    # PE_TTM = close / eps_ttm
    if "eps_ttm" in panel.columns:
        eps = pd.to_numeric(panel["eps_ttm"], errors="coerce")
        close = pd.to_numeric(panel["close"], errors="coerce")
        panel["pe_ttm"] = close / eps.where(eps.abs() > 1e-6, np.nan)

    # PB = close / bps
    if "bps" in panel.columns:
        bps = pd.to_numeric(panel["bps"], errors="coerce")
        close = pd.to_numeric(panel["close"], errors="coerce")
        panel["pb"] = close / bps.where(bps.abs() > 1e-6, np.nan)

    # PS = market_cap / total_revenue (需要 revenue PIT merge 后)
    if "total_revenue" in panel.columns and "market_cap" in panel.columns:
        rev = pd.to_numeric(panel["total_revenue"], errors="coerce")
        mc = pd.to_numeric(panel["market_cap"], errors="coerce")
        panel["ps_ttm"] = mc / rev.where(rev.abs() > 1e-6, np.nan)

    for col in ("pe_ttm", "pb", "ps_ttm"):
        if col in panel.columns:
            v = panel[col].notna().sum()
            print(f"  {col}: {v} valid ({v/len(panel):.1%})")

    return panel


# ================================================================
# 4. 主流程
# ================================================================
def main():
    t0 = time.time()
    print("=" * 65)
    print(" HK Stock Factor Calculation (88 HSI∩HKGT)")
    print("=" * 65)

    # Step 1: Load prices
    print("\n[Step 1] Loading price data...")
    panel = load_hk_prices()
    tickers = sorted(panel["ticker"].unique().tolist())
    print(f"  Ticker count: {len(tickers)}")

    # Step 2: Load benchmark
    print("\n[Step 2] Loading HSI benchmark...")
    bm = load_hk_benchmark()
    if not bm.empty:
        panel = panel.merge(bm, on="date", how="left")
        print(f"  bench_ret: {panel['bench_ret'].notna().sum()} valid")
    else:
        panel["bench_ret"] = np.nan
        print("  WARN: No benchmark, Beta factor will be NaN")

    # Step 3: Load financials
    print("\n[Step 3] Loading financial data...")
    fin = load_hk_financials()
    print(f"  Financial fields: {[c for c in fin.columns if c.islower() or c == 'ticker']}")

    # Step 4: Compute market_cap
    print("\n[Step 4] Computing market_cap...")
    panel = compute_hk_market_cap(panel, fin)

    # Step 5: PIT merge financials
    print("\n[Step 5] PIT merging financial data...")
    if not fin.empty:
        from processor.pit_align import pit_merge
        value_cols = [
            "revenue_yoy", "parent_net_profit_yoy", "gross_margin",
            "roe", "roa", "debt_ratio", "ocf_ratio",
            "eps_ttm", "bps", "basic_eps",
            "total_revenue", "parent_net_profit",
            # 上一报告期归母利润：供 EpG 亏转盈/小分母中性化
            "prev_parent_net_profit",
        ]
        value_cols = [c for c in value_cols if c in fin.columns]
        print(f"  Merging fields: {value_cols}")
        panel = pit_merge(panel, fin, value_cols)
        print(f"  Panel after PIT merge: {panel.shape}")

    # Step 6: Compute valuation ratios (needs PIT merged eps_ttm, bps, total_revenue)
    print("\n[Step 6] Computing valuation ratios (PE/PB/PS)...")
    panel = compute_valuation_ratios(panel)

    # Step 7: Merge southbound holdings
    print("\n[Step 7] Merging southbound holdings...")
    sb = load_southbound()
    if not sb.empty:
        # 合并到 panel (left join on date + ticker)
        sb_keep = sb[["date", "ticker", "holding_pct", "holding_shares", "holding_value"]].copy()
        panel = panel.merge(sb_keep, on=["date", "ticker"], how="left")
        valid_sb = panel["holding_pct"].notna().sum()
        print(f"  holding_pct: {valid_sb} valid ({valid_sb/len(panel):.1%})")
    else:
        panel["holding_pct"] = np.nan
        panel["holding_shares"] = np.nan
        panel["holding_value"] = np.nan

    # Step 8: Industry classification
    print("\n[Step 8] Industry classification...")
    ind_map = load_industry()
    panel["industry"] = panel["ticker"].map(ind_map).fillna("Other")
    n_ind = panel["industry"].nunique()
    print(f"  Industries: {n_ind}, coverage: {panel['industry'].notna().sum()}/{len(panel)}")

    # Step 9: Compute factors
    print(f"\n[Step 9] Computing {len(HK_FACTORS)} factors...")
    for factor_cls in HK_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        raw = factor.compute(panel)
        if isinstance(raw, np.ndarray):
            raw = pd.Series(raw, index=panel.index)
        panel[f"{factor.name}_raw"] = raw
        valid = raw.notna().sum()
        pct = valid / len(raw) if len(raw) > 0 else 0
        print(f"  {factor.name:12s} cat={factor.category:12s} dir={factor.direction:+d}  "
              f"valid={valid:6d}/{len(raw)} ({pct:.1%})")

    # Step 10: Standardize (winsorize + neutralize + zscore)
    print(f"\n[Step 10] Standardize (winsorize + neutralize + zscore)...")
    for factor_cls in HK_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        raw_col = f"{factor.name}_raw"
        if raw_col not in panel.columns:
            continue

        try:
            if "industry" in panel.columns and "ln_market_cap" in panel.columns:
                std = standardize_factor(
                    panel, raw_col,
                    do_winsorize=True,
                    do_neutralize=True,
                    method="zscore",
                )
                panel[f"{factor.name}_z"] = std
            else:
                w = winsorize_cross_section(panel, raw_col, n_sigma=3.0)
                panel[f"{factor.name}_z"] = zscore_cross_section(w, panel["date"], min_count=3)
        except Exception as e:
            print(f"  WARN: {factor.name} standardize failed: {e}")
            w = winsorize_cross_section(panel, raw_col, n_sigma=3.0)
            panel[f"{factor.name}_z"] = zscore_cross_section(w, panel["date"], min_count=3)

    z_cols = [c for c in panel.columns if c.endswith("_z")]
    print(f"  z-score columns: {len(z_cols)}")

    # Step 11: Forward returns
    print("\n[Step 11] Computing forward returns...")
    panel = compute_forward_returns(panel, periods=[1, 5, 10, 21])
    for p in [1, 5, 10, 21]:
        col = f"forward_{p}d_return"
        if col in panel.columns:
            print(f"  {col}: {panel[col].notna().sum()} valid")

    # Step 12: Save to SQLite (hk.db.factor_panel)
    n_saved = save_factor_panel(panel, "hk")
    elapsed = time.time() - t0
    print(f"\n[Done] Panel saved to SQLite (hk.db.factor_panel): {n_saved} rows")
    print(f"  Shape: {panel.shape}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Columns: {len(panel.columns)}")
    print(f"  Factor raw cols: {len([c for c in panel.columns if c.endswith('_raw')])}")
    print(f"  Factor z cols: {len(z_cols)}")

    # Print factor summary
    print(f"\n{'='*65}")
    print(" Factor Summary")
    print(f"{'='*65}")
    print(f"{'Factor':<14} {'Category':<14} {'Dir':>4} {'Raw Valid':>10} {'Z Valid':>10}")
    print("-" * 56)
    for factor_cls in HK_FACTORS:
        factor = factor_cls() if isinstance(factor_cls, type) else factor_cls
        raw_col = f"{factor.name}_raw"
        z_col = f"{factor.name}_z"
        raw_v = panel[raw_col].notna().sum() if raw_col in panel.columns else 0
        z_v = panel[z_col].notna().sum() if z_col in panel.columns else 0
        print(f"{factor.name:<14} {factor.category:<14} {factor.direction:>+4} {raw_v:>10} {z_v:>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
