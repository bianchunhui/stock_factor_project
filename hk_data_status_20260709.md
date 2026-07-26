# 港股数据下载完成状态 — 2026-07-09

## 标的池
- **恒生指数成分股**：93 只（东财软件导出 Table.xlsx）
- **港股通标的**：615 只（东财导出沪港通/深港通 TXT，两名单完全一致）
- **最终标的池（HSI ∩ 港股通）**：88 只
- 排除 5 只非港股通：00823领展房产基金、09618京东集团-SW、09888百度集团-SW、09901新东方-S、09961携程集团-S

## 下载结果

### 1. 港股行情 (hk_panel_price.parquet)
- **行数**: 115,167
- **标的**: 88/88 (100%)
- **日期范围**: 2021-01-04 ~ 2026-07-08
- **列**: date, open, high, low, close, volume, amount, ticker
- **NaN**: close=0, volume=0
- **每只行数**: min=280, max=1352, median=1352 (约5.5年完整数据)
- **数据源**: akshare stock_hk_daily (新浪源, 前复权 qfq)
- **基准**: 02800 Tracker Fund 作为 HSI proxy (1352行, stock_hk_index_daily_sina 有 bug)

### 2. 港股财务指标 (hk_panel_financial.parquet)
- **行数**: 1,244
- **标的**: 88/88 (100%)
- **报告日期范围**: 2016-11-30 ~ 2026-03-31
- **每只行数**: min=10, max=16 (年度+报告期)
- **关键列**: basic_eps, bps, revenue_yoy, gross_margin, holder_profit, eps_ttm 等 (37列)
- **数据源**: akshare stock_financial_hk_analysis_indicator_em

### 3. 南向持股 (hk_panel_hsgt.parquet)
- **行数**: 40,434
- **标的**: 88/88 (100%)
- **日期范围**: 2024-07-09 ~ 2026-07-08 (约2年)
- **每只行数**: min=4, max=469, median=469
- **核心字段**: date, holding_shares, holding_value, holding_pct, ticker
- **holding_pct**: mean=12.68%, max=74.86%
- **数据源**: akshare stock_hsgt_individual_em

### 4. 缓存
- **总缓存文件**: 2,089 个 (A股 1,823 + 港股 266)
- **总大小**: 223.9 MB

## 脚本
| 脚本 | 功能 |
|------|------|
| scripts/clean_hsi_xlsx.py | 清洗东财 HSI 93 只 xlsx |
| scripts/parse_ggt_txt.py | 解析沪/深港通 TXT + 交叉验证 |
| scripts/download_hk_data.py | 港股批量下载（行情+财务+南向持股）|
| scripts/verify_hk_data.py | 数据质量验证 |

## 输出文件
| 文件 | 说明 |
|------|------|
| data/hsi_constituents_20260709.csv | 93 只恒指成分股 |
| data/hkgt_all.csv | 615 只港股通完整名单 |
| data/hsi_and_hkgt_20260709.csv | 93 只 + 港股通标记 |
| data/hsi_hkgt_universe_20260709.csv | 88 只最终标的池 |
| data/hk_panel_price.parquet | 港股行情 panel |
| data/hk_panel_financial.parquet | 港股财务指标 panel |
| data/hk_panel_hsgt.parquet | 南向持股 panel |

## 下一步
- [ ] 港股因子计算（适配现有 A 股因子模块）
  - 价值: PE/PB/PS (从财务指标 + 市值计算)
  - 成长: revenue_yoy / holder_profit_yoy / gross_profit_yoy
  - 质量: ROE / gross_margin / debt_ratio
  - 动量: 1M/3M/6M/12M return
  - 波动率: 20日/60日/120日波动率
  - 流动性: 20日平均成交额 / 换手率
  - 资金流: 南向持股比例变化 (holding_pct delta)
- [ ] 港币/人民币汇率处理（如需合并 A+H 因子面板）
- [ ] 港股行业分类映射（东财行业 → 因子中性化用行业分组）
- [ ] 因子评估（IC/IR/分组回测）+ A股对比
