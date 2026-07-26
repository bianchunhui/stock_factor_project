"""Test HK stock APIs for feasibility."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import akshare as ak

print("=" * 70)
print(" 1. 港股通成分股 (stock_hk_ggt_components_em)")
print("=" * 70)
try:
    df = ak.stock_hk_ggt_components_em()
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(5).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 2. 恒生指数成分股 - 尝试 stock_hk_index_spot_em")
print("=" * 70)
try:
    df = ak.stock_hk_index_spot_em()
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(5).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 3. 港股指数历史 - HSI (stock_hk_index_daily_sina)")
print("=" * 70)
try:
    df = ak.stock_hk_index_daily_sina(symbol="HSI")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Date range: {df['date'].min()} ~ {df['date'].max()}")
    print(df.tail(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 4. 港股个股日频 - 00700 腾讯 (stock_hk_daily)")
print("=" * 70)
try:
    df = ak.stock_hk_daily(symbol="00700", adjust="qfq")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Date range: {df['date'].min()} ~ {df['date'].max()}")
    print(df.tail(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 5. 港股财报 - 00700 (stock_financial_hk_report_em)")
print("=" * 70)
try:
    df = ak.stock_financial_hk_report_em(stock="00700", symbol="利润表", indicator="年报")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 6. 港股财务指标 - 00700 (stock_financial_hk_analysis_indicator_em)")
print("=" * 70)
try:
    df = ak.stock_financial_hk_analysis_indicator_em(symbol="00700", indicator="年报")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 7. 南向资金整体每日净买额 (stock_hsgt_hist_em)")
print("=" * 70)
try:
    df = ak.stock_hsgt_hist_em(symbol="南向资金")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Date range: {df['日期'].min()} ~ {df['日期'].max()}")
    print(df.tail(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 8. 单只港股通标的南向持股 - 00700 (stock_hsgt_individual_em)")
print("=" * 70)
try:
    df = ak.stock_hsgt_individual_em(symbol="00700")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    if len(df) > 0:
        print(f"  Date range: {df.iloc[0, 0]} ~ {df.iloc[-1, 0]}")
    print(df.tail(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 9. 港股实时行情 (stock_hk_spot_em)")
print("=" * 70)
try:
    df = ak.stock_hk_spot_em()
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.head(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 10. 港股个股估值 (stock_hk_valuation_baidu)")
print("=" * 70)
try:
    df = ak.stock_hk_valuation_baidu(symbol="00700", indicator="总市值", period="全部")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.tail(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 70)
print(" 11. 港股股息率 (stock_hk_gxl_lg)")
print("=" * 70)
try:
    df = ak.stock_hk_gxl_lg(symbol="恒生指数")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(df.tail(3).to_string(index=False))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("DONE")
