"""港股因子评估 - 极致内存优化版。

只保留必要列，逐因子计算后立即释放内存。
"""
import sys, time, warnings, gc
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from scipy import stats
warnings.filterwarnings("ignore", category=Warning)

HK_FACTOR_NAMES = [
    "EP", "BP", "SP", "RevG", "EpG",
    "ROE", "ROA", "GPM", "Lev", "CFO",
    "Mom12m", "Rev1m", "LnMV", "Vol60",
    "SBHolding", "SBFlow",
]

def main():
    t0 = time.time()
    print("=" * 70)
    print(" HK Factor Evaluation (Ultra Memory-Optimized)")
    print("=" * 70)

    # Load only needed columns
    print("Loading panel (slim)...", end=" ", flush=True)
    cols_needed = {"date", "ticker"}
    for f in HK_FACTOR_NAMES:
        cols_needed.add(f"{f}_z")
    cols_needed.add("forward_21d_return")
    cols_needed.add("forward_5d_return")
    
    import pyarrow.parquet as pq
    pf = pq.ParquetFile("data/hk_full_factor_panel.parquet")
    all_cols = pf.schema.names
    read_cols = [c for c in all_cols if c in cols_needed]
    panel = pd.read_parquet("data/hk_full_factor_panel.parquet", columns=read_cols)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    print(f"{panel.shape}")

    # Pre-group by date for efficiency
    dates = sorted(panel["date"].unique())
    print(f"  {len(dates)} dates, {panel['ticker'].nunique()} tickers")

    # ===== IC/IR for 5d and 21d =====
    print(f"\n{'='*70}")
    print(f" IC/IR Evaluation")
    print(f"{'='*70}")
    print(f"{'Factor':<12s} {'IC_5d':>8} {'IR_5d':>8} {'IC_21d':>8} {'IR_21d':>8} {'t_21d':>7} {'Win%':>6} {'N':>5}")
    print("-" * 65)

    summary_rows = []
    for fname in HK_FACTOR_NAMES:
        z_col = f"{fname}_z"
        if z_col not in panel.columns:
            continue
        
        for ret_period, ret_col in [(5, "forward_5d_return"), (21, "forward_21d_return")]:
            if ret_col not in panel.columns:
                continue
            
            ic_list = []
            for d in dates:
                g = panel.loc[panel["date"] == d, [z_col, ret_col]].dropna()
                if len(g) < 5:
                    continue
                x = g[z_col].values
                y = g[ret_col].values
                if np.std(x) < 1e-12 or np.std(y) < 1e-12:
                    continue
                r, _ = stats.spearmanr(x, y)
                if np.isfinite(r):
                    ic_list.append(r)
            
            if not ic_list:
                continue
            
            ic_arr = np.array(ic_list)
            n = len(ic_arr)
            mean = ic_arr.mean()
            std = ic_arr.std()
            ir = mean / std if std > 1e-12 else np.nan
            t_stat = ir * np.sqrt(n) if np.isfinite(ir) else np.nan
            pos_rate = (ic_arr > 0).mean()
            
            if ret_period == 5:
                ic5, ir5, pos5 = mean, ir, pos_rate
            else:
                ic21, ir21, t21, pos21, n21 = mean, ir, t_stat, pos_rate, n

        row = {
            "factor": fname,
            "ic_5d": ic5, "ir_5d": ir5,
            "ic_21d": ic21, "ir_21d": ir21, "t_21d": t21,
            "pos_21d": pos21, "n_ic": n21,
        }
        summary_rows.append(row)
        print(f"{fname:<12s} {ic5:>+8.4f} {ir5:>+8.3f} {ic21:>+8.4f} {ir21:>+8.3f} {t21:>7.2f} {pos21:>6.1%} {n21:>5}")

    summary = pd.DataFrame(summary_rows).sort_values("ir_21d", ascending=False).reset_index(drop=True)

    # ===== Quantile Portfolio (21d only, slim) =====
    print(f"\n{'='*70}")
    print(f" Quantile Portfolio (5 groups, 21d)")
    print(f"{'='*70}")
    print(f"{'Factor':<12s} {'Q1':>8} {'Q2':>8} {'Q3':>8} {'Q4':>8} {'Q5':>8} {'LS':>8} {'LS_IR':>8} {'Mono':>6}")
    print("-" * 80)

    q_results = {}
    for fname in HK_FACTOR_NAMES:
        z_col = f"{fname}_z"
        if z_col not in panel.columns or "forward_21d_return" not in panel.columns:
            continue

        q_means = {1: [], 2: [], 3: [], 4: [], 5: []}
        ls_list = []
        
        for d in dates:
            g = panel.loc[panel["date"] == d, [z_col, "forward_21d_return"]].dropna()
            if len(g) < 5:
                continue
            try:
                ranks = g[z_col].rank(method="first")
                q = pd.qcut(ranks, 5, labels=False) + 1
            except ValueError:
                continue
            for qi in range(1, 6):
                mask = q == qi
                if mask.sum() > 0:
                    q_means[qi].append(g.loc[mask, "forward_21d_return"].mean())
            ls_list.append(g.loc[q == 5, "forward_21d_return"].mean() - g.loc[q == 1, "forward_21d_return"].mean())

        if not ls_list:
            continue

        q_avg = {qi: np.mean(v) if v else np.nan for qi, v in q_means.items()}
        ls_arr = np.array([x for x in ls_list if np.isfinite(x)])
        ls_mean = ls_arr.mean() if len(ls_arr) > 0 else np.nan
        ls_std = ls_arr.std() if len(ls_arr) > 0 else np.nan
        ls_ir = ls_mean / ls_std if ls_std and ls_std > 1e-12 else np.nan
        
        # monotonicity
        qs = [q_avg.get(i, np.nan) for i in range(1, 6)]
        valid = [(i+1, m) for i, m in enumerate(qs) if np.isfinite(m)]
        if len(valid) >= 2:
            xs = np.array([v[0] for v in valid])
            ys = np.array([v[1] for v in valid])
            mono = float(np.corrcoef(xs, ys)[0, 1])
        else:
            mono = np.nan

        q_results[fname] = {"ls_mean": ls_mean, "ls_ir": ls_ir, "mono": mono, **{f"q{i}": q_avg[i] for i in range(1,6)}}
        
        print(f"{fname:<12s} {q_avg[1]:>+8.4f} {q_avg[2]:>+8.4f} {q_avg[3]:>+8.4f} {q_avg[4]:>+8.4f} {q_avg[5]:>+8.4f} {ls_mean:>+8.4f} {ls_ir:>+8.3f} {mono:>+6.2f}")
        
        gc.collect()

    # ===== Factor Correlation =====
    print(f"\n{'='*70}")
    print(" Factor Correlation (Spearman)")
    print(f"{'='*70}")
    z_cols = [f"{f}_z" for f in HK_FACTOR_NAMES if f"{f}_z" in panel.columns]
    corr = panel[z_cols].corr(method="spearman")
    names = [c.replace("_z", "") for c in z_cols]
    print(f"\n  {'':>12s}", end="")
    for n in names:
        print(f"{n:>8s}", end="")
    print()
    for i, n in enumerate(names):
        print(f"  {n:<12s}", end="")
        for j in range(len(names)):
            print(f"{corr.iloc[i, j]:>8.2f}", end="")
        print()

    # ===== Final Ranking =====
    print(f"\n{'='*70}")
    print(" FINAL RANKING (by 21d IR)")
    print(f"{'='*70}")
    print(f"\n{'Factor':<12s} {'IC_5d':>8} {'IR_5d':>8} {'IC_21d':>8} {'IR_21d':>8} {'t_21d':>7} {'Win%':>6} {'LS':>8} {'LS_IR':>8} {'Mono':>6}")
    print("-" * 85)
    for _, row in summary.iterrows():
        fname = row["factor"]
        q = q_results.get(fname, {})
        print(f"{fname:<12s} {row['ic_5d']:>+8.4f} {row['ir_5d']:>+8.3f} {row['ic_21d']:>+8.4f} {row['ir_21d']:>+8.3f} {row['t_21d']:>7.2f} {row['pos_21d']:>6.1%} {q.get('ls_mean', np.nan):>+8.4f} {q.get('ls_ir', np.nan):>+8.3f} {q.get('mono', np.nan):>+6.2f}")
    print("-" * 85)

    # Save
    out_dir = Path("data/factors")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_dir / "hk_ic_summary.csv", index=False, encoding="utf-8-sig")
    q_rows = [{"factor": f, **r} for f, r in q_results.items()]
    if q_rows:
        pd.DataFrame(q_rows).to_csv(out_dir / "hk_quantile_summary.csv", index=False, encoding="utf-8-sig")
    if not corr.empty:
        corr.to_csv(out_dir / "hk_factor_correlation.csv", encoding="utf-8-sig")
    print(f"\nSaved: hk_ic_summary.csv, hk_quantile_summary.csv, hk_factor_correlation.csv")
    print(f"Elapsed: {time.time()-t0:.1f}s")
    print("=" * 70)

if __name__ == "__main__":
    main()
