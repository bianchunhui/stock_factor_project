"""统一 SQLite 存储层（替代 parquet 散落缓存）。

三市场分库：ashare.db / hk.db / us.db，置于 data/db/。
核心 API：
  get_conn(market)                -> sqlite3.Connection
  init_dbs()                      -> 预建三库核心表
  upsert(df, table, keys, conn)   -> INSERT OR REPLACE（按 keys 主键去重，动态建表/加列）
  query(sql, params, conn/market) -> pd.DataFrame
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# 项目根 data/db（self-contained，不依赖 config 导入链）：
# fetcher/store/db.py -> parent=store -> parent.parent=fetcher -> parent.parent.parent=项目根
DB_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "db"
DB_FILES = {"ashare": "ashare.db", "hk": "hk.db", "us": "us.db"}


def get_conn(market: str) -> sqlite3.Connection:
    if market not in DB_FILES:
        raise ValueError(f"unknown market {market!r}, expect one of {list(DB_FILES)}")
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_DIR / DB_FILES[market])
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _safe_col(c) -> str:
    """清洗列名/表名，保留中文与括号，空格转下划线、去引号。"""
    c = str(c).strip().replace(" ", "_").replace('"', "").replace("`", "").replace("'", "")
    return c or "col"


def _ensure_table(conn: sqlite3.Connection, table: str, cols: list, keys: list) -> None:
    table = _safe_col(table)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    exists = cur.fetchone() is not None
    if not exists:
        # 所有列（含主键列）都必须有列声明，PK 子句仅引用它们
        col_defs = ", ".join(f'"{_safe_col(c)}"' for c in cols)
        pk = ", ".join(f'"{_safe_col(k)}"' for k in keys)
        ddl = f'CREATE TABLE IF NOT EXISTS "{table}" ({col_defs}, PRIMARY KEY ({pk}))'
        conn.execute(ddl)
        conn.commit()
        return
    # 已存在：缺列则 ALTER ADD（主键列首次建表即有，不在此加）
    existing = {_safe_col(r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")')}
    for c in cols:
        sc = _safe_col(c)
        if sc not in existing and c not in keys:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{sc}"')
    conn.commit()


def upsert(df: pd.DataFrame, table: str, keys: list, conn: sqlite3.Connection) -> int:
    """按 keys 主键做 INSERT OR REPLACE（upsert）。动态建表 / 加列容下列漂移。"""
    if df is None or len(df) == 0:
        return 0
    safe_cols = [_safe_col(c) for c in df.columns]
    df2 = df.copy()
    df2.columns = safe_cols
    _ensure_table(conn, table, safe_cols, keys)
    col_list = ", ".join(f'"{c}"' for c in safe_cols)
    placeholders = ", ".join("?" for _ in safe_cols)
    sql = f'INSERT OR REPLACE INTO "{_safe_col(table)}" ({col_list}) VALUES ({placeholders})'

    def _coerce(v):
        if pd.isna(v):
            return None
        # sqlite3 不支持 pd.Timestamp / datetime / date，转 ISO 字符串
        if isinstance(v, (pd.Timestamp, datetime, date)):
            return v.isoformat()
        # sqlite3 不支持 numpy 标量，转 Python 原生类型
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            return float(v)
        if isinstance(v, np.bool_):
            return bool(v)
        return v

    records = [tuple(_coerce(v) for v in row) for row in df2.itertuples(index=False, name=None)]
    conn.executemany(sql, records)
    conn.commit()
    return len(df2)


def query(sql: str, params=(), conn=None, market: str | None = None) -> pd.DataFrame:
    close = False
    if conn is None:
        if market is None:
            raise ValueError("query needs conn or market")
        conn = get_conn(market)
        close = True
    try:
        return pd.read_sql(sql, conn, params=params)
    finally:
        if close:
            conn.close()


# 预建核心表（固定结构）；财务表列随数据动态加列兜底。
_CORE_TABLES = {
    "daily_price": ["ticker", "date", "open", "high", "low", "close", "volume", "amount"],
    "index_daily": ["ticker", "date", "open", "high", "low", "close", "volume", "amount"],
    # 资金流（东财个股资金流）：列名与 akshare 实际产出对齐
    "fund_flow": ["ticker", "date", "main_net_inflow", "super_big_net_inflow",
                  "big_net_inflow", "mid_net_inflow", "small_net_inflow",
                  "main_net_pct", "super_big_net_pct", "big_net_pct",
                  "mid_net_pct", "small_net_pct", "close", "pct_chg"],
    "factor_panel": ["ticker", "date"],
    "selection_result": ["date", "ticker", "composite", "rank"],
    "backtest_nav": ["date", "nav", "benchmark_nav"],
    "ref_industry": ["ticker", "industry"],
    "ref_industry_map": ["ticker", "industry"],
    "ref_shares": ["ticker", "outstanding_share"],
    "ref_calendar": ["date"],
    "ref_hsgt": ["ticker", "date"],
    # 标的池（港股/美股）：market + ticker 复合主键
    "ref_universe": ["market", "ticker", "name", "sector"],
}


def _keys_for(cols: list) -> list:
    # 宇宙/参考表含 market 维度时，用 (market, ticker) 复合主键
    if "market" in cols and "ticker" in cols:
        return ["market", "ticker"]
    if "ticker" in cols and "date" in cols:
        return ["ticker", "date"]
    if "ticker" in cols:
        return ["ticker"]
    return ["date"]


def init_dbs(markets=("ashare", "hk", "us")) -> Path:
    for m in markets:
        conn = get_conn(m)
        for table, cols in _CORE_TABLES.items():
            _ensure_table(conn, table, cols, _keys_for(cols))
        conn.close()
    return DB_DIR


# ================================================================
# 便捷封装（自动开关连接）
# ================================================================
def save_ref(df: pd.DataFrame, table: str, market: str, keys: list) -> int:
    """写参考表（ref_*），自动开关连接。"""
    conn = get_conn(market)
    try:
        return upsert(df, table, keys, conn)
    finally:
        conn.close()


def save_factor_panel(df: pd.DataFrame, market: str) -> int:
    """写因子面板（ticker, date 主键）。"""
    conn = get_conn(market)
    try:
        return upsert(df, "factor_panel", ["ticker", "date"], conn)
    finally:
        conn.close()


def load_factor_panel(market: str, start: str | None = None,
                      tickers: list | None = None) -> pd.DataFrame:
    """读取因子面板。start: 'YYYYMMDD' 或 ISO；tickers: 限定股票列表。"""
    sql = "SELECT * FROM factor_panel"
    conds, params = [], []
    if start:
        conds.append("date >= ?")
        params.append(str(start))
    if tickers:
        ph = ", ".join("?" for _ in tickers)
        conds.append(f"ticker IN ({ph})")
        params.extend(str(t) for t in tickers)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    return query(sql, params, market=market)


def load_universe(market: str) -> pd.DataFrame:
    """返回标的池 DataFrame。
    A  -> ref_index_weight（沪深300，含 weight）
    HK -> ref_universe WHERE market='HK'
    US -> ref_universe WHERE market='US'
    """
    if market in ("ashare", "A"):
        df = query(
            "SELECT ticker, name, weight FROM ref_index_weight",
            market="ashare",
        )
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        return df
    if market in ("hk", "HK"):
        return query(
            "SELECT ticker, name, sector FROM ref_universe WHERE market=?",
            ["HK"], market="hk",
        )
    if market in ("us", "US"):
        return query(
            "SELECT ticker, name, sector FROM ref_universe WHERE market=?",
            ["US"], market="us",
        )
    raise ValueError(f"unknown market {market!r}")


def get_coverage(market: str) -> dict:
    """Return coverage stats for all relevant tables in one market db.

    Uses SQL aggregation (not DataFrame load) to avoid reading full tables.
    Returns dict like: {
        "daily_price": {"min_date": "2020-01-02", "max_date": "2026-07-16",
                         "rows": 7500, "tickers": 30},
        ...
    }
    Only includes tables that exist and have data.
    """
    conn = get_conn(market)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        existing = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    result = {}
    for table in existing:
        # ---- get column info ----
        conn2 = get_conn(market)
        try:
            cols = [r[1] for r in conn2.execute(f"PRAGMA table_info({table})")]
        finally:
            conn2.close()

        info = {}
        # row count
        try:
            r = query(f"SELECT COUNT(*) AS n FROM [{table}]", [], market=market)
            if not r.empty:
                info["rows"] = int(r["n"].iloc[0])
        except Exception:
            continue
        if info.get("rows", 0) == 0:
            continue

        # ticker count
        if "ticker" in cols:
            try:
                r = query(
                    f"SELECT COUNT(DISTINCT ticker) AS n FROM [{table}]",
                    [], market=market,
                )
                if not r.empty:
                    info["tickers"] = int(r["n"].iloc[0])
            except Exception:
                pass

        # date range: try date / report_date / report_period
        for dc in ("date", "report_date", "report_period"):
            if dc not in cols:
                continue
            try:
                r = query(
                    f"SELECT MIN([{dc}]) AS mn, MAX([{dc}]) AS mx FROM [{table}]",
                    [], market=market,
                )
                if not r.empty:
                    mn, mx = r["mn"].iloc[0], r["mx"].iloc[0]
                    if pd.notna(mn):
                        mn_dt = pd.to_datetime(str(mn), errors="coerce")
                        if pd.notna(mn_dt):
                            info[f"min_{dc}"] = str(mn_dt.date())
                    if pd.notna(mx):
                        mx_dt = pd.to_datetime(str(mx), errors="coerce")
                        if pd.notna(mx_dt):
                            info[f"max_{dc}"] = str(mx_dt.date())
            except Exception:
                pass

        result[table] = info

    return result


if __name__ == "__main__":
    p = init_dbs()
    print("dbs initialized at", p)
