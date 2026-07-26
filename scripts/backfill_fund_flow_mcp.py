"""MCP 历史资金流回补驱动（AI 调用 westock-mcp data_fund_flow 后落库）。

用法（由 AI/脚本编排）：
  1. 调用 mcp__westock-mcp__data_fund_flow(code, start, end) 取单只历史
  2. 把返回信封 {"ok":true,"data":{"code":...,"data":[...]}} 汇总进一个 JSON 文件：
       [{"code":"sz300308","data":[{...},{...}]}, ...]
  3. 运行本脚本读取该 JSON，标准化并 upsert 进 SQLite fund_flow 表：
        python scripts/backfill_fund_flow_mcp.py mcp_fund_flow_batch.json

也可一次传多个文件。落库按 (ticker,date) 幂等覆盖，可多次分批补。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_fund_flow_mcp")


def main():
    ap = argparse.ArgumentParser(description="MCP 资金流历史回补落库")
    ap.add_argument("files", nargs="*", help="MCP 返回信封汇总 JSON 文件（可多个）")
    ap.add_argument("--dir", help="扫描该目录下所有 _frag_*.json 信封文件（与 files 合并）")
    ap.add_argument("--market", default="ashare")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fetcher.fund_flow import build_fund_flow_records, upsert_fund_flow_records

    file_list = list(args.files)
    if args.dir:
        file_list += [str(p) for p in sorted(Path(args.dir).glob("_frag_*.json"))]
    if not file_list:
        logger.error("未指定任何输入文件（用 files 或 --dir）")
        return

    total_written = 0
    total_codes = 0
    for fp in file_list:
        p = Path(fp)
        if not p.exists():
            logger.warning("文件不存在跳过: %s", fp)
            continue
        envelope = json.loads(p.read_text(encoding="utf-8"))
        # 兼容单条信封或信封列表
        if isinstance(envelope, dict):
            envelope = [envelope]
        for item in envelope:
            data = item.get("data", {})
            rows = data.get("data") if isinstance(data, dict) else data
            if not rows:
                logger.warning("空数据: %s", item.get("code", "?"))
                continue
            recs = build_fund_flow_records(rows)
            if recs.empty:
                continue
            n = upsert_fund_flow_records(recs, market=args.market)
            total_written += n
            total_codes += 1
            logger.info("回补 %s -> %d 行", recs["ticker"].iloc[0], n)
    logger.info("回补完成：%d 只 | 共 %d 行", total_codes, total_written)


if __name__ == "__main__":
    main()
