"""数据抓取基础设施。

复用 cta_project / news_event_project 的约定：
- _throttle: 最小请求间隔，避免 akshare 限流
- _call_with_retry: 重试 + 指数退避，致命异常直接抛
- parquet 缓存: md5(name)[:12] 落盘，避免重复请求
- _normalize_*: 每个数据源标准化为统一的英文列名
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from config import CACHE_DIR, FETCH_RETRIES, RETRY_BACKOFF

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def today_str() -> str:
    """今日日期字符串 YYYYMMDD。"""
    return datetime.now().strftime("%Y%m%d")


def cache_key(*parts) -> str:
    """由若干字段生成文件系统安全的缓存键。"""
    raw = "_".join(str(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def to_datetime_safe(s: pd.Series) -> pd.Series:
    """安全转 datetime，自动识别 epoch 数值单位。

    AKShare EM 接口返回的 REPORT_DATE/NOTICE_DATE 是 epoch 微秒 (int64)，
    pd.to_datetime() 不带 unit 参数时默认按纳秒解析，会把微秒值误译为 1970 年。
    本函数对数值型输入自动按微秒解析，对字符串按默认方式解析。
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    if pd.api.types.is_numeric_dtype(s):
        # AKShare EM 返回 epoch 微秒
        return pd.to_datetime(s, errors="coerce", unit="us")
    # 字符串日期
    return pd.to_datetime(s, errors="coerce")


class BaseFetcher:
    """所有数据抓取器的公共基类：节流 / 重试 / 缓存。"""

    def __init__(self, cache_dir: Path = CACHE_DIR, min_interval: float = 0.5):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval = min_interval
        self._last_request_ts = 0.0

    # --------------------------------------------------
    # 节流与重试
    # --------------------------------------------------
    def _throttle(self, interval: Optional[float] = None) -> None:
        """确保两次请求间至少间隔 gap 秒。"""
        gap = interval or self._min_interval
        elapsed = time.time() - self._last_request_ts
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_request_ts = time.time()

    def _call_with_retry(
        self, func, *args,
        interval: Optional[float] = None,
        fatal_exceptions: tuple = (KeyError,),
        **kwargs,
    ):
        """对 akshare 函数调用做重试 + 指数退避。

        fatal_exceptions 中的异常类型直接抛出，不重试（如非交易日 KeyError）。
        """
        last_exc = None
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                self._throttle(interval)
                return func(*args, **kwargs)
            except fatal_exceptions:
                raise
            except Exception as e:
                last_exc = e
                wait = RETRY_BACKOFF ** attempt
                logger.warning(
                    "请求失败 (attempt %d/%d): %s, %.1fs 后重试",
                    attempt, FETCH_RETRIES, e, wait,
                )
                time.sleep(wait)
        raise RuntimeError(f"重试 {FETCH_RETRIES} 次后仍失败: {last_exc}")

    # --------------------------------------------------
    # parquet 缓存
    # --------------------------------------------------
    def _cache_path(self, name: str) -> Path:
        return self.cache_dir / f"{name}.parquet"

    def _load_cache(
        self,
        name: str,
        expected_cols: Optional[list] = None,
        min_rows: int = 1,
        key_cols: Optional[list] = None,
        key_min_ratio: float = 0.5,
    ) -> Optional[pd.DataFrame]:
        """读缓存并做完整性校验，不合格视为脏缓存 → 返回 None 触发重抓。

        - min_rows: 行数下限（默认 1，直接挡掉空壳 / 0 行缓存）
        - expected_cols: 预期列集合，缺列则失效（防 akshare 改列名后旧缓存被静默复用）
        - key_cols: 关键列，非空占比低于 key_min_ratio 则失效（防半截 / 全 NaN 数据）
        """
        p = self._cache_path(name)
        if not p.exists():
            return None
        try:
            df = pd.read_parquet(p)
        except Exception as e:
            logger.warning("缓存读取失败 %s: %s，将重新获取", p.name, e)
            return None

        # 1) 行数校验
        if df is None or len(df) < min_rows:
            logger.warning("缓存 %s 行数不足(%s<%s)，判为脏缓存，将重新获取",
                           p.name, 0 if df is None else len(df), min_rows)
            return None
        # 2) 预期列校验
        if expected_cols:
            missing = [c for c in expected_cols if c not in df.columns]
            if missing:
                logger.warning("缓存 %s 缺列 %s，判为脏缓存，将重新获取", p.name, missing)
                return None
        # 3) 关键列非空占比校验
        if key_cols:
            for c in key_cols:
                if c not in df.columns:
                    logger.warning("缓存 %s 缺关键列 %s，将重新获取", p.name, c)
                    return None
                ratio = df[c].notna().mean()
                if ratio < key_min_ratio:
                    logger.warning("缓存 %s 关键列 %s 非空占比过低(%.0f%%<%.0f%%)，将重新获取",
                                   p.name, c, ratio * 100, key_min_ratio * 100)
                    return None
        return df

    def _save_cache(self, df: pd.DataFrame, name: str) -> None:
        if df is None or len(df) == 0:
            return
        df.to_parquet(self._cache_path(name))

    # --------------------------------------------------
    # SQLite 增量存储（替代 parquet 散落缓存）
    # --------------------------------------------------
    def save_table(self, df: pd.DataFrame, table: str, keys, market: str = "ashare") -> int:
        """增量写入 SQLite：INSERT OR REPLACE 按主键去重。

        直接替代 `_save_cache`，让 fetcher 落库即增量更新（新日期/新报告期
        自动追加，旧的覆盖），不再产生散落 parquet。
        """
        if df is None or len(df) == 0:
            return 0
        from fetcher.store.db import get_conn, upsert
        conn = get_conn(market)
        try:
            return upsert(df, table, list(keys), conn)
        finally:
            conn.close()

    def load_table(self, table: str, market: str = "ashare",
                   ticker=None, date_ge=None, columns=None) -> pd.DataFrame:
        """从 SQLite 读取整表或按 ticker / 起始日期筛选。

        替代 `_load_cache` 的批量场景：fetcher 先查 db，命中即跳过网络重抓，
        从而支持「增量更新」——重跑只补新数据。
        """
        from fetcher.store.db import query
        col_sql = "*" if not columns else ", ".join(f'"{c}"' for c in columns)
        sql = f'SELECT {col_sql} FROM "{table}"'
        conds, params = [], []
        if ticker is not None:
            conds.append("ticker = ?")
            params.append(str(ticker))
        if date_ge is not None:
            conds.append("date >= ?")
            params.append(str(date_ge))
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        return query(sql, params, market=market)
