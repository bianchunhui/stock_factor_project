# 针对 baostock 全量重下时因"行数<700"被拒的 3 只次新大盘股做补写。
# 这 3 只末日接近今日(证明非截断)，只是上市晚、历史短，应接受其完整短历史。
from __future__ import annotations
import sys, time, logging
from pathlib import Path
import pandas as pd
import baostock as bs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config.settings import CACHE_DIR  # noqa: E402
from scripts.redownload_prices_baostock import (  # noqa: E402
    cache_key, today_str, fetch_price_baostock, normalize_ticker,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGETS = ["001280", "001391", "600930"]
START = "20230101"


def main():
    end = today_str()
    lg = bs.login()
    if str(lg.error_code) != "0" and "success" not in str(lg.error_msg).lower():
        logger.error("登录失败 %s %s", lg.error_code, lg.error_msg)
        return
    today_dt = pd.to_datetime(end)
    try:
        for code in TARGETS:
            df = fetch_price_baostock(code, START, end, "1")
            if df is None or len(df) == 0:
                logger.warning("%s 仍无数据，跳过", code)
                continue
            last = df["date"].max()
            if (today_dt - last).days > 5:
                logger.warning("%s 末日过旧 %s，跳过", code, last.date())
                continue
            # 宽松接受：末日接近今日即视为完整(上市晚导致行数少)
            key = cache_key("ashare", code, START, end, "hfq")
            df.to_parquet(CACHE_DIR / f"{key}.parquet")
            logger.info("%s 已补写: %d 行, 末日 %s", code, len(df), last.date())
            time.sleep(0.2)
    finally:
        bs.logout()
        logger.info("补写完成")


if __name__ == "__main__":
    main()
