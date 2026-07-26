# westock (腾讯自选股 MCP) 全量 API 清单

> 来源：westock-mcp 工具清单 + 官方 `westock-data` 文档（`commands.md` / `ai_usage_guide.md`）。
> 实际调用名 = `mcp__westock-mcp__<短名>`，经 `DeferExecuteTool` 调用。
> 行情类（quote/kline/minute/technical/chip）多支持 `codes` 批量；期货/外汇仅支持当日分时、不支持复权。

## A. 数据查询 API（`data_*`）

### 行情 / 时序
| API 短名 | 中文描述 |
|---|---|
| `data_search` | 搜索：股票/ETF/板块/指数/期货/外汇/日韩股，按关键词或代码 |
| `data_quote` | 实时行情快照：个股/指数/板块/ETF/期货/外汇/可转债，含估值·市值·52周·涨跌 |
| `data_kline` | K线行情：日/周/月/季/年，支持复权(qfq/hfq)与日期范围 |
| `data_minute` | 分时行情（1~5日） |
| `data_technical` | 技术指标：MA/MACD/KDJ/RSI/BOLL/BIAS/WR/DMI |
| `data_chip` | 筹码成本分布（仅沪深京A股，获利/套牢盘比例） |
| `data_lhb` | 龙虎榜（仅A股：机构榜/游资榜/活跃席位等） |

### 市场 / 指数
| API 短名 | 中文描述 |
|---|---|
| `data_index` | 指数数据：成份股(`constituent`)、指数清单(`list`) |
| `data_market_overview` | A股大盘画像总评：8维度（收盘/区间/技术/涨跌分布/两融/估值/风格轮动） |
| `data_connect` | 沪深港通标的池（沪股通/深股通成份股） |
| `data_ipo` | 新股日历（沪深/港股/美股申购与上市） |
| `data_changedist` | 市场涨跌分布（沪深A股全市场截面：涨跌/涨跌停/区间/成交额） |
| `data_north_holding` | 北向资金持仓（陆股通持股） |
| `data_south_holding` | 南向资金持仓（港股通持股） |
| `data_trade_calendar` | 交易日历 |

### 板块 / 研究 / 事件
| API 短名 | 中文描述 |
|---|---|
| `data_sector` | 板块/概念股：清单/搜索/成份股/行情榜/信息 |
| `data_score` | 个股综合评分（资金/基本面/风险/技术 + 周月季变动） |
| `data_rating` | 机构评级（港股/美股：目标价&评级/月度趋势/价vs目标价） |
| `data_consensus` | 一致预期（A股/港股盈利·营收预期） |
| `data_report` | 研报列表与详情 |
| `data_dehydrated` | 脱水研报（列表与详情） |
| `data_events` | 事件标签总览（42类：异动/股本/业绩/指数/董监高/股权/解禁/处罚/停复牌） |
| `data_calendar` | 投资日历（财报/分红/新股/停复牌/会议/解禁/增发） |
| `data_risk` | 风险事件（仅A股，8类：ST/质押/解禁/诉讼/增发/高管变动/增减持/评级） |
| `data_suspension` | 停复牌信息（沪深/港股/美股） |

### 资讯 / 资金 / 简况
| API 短名 | 中文描述 |
|---|---|
| `data_news` | 新闻（个股/指数/ETF/板块/期货/外汇列表与详情；另有 `news` 同义入口） |
| `data_notice` | 公告（个股公告列表与全文） |
| `data_fund_flow` | 资金流向：主力/散户/南北向（个股与板块） |
| `data_fund_short` | 卖空数据（港股/美股：卖空股数/金额/比率） |
| `data_fund_block` | 大宗交易（仅沪深） |
| `data_fund_margin` | 融资融券（仅沪深） |
| `data_profile` | 公司简况（基本信息） |
| `data_shareholder` | 股东结构（十大股东/流通/户数；港股持股+机构持仓） |
| `data_disclosure` | 财报披露日历（业绩预约披露日） |
| `data_dividend` | 分红派息（A股/港股/美股，历年） |
| `data_buyback` | 公司回购（A股/港股） |

### 财务 / ETF / 发现 / 宏观 / 跨市场
| API 短名 | 中文描述 |
|---|---|
| `data_finance` | 财务数据：三大报表（利润表/资产负债表/现金流量表，各市场 `type` 不同） |
| `data_etf` | ETF 全维度：详情/持仓/净值/公司/持有人/财务指标 |
| `data_hot` | 热搜榜（股票/微信/新闻/板块/ETF 热度） |
| `data_stocklist` | 公开股单榜单（rank 排行 / detail 详情） |
| `data_macro` | 宏观经济指标（GDP/CPI/PMI/货币/财政/就业/溢价率/预测等 27 个） |
| `data_industry_chain` | 产业链映射 |
| `data_futures` | 期货：合约搜索/资料（行情复用 quote/kline/minute） |
| `data_forex` | 外汇：品种列表/搜索（行情复用 quote/kline/minute） |
| `data_bond` | 可转债/可交换债：详情/条款/明细（行情复用 quote/kline/minute） |

> 合计：数据查询类 **45** 个（含 `news` 同义入口）。

## B. 选股 / 策略工具（`tool_*`）
| API 短名 | 中文描述 |
|---|---|
| `tool_filter` | 条件选股（自定义筛选条件） |
| `tool_strategy` | 策略选股（预置策略） |
| `tool_ranking` | 排行榜选股（按指标排名，如 CompScore 综合评分） |
| `tool_label` | 标的标签管理 |
| `tool_event` | 工具事件 |
| `tool_list_events` | 列出可用事件 |
| `tool_list_labels` | 列出可用标签 |
| `tool_list_presets` | 列出预置策略 |
| `tool_list_ranking_metrics` | 列出排行指标 |
| `tool_list_strategies` | 列出策略 |

> 合计：选股工具 **10** 个。

## C. 自选与模拟交易（`portfolio_*`）
| API 短名 | 中文描述 |
|---|---|
| `portfolio_watchlist` | 自选股列表/管理 |
| `portfolio_watchlist_add` | 加自选 |
| `portfolio_watchlist_batch_add` | 批量加自选 |
| `portfolio_watchlist_remove` | 移除自选 |
| `portfolio_watchlist_groups` | 自选分组 |
| `portfolio_watchlist_move` | 移动自选 |
| `portfolio_watchlist_sort` | 排序自选 |
| `portfolio_watchlist_pin` / `unpin` | 置顶 / 取消置顶自选 |
| `portfolio_watchlist_bottom` | 自选置底 |
| `portfolio_watchlist_note` | 自选备注 |
| `portfolio_group_add` | 分组：新建 |
| `portfolio_group_rename` | 分组：重命名 |
| `portfolio_group_sort` | 分组：排序 |
| `portfolio_paper_portfolio` | 模拟组合总览 |
| `portfolio_paper_positions` | 模拟持仓 |
| `portfolio_paper_trade` | 模拟交易 |
| `portfolio_paper_profit` | 模拟收益 |
| `portfolio_paper_history` | 模拟历史 |
| `portfolio_paper_cancel` | 撤销模拟单 |
| `portfolio_tips_query` | 小贴士：查询 |
| `portfolio_tips_set` | 小贴士：设置 |

> 合计：自选/模拟交易 **22** 个。

---

## 备注：三个因子 Skill 实际仅用 4 个数据 API
A股/港股/美股三个因子 skill 只调用了 `data_kline`、`data_quote`、`data_finance`、`data_fund_flow`（外加用 `data_kline` 拉基准指数）。其余 40+ 个 API 目前未用于因子计算，但可作为因子增强候选，例如：
- `data_technical` —— 技术指标因子（MA/MACD/RSI/KDJ…）
- `data_score` —— 综合评分因子（资金/基本面/风险/技术）
- `data_macro` —— 宏观因子（利率/通胀/景气）
- `data_consensus` —— 一致预期成长因子
- `data_fund_short` —— 卖空比率（港股/美股做空情绪）
- `data_north_holding` / `data_south_holding` —— 南北向持仓变化（资金面）
