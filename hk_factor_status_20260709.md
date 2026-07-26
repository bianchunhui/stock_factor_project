# 港股因子计算完成状态 — 2026-07-09 17:43

## 因子计算结果

### Panel 概况
- 文件: data/hk_full_factor_panel.parquet
- Shape: 115,167 × 72
- 标的: 88 只 (HSI ∩ 港股通)
- 日期范围: 2021-01-04 ~ 2026-07-08
- 计算耗时: 107 秒

### 因子列表 (16 个有效)

| 因子 | 类别 | 方向 | 有效率 | 说明 |
|------|------|------|--------|------|
| EP | 价值 | +1 | 100% | 1/PE_TTM |
| BP | 价值 | +1 | 98.9% | 1/PB |
| SP | 价值 | +1 | 100% | 1/PS |
| CFP | 价值 | +1 | 0% | 无 PCF 数据，无效 |
| RevG | 成长 | +1 | 99.9% | 营收同比 |
| EpG | 成长 | +1 | 99.9% | 归母净利润同比 |
| ROE | 质量 | +1 | 98.9% | 净资产收益率 |
| ROA | 质量 | +1 | 98.9% | 总资产收益率 |
| GPM | 质量 | +1 | 85.9% | 毛利率 |
| Lev | 质量 | -1 | 98.9% | 资产负债率 |
| CFO | 质量 | +1 | 98.4% | 经营现金流/营收 |
| Mom12m | 动量 | +1 | 79.1% | 12月动量 |
| Rev1m | 动量 | -1 | 98.3% | 1月反转 |
| LnMV | 规模 | -1 | 100% | 对数市值 |
| Vol60 | 波动 | -1 | 97.7% | 60日年化波动率 |
| SBHolding | 南向资金 | +1 | 35.0% | 南向持股比例（港股独有）|
| SBFlow | 南向资金 | +1 | 32.0% | 南向持股20日变化率（港股独有）|

### 关键计算逻辑
- outstanding_share: 从 holder_profit / basic_eps 推算
- market_cap: close × outstanding_share (港币)
- PE_TTM: close / eps_ttm
- PB: close / bps
- PS: market_cap / total_revenue
- PIT merge: announcement_date = report_date + 90天
- 行业: 26 个（东财分类，中文）
- 标准化: winsorize(3σ) + industry/size neutralize + zscore

### 与 A 股因子体系对比
- A 股: 24 因子（含情绪/资金流/Turn/Beta）
- 港股: 16 因子（去 Turn/Beta/情绪，新增 SBHolding/SBFlow）
- 两套体系完全独立（币种不同，不混合排名）

### 脚本
- scripts/run_hk_factor_calc.py: 港股因子计算主脚本
- scripts/download_hk_data.py: 港股数据下载
- scripts/verify_hk_data.py: 数据验证

### 下一步
- [ ] IC/IR 因子评估
- [ ] 分组回测 (quintile portfolio)
- [ ] 因子相关性矩阵
- [ ] 补全 CFP 因子（需现金流数据）
- [ ] 补全 Beta 因子（HSI proxy 已有 bench_ret）
- [ ] 港股行业中文→英文映射
