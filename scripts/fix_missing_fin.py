# 补下12只缺失财务数据
# 直接复用项目的 FinancialFetcher（东方财富EM源）
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

from fetcher.financial import FinancialFetcher

MISSING = [
    "000100", "300274", "600000", "600085", "600104",
    "600196", "600741", "600795", "600900", "601127",
    "601607", "688472",
]

def main():
    ff = FinancialFetcher()
    success = 0
    failed = []

    for i, code in enumerate(MISSING):
        try:
            # get_indicators 会自动调三表并合并，use_cache=True 会先检查缓存
            # 之前缓存不存在所以会重新下载，下载完后自动保存缓存
            ind = ff.get_indicators(code, use_cache=True)
            if ind is not None and len(ind) > 0:
                logger.info("[%d/%d] OK %s: %d 期", i+1, len(MISSING), code, len(ind))
                success += 1
            else:
                logger.warning("[%d/%d] EMPTY %s: 无数据", i+1, len(MISSING), code)
                failed.append(code)
        except Exception as e:
            logger.warning("[%d/%d] FAIL %s: %s", i+1, len(MISSING), code, e)
            failed.append(code)

    logger.info("=" * 50)
    logger.info("成功: %d, 失败: %d", success, len(failed))
    if failed:
        logger.info("失败: %s", ", ".join(failed))
    logger.info("=" * 50)

if __name__ == "__main__":
    main()
