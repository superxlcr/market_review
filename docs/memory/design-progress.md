---
name: design-progress
description: Current design progress for the A-stock market review system (updated 2026-06-14)
metadata: 
  node_type: memory
  type: project
  originSessionId: 55145255-5748-4ea9-b1aa-32fd8b27c26e
---

## Design Progress as of 2026-06-14

### Completed — Architecture
- **System Architecture**: 4 Agents + Streamlit Dashboard (CrewAI removed, replaced by direct LLM API calls)
- **Data Layer**: SQLite `tushare_cache` table. DataProvider as single entry point.
- **DataProvider rule**: All data access through DataProvider only. Tushare hidden inside.
  [[data-layer-architecture]]
- **Refactoring (2026-06-06)**: 
  - Step 1: Moved business logic to technical.py, fixed GetMarketBreadthTool violation, deleted custom_tool.py
  - Step 2: DashboardService + rendering/ module. app.py 691→519 lines.
  - Step 3: 交易日自动识别 — 无?date=时从今天逐日回溯找最近交易日；有?date=时校验是否为交易日，非交易日直接报错
  - 新增 `start-dashboard.bat` 一键启动脚本
  - Step 4: KD 指标重构 — 通达信公式 calc_kd() + 背离检测 detect_kd_divergence()，替换旧 KDJ
  - 颜色规范统一：看多=红，看空=绿（[[color-convention]]）
- **CrewAI Removal (2026-06-14)**: 删除 crew.py, main.py, config/agents.yaml, config/tasks.yaml, tools/market_tools.py, README.crewai.md。pyproject.toml 移除 crewai 依赖。Dashboard 零影响。
- **LLM Abstraction Layer (2026-06-14, designed, pending implementation)**:
  - `LLMClient` ABC + `OpenAIClient` (OpenAI 兼容，覆盖 DeepSeek)
  - Prompt 模板独立 `.md` 文件，`{variable}` 占位符
  - 配置从 `.env` 读取：LLM_PROVIDER, MODEL, OPENAI_API_KEY, OPENAI_API_BASE

### Completed — Agent 1 Dashboard
- **Market Overview**: Breadth card (dynamic 涨/跌 sentiment), turnover card, 10d trend chart
- **Index Section** (上证+创业板):
  - K-line chart (Plotly candlestick + 6 MA overlays + 成交额 bar subplot)
  - K-line chart: 成交额 bars (千元→亿)，红涨绿跌，日期标签已隐藏
  - OHLC table: price, open, change%, 今日/昨日成交额
  - MA table: value, direction (1d slope), role (支撑/压制/拖拽), 扣抵日, 扣抵量+后续均量
  - 成交额分析: today amount, 5d trend, 5/10/20均量, 5日10日均量状态 (金叉/死叉+天数)
  - Technical indicators (表格格式，百分比列宽对齐):
    - **KD(9,3,3)**: K/D值, 超买超卖区, |K-D|差值, 背离信号 (K<20/K>80 区分周期)
    - **RSI(9,9,9)**: RSI值, 超买超卖区, vs KD强度, 背离信号 (50 为 walk-back 边界)
    - **BIAS(10,20)**: 10日乖离 (±10 短线超买超卖), 月线乖离 (±7 超买超卖)
  - RSI 背离复用 KD 区间（K<20/K>80），`_find_kd_cycle_start` 公共函数
- **成交量→成交额**: All volume data now uses amount (千元→亿). DB/API zero changes.
- **Date parameter**: 使用 `st.session_state.trade_date` 跨页面共享日期，不再使用 `?date=` query param
- **Color convention**: Red=up/good, Green=down/bad. Volume comparison: gradient gray→saturated at 20%.
- **AI 导语 & 总结 (2026-06-14, designed, pending implementation)**:
  - [[ai-guide-design]] — 设计共识已定
  - `ai_summary` 表：PK (trade_date, summary_type, guide_key)，content + model + created_at
  - 生成时机：切日期 → 查DB无缓存 → 同步生成 → 入库渲染，失败非阻塞
  - 市场全景 3 大板块顶部各加 AI 导语，底部加每日总结
  - 控制台展示总结卡片
  - 实现计划：`docs/superpowers/plans/2026-06-14-agent1-ai-summary.md`（5 个任务）
  - 执行方式：当前会话串行执行（inline），非子代理

### Pending
- **AI Summary Implementation** — 5 tasks ready to execute (next session)
- K-line pattern (K线形态) — TODO placeholder, needs separate discussion
- Agent 2 (板块+赚钱效应+仓位策略)
- Agent 3 (个股技术分析)
- Agent 4 (交易记录+每日存档)

### Key Files
- Dashboard: `dashboard/app.py` (519 lines)
- Service: `dashboard/services/dashboard_service.py`
- Rendering: `dashboard/rendering/styles.py`, `charts.py`
- Technical lib: `src/marketreview/tools/technical.py` (950+ lines)
- Data layer: `src/marketreview/data/data_provider.py`, `cache_manager.py`
- LLM layer (pending): `src/marketreview/llm/__init__.py`, `openai_client.py`, `prompts/`
- Architecture doc: `ARCHITECTURE.md`

### Related
- [[data-layer-architecture]]
- [[agent3-design-decisions]]
- [[ai-guide-design]]

**Why:** Track progress across sessions.
**How to apply:** Read this memory at session start.
