# 多因子选股量化系统

A股（沪深京 + 科创/创业板）与港股通多因子选股框架，覆盖 24 个因子（价值/成长/质量/动量/波动/规模/流动性/情绪）。

## 目录结构

```
stock_factor_project/
├── config/                  # 路径、参数、因子目录
│   ├── settings.py          # 项目根/数据路径/抓取参数
│   └── universe.py          # 市场过滤参数、基准、FACTOR_CATALOG(24因子)
├── fetcher/                 # akshare 数据抓取层
│   ├── base.py              # BaseFetcher: 节流/重试/parquet缓存/to_datetime_safe
│   ├── price.py             # A股/港股/指数日频行情
│   ├── calendar.py          # 交易日历/调仓日
│   ├── financial.py         # 三大报表(利润/资产负债/现金流) + 衍生指标
│   ├── hsgt.py              # 沪深港通北向持股（⚠️ 数据截至 2024-08-16）
│   ├── fund_flow.py         # 东财个股资金流（北向替代, 2024年至今可用）
│   ├── industry.py          # 申万行业分类映射
│   └── spot.py              # 东财实时行情（市值/PE/PB）
├── universe/                # 选股池构建
│   └── builder.py           # Universe(A/HK/A_HK): 成分获取 + ST/新股/流动性过滤
├── factors/                 # 因子库（24 个）
│   ├── base.py              # FactorBase: name/category/direction/compute()
│   ├── value.py             # EP/BP/SP/CFP/DP 价值因子
│   ├── growth.py            # RevG/NetG/EpG 成长因子
│   ├── quality.py           # ROE/ROA/GPM/Lev/CFO 质量因子
│   ├── momentum.py          # Mom12m/Rev1m 动量反转
│   ├── technical.py         # LnMV/Turn/Vol60/Beta
│   └── sentiment.py         # HSGT/Flow/FUp(历史) + MainFlow/SuperBig(现代)
├── processor/               # 数据处理
│   ├── normalize.py         # 横截面缩尾/中性化/zscore/rank
│   ├── align.py             # forward return 计算与对齐
│   └── pit_align.py         # 财报 PIT 对齐(防未来函数, merge_asof)
├── evaluator/               # 因子评估
│   ├── ic_ir.py             # 横截面 IC/IR (groupby date → spearman)
│   └── returns.py           # 分位组合收益/单调性
├── portfolio/               # 组合构建
│   ├── combine.py           # 因子合成 (等权/IC加权/逆方差)
│   ├── builder.py           # Top-N%选股+加权
│   └── backtest.py          # 向量化回测引擎
├── backtest/                 # 指标与成本
│   ├── metrics.py           # 年化/夏普/回撤/信息比率
│   └── costs.py             # A股/港股通交易成本
├── risk/                     # 风控
│   └── controls.py          # 权重约束/行业暴露
├── scripts/
│   ├── eval_single_factor.py  # 单因子端到端评估脚本
│   ├── eval_all_factors.py    # 全量24因子端到端评估脚本
│   ├── fix_cache_dtype.py     # 修复parquet缓存日期dtype
│   └── verify_pit_merge.py    # 验证PIT对齐正确性
├── tests/
│   └── test_fetch.py        # 连通性测试
└── data/{cache,factors,reports}/  # 自动创建的本地数据目录
```

## 快速开始

```bash
pip install -r requirements.txt
python tests/test_fetch.py                    # 连通性测试
python scripts/eval_single_factor.py          # 单因子评估(默认Vol60)
python scripts/eval_single_factor.py --factor Mom12m --index 000905 --max-stocks 100
python scripts/eval_all_factors.py            # 全量24因子评估(默认5股)
python scripts/eval_all_factors.py --max-stocks 50 --start 20230101
```

## 因子目录（24 个）

| 类别 | 因子 | direction | need_pit | 说明 |
|------|------|-----------|----------|------|
| 价值 | EP/BP/SP/CFP/DP | +1 | True | 市盈率/市净率/市销率/市现率/股息率 倒数 |
| 成长 | RevG/NetG/EpG | +1 | True | 营收/归母净利润/EPS 同比增速 |
| 质量 | ROE/ROA/GPM/CFO | +1 | True | 收益率/毛利率/现金流比 |
| 质量 | Lev | -1 | True | 资产负债率（越低越好） |
| 动量 | Mom12m | +1 | False | 12 月动量（剔除近 1 月） |
| 动量 | Rev1m | -1 | False | 1 月反转 |
| 波动 | Vol60/Beta | -1 | False | 60 日波动率/对基准 Beta |
| 规模 | LnMV | -1 | False | 对数流通市值 |
| 流动性 | Turn | -1 | False | 换手率 |
| 情绪 | HSGT/Flow/FUp | +1 | False | 北向持股/增持资金/增持幅度（⚠️ 仅 2014.11~2024.08） |
| 情绪 | MainFlow/SuperBig | +1 | False | 主力/超大单净流入（5 日均值, 2024 年至今） |

## 数据源说明

### 行情数据

A 股日频行情（后复权）通过 `PriceFetcher` 获取，支持沪深京主板/科创/创业/北交所。基准指数行情同接口。实时行情（市值/PE/PB）通过 `SpotFetcher` 获取并按 (date, ticker) 合并到 panel。

### 财报数据（PIT 对齐）

`FinancialFetcher` 通过东方财富 EM 三大报表接口获取利润表/资产负债表/现金流量表，衍生计算 ROE/ROA/毛利率/资产负债率等指标。财报数据通过 `pit_merge` 按 `announcement_date` 做 Point-in-Time 对齐，确保每个交易日只能使用已公告的最新财报，防止未来函数。

⚠️ **重要**：AKShare EM 接口返回的 `REPORT_DATE` / `NOTICE_DATE` 是 epoch 微秒（int64），`pd.to_datetime()` 不带 `unit` 参数会默认按纳秒解析导致日期被误译为 1970 年。项目使用 `to_datetime_safe()` 函数（`fetcher/base.py`）自动识别数值单位，所有日期转换均通过该函数处理。

### 北向资金（⚠️ 2014-11-17 ~ 2024-08-16）

港交所于 2024-08-16 起停止披露沪深股通个股级实时数据。`HSGTFetcher` 的 `stock_hsgt_individual_em` 接口数据**不再更新**，日期范围仅至 2024-08-16。

基于北向资金的 3 个情绪因子（HSGT/Flow/FUp）**仅适用于历史回测**（2014-11 ~ 2024-08），不可用于 2024 年 8 月之后的实时选股。

### 个股资金流（北向替代, 2024 年至今）

`FundFlowFetcher` 通过东财 `stock_individual_fund_flow` 接口获取个股资金流数据，提供主力/超大单/大单/中单/小单净流入，作为北向资金停止后的现代情绪因子数据源。

基于资金流的 2 个情绪因子（MainFlow/SuperBig）覆盖 2024 年至今，是与北向因子互补的现代数据源。在 `eval_all_factors.py` 中两套数据源同时拉取并合并到 panel：历史段用北向因子，现代段用资金流因子。

### 行业分类

`IndustryFetcher` 获取申万一级行业分类，用于横截面行业中性化。

## 核心链路

```
原始数据 → Universe(去ST/新股/停牌/低流动)
  → 财报PIT合并 + 北向/资金流合并 + spot行情合并
  → 因子 compute() → 横截面缩尾+行业/市值中性化 → 截面z-score
  → forward return(t+1持有→t+N平仓) → 对齐
  → 横截面IC/IR评估 → 分位组合单调性
  → 多因子IC加权合成 → Top-N%选股 → 月度调仓回测
```

## 验证结果

### 单因子（4 股 × Vol60）

| 持有期 | IC均值 | IR | 胜率 |
|--------|--------|-----|------|
| 1日 | -0.011 | -0.02 | 43.5% |
| 5日 | -0.042 | -0.07 | 41.9% |
| **21日** | **+0.043** | **0.07** | **46.6%** |

### 全量 24 因子（5 股 × 沪深 300, 2023-01 至今）

财报因子（RevG/NetG/EpG/ROE/ROA/GPM/Lev）经 PIT 对齐后正常切换报告期，不再出现全 panel 常数填充问题。情绪因子双源设计：历史段北向 + 现代段资金流。

## 项目进度

- [x] **Phase 1-3E**: 项目骨架 + 22 因子库 + fetcher + 处理器
- [x] **Phase 3Ga**: fetcher/spot.py + fetcher/fund_flow.py + 情绪因子双源化
- [x] **Phase 3Gb**: 修复 PIT merge dtype bug（epoch 微秒→datetime64）+ 整合资金流到脚本 + 重跑
- [x] **Phase 3I**: 更新 README + FACTOR_CATALOG，明确北向数据可用区间与替代方案
- [ ] **Phase 4**: 完整 24 因子组合 + 沪深 300 全量回测
- [ ] **Phase 5**: 港股通 universe + 汇率处理
- [ ] **Phase 6**: HTML 报告输出
