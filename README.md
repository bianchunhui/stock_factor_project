# 多因子选股量化系统

跨市场（**A股沪深300 / 港股恒生指数∩港股通 / 美股道琼斯30**）多因子选股框架，覆盖 24 个因子（价值/成长/质量/动量/波动/规模/流动性/情绪）。

数据落地采用 **SQLite 分库**（不再依赖散落 parquet），通过本地 Streamlit 面板实现「补数 + 因子计算 + 选股」一站式操作。

## 目录结构

```
stock_factor_project/
├── config/
│   ├── settings.py          # 项目根/数据路径/抓取参数
│   └── universe.py          # 市场过滤参数、基准、FACTOR_CATALOG(24因子)
├── fetcher/                 # 数据抓取层（akshare / westock / yfinance）
│   ├── base.py              # BaseFetcher: 节流/重试/parquet缓存/to_datetime_safe
│   ├── price.py             # A股/港股/指数日频行情（后复权）
│   ├── calendar.py          # 交易日历/调仓日
│   ├── financial.py         # 三大报表(利润/资产负债/现金流) + 衍生指标
│   ├── hsgt.py              # 沪深港通北向持股（⚠️ 数据截至 2024-08-16）
│   ├── fund_flow.py         # westock 个股资金流（北向替代, 2024年至今可用）
│   ├── industry.py          # 申万行业分类映射
│   ├── spot.py              # 实时行情（市值/PE/PB）
│   └── store/db.py          # SQLite 分库读写（ashare.db / hk.db / us.db）
├── universe/                # 选股池构建
│   └── builder.py           # Universe(A/HK/US): 成分获取 + ST/新股/流动性过滤
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
│   ├── ic_ir.py             # 横截面 IC/IR (groupby date -> spearman)
│   └── returns.py           # 分位组合收益/单调性
├── portfolio/               # 组合构建
│   ├── combine.py           # 因子合成 (等权/IC加权/逆方差)
│   ├── builder.py           # Top-N%选股+加权
│   └── backtest.py          # 向量化回测引擎
├── backtest/                # 指标与成本
│   ├── metrics.py           # 年化/夏普/回撤/信息比率
│   └── costs.py             # A股/港股通/美股交易成本
├── risk/                    # 风控
│   └── controls.py          # 权重约束/行业暴露
├── scripts/
│   ├── streamlit_app.py     # ★ 主面板：三市场补数+因子+选股
│   ├── _download_a_share.py # A股行情下载（区间参数）
│   ├── download_hk_data.py  # 港股数据下载
│   ├── download_us_data.py  # 美股数据下载
│   ├── run_factor_calc.py   # A股全量因子计算（含资金流 merge）
│   ├── run_hk_factor_calc.py / run_us_factor_calc.py
│   ├── select_stocks.py     # A股 IC加权选股
│   ├── build_composite_hk.py / build_composite_us.py
│   ├── westock_fetcher.py   # 资金流日更（CLI 逐日区间循环）
│   ├── backfill_fund_flow_mcp.py  # MCP 历史资金流回补落库
│   ├── eval_single_factor.py / eval_all_factors.py
│   └── verify_pit_merge.py  # 验证PIT对齐正确性
├── tools/westock_cli/       # vendored westock CLI（资金流日更，token 内置）
├── tests/test_fetch.py      # 连通性测试
├── data/
│   ├── db/{ashare,hk,us}.db # ★ SQLite 主存储（已 gitignore，本地生成）
│   ├── cache/               # 原始数据 parquet 缓存（中间层）
│   ├── factors/             # 因子结果 parquet
│   └── reports/             # 选股/回测 HTML+CSV 报告
├── start_dashboard.ps1      # 启动 Streamlit 面板（端口 8501）
├── stop_dashboard.ps1       # 停止面板
└── run_ashare.bat / run_hk.bat / run_us.bat  # 纯命令行一键跑全流程
```

## 快速开始

### 方式一：Streamlit 面板（推荐）

```powershell
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动面板（默认 http://localhost:8501）
.\start_dashboard.ps1
# 停止：.\stop_dashboard.ps1
```

面板三个 Tab（A股 / 港股 / 美股），每个 Tab 两块：

1. **数据覆盖区间 + 补数（含因子计算）**
   - 填开始/结束日期 → 点「⚡ 补数 + 因子计算」
   - 自动跑：行情下载 → 资金流增量(westock CLI) → 全量因子重算
2. **执行选股（IC加权）+ 结果展示**
   - 输出最新持仓 CSV/HTML 到 `data/reports/`

### 方式二：纯命令行一键跑

```bash
# A股完整流程：下载行情/财务 -> 24因子 -> IC加权合成 -> 月度调仓回测 -> 输出持仓
run_ashare.bat
# 港股 / 美股 同理：run_hk.bat / run_us.bat
```

### 方式三：分步调试 / 因子评估

```bash
python tests/test_fetch.py                    # 连通性测试
python scripts/eval_single_factor.py          # 单因子评估(默认Vol60)
python scripts/eval_single_factor.py --factor Mom12m --index 000905 --max-stocks 100
python scripts/eval_all_factors.py            # 全量24因子评估
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

### 行情 / 财务（akshare）

A 股日频行情（后复权）、基准指数行情、实时行情（市值/PE/PB）通过 akshare 获取。
财报数据（`FinancialFetcher`）通过东方财富 EM 三大报表接口获取利润表/资产负债表/现金流量表，衍生计算 ROE/ROA/毛利率/资产负债率等指标，并按 `announcement_date` 做 **Point-in-Time 对齐**，防止未来函数。

⚠️ **重要**：AKShare EM 接口返回的 `REPORT_DATE` / `NOTICE_DATE` 是 epoch 微秒（int64），`pd.to_datetime()` 不带 `unit` 参数会默认按纳秒解析导致日期被误译为 1970 年。项目使用 `to_datetime_safe()` 函数（`fetcher/base.py`）自动识别数值单位。

### 北向资金（⚠️ 2014-11-17 ~ 2024-08-16，已停更）

港交所于 2024-08-16 起停止披露沪深股通个股级实时数据。基于北向资金的 3 个情绪因子（HSGT/Flow/FUp）**仅适用于历史回测**，不可用于实时选股。

### 个股资金流（北向替代, 2024 年至今）— westock 双路

2026-07 重构，**彻底弃用东财个股资金流接口**，改用腾讯自选股 westock：

- **历史回补**：MCP `data_fund_flow(start, end)` 批量回填空历史 → `backfill_fund_flow_mcp.py` 落 SQLite（一次性）。
- **日更增量**：vendored westock CLI（`tools/westock_cli/scripts/index.js asfund`）逐日 append 当日快照，走类似行情的增量更新方式，由面板「补数」按钮或 `westock_fetcher.py` 触发。

字段映射（westock -> db 列，单位均为「元」）：
`MainNetFlow→main_net_inflow`、`JumboNetFlow→super_big_net_inflow`、`BlockNetFlow→big_net_inflow`、`MidNetFlow→mid_net_inflow`、`SmallNetFlow→small_net_inflow`。

### 港股 / 美股

- 港股：恒生指数成分 ∩ 港股通标的，行情/财务经 `download_hk_data.py` 落 `hk.db`。
- 美股：道琼斯 30 成分，行情经 `download_us_data.py`（yfinance）落 `us.db`。

### 行业分类

`IndustryFetcher` 获取申万一级行业分类，用于横截面行业中性化。

## 存储（SQLite 分库）

三市场各自独立数据库，置于 `data/db/`（**已加入 .gitignore，不入库**）：

| 库 | 市场 |
|----|------|
| `ashare.db` | A股（沪深300） |
| `hk.db` | 港股 |
| `us.db` | 美股 |

核心表：`daily_price`（日频行情）、`fund_flow`（资金流，westock）、`financial_income/balance/cashflow/indicator`（财报）、`factor_panel`（24 因子原始值+标准化值）、`ref_*`（`ref_universe`/`ref_index_weight`/`ref_industry_map`/`ref_shares` 等参考表）。

因子计算（`run_factor_calc.py`）读取全量行情+全量资金流，对所有历史日期 **全量重算** 并 upsert 覆盖 `factor_panel`——即使只补两天增量，也是整段历史重算。

## 核心链路

```
原始数据(akshare/westock/yfinance) → SQLite 分库
  → Universe(去ST/新股/停牌/低流动)
  → 财报PIT合并 + 资金流(westock)合并 + spot行情合并
  → 因子 compute() → 横截面缩尾+行业/市值中性化 → 截面z-score
  → forward return(t+1持有→t+N平仓) → 对齐
  → 横截面IC/IR评估 → 分位组合单调性
  → 多因子IC加权合成 → Top-N%选股 → 月度调仓回测
```

## 项目进度

- [x] 项目骨架 + 24 因子库 + fetcher + 处理器
- [x] 情绪因子双源化（北向历史 + 资金流现代）
- [x] 财报 PIT 对齐 dtype 修复（epoch 微秒→datetime64）
- [x] 资金流数据源重构：弃东财 → westock（MCP 历史 + CLI 日更）
- [x] SQLite 分库存储（替代散落 parquet）
- [x] 港股通 / 美股（道指）universe + 因子计算 + 选股
- [x] Streamlit 三市场面板（补数+因子+选股一站式）
- [x] HTML 报告输出
```
