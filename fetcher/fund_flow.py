"""个股资金流数据抓取器（情绪因子源，替代 2024-08 起停更的北向资金）。

⚠️ 北向资金于 2024-08-16 起停更，HSGT/Flow/FUp 因子在 2024.8 后失效。
    本模块改用「个股资金流（主力/超大单/大单/中单/小单净流入）」作为现代情绪因子源。

数据源（2026-07 重构，彻底弃用东财个股资金流接口）：
  - 历史回补：腾讯自选股 MCP ``data_fund_flow(start, end)`` 批量回填空历史，落 SQLite。
              由 AI/脚本触发，调用 ``upsert_fund_flow_records`` 写入。
  - 日更增量：vendored westock CLI（``tools/westock_cli/scripts/index.js asfund``）
              逐日 append 当日快照，走类似行情的增量更新方式。

单位：westock 字段均为「元」（与存量 db 一致），无需换算。
字段映射（westock 原始名 -> db 列）：
  MainNetFlow   -> main_net_inflow          （主力净流入，元）
  JumboNetFlow  -> super_big_net_inflow     （超大单净流入）
  BlockNetFlow  -> big_net_inflow           （大单净流入）
  MidNetFlow    -> mid_net_inflow           （中单净流入）
  SmallNetFlow  -> small_net_inflow         （小单净流入）
  EndDate       -> date
  ClosePrice    -> close
  code/symbol   -> ticker（去 sz/sh/bj 前缀为 6 位）
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .base import BaseFetcher, cache_key

logger = logging.getLogger(__name__)


# ============================================================
# 路径 / 运行时解析
# ============================================================
def _resolve_node() -> str:
    """优先用受管 node，回退 PATH 上的 node。"""
    for cand in (
        Path(r"C:/Users/chunh/.workbuddy/binaries/node/versions/22.22.2/node.exe"),
        Path(r"C:/Users/chunh/.workbuddy/binaries/node/versions/22.22.2/node.cmd"),
    ):
        if cand.exists():
            return str(cand)
    return "node"


NODE = _resolve_node()
CLI_JS = Path(__file__).resolve().parent.parent / "tools" / "westock_cli" / "scripts" / "index.js"

# westock 原始字段名 -> db 列名
WESTOCK_FIELD_MAP = {
    "MainNetFlow": "main_net_inflow",
    "JumboNetFlow": "super_big_net_inflow",
    "BlockNetFlow": "big_net_inflow",
    "MidNetFlow": "mid_net_inflow",
    "SmallNetFlow": "small_net_inflow",
    "MainInflowCircRate": "main_inflow_circ_rate",
    "MainNetFlow5D": "main_net_flow_5d",
    "MainNetFlow10D": "main_net_flow_10d",
    "MainNetFlow20D": "main_net_flow_20d",
    "ClosePrice": "close",
}

# db fund_flow 表的标准列（用于回补时裁剪，其余列由 upsert 自动加列兜底）
_FUND_FLOW_COLS = [
    "ticker", "date", "main_net_inflow", "super_big_net_inflow", "big_net_inflow",
    "mid_net_inflow", "small_net_inflow", "main_net_pct", "super_big_net_pct",
    "big_net_pct", "mid_net_pct", "small_net_pct", "close", "pct_chg",
    "main_inflow_circ_rate", "main_net_flow_5d", "main_net_flow_10d", "main_net_flow_20d",
]


# ============================================================
# 代码 / 市场前缀
# ============================================================
def detect_market_prefix(code: str) -> str:
    """根据 6 位股票代码判断交易所前缀 (sh/sz/bj)。"""
    code = str(code).strip().lower().replace("sh", "").replace("sz", "").replace("bj", "")
    if code.startswith(("60", "68", "11", "13")):
        return "sh"
    if code.startswith(("83", "87", "920", "43", "88")):
        return "bj"
    return "sz"


def to_westock_symbol(code: str) -> str:
    """6 位代码 -> westock 带前缀符号（sz300308 / sh600000）。"""
    code = str(code).strip()
    if code[:2] in ("sh", "sz", "bj"):
        return code.lower()
    return f"{detect_market_prefix(code)}{code.zfill(6)}"


# ============================================================
# westock 数据标准化
# ============================================================
def _is_separator(line: str) -> bool:
    """判断 Markdown 表格分隔行（| --- | --- |）。"""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return len(cells) > 1 and all(re.fullmatch(r":?-+:?", c) for c in cells)


def parse_westock_markdown(text: str) -> pd.DataFrame:
    """解析 westock CLI 输出的 Markdown 表格 -> db 形 DataFrame。

    兼容单只（无前缀行）与批量（首行 ``[Batch] 状态: ...`` 摘要）两种输出。
    返回空 DataFrame 表示无数据（如 CLI 返回「数据为空」）。
    """
    table_lines = [ln.rstrip() for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(table_lines) < 2:
        return pd.DataFrame()
    # 找分隔行：分隔行之前是表头，之后是数据
    sep_idx = None
    for i, ln in enumerate(table_lines):
        if _is_separator(ln):
            sep_idx = i
            break
    if sep_idx is None or sep_idx == 0:
        return pd.DataFrame()
    header = [c.strip() for c in table_lines[sep_idx - 1].strip("|").split("|")]
    rows = []
    for ln in table_lines[sep_idx + 1:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    if not rows:
        return pd.DataFrame()
    raw = pd.DataFrame(rows)
    return normalize_westock_raw(raw)


def normalize_westock_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """把含 westock 原始字段（MainNetFlow.../EndDate/code|symbol）的 DataFrame
    标准化为 db 形（ticker/date/main_net_inflow/...）。"""
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    sym_col = "symbol" if "symbol" in raw.columns else ("code" if "code" in raw.columns else None)
    if sym_col is None:
        logger.warning("westock 记录缺 code/symbol 列，无法定位 ticker")
        return pd.DataFrame()

    out = pd.DataFrame()
    out["ticker"] = raw[sym_col].astype(str).str.replace(r"^(sz|sh|bj)", "", regex=True)

    if "EndDate" in raw.columns:
        out["date"] = pd.to_datetime(raw["EndDate"], errors="coerce").dt.strftime("%Y-%m-%d")
    elif "date" in raw.columns:
        out["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    for src, dst in WESTOCK_FIELD_MAP.items():
        if src in raw.columns:
            out[dst] = pd.to_numeric(raw[src], errors="coerce")

    # 丢弃全 NaN 的行
    out = out.dropna(subset=["ticker", "date"], how="any")
    return out.reset_index(drop=True)


def build_fund_flow_records(items: List[dict]) -> pd.DataFrame:
    """MCP ``data_fund_flow`` 返回的 list[dict] -> db 形 DataFrame。

    MCP 原始记录字段与 CLI 同源（含 code/EndDate/MainNetFlow/...），
    直接喂给 ``normalize_westock_raw`` 统一标准化。
    """
    if not items:
        return pd.DataFrame()
    return normalize_westock_raw(pd.DataFrame(items))


# ============================================================
# CLI 调用
# ============================================================
def _run_cli(codes: List[str], date: Optional[str] = None) -> pd.DataFrame:
    """调用 vendored westock CLI ``asfund`` 取资金流快照。

    codes: 6 位代码列表（自动加市场前缀）；date: ``YYYY-MM-DD`` 取历史单日，
    留空取当日快照。返回 db 形 DataFrame（可能为空）。
    """
    if not CLI_JS.exists():
        logger.error("westock CLI 不存在: %s", CLI_JS)
        return pd.DataFrame()
    syms = ",".join(to_westock_symbol(c) for c in codes)
    cmd = [NODE, str(CLI_JS), "asfund", syms]
    if date:
        cmd += ["--date", date]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    except Exception as e:
        logger.warning("westock CLI 调用异常: %s", e)
        return pd.DataFrame()
    if res.returncode != 0:
        logger.warning("westock CLI 非零退出 [%s]: %s", " ".join(cmd[2:4]), res.stderr[:300])
        return pd.DataFrame()
    return parse_westock_markdown(res.stdout)


def fetch_fund_flow_via_cli(codes: List[str], date: Optional[str] = None) -> pd.DataFrame:
    """模块级便捷封装：批量调 CLI 取资金流。供日常增量与 load_fund_flow_panel 补缺。"""
    return _run_cli(list(codes), date=date)


# ============================================================
# 落库（供 MCP 历史回补与 CLI 日更共用）
# ============================================================
def upsert_fund_flow_records(records: pd.DataFrame, market: str = "ashare") -> int:
    """把 db 形资金流记录 upsert 进 SQLite ``fund_flow`` 表（按 ticker+date 去重）。

    供 MCP 历史回补调用：先把 MCP 原始 list[dict] 经 ``build_fund_flow_records``
    转 db 形，再本函数落库。CLI 日更亦经此写入。
    """
    if records is None or len(records) == 0:
        return 0
    from fetcher.store.db import get_conn, upsert

    keep = [c for c in _FUND_FLOW_COLS if c in records.columns]
    df = records[keep].copy()
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    conn = get_conn(market)
    try:
        return upsert(df, "fund_flow", ["ticker", "date"], conn)
    finally:
        conn.close()


# ============================================================
# 抓取器（兼容旧调用方式）
# ============================================================
class FundFlowFetcher(BaseFetcher):
    """个股资金流抓取器。

    存储策略：仿行情数据，SQLite 增量读写。
    - 主源：SQLite ``fund_flow`` 表（按 ticker+date 查询，命中即返回）
    - 兜底：CLI 当日快照（db 缺失时补单日；历史须靠 MCP 回补，CLI 仅给单日）

    用法：
    >>> ff = FundFlowFetcher()
    >>> flow = ff.get_stock_flow("000001")  # 历史资金流（读 db）
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _fetch_via_cli(self, code: str) -> pd.DataFrame:
        """db 缺失时调 CLI 取当日快照（仅单日）。"""
        return _run_cli([code])

    def get_stock_flow(
        self,
        code: str,
        use_cache: bool = True,
        start_date: str = "20200101",
    ) -> pd.DataFrame:
        """获取个股历史资金流（读 SQLite；缺失则 CLI 补当日快照）。

        Parameters
        ----------
        code : str
            6 位股票代码
        start_date : str
            增量读取起始日期（YYYYMMDD）

        Returns
        -------
        DataFrame columns:
            date, ticker, main_net_inflow, super_big_net_inflow, big_net_inflow,
            mid_net_inflow, small_net_inflow,（及 main_net_pct / close 等）
        """
        TABLE, KEYS = "fund_flow", ["ticker", "date"]
        if use_cache:
            try:
                cached = self.load_table(TABLE, market="ashare", ticker=code, date_ge=start_date)
                if cached is not None and len(cached) > 0:
                    return cached
            except Exception as e:
                logger.warning("资金流 db 读取失败 %s: %s，转 CLI", code, e)

        # db 缺失：CLI 当日快照（历史需 MCP 回补）
        logger.info("资金流 db 缺失 %s，CLI 当日快照补齐", code)
        df = self._fetch_via_cli(code)
        if df is not None and len(df) > 0:
            if use_cache:
                self.save_table(df, TABLE, KEYS, market="ashare")
            return df
        return pd.DataFrame()

    def batch_flows(
        self,
        codes: List[str],
        use_cache: bool = True,
        progress_every: int = 10,
    ) -> Dict[str, pd.DataFrame]:
        """批量获取多只股票的资金流（db 优先，缺失走 CLI 当日快照）。"""
        results: Dict[str, pd.DataFrame] = {}
        total = len(codes)
        for i, code in enumerate(codes):
            try:
                f = self.get_stock_flow(code, use_cache=use_cache)
                results[code] = f
            except Exception as e:
                logger.warning("获取 %s 资金流失败: %s", code, e)
                results[code] = pd.DataFrame()
            if (i + 1) % progress_every == 0 or i == total - 1:
                logger.info("资金流进度: %d/%d (%.0f%%)",
                            i + 1, total, (i + 1) / total * 100)
            time.sleep(0.2)
        return results

    def merge_to_panel(
        self,
        panel: pd.DataFrame,
        codes: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """把资金流数据按 (date, ticker) 合并到 panel。"""
        if codes is None:
            codes = panel["ticker"].unique().tolist()

        flows_dict = self.batch_flows(codes, use_cache=use_cache)
        flows = [f for f in flows_dict.values() if not f.empty]
        if not flows:
            return panel

        flow_panel = pd.concat(flows, ignore_index=True)
        keep_cols = [c for c in ["date", "ticker", "main_net_inflow",
                                  "super_big_net_inflow", "big_net_inflow",
                                  "mid_net_inflow", "small_net_inflow"]
                     if c in flow_panel.columns]
        flow_panel = flow_panel[keep_cols]

        panel = panel.merge(flow_panel, on=["date", "ticker"], how="left")
        return panel


# ============================================================
# 模块级取数助手（SQLite 批量取，仿行情）
# ============================================================
def load_fund_flow_panel(
    tickers: List[str],
    market: str = "ashare",
    start_date: Optional[str] = None,
    fill_missing: bool = True,
) -> pd.DataFrame:
    """从 SQLite ``fund_flow`` 表批量取数（增量）。

    优先查 db（历史由 MCP 回补，当日由 CLI 日更 append）；
    对 db 中缺失的 ticker，可经 CLI 取当日快照补齐（fill_missing=True，默认）。
    其余数据不动。

    Parameters
    ----------
    tickers : list[str]
        股票代码列表（6 位）
    start_date : str | None
        增量起始日期（YYYYMMDD）
    fill_missing : bool
        缺失 ticker 是否调 CLI 当日快照补齐

    Returns
    -------
    pd.DataFrame：合并后的资金流（含 date/ticker/main_net_inflow/... 等列）
    """
    from fetcher.store.db import query, upsert, get_conn

    tlist = [str(t).zfill(6) for t in tickers]
    df = pd.DataFrame()
    try:
        ph = ", ".join("?" for _ in tlist)
        sql = f"SELECT * FROM fund_flow WHERE ticker IN ({ph})"
        params: list = list(tlist)
        if start_date:
            sql += " AND date >= ?"
            params.append(str(start_date))
        df = query(sql, params, market=market)
    except Exception as e:
        logger.warning("fund_flow 批量读取失败: %s", e)
        df = pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce") if not df.empty else df

    if fill_missing:
        have = set(df["ticker"].astype(str)) if not df.empty else set()
        missing = [t for t in tlist if t not in have]
        if missing:
            logger.info("fund_flow 缺失 %d 只，CLI 当日快照补齐: %s", len(missing), missing[:5])
            extra = fetch_fund_flow_via_cli(missing)
            if not extra.empty:
                conn = get_conn(market)
                try:
                    upsert(extra, "fund_flow", ["ticker", "date"], conn)
                finally:
                    conn.close()
                extra["date"] = pd.to_datetime(extra["date"], errors="coerce")
                df = pd.concat([df, extra], ignore_index=True) if not df.empty else extra
                df["date"] = pd.to_datetime(df["date"], errors="coerce")

    return df
