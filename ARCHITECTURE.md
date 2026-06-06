# ARCHITECTURE — A-stock Market Review System

## 分层架构

```
┌─────────────────────────────────────────────────┐
│  Dashboard (dashboard/app.py)                    │  ← 展示层：Streamlit UI
│    - 渲染 HTML 表格 / Plotly 图表                │
│    - 调用 rendering/ 中的图表组件                │
│    - 不包含业务逻辑                               │
├─────────────────────────────────────────────────┤
│  Agent Tools (src/marketreview/tools/)           │  ← 工具层：CrewAI BaseTool
│    - market_tools.py   Agent 1 的数据工具        │
│    - contribution.py   指数贡献计算              │
│    - 所有工具必须通过 DataProvider 访问数据      │
├─────────────────────────────────────────────────┤
│  Technical Lib (src/marketreview/tools/)         │  ← 业务逻辑：纯函数
│    - technical.py      技术分析（MA/量/指标等）   │
│    - Dashboard 和 Agent Tools 共用               │
├─────────────────────────────────────────────────┤
│  Data Layer (src/marketreview/data/)             │  ← 数据层：单一入口
│    - DataProvider      对外唯一接口              │
│    - CacheManager      内部 SQLite 缓存          │
│    - Tushare API       仅 DataProvider 内部调用  │
└─────────────────────────────────────────────────┘
```

## 核心设计规则

### 1. DataProvider 是数据唯一入口

- ✅ Dashboard / Agent Tools → `DataProvider.get_daily()` / `get_market_breadth()` / `get_latest_trade_date()`
- ❌ **禁止**在 DataProvider 之外调用 `ts.pro_api()` / `ts.pro_bar()`
- ❌ **禁止**在 DataProvider 之外直接使用 `CacheManager`
- **原因**: Tushare 可能替换为 akshare/Wind，数据源变更只需改 DataProvider 内部

详见 [[data-layer-architecture]]

### 2. 业务逻辑与渲染分离

- 计算/分析函数放在 `technical.py`，Dashboard 和 Agent Tools 共用
- Dashboard 只负责渲染，不实现业务逻辑
- 颜色生成器等纯渲染逻辑放在 Dashboard 侧

### 3. Agent Tools 必须通过 DataProvider

- `GetMarketBreadthTool` 调用 `DataProvider.get_market_breadth()`，不直接访问 `_api`
- `GetIndexTechnicalsTool` 调用 `DataProvider.get_daily()` + `build_technical_summary()`

## 模块职责

### `dashboard/app.py`
Streamlit 页面骨架：标题、日期解析、expander 循环、报告展示。
**不应包含**: 数据获取逻辑（应有 DashboardService）、业务计算（应在 technical.py）。

### `src/marketreview/tools/technical.py`
共享技术分析函数：
| 函数 | 用途 |
|------|------|
| `rows_to_df()` | 缓存行 → DataFrame |
| `calc_ma()` | 计算多周期均线 |
| `ma_direction()` | 均线方向（1日斜率） |
| `ma_arrangement()` | 均线排列（短期/中长期分判） |
| `get_offset_info()` | 扣抵日/扣抵量/后续均量 |
| `get_ma_role()` | 均线作用（支撑/压制/拖拽） |
| `volume_analysis()` | 成交额分析（均额/趋势/交叉） |
| `calc_kdj()` / `calc_rsi()` / `calc_bias()` | 技术指标 |
| `kline_pattern()` | K线形态（单根） |
| `build_technical_summary()` | 综合摘要（Agent 用） |

### `src/marketreview/tools/market_tools.py`
Agent 1 的 CrewAI 工具（BaseTool 子类）：
- `GetIndexTechnicalsTool` — 指数技术分析
- `GetMarketBreadthTool` — 市场宽度数据
- `GetIndexContributionTool` — 权重股贡献

### `src/marketreview/data/data_provider.py`
对外接口：
- `get_daily(code, lookback_days)` — K线数据（缓存+拉取）
- `get_latest_trade_date(code)` — 最新交易日
- `get_market_breadth(trade_date)` — 市场宽度

### `src/marketreview/data/cache_manager.py`
SQLite 缓存 CRUD，仅 DataProvider 内部使用。

## 数据流（以指数页面为例）

```
用户访问 ?date=20260605
  → app.py 解析日期
  → load_data("000001.SH", end_date="20260605")
    → DataProvider.get_daily("000001.SH")
      → CacheManager.get_daily()  [命中则返回，未命中则拉取]
      → Tushare API [仅在缓存过期/不足时]
  → rows_to_df() → DataFrame
  → render_index_section(df)
    → calc_ma() / ma_direction() / get_offset_info() / volume_analysis() / ...
    → HTML 表格 / Plotly 图表
```

## 数据库

当前仅 `tushare_cache` 表（schema.sql）。后续 Agent 2/3/4 会新增：
- `watchlist` — 自选股
- `trade_log` — 交易记录
- `report_archive` — 报告归档
- 等（详见设计文档）

## 文件清单

```
dashboard/
  app.py                    Streamlit 页面

src/marketreview/
  tools/
    technical.py            技术分析函数库（Dashboard + Agent 共用）
    market_tools.py          Agent 1 CrewAI 工具
    contribution.py          指数权重贡献计算
    __init__.py              导出清单
  data/
    data_provider.py         数据层唯一入口
    cache_manager.py         SQLite 缓存（内部）
    schema.sql               DDL
  config/
    agents.yaml              Agent 1 角色定义
    tasks.yaml               Agent 1 任务描述
  crew.py                    CrewAI crew 组装
  main.py                    CLI 入口
```

## 相关文档

- `docs/superpowers/specs/2026-06-04-market-review-system-design.md` — 完整系统设计
- `docs/superpowers/plans/2026-06-05-agent1-implementation.md` — Agent 1 实施计划
- `docs/tushare-integration-notes.md` — Tushare 踩坑笔记
