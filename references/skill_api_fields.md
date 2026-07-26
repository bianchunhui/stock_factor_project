# 三个因子 Skill 实际使用的 westock API 与字段

> 数据来源：三个 skill 的 `land.py` 解析层（逐行核对，非凭记忆）。  
> 调用方式：AI 通过 `DeferExecuteTool` 调用 `mcp__westock-mcp__<短名>`，大响应自动落盘到 `data/raw/*.json`，`land.py` 解析成 parquet 面板。  
> 代码前缀：A股 `sh/sz+6位`，港股 `hk+5位`，美股 `us+代码`；`_ticker()` 去掉 2 位前缀作内部键。

## 0. 调用矩阵（一眼看清谁用了什么）

| westock API           |  A股 cn-stock-factor  | 港股 hk-stock-factor | 美股 us-stock-selector |
| --------------------- | :------------------: | :----------------: | :------------------: |
| `data_kline`（日线 qfq）  |           ✅          |          ✅         |           ✅          |
| `data_quote`（估值快照）    |           ✅          |          ✅         |           ✅          |
| `data_finance`（财报）    |  ✅ income + balance  |    ✅ income（综合）    |          ❌ 无         |
| `data_fund_flow`（资金流） |           ✅          |          ✅         |          ❌ 无         |
| 基准指数（`data_kline` 复用） | 沪深300（代码 `sh000300`） |  hkHSI（代码 `hkHSI`） |   usDJI（代码 `usDJI`）  |



> 注意：美股 skill 文件名为 `us_price.parquet` / `us_quote.parquet` / `us_dji.parquet`，与 A/H 的 `panel_price`/`spot_all`/`benchmark` 命名不同，但数据来源、解析逻辑一致。

---

## 1. `data_kline` —— K线（三市场共用同一节点结构）

**请求参数**：`codes`（批量）、`period=day`、`fq=qfq`、`limit=N`（如 260）  
**节点字段（raw → 内部列）**：

| raw 字段     | 含义   | 内部列（A/H）   | 内部列（us）  |
| ---------- | ---- | ---------- | -------- |
| `date`     | 日期   | `date`     | `date`   |
| `open`     | 开盘   | `open`     | `open`   |
| `high`     | 最高   | `high`     | `high`   |
| `low`      | 最低   | `low`      | `low`    |
| `last`     | 收盘   | `close`    | `close`  |
| `volume`   | 成交量  | `volume`   | `volume` |
| `amount`   | 成交额  | `amount`   | `amount` |
| `exchange` | 换手率% | `turnover` | ❌ 美股不取   |

**基准指数**：复用 `data_kline`，只取 `date` + `last`（内部列 `bench_close`）。

---

## 2. `data_quote` —— 实时行情快照（字段差异最大）

### A股（cn）

| raw 字段                           | 含义          | 内部列                              |
| -------------------------------- | ----------- | -------------------------------- |
| `name`                           | 名称          | `name`                           |
| `price`                          | 现价          | `price`                          |
| `pe_ratio`                       | 动态 PE       | `pe`                             |
| `pe_lyr`                         | 静态 PE       | `pe_lyr`                         |
| `pb_ratio`                       | 市净率         | `pb`                             |
| `dividend_ratio_ttm`             | 股息率(TTM)    | `div_yield`                      |
| `total_market_cap`               | 总市值         | `mktcap`                         |
| `circulating_market_cap`         | 流通市值        | `circ_mktcap`                    |
| `total_shares`                   | 总股本         | `total_shares`                   |
| `high_52week`                    | 52周最高       | `high_52w`                       |
| `low_52week`                     | 52周最低       | `low_52w`                        |
| `chg_5d` / `chg_20d` / `chg_60d` | 5/20/60日涨跌% | `chg_5d` / `chg_20d` / `chg_60d` |
| `chg_ytd`                        | 年初至今涨跌%     | `chg_ytd`                        |
| `turnover_rate`                  | 换手率         | `turnover_rate`                  |
| `volume_ratio`                   | 量比          | `volume_ratio`                   |
| `time`                           | 时间戳         | `as_of`                          |

### 港股（hk）

比 A股 **少 4 个字段**：`pe_lyr`、`circulating_market_cap`、`turnover_rate`、`volume_ratio`。  
其余：`name, price, pe_ratio, pb_ratio, dividend_ratio_ttm, total_market_cap, high_52week, low_52week, chg_5d, chg_20d, chg_60d, chg_ytd, time`（内部列名同 A股）。

### 美股（us）

只取估值 4 项 + 价 + 时间，**无** 52周高低、短期涨跌、股息率：  
`pe_ratio, pb_ratio, total_market_cap, total_shares, price, time`  
→ 内部列：`pe_ratio, pb_ratio, total_market_cap, total_shares, price, fetch_date`。

---

## 3. `data_finance` —— 财务数据

### A股 income（利润表，`type=income`）

| raw 字段                     | 含义         | 内部列                |
| -------------------------- | ---------- | ------------------ |
| `EndDate`                  | 报告期        | `end_date`         |
| `OperatingRevenueTTM`      | 营业总收入(TTM) | `revenue_ttm`      |
| `GrossProfitTTM`           | 毛利(TTM)    | `gross_profit_ttm` |
| `NPParentCompanyOwnersTTM` | 归母净利润(TTM) | `np_ttm`           |
| `OperatingProfitTTM`       | 营业利润(TTM)  | `op_profit_ttm`    |
| `TotalOperatingRevenueTTM` | 总营收(TTM)   | `total_rev_ttm`    |
| `BasicEPS`                 | 基本每股收益     | `basic_eps`        |

### A股 balance（资产负债表，`type=balance`）

| raw 字段                   | 含义      | 内部列                   |
| ------------------------ | ------- | --------------------- |
| `EndDate`                | 报告期     | `end_date`            |
| `TotalCurrentAssets`     | 流动资产合计  | `total_assets`(与下项相加) |
| `TotalNonCurrentAssets`  | 非流动资产合计 | `total_assets`(与上项相加) |
| `TotalShareholderEquity` | 股东权益合计  | `equity`              |
| `TotalLiability`         | 负债合计    | `total_liability`     |

> A股需 income + balance 按 `[ticker, end_date]` 合并：ROE/资产负债率靠 balance，成长率(YoY)需多期算。

### 港股 income（综合财报，`type=income`，**单次即含比率与成长**）

| raw 字段                 | 含义        | 内部列             |
| ---------------------- | --------- | --------------- |
| `EndDate`              | 报告期       | `end_date`      |
| `OperatingIncome`      | 营业收入      | `revenue_ttm`   |
| `OperatingProfit`      | 营业利润      | `op_profit_ttm` |
| `GrossIncomeRatio`     | 毛利率%      | `gpm_ratio`     |
| `RoeWeighted`          | 加权 ROE%   | `roe_ratio`     |
| `DebtAssetsRatio`      | 资产负债率%    | `lev_ratio`     |
| `ROA`                  | 总资产收益率%   | `roa`           |
| `ProfitToShareholders` | 归母净利润     | `np`            |
| `BasicEPS`             | 基本每股收益    | `eps`           |
| `OperatingRevenueGr1y` | 营收 YoY%   | `revg`          |
| `NpParentCompanyGr1y`  | 归母净利 YoY% | `npg`           |

> 港股**无需 balance**——ROE/负债率/毛利率/营收·净利成长率都在 income 里直接给。

### 美股

`data_finance` **未使用**（skill 明确无美股财报接口）。

---

## 4. `data_fund_flow` —— 资金流向

### A股

| raw 字段               | 含义        | 内部列                     |
| -------------------- | --------- | ----------------------- |
| `MainNetFlow`        | 主力净流      | `main_net_flow`         |
| `MainNetFlow5D`      | 主力 5日净流   | `main_net_flow_5d`      |
| `MainNetFlow20D`     | 主力 20日净流  | `main_net_flow_20d`     |
| `RetailInFlow`       | 散户流入      | 入参（见下）                  |
| `RetailOutFlow`      | 散户流出      | 入参（见下）                  |
| `BlockNetFlow`       | 特大单净流     | `block_net_flow`        |
| `JumboNetFlow`       | 大单净流      | `jumbo_net_flow`        |
| `MidNetFlow`         | 中单净流      | `mid_net_flow`          |
| `SmallNetFlow`       | 小单净流      | `small_net_flow`        |
| `MainInflowCircRate` | 主力流入占流通盘比 | `main_inflow_circ_rate` |

> 散户净流 **自行计算**：`retail_net_flow = RetailInFlow − RetailOutFlow`（westock 只给 In/Out，无直接 Net）。

### 港股

仅当日快照，**无 N 日累计**：  
`MainNetFlow`(主力净流) / `RetailNetFlow`(散户净流) / `TotalNetFlow`(总净流)  
→ 内部列同名 `main_net_flow / retail_net_flow / total_net_flow`。

### 美股

`data_fund_flow` **未使用**。

---

## 5. 跨市场字段差异速记（影响统一因子设计）

1. **quote 三市场不统一**：A股最全（含 `pe_lyr/circ_mktcap/turnover_rate/volume_ratio`），港股少 4 项，美股只 4 个估值项。
   - 可统一因子：`EP=1/pe`、`BP=1/pb`、`LnMV=ln(mktcap)`（三市场都有 `pe_ratio/pb_ratio/total_market_cap`）。
   - 仅 A股有：`turnover_rate`、`volume_ratio`（量价情绪类因子）。
2. **finance 港 vs A 结构不同**：港股单次 income 齐活；A股要 income+balance 合并，且 YoY/ROE/负债率需多期或 balance。
3. **fund_flow 港股仅快照**：回测中因子值不随时间更新（除非补历史接口）；A股有 `5D/20D` 累计可跨期。
4. **美股字段最少**：只有 kline + quote（4 个估值项），无财报、无资金流。
