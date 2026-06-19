# A股复盘系统 — 架构文档

> 最后更新：2026-06-18

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
| `stk_limit_cache` | 涨跌停价（日频） | ts_code, trade_date, up_limit, down_limit |
| `industry_member_cache` | 申万行业成分股映射 | industry_code, con_code |
| `industry_daily` | 行业合成日K线（自下而上加权） | industry_code, trade_date, OHLCV, up/down/flat/stock_count |
| `ai_summary` | AI 总结缓存 | trade_date, summary_type, guide_key, content, model |

### 4.2 复权策略

- **存储**：不复权价格 + per-date `adj_factor`
- **读取时转换**：`qfq_price = raw_price × adj_factor / latest_adj_factor`
- **优势**：一组原始数据可生成任意日期的前复权，无需每次除权后重算

### 4.3 CacheManager 特性

- **Schema 自动检测**：启动时逐表检查列结构，仅删除/重建不匹配的表（不丢弃整个数据库）
- **日期边界检查**：`daily_basic_has_range()` 检查 end_date 是否有数据行（避免 SQL GROUP BY 对零行日期不可见导致的隐性数据缺失）
- **数据覆盖率验证**：`DataProvider._validate_coverage()` 在数据加载后自动检测每日期望股票数是否 >= 90%，不足则自动重新拉取

### 4.4 缓存分级设计

系统有三层缓存，边界清晰，不可混用：

#### L1: Streamlit `@st.cache_data` — 进程级, TTL 过期

- **位置**: `dashboard/pages/01_市场全景.py:742`, `load_market_overview(date)`
- **用途**: 防止页面交互（点击 widget）触发的重复计算。是整个聚合结果的 UI 层缓存。
- **适用**: 计算结果几秒到几分钟后会失效的场景。

#### L2: 模块级 `_FETCH_CACHE: dict` — 进程级, 无过期

- **位置**: `src/marketreview/tools/industry.py:18`
- **用途**: 缓存 `index_classify` 返回的申万行业分类树元数据（~200 行，几 KB）。
- **适用**: 数据量小、拉取成本低（几次 API 调用）、不需要跨重启。典型场景：外部 API 返回的分类/枚举/配置，其更新频率和代码里的硬编码常量一样低。
- **规则**: 空结果和异常不缓存 — 防止瞬态失败永久损坏。

#### L3: SQLite DB — 持久化, 跨重启

所有 `CacheManager` 管理的 11 张表。这是系统的主力缓存层。

| 表 | 数据类型 | 拉取成本 | 被谁消费 |
|---|----------|----------|----------|
| `tushare_cache` | 原始日K线 + adj_factor | 极高（全市场逐日分页） | Agent 1/2/3 |
| `daily_basic_cache` | 市值 (total_mv/circ_mv) | 高（全市场分页） | Agent 1/2 |
| `stock_basic_cache` | 股票基础列表 | 低（一次性） | Agent 1/3 |
| `stock_industry_cache` | 个股→行业映射 | 中（逐股查询） | Agent 2 |
| `industry_member_cache` | 行业→成分股列表 | 中（逐行业查询） | Agent 2 |
| `industry_daily` | 行业合成日K线 | 极高（自下而上计算） | Agent 2 |
| `stk_limit_cache` | 涨跌停价 | 低（单日查询） | Agent 1 |
| `wave33_cache` | 扫描结果 | 高（全市场扫描） | Agent 1 |
| `index_weight_cache` | 指数权重 | 低（逐指数查询） | Agent 1 |
| `index_contribution_cache` | 贡献分析结果 | 中（计算） | Agent 1 |
| `ai_summary` | AI 导语文本 | 中（LLM 调用） | 三大页面 |

#### 判断标准

一个数据放哪个层级，看三个维度：

| 维度 | L1 (Streamlit TTL) | L2 (模块 dict) | L3 (SQLite DB) |
|------|-------------------|----------------|----------------|
| 数据量 | 任意（但 TTL 短） | < 几 KB | > 几千行 |
| 跨重启 | 不需要 | 不需要 | 需要 |
| 变化频率 | 分钟级 | 年更 | 日更以上 |

**访问规则**（参见两窗口缓存设计）：
- 所有 tushare API 调用必须经过 `DataProvider`，`DashboardService` 不得直接访问 API
- 时间序列数据遵循两窗口模式：USE 窗口检查 → CACHE 窗口回填
- DB 查询必须带 `trade_date` 过滤

## 5. 数据加载流程

```
用户选择日期 -> 控制台 00_控制台.py
  ├── 快速路径：check_cache_coverage() -> K线 + daily_basic 均覆盖
  │   ├── ensure_wave33_computed() -> 扫描或跳过
  │   └── generate_ai_summary() -> 生成/读取 AI 总结
  └── 慢速路径：ensure_data_loaded()
        ├── 判断缺失范围 -> 20天/chunk 分页拉取 api.daily + api.adj_factor
        ├── _ensure_indices_loaded() -> api.index_daily（6个跟踪指数）
        ├── _fetch_stock_basic_once() -> 全 A 股列表
        ├── _ensure_daily_basic_loaded() -> 市值数据（10天/chunk）
        ├── _validate_coverage() -> 覆盖率检查 + 自动补拉
        ├── ensure_wave33_computed() -> 33公式扫描
        └── generate_ai_summary() -> AI 总结
```

**关键参数：**
- `_FETCH_DAYS = 1000`：拉取 1000 天 K 线历史
- `_CHECK_DAYS = 500`：检查 500 天覆盖率即视为完整
- `_CHUNK_DAYS = 20`：每 chunk 20 个日历日（避免 tushare 分页 offset 超限）

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
| 数据层 | SQLite（11 表，自愈 schema） |
| LLM | DeepSeek / OpenAI-compatible API（并发调用） |
| 数据源 | Tushare Pro API |
| 日志 | Python logging（每模块独立文件 + errors.log 汇总） |
