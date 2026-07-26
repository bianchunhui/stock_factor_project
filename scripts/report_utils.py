"""统一结果输出模块：CSV + HTML，按运行日期写入 report/<YYYY-MM-DD>/。

覆盖 A股(ashare) / 港股(hk) / 美股(us) 三市场。
- save_csv_html(): 人类可读结果（选股清单、净值曲线等）→ 写 UTF-8-sig CSV + 浅色主题热力 HTML
- save_panel():    完整因子面板（大数据量）→ 写 parquet(无损快照) + CSV；超大表(>5w行)不生成 HTML

HTML 约定：浅色主题；数值列按行内 min-max 渐变着色；收益率类列遵循
中国股市"涨红跌绿"约定（正=红、负=绿）。
"""
from __future__ import annotations

import html
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd

# report/ 位于项目根目录（scripts/ 的上级）
REPORT_ROOT = Path(__file__).resolve().parent.parent / "report"

# 中国股市配色：涨=红 跌=绿
UP_RGB = (216, 57, 43)    # 红（涨）
DOWN_RGB = (26, 152, 80)  # 绿（跌）
# 通用数值热力（钢蓝渐变）
HEAT_RGB = (70, 130, 180)

# 面板生成 HTML 的行数上限（避免浏览器卡死）
PANEL_HTML_MAX_ROWS = 50000


def report_dir(run_date=None) -> Path:
    """返回 report/ 目录并确保存在。不再使用日期子目录（避免磁盘堆积）。"""
    d = REPORT_ROOT
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------------------
def _is_return_col(col: str) -> bool:
    c = str(col).lower()
    return any(k in c for k in ("return", "ret", "涨幅", "收益", "涨跌", "pnl", "_nav"))


def _fmt_val(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return str(v)
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return f"{v:.4f}"
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    return html.escape(str(v))


def _cell_style(values: pd.Series) -> list:
    """返回与 values 等长的 inline-style 字符串（数值列热力，其余为空）。"""
    arr = pd.to_numeric(values, errors="coerce")
    if arr.isna().all():
        return [""] * len(values)
    lo, hi = float(arr.min()), float(arr.max())
    rng = (hi - lo) or 1.0
    is_ret = _is_return_col(getattr(values, "name", ""))
    styles = []
    for x in arr.to_numpy():
        if pd.isna(x):
            styles.append("")
            continue
        t = (float(x) - lo) / rng  # 0..1
        if is_ret:
            r, g, b = (UP_RGB if x >= 0 else DOWN_RGB)
            a = 0.16 + 0.55 * (t if x >= 0 else (1 - t))
        else:
            r, g, b = HEAT_RGB
            a = 0.10 + 0.45 * t
        styles.append(f"background:rgba({r},{g},{b},{a:.2f})")
    return styles


def _to_html(df: pd.DataFrame, title: str, subtitle: str) -> str:
    cols = list(df.columns)
    styles_per_col = {
        c: _cell_style(df[c])
        for c in cols
        if pd.api.types.is_numeric_dtype(df[c]) and not df[c].isna().all()
    }
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body_rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        tds = []
        for c in cols:
            style = styles_per_col.get(c, [""] * len(df))[i] if c in styles_per_col else ""
            tds.append(f"<td style='{style}'>{_fmt_val(row[c])}</td>")
        body_rows.append(f"<tr>{''.join(tds)}</tr>")
    n = len(df)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
 body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:24px;color:#222;background:#fff}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#888;font-size:13px;margin-bottom:14px}}
 table{{border-collapse:collapse;font-size:13px;width:auto}}
 th,td{{border:1px solid #e3e3e3;padding:5px 10px;text-align:right;white-space:nowrap}}
 th{{background:#f5f6f8;position:sticky;top:0;font-weight:600}}
 td:first-child,th:first-child{{text-align:left}}
 tr:nth-child(even) td{{background-color:#fafbfc}}
 caption{{caption-side:bottom;color:#999;font-size:12px;margin-top:8px;text-align:left}}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<div class="sub">{html.escape(subtitle)} | 共 {n} 行</div>
<table>
<thead><tr>{head}</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
<caption>生成时间：{now} | 数值热力；涨红跌绿（中国股市约定）</caption>
</body>
</html>"""


def _as_df(obj) -> pd.DataFrame:
    """Series / DataFrame 统一成带 'date' 列的 DataFrame。"""
    if isinstance(obj, pd.Series):
        df = obj.to_frame(name=getattr(obj, "name", "value") or "value")
        df = df.reset_index()
        # 无名列重命名为 date（通常为日期索引）
        if df.columns[0] in ("index", ""):
            df = df.rename(columns={df.columns[0]: "date"})
        return df
    return obj


# ----------------------------------------------------------------------------
# 对外 API
# ----------------------------------------------------------------------------
_TODAY = datetime.now().strftime("%Y%m%d")


def _suffix(name: str) -> str:
    """Append today's date to filename so different-day runs don't overwrite."""
    return f"{name}_{_TODAY}"


def save_csv_html(market: str, name: str, df,
                  title: str = None, subtitle: str = None):
    """写 CSV（UTF-8-sig）+ HTML 到 report/<market>_<name>_YYYYMMDD.(csv|html)。

    文件名自动带当日日期后缀（同一天覆盖自己，不同天互不覆盖）。
    返回 (csv_path, html_path)。
    """
    df = _as_df(df)
    d = report_dir()
    fname = _suffix(name)
    csv_path = d / f"{market}_{fname}.csv"
    html_path = d / f"{market}_{fname}.html"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    title = title or f"{market.upper()} {name}"
    sub = subtitle or f"{market.upper()} 选股/回测结果"
    html_path.write_text(_to_html(df, title, sub), encoding="utf-8")
    print(f"  Saved: {csv_path}")
    print(f"  Saved: {html_path}")
    return csv_path, html_path


def save_panel(market: str, name: str, df):
    """写完整因子面板：parquet(无损快照) + CSV；行数 > 上限不生成 HTML。

    文件名自动带当日日期后缀。
    返回 parquet 路径。
    """
    df = _as_df(df)
    d = report_dir()
    fname = _suffix(name)
    parquet_path = d / f"{market}_{fname}.parquet"
    csv_path = d / f"{market}_{fname}.csv"
    df.to_parquet(parquet_path)
    if len(df) <= PANEL_HTML_MAX_ROWS:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"  Saved: {csv_path}")
    else:
        print(f"  [skip CSV] {market}_{name}: {len(df)} 行超过阈值，仅写 parquet")
    print(f"  Saved: {parquet_path}")
    return parquet_path


if __name__ == "__main__":
    # 自测
    demo = pd.DataFrame({
        "ticker": ["A", "B", "C", "D"],
        "name": ["甲", "乙", "丙", "丁"],
        "weight": [0.25, 0.25, 0.25, 0.25],
        "score": [1.2, -0.5, 0.0, 0.8],
        "fwd_ret": [0.03, -0.02, 0.0, 0.01],
    })
    save_csv_html("ashare", "demo_holdings", demo, title="Demo Holdings")
    save_panel("ashare", "demo_panel", demo)
    print("report_utils self-test OK")
