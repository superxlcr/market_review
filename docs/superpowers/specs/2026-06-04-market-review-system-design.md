# A股复盘系统 — 完整设计规格书

> 日期：2026-06-04 | 状态：待评审

## 1. 系统概述

基于 CrewAI Flow 的 A 股每日复盘系统。<strong>交易日手动触发一次</strong>：大盘分析 → 板块+赚钱效应 → 个股跟踪 → 存档。前端用 Streamlit Dashboard 单页展示全部结果。

### 1.1 核心理念

- **LLM 做推理**（趋势判断、状态归类、文字总结）
- **代码做计算**（均线、指标、分位、公式）
- **基本面一次性判定，技术面每日跟踪**
- **Agent 给参考点位，用户自己做交易决策**

---

## 2. 系统架构

```
CrewAI Flow (main.py)
  ├── @start → Agent 1: 大盘分析
  ├── @listen(Agent1) → Agent 2: 板块+赚钱效应+仓位策略
  ├── @listen(Agent2) → Agent 3: 个股技术分析（自选股逐只）
  └── @listen(Agent3) → Agent 4: 交易记录+每日存档+跨日追踪

工具层 (src/marketreview/tools/)
  ├── technical.py        # 通用技术分析（K线/均线/量能/指标）— Agent 1/2/3 共享
  ├── contribution.py     # 权重贡献分析（指数+板块）— Agent 1/2
  ├── wave33.py           # 33公式计算 — Agent 2 专用
  ├── valuation.py        # 基本面判定 PE/PB/DCF — 选股工具，非 daily Agent
  └── position_manager.py # 持仓成本分层止损止盈 — Agent 3 专用

数据层 (src/marketreview/data/)
  ├── data_provider.py    # 抽象接口 — 对上层隐藏数据源，Agent 工具只调这一层
  └── cache_manager.py    # 缓存持久化 — SQLite 读写/过期策略/批量预取

展示层 (Streamlit)
  └── dashboard.py        # 单页 APP，读取 Flow State + SQLite 渲染
```

> **数据层设计原则**：Agent 工具只调用 `data_provider` 的抽象方法（如 `get_daily(code, start, end)`），不感知底层是 tushare/akshare/wind。`data_provider` 内部先查 `cache_manager`，miss 再调外部 API 并写缓存。换数据源只改 `data_provider` 内部实现，上层零影响。

---

## 3. 数据层（SQLite，8 表）

| 表 | 用途 | 关键字段 |
|----|------|----------|
| `tushare_cache` | 日线/周线缓存（前复权） | code, date, open/high/low/close/vol, adj_factor |
| `watchlist` | 自选股 | code, name, industry, **tradable_type**(left/right/skip), tech_points(JSON), added_date |
| `trade_log` | 交易记录 | code, entry_date, entry_price, exit_date, exit_price, shares, reason |
| `pending_items` | 跨日追踪 | code, item_type, content, created_date, resolved_date |
| `report_archive` | 每日复盘存档 | date, agent_name, report_markdown, signals_json |
| `system_config` | 系统配置 | key, value |
| `custom_groups` | 自定义分组 | id, name, parent_group_id |
| `custom_group_members` | 分组成员 | group_id, stock_code |

### 3.1 复权策略

- **存储**：后复权价格 + adj_factor
- **计算**：前复权 = close × latest_adj_factor / adj_factor
- **展示**：统一用前复权

---

## 4. 通用技术分析框架（technical.py）

> 指数、行业板块、个股均使用以下 4 个分析维度。Agent 调用同样的工具方法，区别仅在于传入的标的类型和上下文。

### 4.1 K 线形态分析

- 单根 K 线：实体/影线比例 → 多空力量对比
- 组合形态：十字星/锤子线/吞没/孕线 → 短期方向信号
- 趋势观察：连阳/连阴、高低点方向 → 当前趋势强度

### 4.2 均线 + 成交量分析

- **均线系统**：MA5/10/20/60 排列（多头/空头/缠绕）+ 方向（↑/↓/→）
- **量价关系**：放量/缩量 vs 涨跌，判断资金态度
- **均量线**：5日/20日均量，当前量能处于什么水平
- **关键均线位置**：价格在 MA20/MA60 上方还是下方

### 4.3 技术指标

- **KDJ**：超买/超卖区域、金叉/死叉
- **RSI(6/14)**：短期/中期强弱
- **BIAS(6/12/24)**：乖离率，判断偏离均线的程度

### 4.4 权重贡献分析（仅指数 + 行业板块）

> 由 `contribution.py` 提供，个股 Agent 不调用。

- 对指数：前 10 权重股的涨跌贡献（拉升/拖累了多少点）
- 对板块：板块内权重股的集体方向 + 板块对大盘的贡献

---

## 5. Agent 1：大盘分析

### 5.1 定义

| 属性 | 值 |
|------|-----|
| Role | A股大盘分析师 |
| Goal | 判断今日整体市场环境（牛/熊/震荡/极端） |
| Tools | technical.py, contribution.py, data_provider.py |
| LLM | deepseek-v4-pro |
| max_iter | 10 |

### 5.2 分析内容

**技术分析（复用 §4 框架）：**
- 对上证指数、创业板指分别执行 K线形态 + 均线量能 + 技术指标 + 权重贡献

**Agent 1 特有分析：**
- **市场宽度**：涨跌比、涨停/跌停数、成交额（含环比变化、5日均量对比）

### 5.3 输出 → Flow State

| 字段 | 类型 | 说明 |
|------|------|------|
| `market_status` | str | 大盘定性（如"缩量偏弱，创业板相对强势"） |
| `market_detail` | dict | 各项指标结构化数据 |
| `index_contribution` | list[dict] | 指数成分股贡献 |

---

## 6. Agent 2：板块+赚钱效应+仓位策略

### 6.1 定义

| 属性 | 值 |
|------|-----|
| Role | A股板块轮动与仓位策略分析师 |
| Goal | 识别主力资金方向 + 33公式计算赚钱效应 + 输出仓位建议 |
| Tools | technical.py, contribution.py, wave33.py, data_provider.py |
| LLM | deepseek-v4-pro |
| max_iter | 12 |

### 6.2 分析内容

**技术分析（复用 §4 框架）：**
- 对每个板块指数执行 K线形态 + 均线量能 + 技术指标 + 权重贡献

**Agent 2 特有分析：**
- **33 公式赚钱效应**：`wave33.py` 计算 3浪3股票数量 + 20日盈利占比。关键是**数量变化趋势**（如"3日上升、5日下降"），不是绝对值。趋势决定市场情绪方向，进而决定仓位策略。
- **仓位策略**：基于33公式趋势 + 大盘环境的综合结论（具体阈值实现时再细化）。输出风险等级 + 仓位建议。
- **板块筛选**：涨幅前5 + 主力净流入，板块内代表性个股（含33公式状态）

### 6.3 输出 → Flow State

| 字段 | 类型 | 说明 |
|------|------|------|
| `sector_analysis` | str | 板块分析 Markdown |
| `wave33_count` | int | 3浪3股票数量 |
| `wave33_trend` | str | 变化趋势（如"近3日↓ 近5日↓"） |
| `position_advice` | str | 仓位策略结论（风险等级 + 建议仓位） |

---

## 7. Agent 3：个股技术分析

### 7.1 基本面 vs 技术面分离

| 环节 | 时机 | 工具 | 产出 |
|------|------|------|------|
| 基本面判定 | 加入自选股时（一次性） | `valuation.py`（PE/PB分位 + DCF + 财报交叉） | `tradable_type`: left / right / skip |
| 技术面分析 | 每日复盘 | `technical.py` | 技术状态 + 关键点位 + 持仓管理 |

> **基本面判定不是 Agent**，是纯代码工具 `valuation.py`。只在加自选股/财报更新时手动触发。不在每日 Flow 执行链路上。

### 7.2 Agent 定义

| 属性 | 值 |
|------|-----|
| Role | A股个股技术分析师 |
| Goal | 判定每只自选股技术状态，输出入场/止损/止盈参考点位 |
| Backstory | 资深个股技术分析师，擅均线/量价/K线形态。不做基本面判断（选股时已定） |
| Tools | technical.py, position_manager.py, data_provider.py |
| LLM | deepseek-v4-pro |
| max_iter | 15 |

### 7.3 分析内容

**技术分析（复用 §4 框架）：**
- 对每只自选股执行 K线形态 + 均线量能 + 技术指标（个股不调 contribution.py）

**Agent 3 特有分析：**
- 四状态判定 + 13天规则
- 未持仓 → 关键技术点位表
- 已持仓 → 成本分层止损止盈

### 7.4 四状态判定规则

> **初步框架**，具体判定条件和参数后面实现时细化。

| 状态 | 条件 | 操作 |
|------|------|------|
| 🔴 上升中（不能介入） | MA5/10/20↑ 多头 + 价格在 MA5 上方 + 无回调 | 已持仓按分层管理，未持仓等回调 |
| 🟢 已回调 X 天 | 多头未破 + 价格从高点回落 + X < 13 天 | 找拉回买入点位 |
| 🟡 等待突破 | 回调 ≥ 13 天 | 拉回模式失效，只等放量突破 |
| ⚫ 下跌中 | MA60↓ + 价格在所有均线下方 | 忽略，趋势已坏 |

**判定逻辑**：MA60 方向 + 价格与 MA60 关系 → 定大方向（多头/空头）；价格与 MA5/MA10 关系 + 距前高天数 → 定子状态。

**13 天规则**：回调超过 13 天 → 拉回模式失效 → 切换到等待突破。已持仓不受此规则影响。

### 7.5 两种分析路径

#### 未持仓 → 入场参考

输出关键技术点位表（每项附止损价）：

- MA20 支撑、MA60 支撑、量价节点支撑、缺口支撑、前低支撑
- 前高压力（突破目标）
- 仅"等待突破"状态：回调一半突破位 = (前高 + 回调低点) / 2

#### 已持仓 → 成本分层管理

| 浮盈区间 | 止损策略 | 止盈策略 |
|----------|----------|----------|
| 0% ~ 10% | 入场成本 -3~5% | 不设止盈 |
| 10% ~ 20% | 移动止损至成本+3% | 回撤止盈：最高点-5% |
| 20%+ | 移动止损至 MA20 / 最高点-8% | 无硬止盈，跟 MA20/MA60 |

### 7.6 输出 → Flow State

| 字段 | 类型 | 说明 |
|------|------|------|
| `stock_analysis` | str | 所有自选股结构化分析 Markdown |
| `stock_signals` | list[dict] | [{code, name, state, key_levels, position_tier}] |
| `watchlist_updates` | list[dict] | 技术点位快照更新 |
| `pending_items` | list[dict] | 跨日追踪（如"回调第8天，距13天切换剩5天"） |

---

## 8. Agent 4：交易记录+每日存档+跨日追踪

> **简要设计**（待展开讨论）

### 8.1 职责

- **交易记录归档**：将当天的买卖操作写入 `trade_log`
- **每日存档**：将所有 Agent 输出写入 `report_archive`
- **跨日追踪管理**：处理 `pending_items`（过期清理、状态更新、提醒生成）

### 8.2 输入

- Agent 1/2/3 所有输出
- `trade_log` 增量
- `pending_items` 存量

### 8.3 输出

- `report_archive` 新行
- `pending_items` 更新
- 跨日对比摘要（如"上周今日 vs 本周今日"）

---

## 9. Dashboard（Streamlit 单页）

### 9.1 布局（从上到下）

```
┌─ 页面标题 + 日期 ─────────────────────────────┐
│ Agent 1: 大盘分析                              │
│  ├ 涨跌比 + 成交额（信息卡）                    │
│  ├ 📈 上证指数 K线+均线+量能 [可折叠]           │
│  └ 📈 创业板指 K线+均线+量能 [可折叠]           │
├─ Agent 2: 赚钱效应 + 仓位策略 + 板块分析        │
│  ├ 33公式柱状图 + 变化趋势（3日/5日）            │
│  ├ 仓位策略结论卡片                             │
│  └ 📊 板块分析 [可折叠]                         │
│      └ 每板块 = 完整K线+均线+量能卡片（同上证/创业板格式）│
├─ Agent 3: 个股技术分析                         │
│  ├ 自选股概览条（总数 / 持仓数）                 │
│  ├ 🍶 贵州茅台 [可折叠]                         │
│  │   ├ K线图 + 均线 + 量能 + AI评语             │
│  │   └ 关键技术点位表 / 持仓管理卡片             │
│  ├ 🔋 宁德时代 [可折叠]                         │
│  └ ... 更多自选股 ...                           │
└─ 底部: 状态规则速查 + 免责声明                  │
```

### 9.2 交互

- 指数/板块/个股均为**可折叠卡片**，默认展开关键项
- K 线图支持日/周/月切换（简化版用按钮，正式版用 Plotly）
- 亮色主题

---

## 10. 待决事项

> Agent 4 详细设计后续展开讨论（本次 spec scope 主要为 Agent 1-3 + Dashboard）

---

## 11. 技术栈

| 层 | 技术 |
|----|------|
| 编排 | CrewAI Flow（Python） |
| LLM | deepseek-v4-pro（所有 Agent） |
| 工具层 | Python（pandas + numpy + tushare） |
| 数据 | SQLite（8 表） |
| 前端 | Streamlit（Plotly 图表） |
| 数据源 | Tushare Pro API |
