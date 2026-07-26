"""多因子选股 Dashboard — Streamlit 可视化页面。

三 Tab: A股(沪深300) / 港股(恒生指数∩港股通) / 美股(道指30)

每 Tab 两块区域:
  1. 数据覆盖区间 + 补数(含因子计算)
  2. 执行选股(IC加权) + 结果展示
"""

from __future__ import annotations

import subprocess
import sys
import time
import glob
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.store.db import get_coverage

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
PYTHON = "C:/Users/chunh/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "report"

MARKETS = {
    "A股 (沪深300)": {
        "key": "ashare",
        "download_script": "scripts/_download_a_share.py",
        "factor_script": "scripts/run_factor_calc.py",
        "select_script": "scripts/select_stocks.py",
        "select_args": [
            "--from-panel", str(PROJECT_ROOT / "data" / "factors" / "_streamlit_fallback.parquet"),
            "--top-pct", "10",
        ],
        "result_glob": "ashare_holdings",
        "top_n": 30,
        "ticker_count": 300,
        "display_tables": ["daily_price", "factor_panel", "ref_index_weight"],
    },
    "港股 (恒生指数)": {
        "key": "hk",
        "download_script": "scripts/download_hk_data.py",
        "factor_script": "scripts/run_hk_factor_calc.py",
        "select_script": "scripts/build_composite_hk.py",
        "select_args": [],
        "result_glob": "hk_top20_equal_weight",
        "top_n": 20,
        "ticker_count": 88,
        "display_tables": ["daily_price", "financial_indicator", "factor_panel", "ref_universe"],
    },
    "美股 (道琼斯30)": {
        "key": "us",
        "download_script": "scripts/download_us_data.py",
        "factor_script": "scripts/run_us_factor_calc.py",
        "select_script": "scripts/build_composite_us.py",
        "select_args": [],
        "result_glob": "us_top10_equal_weight",
        "top_n": 10,
        "ticker_count": 30,
        "display_tables": ["daily_price", "valuation", "factor_panel", "ref_universe"],
    },
}

TABLE_LABELS = {
    "daily_price": "日行情",
    "valuation": "估值(PE/PB/PCF)",
    "financial_indicator": "财务指标",
    "financial_income": "利润表",
    "factor_panel": "因子面板",
    "ref_universe": "股票池",
    "ref_index_weight": "沪深300成分",
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _run_script(script_rel: str, extra_args: list | None = None) -> tuple[int, str, str]:
    """Run a Python script in the project root, return (exit_code, stdout, stderr)."""
    script_path = str(PROJECT_ROOT / script_rel)
    args = [PYTHON, script_path] + (extra_args or [])
    try:
        result = subprocess.run(
            args, capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=600,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT (600s)"
    except Exception as e:
        return -1, "", str(e)


def _run_script_stream(
    script_rel: str, log_ph, extra_args: list | None = None
) -> tuple[int, str, str]:
    """Run a Python script, streaming stdout line-by-line to a Streamlit placeholder.

    Returns (exit_code, full_stdout, full_stderr) after completion.
    """
    script_path = str(PROJECT_ROOT / script_rel)
    args = [PYTHON, script_path] + (extra_args or [])
    all_out = []
    all_err = []
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(PROJECT_ROOT), bufsize=1,
        )
        # Read stdout line by line, update log placeholder
        for line in iter(proc.stdout.readline, ""):
            all_out.append(line)
            log_ph.code("".join(all_out[-60:]), language="text")

        proc.wait(timeout=600)
        stderr_text = proc.stderr.read()
        if stderr_text:
            all_err.append(stderr_text)
        return proc.returncode, "".join(all_out), stderr_text
    except subprocess.TimeoutExpired:
        proc.kill()
        return -1, "".join(all_out), "TIMEOUT (600s)"
    except Exception as e:
        return -1, "".join(all_out), str(e)


def _download_ashare(start_date: str, end_date: str) -> tuple[bool, str]:
    """A-share incremental download using fetcher classes directly.

    Each ticker is downloaded one-by-one (fetcher handles cache + rate limiting).
    Most tickers skip API call if data already exists in db for the range.
    Financials allow partial failures (some API endpoints may be blocked).
    """
    from fetcher import PriceFetcher, FinancialFetcher
    from fetcher.store.db import query

    msgs = []

    # universe
    uni = query("SELECT ticker FROM ref_index_weight", [], market="ashare")
    if uni.empty:
        return False, "ERROR: ref_index_weight is empty"
    tickers = sorted(uni["ticker"].astype(str).str.zfill(6).tolist())
    msgs.append(f"Universe: {len(tickers)} tickers")

    # 1. Prices (one by one, fetcher skips cached via `use_cache=True`)
    pf = PriceFetcher()
    p_ok = 0
    p_fail = 0
    total = len(tickers)
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
                msgs.append(f"  [price] {t}: {type(e).__name__}")
        if i % 10 == 0 or i == total:
            print(f"  [price] {i}/{total} ({p_ok} ok, {p_fail} fail)", flush=True)
    msgs.append(f"Price: {p_ok} with data, {p_fail} no-data/fail")

    # 1b. Index (000300 CSI 300 benchmark, force re-download to cover new dates)
    try:
        pf.get_a_index_daily("000300", start_date, end_date, use_cache=False)
        msgs.append("Index (000300) download OK")
    except Exception as e:
        msgs.append(f"Index (000300) FAILED: {type(e).__name__}: {e}")

    # 2. Financials (one by one, partial failures allowed)
    ff = FinancialFetcher()
    fin_ops = [
        ("profit_sheet", lambda t: ff.get_profit_sheet(t)),
        ("balance_sheet", lambda t: ff.get_balance_sheet(t)),
        ("indicators", lambda t: ff.get_indicators(t)),
    ]
    for label, fn in fin_ops:
        ok = 0
        fail = 0
        for i, t in enumerate(tickers, 1):
            try:
                fn(t)
                ok += 1
            except Exception:
                fail += 1
            if i % 30 == 0 or i == total:
                print(f"  [{label}] {i}/{total} ({ok} ok, {fail} fail)", flush=True)
        msgs.append(f"{label}: {ok} OK, {fail} failed")

    return True, "\n".join(msgs)


def _last_coverage_date(cov: dict, table: str) -> str | None:
    """Extract the last date from coverage dict for a table."""
    if table not in cov:
        return None
    info = cov[table]
    for k in ("max_date", "max_report_date", "max_report_period"):
        if k in info:
            return str(info[k])
    return None


def _calc_default_dates(cov: dict, market_cfg: dict) -> tuple[str, str]:
    """Calculate default start/end dates for incremental download.

    Start = MAX(last_data_date across all display tables) + 1, capped to today.
    End = today.

    Example: data ends at 2026-07-09 → start = 2026-07-10.
             if start > today, clamp to today (data already up to date).
    """
    today = datetime.now().date()

    # Find the MAX (most recent) data date across all display tables
    last_date = None
    for tbl in market_cfg["display_tables"]:
        d = _last_coverage_date(cov, tbl)
        if not d:
            continue
        try:
            ld = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if last_date is None or ld > last_date:
            last_date = ld

    if last_date is None:
        # No data at all - default to a year ago
        start = today - timedelta(days=365)
    else:
        start = last_date + timedelta(days=1)
        if start > today:
            start = today

    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def _load_latest_result(market_cfg: dict) -> pd.DataFrame | None:
    """Load the latest stock selection result CSV from report/ (by date suffix)."""
    # Match files like ashare_holdings_YYYYMMDD.csv
    base = market_cfg["result_glob"]
    pattern = str(REPORT_DIR / f"{base}_*.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None
    try:
        df = pd.read_csv(files[0], encoding="utf-8-sig")
        return df
    except Exception:
        return None


def _find_latest_html(market_cfg: dict) -> str | None:
    """Find latest HTML report for a market."""
    base = market_cfg["result_glob"]
    pattern = str(REPORT_DIR / f"{base}_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


# ---------------------------------------------------------------------------
# Streamlit 页面
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="多因子选股 Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("📊 多因子选股 Dashboard")
st.caption("A股(沪深300) · 港股(恒指∩港股通) · 美股(道指30)")

tabs = st.tabs(list(MARKETS.keys()))

for tab, (market_name, market_cfg) in zip(tabs, MARKETS.items()):
    with tab:
        # ===================================================================
        # 区域1: 数据覆盖 + 补数(含因子计算)
        # ===================================================================
        st.subheader("📡 数据状态 & 补数")

        # ---- 刷新覆盖区间 ----
        if f"cov_{market_cfg['key']}" not in st.session_state:
            st.session_state[f"cov_{market_cfg['key']}"] = get_coverage(market_cfg["key"])

        cov = st.session_state[f"cov_{market_cfg['key']}"]

        col_refresh, _ = st.columns([1, 5])
        with col_refresh:
            if st.button("🔄 刷新状态", key=f"refresh_{market_cfg['key']}"):
                st.session_state[f"cov_{market_cfg['key']}"] = get_coverage(market_cfg["key"])
                st.rerun()

        # 展示覆盖表
        if cov:
            rows = []
            for tbl in market_cfg["display_tables"]:
                if tbl not in cov:
                    continue
                info = cov[tbl]
                label = TABLE_LABELS.get(tbl, tbl)
                date_range = ""
                for k in ("min_date", "min_report_date"):
                    if k in info:
                        date_range = f"{info[k]} ~ {info.get(k.replace('min','max'), '?')}"
                        break
                rows.append({
                    "表": label,
                    "行数": info.get("rows", "-"),
                    "标的数": info.get("tickers", "-"),
                    "区间": date_range,
                })
            if rows:
                st.dataframe(
                    pd.DataFrame(rows),
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.warning("无数据，请先运行迁移脚本填充数据库")

        # ---- 增量补数 + 因子计算 ----
        st.markdown("---")
        default_start, default_end = _calc_default_dates(cov, market_cfg)

        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            start_date = st.text_input("开始日期", value=default_start, key=f"start_{market_cfg['key']}")
        with c2:
            end_date = st.text_input("结束日期", value=default_end, key=f"end_{market_cfg['key']}")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)  # align button
            run_btn = st.button(
                "⚡ 补数 + 因子计算",
                key=f"download_{market_cfg['key']}",
                type="primary",
                use_container_width=True,
            )

        if run_btn:
            status_placeholder = st.empty()
            log_placeholder = st.empty()

            log_lines = []

            # Step A: Download
            dl_script = market_cfg["download_script"]
            if dl_script:
                status_placeholder.info(
                    f"⏳ 下载 {market_name} [{start_date}~{end_date}]..."
                    f" ({market_cfg['ticker_count']}只约3-10分钟, 请等待)"
                )
                ec, out, err = _run_script(
                    dl_script, extra_args=[start_date, end_date],
                )
                if err:
                    log_lines.append(f"STDERR:\n{err[-1000:]}")
                log_lines.append(f"--- download ({market_cfg['key']}) ---")
                log_lines.append(out[-2000:] if len(out) > 2000 else out)
                if ec != 0:
                    status_placeholder.error(f"下载失败 (exit={ec})")
                    log_placeholder.code("\n".join(log_lines), language="text")
                    st.stop()
                status_placeholder.success("下载完成 ✓")
                log_placeholder.code(out[-6000:] if len(out)>6000 else out, language="text")
            else:
                log_lines.append(f"--- download skipped (no script for {market_cfg['key']}) ---")

            # Step A.5: 资金流增量（westock CLI 日更）
            # 与行情一致：透传同一区间 [start_date, end_date]，脚本内部逐日循环。
            # 点「补数」即把资金流增量落库，单按钮即可补齐。
            # 非致命：失败仅告警，不阻断后续因子计算（沿用已有资金流）。
            status_placeholder.info("⏳ 资金流增量 (westock CLI) ...")
            ec, out, err = _run_script(
                "scripts/westock_fetcher.py", extra_args=[start_date, end_date],
            )
            if err:
                log_lines.append(f"STDERR:\n{err[-1000:]}")
            log_lines.append("--- fund flow incremental (westock CLI) ---")
            log_lines.append(out[-2000:] if len(out) > 2000 else out)
            if ec != 0:
                log_lines.append("⚠️ 资金流增量失败，已跳过（因子计算继续，沿用已有资金流）")
                status_placeholder.warning("资金流增量失败，已跳过（继续因子计算）")
            else:
                status_placeholder.success("资金流增量完成 ✓")
            log_placeholder.code("\n".join(log_lines), language="text")

            # Step B: Factor calc
            status_placeholder.info("⏳ 因子计算 ...")
            ec, out, err = _run_script(market_cfg["factor_script"])
            if err:
                log_lines.append(f"STDERR:\n{err[-1000:]}")
            log_lines.append(f"--- factor calc ({market_cfg['key']}) ---")
            log_lines.append(out[-3000:] if len(out) > 3000 else out)
            if ec != 0:
                status_placeholder.error(f"因子计算失败 (exit={ec})")
                log_placeholder.code("\n".join(log_lines), language="text")
                st.stop()
            status_placeholder.success("因子计算完成 ✓")

            log_placeholder.code("\n".join(log_lines), language="text")
            # refresh coverage
            st.session_state[f"cov_{market_cfg['key']}"] = get_coverage(market_cfg["key"])
            st.rerun()

        # ===================================================================
        # 区域2: 执行选股
        # ===================================================================
        st.markdown("---")
        st.subheader("🎯 执行选股")

        c1, c2 = st.columns([2, 4])
        with c1:
            select_btn = st.button(
                "🚀 执行选股 (IC加权)",
                key=f"select_{market_cfg['key']}",
                type="primary",
                use_container_width=True,
            )

        if select_btn:
            sel_status = st.empty()
            sel_log = st.empty()

            sel_status.info("⏳ IC加权选股 ...")
            ec, out, err = _run_script(
                market_cfg["select_script"],
                extra_args=market_cfg["select_args"],
            )
            st.session_state.task_label = None
            log_text = f"--- select ({market_cfg['key']}) ---\n{out[-3000:] if len(out)>3000 else out}"
            if err:
                log_text += f"\nSTDERR:\n{err[-500:]}"
            if ec != 0:
                sel_status.error(f"选股失败 (exit={ec})")
                sel_log.code(log_text, language="text")
            else:
                sel_status.success("选股完成 ✓")
                sel_log.code(log_text, language="text")
                # Force re-load
                st.session_state.pop(f"result_{market_cfg['key']}", None)
                st.rerun()

        # ---- 展示最近选股结果 ----
        result_key = f"result_{market_cfg['key']}"
        if result_key not in st.session_state:
            st.session_state[result_key] = _load_latest_result(market_cfg)

        result_df = st.session_state[result_key]

        if result_df is not None and not result_df.empty:
            st.markdown("### 最新选股持仓")

            # 美化展示
            show_cols = [c for c in ["ticker", "name", "weight", "composite_score",
                                      "industry", "sector", "composite_eq",
                                      "composite_ic"] if c in result_df.columns]
            display = result_df[show_cols].copy()

            # 数值格式化
            for c in display.columns:
                if "weight" in c.lower():
                    display[c] = display[c].apply(
                        lambda x: f"{x*100:.1f}%" if pd.notna(x) else ""
                    )
                elif "score" in c.lower() or "composite" in c.lower():
                    display[c] = display[c].apply(
                        lambda x: f"{x:.2f}" if pd.notna(x) else ""
                    )

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ticker": st.column_config.TextColumn("代码", width="small"),
                    "name": st.column_config.TextColumn("名称", width="medium"),
                    "weight": st.column_config.TextColumn("权重", width="small"),
                    "composite_score": st.column_config.TextColumn("综合得分", width="small"),
                    "composite_eq": st.column_config.TextColumn("等权得分"),
                    "composite_ic": st.column_config.TextColumn("IC加权得分"),
                    "industry": st.column_config.TextColumn("行业"),
                    "sector": st.column_config.TextColumn("行业"),
                },
            )

            # 快捷链接
            html_path = _find_latest_html(market_cfg)
            if html_path:
                st.caption(f"📄 完整报告: `{html_path}`")
        else:
            st.info("暂无选股结果。点击上方'执行选股'按钮开始。")
