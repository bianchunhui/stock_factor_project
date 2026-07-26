"""项目路径与抓取参数设置。"""
from pathlib import Path

# 项目根目录：stock_factor_project/config/settings.py -> stock_factor_project/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 数据存储
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"          # 原始数据 parquet 缓存
FACTOR_DIR = DATA_DIR / "factors"       # 因子计算结果
REPORT_DIR = DATA_DIR / "reports"       # 回测/评估报告

# 抓取参数
FETCH_TIMEOUT = 30          # 单次请求超时（秒），通过 time.sleep 控制节流
FETCH_RETRIES = 3           # 失败重试次数
RETRY_BACKOFF = 1.5         # 重试退避因子（指数退避）

# 默认回测区间
DEFAULT_START = "20210101"
DEFAULT_END = None           # None 表示到最新

# 交易日常数
TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21

# 确保目录存在
for _d in (DATA_DIR, CACHE_DIR, FACTOR_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
