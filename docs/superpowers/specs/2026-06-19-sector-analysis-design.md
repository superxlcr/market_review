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

按日聚合的行业级 OHLCV。每股等权计算价格变化，成交额/量直接求和。

```sql
CREATE TABLE IF NOT EXISTS industry_daily (
    industry_code TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    open          REAL,            -- 等权开盘价
    high          REAL,            -- 等权最高价
    low           REAL,            -- 等权最低价
    close         REAL,            -- 等权收盘价
    amount        REAL,            -- 总成交额（千元）
    vol           REAL,            -- 总成交量
    up_count      INTEGER,         -- 上涨家数
    down_count    INTEGER,         -- 下跌家数
    flat_count    INTEGER,         -- 平盘家数
    stock_count   INTEGER,         -- 成分股总数
    PRIMARY KEY (industry_code, trade_date)
);
```

### 3.3 聚合计算逻辑

对每个行业在交易日 T：

1. 从 `industry_member_cache` 获取成分股列表
2. 从 `tushare_cache` 读取所有成分股的当日 OHLCV（已前复权）
3. 价格：所有成分股价格的 **中位数**（等权，避免大市值股主导）
4. 成交额/量：所有成分股 **求和**
5. 涨跌家数：逐股比较 close vs pre_close（前复权后）

### 3.4 数据加载时机

在 `ensure_data_loaded()` 流程末尾（daily_basic 加载完成后）执行：

```
ensure_data_loaded()
  ├── ... (现有流程)
  ├── ensure_industry_members()   -- 首次/月度：拉取63个行业的成分股
  └── ensure_industry_daily()     -- 补齐 industry_daily 缺失日期
```

提供 `DashboardService` 方法：
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

> 注：指数采用等权聚合，均线角色/扣抵逻辑是否适用待后续评估微调。

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

### 5.4 缓存

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

### Phase 2: 服务层

5. `DashboardService` 添加行业相关方法
6. 新增行业聚合逻辑模块 `src/marketreview/tools/industry.py`
7. 拆分配置常量化

### Phase 3: AI 导语

8. 新增 `prompts/guide_sector_item.md`
9. 新增 `prompts/guide_sector_summary.md`
10. `DashboardService.generate_ai_sector_analysis()` 实现三步流水线

### Phase 4: 页面

11. `02_板块分析.py` 重写：AI 导语 → TOP5/BOTTOM5 → 行业分析 expander
12. 抽取 `render_index_section()` 使其可同时用于指数和行业（或直接复用）
13. 权重贡献 `pick_industry_label()` 同步更新

### Phase 5: 联调

14. 端到端测试：控制台加载 → 板块页面渲染 → AI 导语生成
15. 与 `01_市场全景` 的数据一致性验证

---

## 8. 关键设计决策

| 决策 | 原因 |
|------|------|
| 等权中位数聚合（非市值加权） | 行业内部大小票分化严重，中位数更能代表"行业整体" |
| 递归替换而非混合列表 | 逻辑自洽：拆 L1→L2→L3，不需要手动同步两份列表 |
| 行业分析集合去重 | TOP5 和权重贡献上榜行业可能重叠，expander 只出现一次 |
| AI 三步流水线 | 与市场全景模式一致：先并行出各行业导语 → 汇总总结 |
| 行业日线缓存而非实时聚合 | 63 行业 × 5000 股票聚合成本高，遵循"写时计算"原则 |
