"""基础连通性测试（仿 cta_project/tests/test_fetch_basic.py）。

运行：python tests/test_fetch.py
逐项验证数据抓取链路，任一项失败给出明确提示（网络/接口变更）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 把项目根加入 sys.path（脚本式运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher import CalendarFetcher, PriceFetcher


def _ok(name: str) -> None:
    print(f"  [OK] {name}")


def _fail(name: str, err: Exception) -> None:
    print(f"  [FAIL] {name}: {type(err).__name__}: {err}")


def test_calendar() -> bool:
    print("\n[1] 交易日历")
    try:
        cal = CalendarFetcher()
        dates = cal.trade_dates(use_cache=False)
        assert len(dates) > 100, "交易日数量过少"
        last = dates.iloc[-1]
        print(f"    最近交易日: {last.date()}, 共 {len(dates)} 个交易日")
        # 月末日
        me = cal.month_end_dates("20240101", "20240630")
        print(f"    2024H1 月末日数: {len(me)}")
        _ok("交易日历")
        return True
    except Exception as e:
        _fail("交易日历", e)
        return False


def test_a_daily() -> bool:
    print("\n[2] A 股日频行情 (平安银行 000001)")
    try:
        pf = PriceFetcher()
        df = pf.get_a_share_daily("000001", "20240101", "20240131", use_cache=False)
        assert len(df) > 0, "返回空"
        need = {"date", "ticker", "close"}
        assert need.issubset(df.columns), f"缺列 {need - set(df.columns)}"
        print(f"    列: {list(df.columns)}")
        print(f"    样本: {len(df)} 行, 区间 {df['date'].min().date()} ~ {df['date'].max().date()}")
        _ok("A 股日频")
        return True
    except Exception as e:
        _fail("A 股日频", e)
        return False


def test_a_index() -> bool:
    print("\n[3] A 股指数基准 (沪深300)")
    try:
        pf = PriceFetcher()
        df = pf.get_a_index_daily("000300", "20240101", "20240131", use_cache=False)
        assert len(df) > 0, "返回空"
        print(f"    样本: {len(df)} 行, 收盘 {df['close'].iloc[-1]:.2f}")
        _ok("A 股指数基准")
        return True
    except Exception as e:
        _fail("A 股指数基准", e)
        return False


def test_index_cons() -> bool:
    print("\n[4] 沪深300 成分股")
    try:
        from universe import Universe
        u = Universe(mode="A", start="20240101", end="20240131", index_symbol="000300")
        cons = u.constituents(use_cache=False)
        assert len(cons) > 0, "返回空"
        print(f"    成分数: {len(cons)}")
        print(f"    示例: {cons[['ticker', 'name']].head(3).to_dict('records')}")
        _ok("沪深300成分")
        return True
    except Exception as e:
        _fail("沪深300成分", e)
        return False


def main() -> int:
    print("=" * 56)
    print(" 多因子选股系统 - 基础连通性测试")
    print("=" * 56)
    results = [
        test_calendar(),
        test_a_daily(),
        test_a_index(),
        test_index_cons(),
    ]
    n_pass = sum(results)
    print(f"\n{'=' * 56}")
    print(f" 通过 {n_pass}/{len(results)}")
    print("=" * 56)
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
