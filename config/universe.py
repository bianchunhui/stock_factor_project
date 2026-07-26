"""Universe 与因子目录定义。

market == "A"   : 沪深京 A 股（含科创板 / 创业板 / 北交所）
market == "HK"  : 港股通成分
market == "A_HK": 两者合并
"""
from __future__ import annotations

# ------------------------------------------------------------------
# Universe 默认过滤参数
# ------------------------------------------------------------------
UNIVERSE_FILTERS = {
    "A": {
        "drop_st": True,            # 去除 ST /*ST
        "min_list_days": 250,       # 上市满 250 个交易日（去新股）
        "min_amount_20d": 1e7,      # 近 20 日日均成交额下限（元）
        "drop_paused": True,        # 调仓日停牌剔除
    },
    "HK": {
        "drop_st": True,
        "min_list_days": 250,
        "min_amount_20d": 1e7,      # 港币
        "drop_paused": True,
    },
    "A_HK": {},                      # 合并模式沿用 A / HK 各自过滤
}

# 基准指数（用于计算超额收益与 Beta 因子）
BENCHMARK = {
    "A": "000300",          # 沪深 300
    "HK": "HSI",            # 恒生指数
    "A_HK": "000300",       # 合并默认以沪深 300 对标
}

# 沪深交易所代码前缀判定
SH_PREFIX = ("60", "68", "11", "13")        # 沪市：主板 60 / 科创 68 / 可转债 11 / 国债 13
SZ_PREFIX = ("00", "30", "12")              # 深市：主板/中小 00 / 创业 30 / 可转债 12
BJ_PREFIX = ("83", "87", "920", "43", "88") # 北交所

# 申万一级行业代码长度（中性化时用一级）
SW_LEVEL1_CODE_LEN = 6  # 申万一级行业代码如 801010


# ------------------------------------------------------------------
# 因子目录（Phase 2+ 逐步填充）
# ------------------------------------------------------------------
# name -> (category, direction, need_pit, description)
# direction: +1 越大越好；-1 越小越好
FACTOR_CATALOG = {
    # 价值
    "EP":   ("value",     +1, True,  "市盈率倒数 1/PE"),
    "BP":   ("value",     +1, True,  "市净率倒数 1/PB"),
    "DP":   ("value",     +1, True,  "股息率"),
    "SP":   ("value",     +1, True,  "市销率倒数 1/PS"),
    "CFP":  ("value",     +1, True,  "市现率倒数 1/PCF"),
    # 成长
    "RevG": ("growth",    +1, True,  "营业收入同比增速"),
    "NetG": ("growth",    +1, True,  "归母净利润同比增速"),
    "EpG":  ("growth",    +1, True,  "EPS 同比增速"),
    # 质量
    "ROE":  ("quality",   +1, True,  "净资产收益率"),
    "ROA":  ("quality",   +1, True,  "总资产收益率"),
    "Lev":  ("quality",   -1, True,  "资产负债率（越低越好）"),
    "GPM":  ("quality",   +1, True,  "销售毛利率"),
    "CFO":  ("quality",   +1, True,  "经营现金流 / 净利润"),
    # 动量
    "Mom12m": ("momentum", +1, False, "12 个月动量（剔除近 1 月）"),
    "Rev1m":  ("momentum", -1, False, "1 个月反转（短期反转效应）"),
    # 波动
    "Vol60": ("volatility", -1, False, "60 日已实现波动率（低波动溢价）"),
    "Beta":  ("volatility", -1, False, "对基准的 Beta"),
    # 规模 / 流动性
    "LnMV":  ("size",      -1, False, "对数流通市值（小市值效应）"),
    "Turn":  ("liquidity", -1, False, "换手率（低换手溢价）"),
    # 情绪（历史段：北向资金，2014-11 ~ 2024-08-16）
    "HSGT":     ("sentiment", +1, False, "北向持股占比（%, 仅 2014.11~2024.08）"),
    "Flow":     ("sentiment", +1, False, "北向今日增持资金（万元, 仅 2014.11~2024.08）"),
    "FUp":      ("sentiment", +1, False, "北向近 20 日增持幅度（仅 2014.11~2024.08）"),
    # 情绪（现代源：东财个股资金流, 2024 年至今可用）
    "MainFlow": ("sentiment", +1, False, "主力资金净流入（万元, 5 日均值）"),
    "SuperBig": ("sentiment", +1, False, "超大单净流入（万元, 5 日均值）"),
}

# 按类别分组（便于按类输出报告）
CATEGORIES = ("value", "growth", "quality", "momentum",
              "volatility", "size", "liquidity", "sentiment")


def factors_by_category(category: str) -> list[str]:
    """返回某类别下所有因子名。"""
    return [k for k, v in FACTOR_CATALOG.items() if v[0] == category]
