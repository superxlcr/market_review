# A股复盘系统 — 架构文档

> 最后更新：2026-06-21

## 1. 系统概述

基于 Streamlit 的 A 股每日复盘仪表盘。用户在**控制台**选择交易日 → 系统自动加载数据 → 展示市场全景 + 板块分析 + 个股追踪。AI 在每个板块顶部生成导语总结。

**核心理念：**
- **LLM 做推理**（趋势判断、状态归类、文字总结）
- **代码做计算**（均线、指标、公式筛选、权重贡献）
- **数据提前加载到本地缓存**，Dashboard 只读缓存
- **AI 只给数据和用法说明，不下结论** — 列表给 AI 自己找规律

## 2. 架构总览

```
Dashboard (Streamlit, 4 pages)
  └── DashboardService  (统一服务门面)
        ├── DataProvider   (数据抽象层)
        │     └── CacheManager  (SQLite 缓存)
        │           └── schema.sql
        ├── Tools  (纯计算模块)
        │     ├── technical.py       # 技术指标 (MA/KD/RSI/BIAS/背离)
        │     ├── contribution.py    # 权重贡献分析
        │     ├── wave33.py          # 3浪3选股公式
        │     └── kline_patterns.py  # K线形态识别
        └── LLM  (AI 总结)
              ├── OpenAIClient       # LLM 客户端
              ├── concurrent.py      # 并发 LLM 调用
              ├── system.md          # 共享系统提示词
              └── prompts/           # 各板块用户提示词模板
```

**与原始设计的差异：** 系统已从 CrewAI Flow 架构完全重构为纯 Streamlit + 服务层架构。不再使用 CrewAI Agent 编排，所有逻辑由 `DashboardService` 直接调用工具模块完成，AI 总结通过 LLM 直调实现。

## 3. 项目目录结构

```
marketreview/
├── architecture.md               ← 本文件
├── AGENTS.md                     # CrewAI 参考（保留用于模板参考）
├── dashboard/
│   ├── app.py                    # Streamlit 入口（多页面导航）
│   ├── pages/
│   │   ├── 00_控制台.py          # 日期选择 + 数据加载 + AI 总结触发
│   │   ├── 01_市场全景.py        # 大盘分析（上证/创业板）+ 33公式
│   │   ├── 02_板块分析.py        # 行业板块分析
│   │   └── 03_个股追踪.py        # 自选股追踪
│   ├── rendering/
│   │   ├── charts.py             # Plotly 图表构建（K线+均线+成交量）
│   │   └── styles.py             # 颜色工具 + CSS
│   └── services/
│       └── dashboard_service.py  # 统一服务门面
├── src/marketreview/
│   ├── data/
│   │   ├── cache_manager.py      # SQLite 缓存读写
│   │   ├── data_provider.py      # 数据抽象层（tushare → 缓存）
│   │   └── schema.sql            # DDL（8 表 + 索引）
│   ├── tools/
│   │   ├── technical.py          # 技术分析工具
│   │   ├── contribution.py       # 权重贡献 + 行业频率
│   │   ├── wave33.py             # 33 公式选股
│   │   └── kline_patterns.py     # K 线形态检测
│   ├── llm/
│   │   ├── __init__.py           # LLMClient 抽象 + 工厂
│   │   ├── openai_client.py      # OpenAI-compatible 客户端
│   │   ├── concurrent.py         # 并发批量 LLM 调用
│   │   ├── system.md             # 共享系统提示词
│   │   └── prompts/
│   │       ├── guide_sh_index.md  # 上证指数导语模板
│   │       ├── guide_cz_index.md  # 创业板指导语模板
│   │       └── summary.md         # 总览摘要模板
│   └── log_util.py               # 日志工具（每模块独立文件）
├── data/                         # SQLite 数据库文件（marketreview.db）
├── logs/                         # 日志文件
└── .env                          # 环境变量（TUSHARE_TOKEN, OPENAI_API_KEY 等）
```

## 4. 数据层

### 4.1 数据库（SQLite，11 表）

| 表 | 用途 | 关键字段 |
|----|------|----------|
| `tushare_cache` | 日线 K 线缓存（不复权 + adj_factor） | code, date, OHLCV, amount, adj_factor, asset_type |
| `index_weight_cache` | 指数成分股权重（月度发布） | index_code, con_code, weight_date, weight |
| `stock_industry_cache` | 申万行业分类（3级） | ts_code, name, l1/l2/l3 code/name |
| `stock_basic_cache` | 全 A 股基础信息 | ts_code, name, list_date, is_st |
| `daily_basic_cache` | 市值数据（日频） | ts_code, trade_date, total_mv, circ_mv |
| `wave33_cache` | 33公式每日选股结果 | trade_date, count, profit_count, profit_pct, stock_codes(JSON) |
| `index_contribution_cache` | 指数权重贡献缓存 | index_code, trade_date, top_n, weight_type, data(JSON) |
| `ai_summary` | AI 总结缓存 | trade_date, summary_type, guide_key, content, model, created_at |
| `industry_classify` | 申万行业分类（L1/L2/L3 层级） | index_code, industry_name, level, industry_code, parent_code, src |
| `industry_daily` | 行业日线行情（sw_daily 付费 API） | industry_code, trade_date, open, high, low, close, vol, amount, pct_change |
| `stk_limit_cache` | 个股涨跌停价格 | ts_code, trade_date, up_limit, down_limit |

### 4.2 复权策略

- **存储**：不复权价格 + per-date `adj_factor`
- **读取时转换**：`qfq_price = raw_price × adj_factor / latest_adj_factor`
- **优势**：一组原始数据可生成任意日期的前复权，无需每次除权后重算

### 4.3 CacheManager 特性

- **Schema 自动检测**：启动时逐表检查列结构，仅删除/重建不匹配的表（不丢弃整个数据库）
- **日期边界检查**：`daily_basic_has_range()` 检查 end_date 是否有数据行（避免 SQL GROUP BY 对零行日期不可见导致的隐性数据缺失）
- **数据覆盖率验证**：`DataProvider._validate_coverage()` 在数据加载后自动检测每日期望股票数是否 >= 90%，不足则自动重新拉取

## 5. 数据加载流程（控制台 "应用" 按钮触发）

### 5.1 总览：两阶段流水线

```
用户点击 "应用" → 控制台 00_控制台.py
  │
  ├─ Phase 1: 日期验证
  │     is_trading_day(date) → Tushare trade_cal API（无缓存）
  │     有效 → 设置 pending_load_date → st.rerun()
  │
  └─ Phase 2: 数据加载（rerun 后 consume pending flag）
        │
        ├─ Step A: ensure_data_loaded(date)
        │     ├─ A1. 判断 K 线缺失范围（代理股票法）
        │     ├─ A2. [有缺失] 分 chunk 拉取 api.daily + api.adj_factor
        │     ├─ A3. _ensure_indices_loaded（6个跟踪指数）
        │     ├─ A4. _fetch_stock_basic_once（全 A 股列表）
        │     ├─ A5. _ensure_daily_basic_loaded（市值数据）
        │     ├─ A6. _validate_coverage（≥90% 覆盖率检查）
        │     ├─ A7. _ensure_industry_daily（行业日线）
        │     └─ A8. _ensure_stock_industries（个股→行业分类）
        │
        ├─ Step B: ensure_wave33_computed(date)
        │     两窗口缓存：USE(40td) 检查 / CACHE(80td) 超取
        │
        └─ Step C: AI 总结生成（cache-first）
              ├─ get_ai_summary() → 未命中则 generate_ai_summary()
              └─ get_ai_summary(sector) → 未命中则 generate_ai_sector_analysis()
```

### 5.2 Step A1 — K 线缓存判断：代理股票法

**核心思路：** 不做全表扫描，用一只代理股票（`000001.SZ` 平安银行）判断整体缓存状态。

```
cache.get_latest_date("000001.SZ")  → proxy_latest（缓存最新日期）
cache.get_earliest_date("000001.SZ") → proxy_earliest（缓存最早日期）

关键常量：
  _FETCH_DAYS = 1000 日历日（~670 个交易日，拉取窗口）
  _CHECK_DAYS = 500 日历日（~330 个交易日，检查窗口）

缺失判定：
  1. proxy_latest < end_date     → 尾部缺口：(proxy_latest+1, end_date]
  2. proxy_earliest > check_start → 头部缺口：[fetch_start, proxy_earliest-1)
  3. 代理股票无数据                 → 全量回填：[fetch_start, end_date]

结果：
  missing_ranges = []  → 快路径（跳过 K 线拉取，只做验证）
  missing_ranges ≠ []  → 慢路径（分 chunk 拉取）
```

**为什么代理股票可行：** 所有 A 股 K 线数据按日期统一拉取，每 chunk 包含当日全市场数据。代理股票的范围即代表全部股票的范围。

### 5.3 Step A2 — 慢路径：分 chunk 并发拉取

**触发条件：** `missing_ranges` 非空。

**分 chunk 规则：**
```
每个 missing_range 按 _CHUNK_DAYS=20 日历日切分
  → 每 chunk 独立调用 api.daily() + api.adj_factor()
  → 并发数：_MAX_FETCH_WORKERS=4（4 线程并行处理 chunk）
```

**每个 chunk 的拉取流程：**
```
1. api.daily(trade_date 在 chunk 范围内)
     → 逐页拉取，每页最多 5000 行，最多 30 页
     → 写入 tushare_cache（此时 adj_factor=1.0 占位）

2. api.adj_factor(ts_code 在 chunk 涉及的股票中)
     → 拉取复权因子
     → UPDATE tushare_cache 对应行的 adj_factor 为真实值
```

**为什么分 20 天小 chunk：** Tushare `api.daily` 分页 offset 上限 15000 行。不分小 chunk 会导致大日期范围的末页 offset 超限、数据被截断。

### 5.4 Step A3~A6 — 指数 / 股票基础 / 市值 / 覆盖率

| Step | 方法 | 缓存判断 | 拉取逻辑 |
|------|------|----------|----------|
| A3 | `_ensure_indices_loaded` | 每个指数单独检查：`latest >= end_date AND earliest <= start_date` | 不满足 → `api.index_daily()`；6 个指数：`000001.SH, 399006.SZ, 000016.SH, 000300.SH, 399001.SZ, 399005.SZ` |
| A4 | `_fetch_stock_basic_once` | `cache.get_stock_basic()` 非空即跳过 | 空 → `api.stock_basic()` 拉取全 A 股列表，过滤 SH/SZ 交易所，标记 ST |
| A5 | `_ensure_daily_basic_loaded` | 每 10 天 chunk 调 `daily_basic_has_range(cs, ce)`：检查范围内每天 ≥90% 股票数，且 end_date 14 天内至少一天有数据 | 不满足 → `api.daily_basic()` 拉取市值 |
| A6 | `_validate_coverage` | 遍历范围内每个日期，`count_daily_date(d) / stock_basic_count >= 90%` | 不足 → 重拉该日期的 chunk，最多重试 2 次；持续不足记录 error 日志 |

### 5.5 Step A7 — 行业日线加载（关键差异点）

**与 K 线加载的核心差异：**

| 维度 | K 线（tushare_cache） | 行业日线（industry_daily） |
|------|----------------------|---------------------------|
| API | `api.daily`（免费） | `api.sw_daily`（付费） |
| 缓存判断 | 1 只代理股票 | 展示行业 + 自选行业逐个检查（数量由拆分规则 + 配置文件决定） |
| 拉取粒度 | 20 天 chunk | 按行业整段拉取 |
| 并发 | 4 worker 处理 chunk | 4 worker 处理行业 |
| 检查窗口 | 500 日历日 | 40 日历日（`_INDUSTRY_CHECK_DAYS`） |
| 拉取窗口 | 1000 日历日 | 1000 日历日（`_INDUSTRY_FETCH_DAYS`） |
| 覆盖率校验 | ✅ 有 | ❌ 无 |

**行业分类加载（前置依赖）：**
```
_ensure_industry_classify():
  cache.has_industry_classify() → True → 跳过
  False → api.index_classify(L1) + api.index_classify(L2) + api.index_classify(L3)
       → upsert_industry_classify() → 永久缓存（行业分类不变）
```

**展示行业代码解析：**
```
_get_display_industry_codes():
  1. 从 industry_classify 读取全部 L1/L2/L3
  2. 应用递归拆分规则（见 §5.6）
  3. 输出展示行业代码（当前：25 L1 + 24 L2 + 14 L3 = 63 个，数量随拆分配置变化）
```

**自选行业代码解析（新增）：**
```
_get_watchlist_industry_codes():
  1. 读取 config/watchlist_industries.txt
  2. 在 industry_classify 表中精确匹配名称 → (code, name, level)
  3. 匹配失败的名称 → logger.warning，跳过
```

**行业日线缓存判断（展示行业 ∪ 自选行业）：**
```
codes_to_check = _get_display_industry_codes() ∪ _get_watchlist_industry_codes()
// 并集去重 — 自选行业可能已包含在展示行业中

for each code in codes_to_check:
  latest = cache.get_latest_industry_date(code)
  earliest = cache.get_earliest_industry_date(code)
  
  if latest >= end_date AND earliest <= fetch_start:
    → 跳过（缓存完整）
  else:
    → 加入 to_fetch 列表
```

**并发拉取：**
```
to_fetch 列表 → ThreadPoolExecutor(max_workers=4)
  每个行业 1 次 api.sw_daily() 调用
  → upsert_industry_daily_bulk() 写入 industry_daily 表
```

**为什么行业按整段拉取而非 chunk：** `api.sw_daily` 单行业 1000 天数据约 659 行，远小于 5000 行分页限制，一次调用即可全部返回。

### 5.6 行业拆分规则

**配置文件：** `src/marketreview/tools/industry.py`

```python
SPLIT_L1 = {'建筑材料', '有色金属', '汽车', '电力设备', '电子', '通信'}
SPLIT_L2 = {'半导体', '元件', '光伏设备'}
```

**递归替换逻辑：**
```
输入: 31 个申万 L1 行业
for each L1:
    if L1 in SPLIT_L1 → 替换为该 L1 下的全部 L2
        for each L2:
            if L2 in SPLIT_L2 → 替换为该 L2 下的全部 L3
            else → 保留 L2
    else → 保留 L1

结果：25 L1 + 24 L2 + 14 L3 = 63 个展示行业
```

### 5.7 Step A8 — 个股行业分类

```
_ensure_stock_industries():
  1. cache.get_stock_industries(all_codes) → 批量检查已有分类
  2. 只拉取缺失的个股（首次 ~5000 只，后续仅新增）
  3. 对每只缺失个股调用 api.index_member_all()
  4. 限速：1 worker，每次调用间隔 0.15s（~400 次/分钟，低于 500/min 限制）
  5. 写入 stock_industry_cache（永久缓存）
```

### 5.8 Step B — Wave33 两窗口缓存

**两窗口设计：**
```
USE 窗口  = 40 个交易日（15 K线柱 + 21 滚动窗口 + 4 缓冲）
CACHE 窗口 = 80 个交易日（2× USE 窗口，超取）
```

**缓存判断逻辑：**
```
1. 获取 end_date 前 180 天的交易日列表
2. 取最近 40 个交易日作为 USE 窗口
3. 检查 USE 窗口中每个日期：cache.has_wave33_date(d)

快路径（USE 窗口全部命中）：
  → _precompute_cumulative_profit(use_dates)
  → 返回（不触发扫描）

慢路径（USE 窗口有缺失）：
  → 取 80 个交易日作为 CACHE 窗口
  → 扫描 CACHE 窗口中所有未缓存的日期
  → scan_wave33() 逐日扫描选股结果
  → _precompute_cumulative_profit(use_dates)
```

**设计意图：** 用户在相邻日期之间切换时（如 6/20 → 6/19），新日期的 40 天 USE 窗口大部分已在上次 80 天 CACHE 扫描中覆盖，快路径直接命中。

### 5.9 Step C — AI 总结（cache-first）

```
市场全景 AI（summary_type=None）：
  期望 keys: {"guide/sh_index", "guide/cz_index", "summary"}
  cache 命中全部 3 个 → 跳过
  缺失任意一个 → generate_ai_summary()
    ├─ get_market_overview() [读缓存，个股 <4000 时 fallback 到 live API]
    ├─ build_technical_summary() × 2 [纯读缓存]
    ├─ batch_chat() → 2 个指数导语并发 LLM 调用
    ├─ llm.chat() → 1 个全景总结 LLM 调用
    └─ save_ai_summary() × 3

板块分析 AI（summary_type="sector_analysis"）：
  期望 keys: {"sector_summary"} + 每个分析集行业的 "sector/{code}"
             + 每个自选行业的 "sector/{code}"（与展示行业同模板）
  cache 命中全部 → 跳过
  缺失任意一个 → generate_ai_sector_analysis()
    ├─ get_industry_analysis_set() [TOP5 + BOTTOM5 + 频繁行业，去重]
    ├─ get_watchlist_industries() [自选行业列表]
    ├─ 合并去重后 batch_chat() → 每个行业 1 次并发 LLM 调用（max 4 workers）
    ├─ llm.chat() → 1 个行业总结 LLM 调用
    └─ save_ai_summary() × N
```

### 5.10 缓存判断决策树（总览）

```
ensure_data_loaded(end_date)
│
├─ 代理股票范围检查
│     ├─ 完整 → 快路径（跳过 K 线拉取）
│     └─ 不完整 → 慢路径（分 chunk 拉取）
│
├─ 指数数据（6 个指数，各自独立检查）
│     ├─ latest >= end AND earliest <= start → 跳过
│     └─ 否则 → api.index_daily()
│
├─ 股票基础信息
│     ├─ stock_basic_cache 非空 → 跳过
│     └─ 空 → api.stock_basic()
│
├─ 市值数据（10 天 chunk，逐段检查）
│     ├─ daily_basic_has_range(cs, ce) → 跳过
│     └─ 否则 → api.daily_basic()
│
├─ K 线覆盖率（逐日检查）
│     ├─ 每天 ≥90% → 通过
│     └─ <90% → 重拉，最多 2 次
│
├─ 行业分类
│     ├─ industry_classify 非空 → 跳过
│     └─ 空 → api.index_classify() × 3
│
├─ 行业日线（展示行业 ∪ 自选行业，逐个检查）
│     ├─ latest >= end AND earliest <= fetch_start → 跳过
│     └─ 否则 → api.sw_daily()
│
└─ 个股行业分类（批量检查）
      ├─ 已缓存 → 跳过
      └─ 缺失 → api.index_member_all()（1 worker, 0.15s 限速）
```

### 5.11 关键常量速查

| 常量 | 值 | 作用 |
|------|-----|------|
| `_FETCH_DAYS` | 1000 日历日 | K 线拉取窗口 |
| `_CHECK_DAYS` | 500 日历日 | K 线覆盖检查窗口 |
| `_CHUNK_DAYS` | 20 日历日 | 单 chunk 大小（防 offset 超限） |
| `_MAX_FETCH_WORKERS` | 4 | K 线并发 worker 数 |
| `_DB_FETCH_DAYS` | 180 日历日 | 市值数据拉取窗口 |
| `_BASIC_CHUNK_DAYS` | 10 日历日 | 市值数据 chunk 大小 |
| `_INDUSTRY_FETCH_DAYS` | 1000 日历日 | 行业日线拉取窗口 |
| `_INDUSTRY_CHECK_DAYS` | 40 日历日 | 行业日线检查窗口（~27td） |
| `_INDUSTRY_MAX_WORKERS` | 4 | 行业并发 worker 数 |
| `_STOCK_IND_MAX_WORKERS` | 1 | 个股行业分类 worker（限速） |
| `MAX_PAGES_PER_CHUNK` | 30 | 单 chunk 最大页数 |
| `_BREADTH_CACHE_MIN_STOCKS` | 4000 | 涨跌比走缓存的阈值 |

## 6. Dashboard 页面

### 6.0 控制台（00_控制台.py）
- 日期选择器 + 交易日验证
- 数据加载进度（多阶段进度回调：K线/市值/指数/33公式/AI）
- AI 总结卡片 + 各板块导语展示

### 6.1 市场全景（01_市场全景.py）

#### 页面布局（自上而下）

| 区块 | 内容 | 数据来源 |
|------|------|----------|
| Header | "市场全景 — YYYY-MM-DD" | `session_state.trade_date` |
| AI 总览 | 4-5 句市场全景摘要 | `get_ai_summary(date)["summary"]` |
| 市场概览 | 涨跌比卡片 + 成交额卡片（沪/深/京）+ 环比 | `get_market_overview(date)` |
| 10日成交额 | 柱状图 + 5日/10日均量对比 | 同上（逐日前溯 10 个交易日） |
| 33公式趋势 | 21日滚动去重选股数 + 20日盈利占比 | `get_wave33_data()` |
| **上证指数** | expander（默认展开）— 见下方子结构 | `get_index_data("000001.SH")` |
| **创业板指** | expander — 同上子结构 | `get_index_data("399006.SZ")` |

#### 指数分析子结构 (render_index_section)

每个指数 expander 内部按顺序包含：
1. **AI 导读 banner** — 2-3 句技术面总结（LLM 生成，缓存读取）
2. **K线图** — Plotly 蜡烛图 + 6 条 MA 叠加（MA5蓝/MA10橙/MA20紫/MA60绿/MA120深橙/MA240棕）+ 成交量柱
3. **OHLC 卡片** — 开/高/低/收 + 涨跌幅 + K线形态检测结果
4. **均线表格** — 6 周期 MA 值 + 方向（上扬/下跌/走平）+ 角色（支撑/压力/拖拽）+ 扣抵日/扣抵量
5. **成交量表格** — 今日量 + 均量对比 + 扣抵量对比 + 5日趋势 + 金叉/死叉状态
6. **技术指标行**：
   - 短期趋势标签（多头/空头/盘整）
   - KD 卡片 — K/D 值 + 超买超卖区 + KD 差值 + 收敛预警 + 背离信号
   - RSI 卡片 — RSI 值 + 超买超卖区 + vs-KD 强度 + 背离信号
   - BIAS 卡片 — 10日/20日乖离率 + 超买超卖判定
7. **权重贡献** — 领涨 Top10（红）/ 领跌 Top10（绿）：代码+名称+行业+权重+涨跌幅+贡献度
   - 底部：近5日行业频次（出现 ≥3 天的频繁涨/跌行业）

#### 技术指标判定规则

**KD 区间（双线判定，2026-06-18 修订）：**
- 超买区：K > 80 **且** D > 80
- 超卖区：K < 20 **且** D < 20
- 其余：常态区
- |K-D| ≥ 20 → 开口过大，大概率收敛预警

**KD/RSI 背离方向判定：**
- 当日 MA5/MA10/MA20 趋势 → 多头找顶背离，空头找底背离
- MA 缠绕时：向前回溯最多 20 天，取最后明确趋势
- **背离失效 guard**（防止滞后信号）：
  - 底背离失效：价格 20 日新高、KD 双线超买（K,D>80）、RSI>70 → 空头趋势已反转
  - 顶背离失效：价格 20 日新低、KD 双线超卖（K,D<20）、RSI<30 → 多头趋势已反转

**RSI 区间：** >70 超买，<30 超卖。背离周期边界 = 50

**BIAS（乖离率）：**
- BIAS10：\|值\| > 10% → 短线超买/超卖
- BIAS20：\|值\| > 7% → 月线超买/超卖

**K线形态（6 种，含高低档判定）：**
1. 多头吞影线（仙人指路）— 偏多
2. 空头吞影线 — 偏空
3. 颈上线 — 偏空
4. 颈内线 — 偏空
5. 纺锤线（高档/低档）— 偏空/偏多
6. 高档长阳 — 偏空

高低档判定：MA5>MA10>MA20（多头排列）或 近**20**日最高价/最低价创阶段新高/新低

#### 涨跌比数据流

```
DataProvider.get_market_breadth(date)
  ├─ 缓存路径（≥4000 只）：_breadth_from_cache
  │   逐行比对 close vs 前日 close → 涨/跌/平
  │   涨停/跌停：_get_stk_limits → stk_limit_cache（永久缓存，首次使用即拉取）
  └─ API 路径（<4000 只）：_breadth_from_api → tushare daily API
```

### 6.2 板块分析（02_板块分析.py）
- 申万行业板块技术分析（复用同一技术指标框架）
- 权重贡献 + 行业频率统计

### 6.3 个股追踪（03_个股追踪.py）
- 自选股 K 线 + 技术指标展示
- 待扩展：四状态判定、持仓分层管理

## 7. 工具模块

### 7.1 technical.py — 技术分析
| 功能 | 函数 |
|------|------|
| 均线系统 | `calc_ma()`, `ma_direction()`, `ma_arrangement()` |
| 成交量分析 | `volume_analysis()` (含扣抵量、均额交叉、5日趋势) |
| KD 指标 | `calc_kd()` (展示用), `calc_kd_standard()` (筛选用) |
| RSI | `calc_rsi()` (通达信 SMA 公式) |
| BIAS | `calc_bias()`, `bias_status()` (超买/超卖判定) |
| WR | `calc_wr()` |
| KD 背离 | `detect_kd_divergence()` (含区间边界检测) |
| RSI 背离 | `detect_rsi_divergence()` |
| 扣抵分析 | `get_offset_info()` (扣抵日定位 + 均量窗口) |
| 均线角色 | `get_ma_role()` (支撑/压制/拖拽) |
| K线形态 | `kline_pattern()` (单K线：实体/影线比例) |
| 综合摘要 | `build_technical_summary()` |

### 7.2 contribution.py — 权重贡献
- `build_index_contribution()`：从 circ_mv 动态计算成分股权重，输出领涨/领跌 Top10
- `build_industry_frequency()`：跨日统计行业出现频率（>=3天）
- `pick_industry_label()`：L1/L2/L3 行业标签覆盖逻辑

### 7.3 wave33.py — 33 公式选股
- 条件：连续5日 K>80 + WR(10/20)<20 + RSI(9)>70 + 市值 > 100亿
- 两窗口缓存设计：
  - **USE 窗口**：40 个交易日（满足图表显示）
  - **CACHE 窗口**：80 个交易日（2x 超取 = 切换日期即时命中）
- 滚动 21 日去重 + 累计盈利预计算
- `compute_trend()`：趋势方向判定（含滞后确认逻辑）

### 7.4 kline_patterns.py — K 线形态识别
- 两阶段架构：单K线分类 -> 多K线形态匹配
- 当前支持：多头吞影线（仙人指路）、空头吞影线、颈上线/颈内线、高档/低档纺锤线

## 8. AI 总结（3 步流水线）

### 8.1 提示词架构
所有 AI 调用共享同一个 **系统提示词**（`system.md`），定义分析优先级：
1. **结构** > 2. **成交量** > 3. **K线价格** > 4. **技术指标**

每个输出板块有独立的 **用户提示词模板**（`prompts/*.md`），使用 `{data}` 和 `{market_data}` 占位符注入结构化数据。

### 8.2 生成流程
```
1. Breadth（市场广度）-> 涨跌结构 + 成交额 + 33公式数据 JSON
2. Index guides（并行）-> 上证指数 + 创业板指（各含完整技术数据 + 权重贡献）
3. Summary -> 基于 index guides 结果，生成全景总览
```

### 8.3 缓存策略
- AI 结果按 `(trade_date, summary_type, guide_key)` 唯一键存入 `ai_summary` 表
- 先读缓存，未命中才调用 LLM
- 占位符 "AI 摘要暂时不可用" 会被跳过，触发重试
- 并发调用失败不阻塞其他调用

## 9. LLM 层

| 文件 | 职责 |
|------|------|
| `__init__.py` | `LLMClient` 抽象类 + `create_llm_client()` 工厂 |
| `openai_client.py` | OpenAI-compatible 客户端（支持 DeepSeek/OpenAI） |
| `concurrent.py` | `batch_chat()` — ThreadPoolExecutor 并发调用，支持进度回调 |

LLM 配置通过环境变量：
- `OPENAI_API_BASE`：API 端点（自动补全 `/v1`）
- `OPENAI_API_KEY`：API 密钥
- `MODEL`：模型名（默认 `deepseek-chat`）

## 10. 颜色约定

- **红 = 上涨/偏多/看涨** (`#e53935`)
- **绿 = 下跌/偏空/看跌** (`#43a047`)
- **灰 = 中性/持平** (`#999`)
- K 线图：红阳绿阴（A 股习惯）
- 成交量柱：红涨绿跌

## 11. 关键设计决策

| 决策 | 原因 |
|------|------|
| 不复权存储 + 读取时前复权 | 避免除权后全量重算；一组数据支持任意日期前复权 |
| circ_mv 而非 total_mv 计算权重 | A 股有大量非流通股（国有、创始人），total_mv 虚高 |
| 权重贡献缓存仅存动态计算结果 | 回退到月度权重时不缓存，等市值数据就绪后自动更新 |
| 两窗口缓存（USE/CACHE） | USE 窗口检查快 -> 切换日期即时命中；CACHE 窗口超取减少扫描频率 |
| 累计盈利预计算 | 将昂贵的 per-stock 20日盈利检查从读路径移到写路径，UI 即时渲染 |
| 覆盖率自动验证 + 补拉 | 防止 tushare 分页截断造成的隐性数据缺失 |
| AI 只收数据和用法，不下结论 | 让 AI 基于数据自行分析，避免 prompt 中的偏见引导 |
| 系统提示词 + 用户提示词分离 | system 定义分析框架，user 注入当日数据，复用 system 上下文 |

## 12. 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Streamlit（Plotly K线图表） |
| 服务层 | Python（DashboardService 门面模式） |
| 数据层 | SQLite（8 表，自愈 schema） |
| LLM | DeepSeek / OpenAI-compatible API（并发调用） |
| 数据源 | Tushare Pro API |
| 日志 | Python logging（每模块独立文件 + errors.log 汇总） |
