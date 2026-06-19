# 板块分析（Agent 2）— 设计文档

> 日期：2026-06-19
> 状态：待实现

## 1. 概述

将 `02_板块分析.py` 从 mock 占位符改造为完整的行业板块分析页面。

核心思路：申万行业指数没有现成 K 线，通过「成分股聚合」自下而上构建行业级 OHLCV，再复用市场全景的技术分析框架。

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

### 3.1 新表：`industry_member_cache`

缓存每个行业代码的成分股列表（通过 `tushare index_member` API 获取，月度刷新）。

```sql
CREATE TABLE IF NOT EXISTS industry_member_cache (
    industry_code TEXT NOT NULL,   -- 行业代码 (801081.SI / 850814.SI ...)
    con_code      TEXT NOT NULL,   -- 成分股代码
    PRIMARY KEY (industry_code, con_code)
);
```

### 3.2 新表：`industry_daily`

按日聚合的行业级 OHLCV。采用**市值加权**（与真实指数计算方式一致），以 `circ_mv`（流通市值）为权重。

```sql
CREATE TABLE IF NOT EXISTS industry_daily (
    industry_code TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    open          REAL,            -- 市值加权开盘价
    high          REAL,            -- 市值加权最高价
    low           REAL,            -- 市值加权最低价
    close         REAL,            -- 市值加权收盘价
    amount        REAL,            -- 总成交额（千元）
    vol           REAL,            -- 总成交量
    up_count      INTEGER,         -- 上涨家数
    down_count    INTEGER,         -- 下跌家数
    flat_count    INTEGER,         -- 平盘家数
    stock_count   INTEGER,         -- 成分股总数
    PRIMARY KEY (industry_code, trade_date)
);
```

### 3.3 市值加权聚合 — 为什么必须和真实指数一致

行业指数的核心用途之一，就是观察**权重股与小盘股的分化**：

- 权重股趴窝、小票乱炒 → 指数微涨但上涨家数很高 → 说明资金在炒题材，龙头未动
- 只有权重在动、其他不动 → 指数大涨但上涨家数很低 → 说明拉权重护盘，赚钱效应差

如果用等权或中位数聚合，这两种分化都会被掩盖。市值加权保留了指数内部的**结构信息**，让技术分析（均线角色、KD/RSI 背离、扣抵量等）与真实指数的分析逻辑保持一致。

**举例：半导体行业（209 只成分股）某天**

| 股票 | 流通市值 | 涨跌幅 | 权重 |
|------|----------|--------|------|
| 中芯国际 | 5000亿 | +0.3% | 25% |
| 寒武纪 | 2000亿 | +8.2% | 10% |
| 韦尔股份 | 1500亿 | +1.1% | 7.5% |
| ... (206只中小票) | 20~800亿 | -3%~+10% | 57.5% |

- 市值加权涨幅 ≈ 25%×0.3% + 10%×8.2% + 7.5%×1.1% + ...  → 结果反映"持有半导体板块的资金今天赚了多少"
- 同时保留 `up_count` / `down_count` 字段，可以观察：指数涨了但上涨家数很少（权重独舞），或指数没动但上涨家数很多（小票狂欢）
- 这与 01_市场全景 分析上证/创业板时的逻辑完全一致

**算法**：
1. 每日取所有成分股的 circ_mv → 计算每只股票的权重 `w_i = circ_mv_i / Σ circ_mv`
2. 行业涨跌幅 = `Σ (w_i × return_i)`（市值加权平均涨跌幅）
3. 用加权涨跌幅累乘构建行业价格曲线：`close_t = close_{t-1} × (1 + weighted_return_t)`
4. open/high/low 同理基于各成分股的 O/H/L 涨跌幅加权推算
5. 成交额/量 = 所有成分股 **求和**
6. 涨跌家数 = 逐只比较 close vs pre_close

### 3.4 聚合计算逻辑

对每个行业在交易日 T：

1. 从 `industry_member_cache` 获取成分股列表
2. 从 `tushare_cache` 读取所有成分股的当日 OHLCV（已前复权）
3. 从 `daily_basic_cache` 读取所有成分股的当日 circ_mv
4. 价格：基于 circ_mv **加权** 的涨跌幅累乘构建
5. 成交额/量：所有成分股 **求和**
6. 涨跌家数：逐股比较 close vs pre_close（前复权后）

### 3.5 数据加载时机

在 `ensure_data_loaded()` 流程末尾（daily_basic 加载完成后）执行：

```
ensure_data_loaded()
  ├── ... (现有流程)
  ├── ensure_industry_members()   -- 首次/月度：拉取63个行业的成分股
  └── ensure_industry_daily()     -- 补齐 industry_daily 缺失日期
```

### 3.6 控制台进度回调 & 日志

行业数据加载需接入控制台的进度条系统。在 `ensure_data_loaded()` 内新增两个阶段：

| 阶段 | progress_cb phase | 日志 |
|------|-------------------|------|
| 拉取成分股 | `"industry_members"` | `log.info("ensure_industry_members: %d/%d industries...")` |
| 聚合日线数据 | `"industry_daily"` | `log.info("ensure_industry_daily: date=%s, %d industries...")` |

遵循项目日志规范：`marketreview_tools_industry.log` 独立日志文件。

### 3.7 DashboardService 新增方法

- `ensure_industry_members(progress_cb)` → 拉取成分股列表
- `ensure_industry_daily(trade_date, progress_cb)` → 补齐行业日线
- `get_industry_daily(industry_code, end_date, lookback)` → 读行业K线
- `get_industry_ranking(trade_date)` → 63个行业按涨跌幅排序

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

从 63 个行业中按涨跌幅排序，取前 5 和后 5，展示：
- 行业名称 + 层级标签（L1/L2/L3）
- 涨跌幅（颜色编码）
- 上涨家数占比（如 `32/45 ↑`）
- 总成交额

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

> 注：行业指数采用市值加权聚合，与真实指数的技术分析逻辑完全一致，均线角色/扣抵逻辑直接适用。

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
| `get_industry_list()` | 返回 63 个行业的 (code, name, level) 列表 |
| `ensure_industry_members(progress_cb)` | 拉取成分股列表（首次/月度刷新） |
| `ensure_industry_daily(trade_date, progress_cb)` | 补齐行业日线数据 |
| `get_industry_daily(code, end_date, lookback)` | 读取行业 K 线 DataFrame |
| `get_industry_ranking(trade_date)` | 63 行业按涨跌幅排序 |
| `get_industry_analysis_set(trade_date)` | 选出去重后的分析集合（TOP5/BOTTOM5 + 权重贡献 + 频繁行业） |
| `get_ai_sector_guide(trade_date, industry_code)` | 读取单个行业 AI 导语缓存 |
| `get_ai_sector_summary(trade_date)` | 读取行业总结 AI 导语缓存 |
| `generate_ai_sector_analysis(trade_date, progress_cb)` | 完整三步流水线：行业导语（并行）→ 总结导语 |

---

## 7. 实现步骤

### Phase 1: 数据层

1. 新增 `industry_member_cache` + `industry_daily` 两张表到 `schema.sql`
2. `CacheManager` 添加对应读写方法
3. `DataProvider` 添加 `ensure_industry_members()` + `ensure_industry_daily()`
4. `ensure_data_loaded()` 末尾调用行业数据加载
5. 补充控制台进度条回调（`"industry_members"` / `"industry_daily"` 阶段）
6. 补充日志：新文件 `logs/marketreview_tools_industry.log`

### Phase 2: 服务层

7. `DashboardService` 添加行业相关方法
8. 新增行业聚合逻辑模块 `src/marketreview/tools/industry.py`（含日志初始化）
9. 拆分配置常量化（SPLIT_L1 / SPLIT_L2）

### Phase 3: AI 导语

10. 新增 `prompts/guide_sector_item.md`
11. 新增 `prompts/guide_sector_summary.md`
12. `DashboardService.generate_ai_sector_analysis()` 实现三步流水线
13. 补充控制台进度回调（`"sector_start"` / `"sector_progress"` / `"sector_done"` / `"sector_summary_start"` / `"sector_summary_done"`）
14. AI 版本号升级

### Phase 4: 页面

15. `02_板块分析.py` 重写：AI 导语 → TOP5/BOTTOM5 → 行业分析 expander
16. 抽取 `render_index_section()` 使其可同时用于指数和行业（或直接复用）
17. 权重贡献 `pick_industry_label()` 同步更新为递归替换逻辑
18. `00_控制台.py` 增加行业分类规则展示（expander）

### Phase 5: 联调

19. 端到端测试：控制台加载 → 板块页面渲染 → AI 导语生成
20. 与 `01_市场全景` 的数据一致性验证

---

## 8. 关键设计决策

| 决策 | 原因 |
|------|------|
| 市值加权聚合（与真实指数一致） | 保留权重股 vs 小盘股的结构信息，分化行情可见；与现有技术分析框架兼容 |
| 递归替换而非混合列表 | 逻辑自洽：拆 L1→L2→L3，不需要手动同步两份列表 |
| 行业分析集合去重 | TOP5 和权重贡献上榜行业可能重叠，expander 只出现一次 |
| AI 三步流水线 | 与市场全景模式一致：先并行出各行业导语 → 汇总总结 |
| 行业日线缓存而非实时聚合 | 63 行业 × 5000 股票聚合成本高，遵循"写时计算"原则 |
