"""多因子选股系统配置模块。"""
from .settings import (
    PROJECT_ROOT,
    DATA_DIR,
    CACHE_DIR,
    FACTOR_DIR,
    REPORT_DIR,
    FETCH_TIMEOUT,
    FETCH_RETRIES,
    RETRY_BACKOFF,
    DEFAULT_START,
    DEFAULT_END,
    TRADING_DAYS_PER_YEAR,
    TRADING_DAYS_PER_MONTH,
)
from .universe import (
    UNIVERSE_FILTERS,
    BENCHMARK,
    SH_PREFIX,
    SZ_PREFIX,
    BJ_PREFIX,
    SW_LEVEL1_CODE_LEN,
    FACTOR_CATALOG,
    CATEGORIES,
    factors_by_category,
)
