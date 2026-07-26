# 多因子选股项目 · 代码审查报告
日期：2026-07-10
审查范围：`factors/`、`fetcher/`、`evaluator/`、`processor/`、`backtest/`、`scripts/select_stocks.py`
方法：Explore 子代理通读全代码 + 主 agent 亲自验证最致命疑点（读源码核对）

---

## 一、总体结论（先给你定心丸）

**没有发现因子方向反转、选股反转这类致命逻辑 bug。**

之前遇到的江波龙/百济神州异常、行情缺失、北向空值，全部是**「数据层」问题**（数据源停更、接口参数漂移、缓存完整性缺失），不是因子逻辑本身写错了。因子方向、PIT 对齐、合成、选股主逻辑均经核对确认正确。

但存在 **4 个中等程度问题**（方法论 / 健壮性），其中「滚动 IC 前视偏差」对选股权重有轻微但真实的影响，建议优先修。

---

## 二、已亲自验证的重点问题

### 中危-1 ｜ 滚动 IC 权重存在前视偏差（最该优先修）⭐
- **位置**：`scripts/select_stocks.py:189-213`
- **现象**：`forward_21d_return` 对整张 panel 一次性算好；IC 估计窗口
  `window_data = panel[(date>=start) & (date < d)]` 只排除 `d` 当月，
  **未排除 `d` 之前 21 个交易日内**的行。这些行的 forward return 用到了
  `close[t+21]`（其中 `t+21 > d`，即 `d` 之后才发生的收益）去估计 `d` 月的因子权重。
- **影响**：walk-forward「无前视」被破坏，系统性高估权重稳定性；泄漏约窗口的 1/12（≈1 个月）。
- **修复**：窗口改为 `panel["date"] < d - pd.DateOffset(days=21)`（或交易日偏移），
  保证窗口内所有 `t` 的 `t+21 ≤ d`。

### 中危-2 ｜ 北向僵尸因子默认仍拉取（已确认 2026 截面安全，但应清理）
- **位置**：`scripts/select_stocks.py:419`、`factors/sentiment.py:157`
- **现象**：`HSGT/Flow/FUp` 数据仅至 2024-08-16，但默认 `not args.skip_hsgt` 仍每次去拉；
  `SENTIMENT_FACTORS` 仍包含它们。
- **安全确认（已读源码）**：`fetch_and_merge_hsgt`（`eval_all_factors.py:161`）为
  **精确日期 merge（无 forward-fill）**，2024-08-16 之后北向列为 NaN；
  合成 `combine_factors_rolling_ic` 用 `mask=notna` 做 NaN-tolerant 加权，全 NaN 因子不参与
  → **2026 截面不会全 NaN、不会选股反转**。
- **残留问题**：① 每次运行白拉已停更接口（慢且必空）；② 等权回退 / 权重日志把 3 个僵尸计入分母，日志失真。
- **修复**：默认开启 `--skip-hsgt`；或在合成前按 `HSGT_DATA_END_DATE` 动态剔除已失效因子。

### 中危-3 ｜ 诊断脚本 IC 未应用 direction（仅展示层误导）
- **位置**：`scripts/eval_all_factors.py:277-280`
- **现象**：对原始 `z_col`（未乘 direction）算 IC。对 `direction=-1` 的因子
  （Lev/Vol60/LnMV/Rev1m/Turn/Beta），原始 z 越大越差 → IC 为负，
  汇总表按 ir 降序把它们排末尾，容易误判「因子无效」。
- **影响**：不影响实盘（合成走 `_dz` 已乘方向），**只影响人工解读因子排名**。
- **修复**：诊断也基于 `_dz` 算 IC，与合成口径一致。

### 中危-4 ｜ 缓存命中无 schema/行数校验（脏缓存静默复用风险）
- **位置**：`fetcher/base.py:110-117`
- **现象**：`_load_cache` 仅检查文件存在 + 能 `read_parquet`，不校验预期列是否齐全、行数 > 0、关键列非空。
  若 akshare 改列名 / 返回空壳 / 半截数据，旧缓存被静默复用 → 下游 KeyError 或悄悄全 NaN。
- **修复**：命中时校验「预期列集合 + 行数阈值 + 关键列非空占比」，不满足则失效重抓。

---

## 三、低危清单（认同 Explore 发现，非紧急）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 低1 | `processor/align.py:46` | forward return 用 `close[t]` 买入，含同日收益 | 轻微同日乐观偏差（对动量无泄漏，对价值/质量有轻微） |
| 低2 | `backtest/backtest.py:75` | 调仓日对新组合计当日收益 | 轻微高估收益、低估首日波动 |
| 低3 | `fetcher/financial.py:287` | 公告日 Q1 估算 lag=120 天 | 保守（不偷看未来），仅使 4–7 月基本面因子偏旧 |
| 低4 | `processor/pit_align.py:98` | `pit_merge` 重排行顺序但 docstring 称不变 | 当前下游不敏感，无功能 bug |
| 低5 | `config/universe.py:65` | CFO 目录描述"现金流/净利润"与实际"现金流/营收"不符 | 仅文档误导 |
| 低6 | `fetcher/price.py:135` | 缓存键不含 `market`/`skip_em` | 切换数据源可能命中同名缓存 |
| 低7 | `processor/normalize.py:34` | 小截面(<need+2)跳过中性化 | 仅 `--max-stocks 5` 调试时显著，全量 300 只无碍 |

---

## 四、明确「未发现明显问题」的维度

- **因子方向**：24 因子 `direction` 与含义一致，合成经 `_dz` 统一取负，无反转。✅
- **PIT 对齐**：`merge_asof(direction="backward")` 正确；公告日 NaT 已 `dropna` + 估算兜底。✅
- **标准化/缺失值**：z-score 有 `min_count` 守卫、winsorize ±3σ、中性化方向正确、NaN 由合成层 tolerant 处理。✅
- **合成逻辑**：权重为正（IC>0 门控）、IR 阈值过滤、NaN 自动重分配均正确。✅
- **选股逻辑**：每月独立 `nlargest`；最新日全 NaN 回退到最近有效日，逻辑正确。✅
- **回测主逻辑**：未用未来数据（除低2近似）、已计交易成本、净值 `cumprod` 正确。✅

---

## 五、建议优先修复顺序

1. **滚动 IC 窗口边界**（一行改动，消除前视）— 中危-1
2. **默认 skip 北向 + 动态剔除失效因子** — 中危-2
3. **诊断 IC 与合成口径统一** — 中危-3
4. **缓存加 schema/行数校验** — 中危-4

> 以上 4 项均为「非紧急但值得做」的加固；中危-1 对结果影响最大，建议最先处理。
