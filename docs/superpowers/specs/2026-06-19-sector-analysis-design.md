# 板块分析（Agent 2）— 设计文档

> 日期：2026-06-19（修订：2026-06-20 数据层完成）
> 状态：Phase 1 完成 / Phase 2-5 待实现

## 1. 概述

将 `02_板块分析.py` 从 mock 占位符改造为完整的行业板块分析页面。

核心思路：使用 **tushare `sw_daily` 付费 API** 直接获取申万行业日线行情（OHLCV），无需成分股聚合。行业分类通过 `index_classify` API 获取 L1/L2/L3 层级关系。数据源是申万官方指数，与真实行情完全一致，直接复用市场全景的技术分析框架。

---

## 2. 行业粒度：递归拆分规则

### 2.1 配置

```python
# 哪些 L1 需要拆分为 L2
SPLIT_L1 = {'建筑材料', '有色金属', '汽车', '电力设备', '电子', '通信'}

# 哪些 L2 需要进一步拆分为 L3
SPLIT_L2 = {'半导体', '元件', '光伏设备'}
```

### 2.2 递归替换逻辑

```
输入: 31 个申万 L1 行业
for each L1:
    if L1 in SPLIT_L1 → 取该 L1 下的全部 L2
        for each L2:
            if L2 in SPLIT_L2 → 取该 L2 下的全部 L3
            else → 保留 L2
    else → 保留 L1
```

### 2.3 最终结果

| 层级 | 数量 | 示例 |
|------|------|------|
| L1 | 25 | 农林牧渔、钢铁、汽车、银行、医药生物... |
| L2 | 24 | 工业金属、消费电子、电池、通信设备、水泥... |
| L3 | 14 | 数字芯片设计、半导体设备、逆变器、被动元件... |
| **合计** | **63** | |

### 2.4 权重贡献同步

`contribution.py` 的 `pick_industry_label()` 同步改为递归替换逻辑：
- 命中 SPLIT_L2 → 取 L3 name
- 命中 SPLIT_L1 → 取 L2 name
- 否则 → 取 L1 name

不再维护独立的 L1_OVERRIDE / L3_OVERRIDE 硬编码列表。

### 2.5 控制台展示

在 `00_控制台.py` 增加一块「行业分类规则」区域，列明当前拆分配置，让用户不看代码也能了解分类逻辑：

```
┌─ 行业分类规则 ──────────────────────────────┐
│  默认按申万一级行业（31个）展示                │
│  拆分 L1→L2：建筑材料、有色金属、汽车、         │
│             电力设备、电子、通信               │
│  拆分 L2→L3：半导体、元件、光伏设备             │
│  最终板块数：25 L1 + 24 L2 + 14 L3 = 63       │
└─────────────────────────────────────────────┘
```

可折叠（expander），默认收起。

---

## 3. 数据层

### 3.1 数据源：`sw_daily` 付费 API

tushare `sw_daily` 接口直接提供申万行业指数的每日 OHLCV 数据，无需成分股聚合。

| 字段 | 说明 |
|------|------|
| `ts_code` | 行业指数代码（如 `801081.SI`） |
| `trade_date` | 交易日（YYYYMMDD） |
| `open` / `high` / `low` / `close` | 行业指数 OHLC |
| `vol` | 总成交量 |
| `amount` | 总成交额（千元） |
| `pct_change` | 涨跌幅（%） |

数据覆盖：31 个 L1 + 134 个 L2 + 258 个 L3 = **~439 个行业**，最早可追溯到 2018 年。

### 3.2 行业分类：`index_classify` API

`index_classify(level, src='SW2021')` 返回申万行业分类层级：

| 字段 | 说明 |
|------|------|
| `index_code` | 行业指数代码（如 `801081.SI`） |
| `industry_name` | 行业名称 |
| `level` | L1 / L2 / L3 |
| `industry_code` | 行业分类代码（如 `270000`） |
| `parent_code` | 父级分类代码（L1 的 parent=0） |
| `src` | 分类标准（SW2021） |

### 3.3 新表：`industry_daily`

直接从 `sw_daily` 落表，字段与 API 一致：

```sql
CREATE TABLE IF NOT EXISTS industry_daily (
    industry_code TEXT NOT NULL,   -- 行业指数代码 (801081.SI / 850811.SI ...)
    trade_date    TEXT NOT NULL,
    open          REAL,            -- 开盘价
    high          REAL,            -- 最高价
    low           REAL,            -- 最低价
    close         REAL,            -- 收盘价
    vol           REAL,            -- 成交量
    amount        REAL,            -- 成交额（千元）
    pct_change    REAL,            -- 涨跌幅（%）
    PRIMARY KEY (industry_code, trade_date)
);
```

> 不再需要 `industry_member_cache` 表。行业指数直接来自申万官方，无需维护成分股列表。

### 3.4 行业分类缓存：`industry_classify`

`index_classify` 结果落表缓存（分类规则不会频繁变动）：

```sql
CREATE TABLE IF NOT EXISTS industry_classify (
    index_code     TEXT PRIMARY KEY,  -- 行业指数代码
    industry_name  TEXT NOT NULL,     -- 行业名称
    level          TEXT NOT NULL,     -- L1 / L2 / L3
    industry_code  TEXT NOT NULL,     -- 行业分类代码
    parent_code    TEXT NOT NULL,     -- 父级分类代码
    src            TEXT NOT NULL      -- 分类标准
);
```

### 3.5 数据加载时机

在 `ensure_data_loaded()` 末尾（daily_basic 之后）执行：

```
ensure_data_loaded()
  ├── ... (现有流程：K线 → 指数 → daily_basic → 验证)
  └── ensure_industry_daily(trade_date, lookback_days=1000)
        ├── 首次调用：lazy-init 行业分类（index_classify → industry_classify 表）
        └── 补齐每个行业的 industry_daily（复用现有 USE/CACHE 双窗口逻辑）
```

无需独立的 `ensure_industry_members()` 步骤。

### 3.6 双窗口缓存复用

行业数据加载复用与个股 K 线相同的 USE/CACHE 双窗口模式：

```
USE 窗口 = 40td：检查 industry_daily 表覆盖率
CACHE 窗口 = 2× USE = 80td：不足时从 sw_daily 补齐
```

遵循 [[Two-Window Cache Design]] 和 [[Always Filter By Date]] 约定。

### 3.7 控制台进度回调 & 日志

| 阶段 | progress_cb phase | 日志 |
|------|-------------------|------|
| 行业分类初始化 | `"industry_classify"` | `log.info("ensure_industry_classify: %d industries loaded")` |
| 行业日线补齐 | `"industry_daily"` | `log.info("ensure_industry_daily: date=%s, %d/%d industries")` |

遵循 [[Logging Convention]]：`marketreview_data_industry.log` 独立日志文件（与 data_provider 同目录）。

### 3.8 DataProvider 新增方法

- `ensure_industry_classify()` → 首次/按需拉取行业分类，写入 `industry_classify` 表
- `ensure_industry_daily(trade_date, lookback_days=1000)` → 补齐行业日线
- `get_industry_daily(industry_code, end_date, lookback)` → 读行业 K 线 DataFrame
- `get_industry_list()` → 返回展示用行业列表（按拆分配置过滤后）
- `get_industry_ranking(trade_date)` → 按涨跌幅排序

---

## 4. 页面布局 (`02_板块分析.py`)

### 4.1 整体结构

```
┌──────────────────────────────────────────────┐
│  1. AI 行业总结导语                            │
│     "今日行业轮动核心在半导体..."               │
├──────────────────────────────────────────────┤
│  2. 今日 TOP 5 / BOTTOM 5                     │
│     ┌──────────────┐  ┌──────────────┐       │
│     │ 🥇 半导体    │  │ 📉 煤炭      │       │
│     │ 🥈 光伏设备  │  │ 📉 银行      │       │
│     │ ...          │  │ ...          │       │
│     └──────────────┘  └──────────────┘       │
├──────────────────────────────────────────────┤
│  3. 行业详细分析（expander 列表）              │
│     ▸ 半导体     +4.3%  🥇涨幅第1 📊权重上榜   │
│     ▸ 逆变器     +5.1%  🥇涨幅第1             │
│     ▸ 工业金属   +3.2%  🔁近5日频繁领涨       │
│     ▸ ...                                     │
│     （默认展示10~15个，去重后）                  │
├──────────────────────────────────────────────┤
│  4. 待扩展：用户自选行业（控制台配置）           │
└──────────────────────────────────────────────┘
```

### 4.2 TOP 5 / BOTTOM 5 卡片

从展示行业中按 `pct_change` 排序，取前 5 和后 5，展示：
- 行业名称 + 层级标签（L1/L2/L3）
- 涨跌幅（颜色编码，遵循 [[Color Convention]]：红=涨，绿=跌）
- 总成交额
- 排名徽章

### 4.3 行业分析集合（去重 + 入选理由）

分析候选来源（取并集后去重）：

| 优先级 | 来源 | 标签 |
|--------|------|------|
| 1 | 当日涨幅 TOP 5 | `🥇 涨幅第N` |
| 2 | 当日跌幅 TOP 5 | `📉 跌幅第N` |
| 3 | 权重贡献上榜行业（当日） | `📊 权重贡献上榜` |
| 4 | 近 5 日频繁领涨/领跌行业（≥3 天） | `🔁 近5日频繁领涨/领跌` |
| 5 | 用户自选行业（未来） | `⭐ 自选` |

每个行业 expander 的标题行显示：**行业名 + 涨跌幅 + 入选理由标签列表**。

### 4.4 行业详细分析 Expander

复用 `01_市场全景.py` 的 `render_index_section()` 模板（或抽取为共享函数），包含：

1. **AI 行业导语**（2-3 句技术面总结）
2. **K 线图**（Plotly 蜡烛图 + MA 叠加 + 成交量柱）
3. **OHLC 卡片**（开/高/低/收 + 涨跌幅 + K 线形态）
4. **均线表格**（MA5/10/20/60/120/240 + 方向 + 角色）
5. **成交量表格**（今日量 + 均量对比 + 扣抵量）
6. **技术指标**（KD + RSI + BIAS + 背离）

> 注：行业指数来自申万官方 `sw_daily`，与真实指数完全一致，均线角色/扣抵逻辑直接适用。

---

## 5. AI 导语：三步流水线

### 5.1 提示词文件

| 文件 | 用途 |
|------|------|
| `prompts/guide_sector_item.md` | 单个行业导语模板 |
| `prompts/guide_sector_summary.md` | 行业总结导语模板 |

### 5.2 生成流程

```
market_data (市场整体涨跌+成交额)
    │
    ├──→ 半导体导语 (行业技术数据 + market_data)
    ├──→ 光伏设备导语 (行业技术数据 + market_data)
    ├──→ 银行导语 (行业技术数据 + market_data)
    ├──→ ... (并行，10~15 个)
    │
    └──→ 行业总结导语 (所有行业导语 + market_data + 排名)
```

与 `01_市场全景` 一致的模式：先并行生成各行业导语，再汇总生成总导语。

### 5.3 数据注入

每个行业导语接收：
- `market_data`：涨跌结构 + 成交额（与市场全景共享格式）
- `data`：该行业的技术指标 JSON（复用 `_build_index_ai_data()` 的格式）

行业总结导语接收：
- `market_data`：同上
- `sector_guides`：所有行业导语内容
- `ranking`：TOP 5 / BOTTOM 5 排名

### 5.4 控制台进度回调 & 日志

AI 导语生成需接入控制台进度系统。在 `generate_ai_sector_analysis()` 内：

| 阶段 | progress_cb phase | 日志 |
|------|-------------------|------|
| 行业导语并行生成 | `"sector_start"` / `"sector_progress"` / `"sector_done"` | `log.info("stage=sector_guides elapsed=%.1fs keys=%s")` |
| 行业总结导语 | `"sector_summary_start"` / `"sector_summary_done"` | `log.info("stage=sector_summary elapsed=%.1fs")` |

AI 版本号同步升级（`_AI_VERSION` → 对应大板块 X 位递增）。

### 5.5 缓存

AI 结果按 `(trade_date, 'sector_analysis', guide_key)` 存入 `ai_summary` 表。
- `guide_key = 'sector/<industry_code>'` — 单行业导语
- `guide_key = 'sector_summary'` — 行业总结导语

---

## 6. DashboardService 新增方法

| 方法 | 用途 |
|------|------|
| `get_industry_split_config()` | 返回 SPLIT_L1 / SPLIT_L2 配置 |
| `get_industry_list()` | 返回展示行业列表（拆分配置过滤后），含 code/name/level |
| `ensure_industry_classify()` | 拉取行业分类层级（首次/按需） |
| `ensure_industry_daily(trade_date, progress_cb)` | 补齐行业日线数据 |
| `get_industry_daily(code, end_date, lookback)` | 读取行业 K 线 DataFrame |
| `get_industry_ranking(trade_date)` | 展示行业按涨跌幅排序 |
| `get_industry_analysis_set(trade_date)` | 选出去重后的分析集合（TOP5/BOTTOM5 + 权重贡献 + 频繁行业） |
| `get_ai_sector_guide(trade_date, industry_code)` | 读取单个行业 AI 导语缓存 |
| `get_ai_sector_summary(trade_date)` | 读取行业总结 AI 导语缓存 |
| `generate_ai_sector_analysis(trade_date, progress_cb)` | 完整三步流水线：行业导语（并行）→ 总结导语 |

---

## 7. 实现步骤

### Phase 1: 数据层 ✅（2026-06-20 完成）

1. ✅ 新增 `industry_daily` + `industry_classify` 两张表到 `schema.sql`
2. ✅ `CacheManager` 添加对应读写方法（8 个方法 + schema validator）
3. ✅ `DataProvider` 添加 `_ensure_industry_classify()` + `_ensure_industry_daily()` + `_get_display_industry_codes()` + `get_industry_daily()`
4. ✅ 行业日线通过 `sw_daily` API 获取并落表，按行业并发（4 线程），每行业 ~659 行一页即可
5. ✅ `ensure_data_loaded()` 末尾 + 快速通道均调用行业数据加载
6. ✅ `check_cache_coverage()` 补充行业覆盖率检查
7. ✅ 进度回调 phase：`"ind_classify"` / `"ind_daily"`
8. ✅ 日志完善：sw_daily 单行业日志含 code + rows + 耗时（INFO 级别）

**实现细节与设计差异**：
- 拉取范围为 63 个展示行业（SPLIT_L1/L2 规则计算），非全量 439 个
- 按行业并发拉取，非按日期段 chunk（单行业 1000d ≈ 659 行，无需分页）
- 行业数据存在独立 `industry_daily` 表，不复用 `tushare_cache`（字段不同：有 pct_change，无 adj_factor）
- SQLite WAL 模式 + `busy_timeout=30000`：`_upsert_adj_factors` 修复为走 `cache._get_conn()`（2026-06-20 踩坑：裸 `sqlite3.connect()` 无 timeout，8 并发写抛 `database is locked`）
- 独立日志文件待实现（当前与 data_provider 共用 `marketreview_data_data_provider.log`）

### Phase 2: 服务层

8. `DashboardService` 添加行业相关方法
9. 拆分配置常量化（SPLIT_L1 / SPLIT_L2 → `src/marketreview/tools/industry.py`）
10. 行业列表构建逻辑（递归拆分 + 名称映射）

### Phase 3: AI 导语

11. 新增 `prompts/guide_sector_item.md`
12. 新增 `prompts/guide_sector_summary.md`
13. `DashboardService.generate_ai_sector_analysis()` 实现三步流水线
14. 补充控制台进度回调（`"sector_start"` / `"sector_progress"` / `"sector_done"` / `"sector_summary_start"` / `"sector_summary_done"`）
15. AI 版本号升级（`_AI_VERSION` X 位递增 → `"3.x.x"`）

### Phase 4: 页面

16. `02_板块分析.py` 重写：AI 导语 → TOP5/BOTTOM5 → 行业分析 expander
17. 抽取 `render_index_section()` 使其可同时用于指数和行业（或直接复用）
18. 权重贡献 `pick_industry_label()` 同步更新为递归替换逻辑
19. `00_控制台.py` 增加行业分类规则展示（expander）

### Phase 5: 联调

20. 端到端测试：控制台加载 → 板块页面渲染 → AI 导语生成
21. 与 `01_市场全景` 的数据一致性验证

---

## 8. 关键设计决策

| 决策 | 原因 |
|------|------|
| 使用 `sw_daily` 付费 API（而非成分股聚合） | 申万官方指数，数据准确、零计算耗时、无最早日期限制、无需维护成分股列表 |
| 递归替换而非混合列表 | 逻辑自洽：拆 L1→L2→L3，不需要手动同步两份列表 |
| 行业分析集合去重 | TOP5 和权重贡献上榜行业可能重叠，expander 只出现一次 |
| AI 三步流水线 | 与市场全景模式一致：先并行出各行业导语 → 汇总总结 |
| 行业日线缓存到 SQLite | 遵循现有双窗口缓存模式，避免每次页面刷新都调 API |
| 按行业并发拉取（非按日期段） | sw_daily 不支持无 ts_code 全量拉取（内部 4000 行上限），单行业 1000d=659 行，一页即可 |
| 只拉 63 个展示行业（非全量 439） | 当前分析只需这 63 个，未展示行业用到时再拉 |
