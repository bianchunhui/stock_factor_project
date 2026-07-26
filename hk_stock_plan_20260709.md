# 港股选股模块方案设计

> 2026-07-09 | 基于项目现有架构 + akshare API实测结果

---

## 一、A股 vs 港股：差异分析

| 维度 | A股 | 港股 |
|------|-----|------|
| **交易制度** | T+1，涨跌停±10%/20% | T+0，无涨跌停 |
| **交易时间** | 9:30-15:00（午休1.5h） | 9:30-16:00（午休1h），有盘前竞价 |
| **计价币种** | 人民币 CNY | 港币 HKD |
| **财报频率** | 季度（Q1/中报/Q3/年报） | 半年报+年报（部分有季报） |
| **财报科目** | 中文标准科目 | 中英文混合，IFRS格式 |
| **行业分类** | 申万一级 | 恒生行业分类（HICS） |
| **复权方式** | 后复权（hfq）为主 | 前复权（qfq）为主 |
| **做空** | 有限制（融券） | 成熟，卖空普遍 |
| **流动性** | 普遍较好 | 两极分化严重（头部活跃，小票仙股多） |
| **数据频率** | 日频/分钟 | 日频/分钟 |
| **财务可得性** | 东方财富完整 | 东方财富有港股财报（三大报表+指标） |

### 结论：**建议单独做，不合并**

原因：
1. **财务数据结构不同**：港股财报是IFRS，科目名称、报告频率（半年报为主）都和A股不同
2. **行业分类不同**：申万 vs 恒生HICS，中性化处理不能混用
3. **币种不同**：市值/成交额一个是CNY一个是HKD，截面比较无意义
4. **因子逻辑有差异**：港股的流动性因子权重应更高（仙股多），A股的ST/涨跌停因子港股没有
5. **数据源不同**：A股用新浪/baostock，港股用新浪stock_hk_daily

但**因子框架代码可以复用**（Factor基类、标准化流程、IC/IR评估等），只是数据加载和部分因子实现要分开。

---

## 二、选股池构建

### 目标：恒生指数成分股 ∩ 港股通标的

#### 2.1 恒生指数成分股

**实测结果**：`stock_hk_index_spot_em` 返回359个港股指数（含恒生指数HSI），但这是指数列表，不是成分股。

**获取恒生指数成分股的可行方案**：

方案A：akshare `stock_hk_index_spot_em` + 手动筛选HSI → ❌ 只返回指数行情，不含成分股

方案B：恒生指数公司官网 → 需要爬虫或API

方案C：**akshare港股实时行情 `stock_hk_spot_em`** → ❌ 当前网络不通

方案D：**新浪 `stock_hk_spot`** → 获取所有港股代码列表，然后需要另一个来源标记哪些是恒生指数成分

方案E：**港股通成分 `stock_hk_ggt_components_em`** → ❌ 当前网络不通

方案F：**东方财富网页爬取恒生指数成分股** → 可行但需要爬虫

方案G：**akshare `stock_zh_ah_name`** → 只返回A+H股，不是全部恒生成份

#### 2.2 推荐方案

```
恒生指数成分股：
  → 恒生指数公司官网API: https://www.hsi.com.hk/eng/indexes/all-indexes/hsi
  → 或直接用固定列表（恒生指数成分股变动频率低，约每季度调整一次）
  → 或尝试东财网页接口直接获取

港股通标的：
  → akshare stock_hk_ggt_components_em（当前网络偶尔不通，需重试）
  → 备选：沪深交易所官网爬取港股通名单
```

#### 2.3 交叉筛选

```python
# 伪代码
hsi_constituents = fetch_hsi_constituents()  # 恒生指数成分股 ~80只
ggt_constituents = fetch_ggt_constituents()  # 港股通标的 ~500+只
target_pool = hsi_constituents & ggt_constituents  # 交集 ~70-80只
```

预期规模：恒生指数成分股约80只，港股通约500只，交集约70-80只。

---

## 三、数据源方案

### 3.1 行情数据 ✅ 已验证可用

| 数据 | API | 状态 | 说明 |
|------|-----|------|------|
| 港股个股日频 | `ak.stock_hk_daily(symbol="00700", adjust="qfq")` | ✅ 可用 | 新浪源，2004年至今，含OHLCV |
| 恒生指数日频 | `ak.stock_hk_index_daily_sina(symbol="HSI")` | ✅ 可用 | 2013年至今，含OHLCV |
| 港股实时行情 | `ak.stock_hk_spot_em()` | ❌ 网络不通 | 东财源，需重试或换源 |

### 3.2 财务数据 ✅ 已验证可用

| 数据 | API | 状态 | 说明 |
|------|-----|------|------|
| 港股三大报表 | `ak.stock_financial_hk_report_em(stock="00700", symbol="利润表", indicator="年报")` | ✅ 可用 | 东财源，逐条返回科目 |
| 港股财务指标 | `ak.stock_financial_hk_analysis_indicator_em(symbol="00700", indicator="年报")` | ✅ 可用 | 含ROE/ROA/EPS/毛利率等，9期数据 |
| 港股估值 | `ak.stock_hk_valuation_baidu(symbol="00700", indicator="总市值", period="全部")` | ✅ 可用 | 百度源，620期历史估值数据 |

**注意**：港股财务指标API只返回9期数据（年报/半年报），比A股的86期少很多，因为港股以半年报+年报为主。

### 3.3 南向资金数据 ✅ 已验证可用（核心差异化因子）

| 数据 | API | 状态 | 说明 |
|------|-----|------|------|
| 南向资金整体净买额 | `ak.stock_hsgt_hist_em(symbol="南向资金")` | ✅ 可用 | 2014年至今，2666行 |
| 单只港股南向持股 | `ak.stock_hsgt_individual_em(symbol="00700")` | ✅ 可用 | 2024-07至今，469行 |
| 港股通机构持股统计 | `ak.stock_hsgt_institution_statistics_em(market="南向持股")` | 待测 | 可能可用 |

**关键发现**：南向资金个股持股数据（`stock_hsgt_individual_em`）对港股是**2024-07-09至今**，比A股北向数据（2024-08-16停报）更晚更新。这意味着南向资金因子是**港股独有的、可实时使用的alpha因子**！

---

## 四、因子设计

### 4.1 可复用因子（与A股相同逻辑，数据源不同）

| 因子类别 | 因子名 | 数据源 | 备注 |
|---------|--------|--------|------|
| **动量** | MOM_20D / MOM_60D / MOM_120D | stock_hk_daily | 日频收盘价 |
| **动量** | REV_5D / REV_20D | stock_hk_daily | 短期反转 |
| **波动** | VOL_60D / VOL_120D | stock_hk_daily | 已实现波动率 |
| **波动** | ILLIQ | stock_hk_daily | Amihud非流动性 |
| **技术** | TURN_20D / TURN_60D | stock_hk_daily | 换手率（需outstanding_share） |
| **技术** | CR_20D / CR_60D | stock_hk_daily | 量价相关 |
| **价值** | PE / PB | 财务指标 + 市值 | 需要股本数据 |
| **成长** | ROE / ROA / 毛利率 | stock_financial_hk_analysis_indicator_em | 直接获取 |
| **成长** | 营收增速 / 利润增速 | 同上 | YoY字段直接提供 |
| **质量** | 资产负债率 / 流动比率 | 同上 | 直接提供 |

### 4.2 港股独有因子

| 因子名 | 数据源 | 逻辑 |
|--------|--------|------|
| **SOUTH_HOLDING_PCT** | stock_hsgt_individual_em | 南向持股占比（绝对水平） |
| **SOUTH_HOLDING_CHG_20D** | 同上 | 南向持股20日变化（资金动向） |
| **SOUTH_HOLDING_CHG_60D** | 同上 | 南向持股60日变化 |
| **SOUTH_FLOW** | stock_hsgt_hist_em | 南向资金整体净流入（市场情绪） |
| **HK_PREMIUM** | A+H股价比 | A股对H股溢价率（如适用） |
| **HK_LIQUIDITY** | stock_hk_daily | 成交额/市值（港股流动性分化严重） |

### 4.3 因子总数

- 可复用：约18-20个（动量4+波动3+技术3+价值2+成长3+质量3）
- 港股独有：约5-6个
- **合计：约24个**（与A股因子数一致）

---

## 五、架构设计

```
stock_factor_project/
├── config/
│   └── settings.py          # 新增HK相关配置
├── fetcher/
│   ├── price.py             # 已有 get_hk_daily() ✅
│   ├── financial.py         # 新增 HKFinancialFetcher
│   ├── hsgt.py              # 扩展支持南向资金（当前只支持北向）
│   ├── industry.py          # 新增 HKIndustryFetcher（恒生行业分类）
│   └── spot.py              # 扩展支持港股spot
├── universe/
│   └── builder.py           # 已有 mode="HK" 框架 ✅，需完善实现
├── factors/
│   ├── base.py              # 复用 ✅
│   ├── momentum.py          # 复用 ✅
│   ├── volatility.py        # 复用 ✅
│   ├── technical.py         # 复用 ✅
│   ├── value.py             # 复用（数据源不同）✅
│   ├── quality.py           # 复用 ✅
│   ├── growth.py            # 复用 ✅
│   └── sentiment.py         # 新增南向资金因子
├── processor/               # 全部复用 ✅
├── scripts/
│   ├── download_hk_data.py  # 港股数据下载脚本
│   ├── run_hk_factor_calc.py # 港股因子计算
│   └── combine_a_hk.py      # A+港股组合选股
└── data/
    ├── cache/               # 共用缓存目录
    └── factors/
        ├── hs300_*.parquet  # A股因子面板（已有）
        └── hsi_*.parquet    # 港股因子面板（新增）
```

---

## 六、实施步骤

### Phase 1：数据基础设施（预计2-3小时）
1. 解决恒生指数成分股获取问题（东财网络重试 / 固定列表 / 爬虫）
2. 获取港股通标的列表
3. 交叉筛选确定最终选股池
4. 实现 HKFinancialFetcher（财报+指标）
5. 扩展 HSGTFetcher 支持南向资金

### Phase 2：数据下载（预计1-2小时）
1. 下载全部选股池港股日频行情
2. 下载财务指标数据
3. 下载南向持股数据
4. 下载恒生指数基准

### Phase 3：因子计算（预计1-2小时）
1. 适配因子计算脚本（从A股版改造）
2. 新增南向资金因子
3. 运行因子计算
4. 评估IC/IR

### Phase 4：组合选股（预计1小时）
1. 因子合成
2. 生成持仓
3. A+港股组合（可选）

---

## 七、关键风险

1. **东财网络不稳定**：多个EM接口超时，需重试机制 + 备选数据源
2. **港股财务数据频率低**：半年报+年报为主，PIT对齐点少，因子覆盖可能稀疏
3. **南向持股数据短**：只有2024-07至今，约2年，回测样本不足
4. **恒生成分股获取**：akshare无直接API，可能需要爬虫或固定列表
5. **港币/人民币汇率**：如做A+H组合选股，需处理汇率转换
