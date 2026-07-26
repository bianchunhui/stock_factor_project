"""解析道琼斯指数成分股快照文件，生成美股选股池 universe CSV。

输入：从行情软件导出的固定宽度（空格分隔）表格，含 序/代码/名称/最新/涨幅%/...
      默认读取 C:/Users/chunh/Downloads/Table道琼斯.txt
输出：data/dj_universe_YYYYMMDD.csv，列：ticker, name, sector

注意：
  - 代码列即美股 ticker（如 CSCO / AAPL），可直接用于 akshare 美股接口
  - sector 为内置 GICS 行业映射（道指 30 只手工标注），供因子中性化使用
  - 本脚本纯本地解析，不联网
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_SRC = r"C:/Users/chunh/Downloads/Table道琼斯.txt"
OUT_DIR = Path("data")

# 道指 30 只 GICS 行业（手工标注，供行业中性化）
SECTOR_MAP = {
    "CSCO": "Information Technology",
    "AXP": "Financials",
    "GS": "Financials",
    "JPM": "Financials",
    "UNH": "Health Care",
    "AMZN": "Consumer Discretionary",
    "HON": "Industrials",
    "AAPL": "Information Technology",
    "HD": "Consumer Discretionary",
    "SHW": "Materials",
    "MMM": "Industrials",
    "MSFT": "Information Technology",
    "V": "Financials",
    "TRV": "Financials",
    "NKE": "Consumer Discretionary",
    "DIS": "Communication Services",
    "MCD": "Consumer Discretionary",
    "NVDA": "Information Technology",
    "MRK": "Health Care",
    "WMT": "Consumer Staples",
    "BA": "Industrials",
    "GOOGL": "Communication Services",
    "KO": "Consumer Staples",
    "CAT": "Industrials",
    "PG": "Consumer Staples",
    "CVX": "Energy",
    "AMGN": "Health Care",
    "JNJ": "Health Care",
    "IBM": "Information Technology",
    "CRM": "Information Technology",
}

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,5}$")


def _read_text(path: str) -> list[str]:
    """兼容 GBK / UTF-8 编码读取文本行。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return raw.decode(enc).splitlines()
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("gb18030", errors="ignore").splitlines()


def parse_table(path: str) -> pd.DataFrame:
    """解析固定宽度快照表，返回 ticker/name 两列。"""
    rows = []
    for line in _read_text(path):
        line = line.rstrip("\n")
        if not line.strip():
            continue
        tokens = line.split()
        # 跳过表头（序 代码 名称 ...）
        if tokens and tokens[0] == "序":
            continue
        # 需要一个数字序号开头 + ticker token
        if len(tokens) < 3:
            continue
        ticker = tokens[1]
        if not TICKER_RE.match(ticker):
            continue
        name = tokens[2]  # 道指 30 名称均为单 token（无空格）
        rows.append({"ticker": ticker, "name": name})
    return pd.DataFrame(rows)


def main(src: str | None = None):
    src = src or DEFAULT_SRC
    p = Path(src)
    if not p.exists():
        print(f"[ERROR] 源文件不存在: {src}")
        return 1

    df = parse_table(str(p))
    if df.empty:
        print("[ERROR] 未解析到任何成分股，请检查文件格式")
        return 1

    # 补 sector
    df["sector"] = df["ticker"].map(SECTOR_MAP).fillna("Other")
    missing = df.loc[df["sector"] == "Other", "ticker"].tolist()
    if missing:
        print(f"  [WARN] 以下 ticker 无内置行业映射，标记为 Other: {missing}")

    # 去重保序
    df = df.drop_duplicates("ticker").reset_index(drop=True)

    out_name = f"dj_universe_{datetime.now():%Y%m%d}.csv"
    out_path = OUT_DIR / out_name
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[OK] 解析 {len(df)} 只道指成分股")
    print(f"     输出: {out_path}")
    print(f"     行业分布: {df['sector'].value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(arg))
