# 数据库初始化闸门 — 设计文档

> 2026-06-19 · brainstorming 产出

## 概述

将控制台页面改造为**两阶段模式**：初始化阶段（一次性全量拉取 + 预计算）和日常使用阶段（秒开）。
未初始化前，日期选择器灰掉不可用，强制用户先完成初始化。

## 数据范围

| 项目 | 值 | 说明 |
|---|---|---|
| 数据起始日期 | **2021-01-01** | 固定起点，不用相对窗口 |
| 日期选择器下限 | **2023-01-01** | 留 2 年 MA240 缓冲 |
| 数据新鲜度阈值 | **15 天** | MAX(date) ≥ 今天-15 天视为正常 |

## UI 三态

### 状态 A：未初始化

- 行业分类规则 expander（保留，默认折叠）
- 「🔧 数据库初始化」标题 + 大按钮「🔄 开始初始化」
- 提示预计耗时（K线 ~4min + 市值 ~2min + 行业指数 ~8min + 3浪3 ~1min）
- 日期选择器 + 应用按钮灰掉不可用
- 无 AI 总结卡片

### 状态 B：初始化进行中

- 按钮变为进度面板，4 个阶段各显示状态（⏳进行中 / ✅完成 / ⏸等待中）
- 每阶段显示补拉详情（日期范围、段数）
- 实时日志滚动（如 `[INIT] K线: chunk 3/12 完成 (2022-05 ~ 2022-08), 耗时 35.2s`）
- 日期选择器保持灰色

### 状态 C：已就绪（日常使用）

- 一行绿色状态条：「✅ 数据库已就绪 · 2021-01-04 ~ 2026-06-18 · 60 行业 · 1320 交易日」
- 日期选择器正常可用
- 后续日常使用：日期选择 → 点应用 → 增量拉取（复用现有 `ensure_data_loaded` 逻辑）

## 快速检测 `_check_db_ready()`（页面加载自动跑，<1s）

4 条 SQL，纯只读：

| 表 | 检查项 |
|---|---|
| `tushare_cache` | MIN(date) ≤ 2021-01-01 **且** MAX(date) ≥ 今天-15 天（asset_type='stock'） |
| `daily_basic_cache` | MIN(trade_date) ≤ 2021-01-01 **且** MAX(trade_date) ≥ 今天-15 天 |
| `industry_daily` | COUNT(*) > 0 **且** MIN(trade_date) ≤ 2021-01-01 **且** MAX(trade_date) ≥ 今天-15 天 |
| `wave33_cache` | COUNT(*) > 0 **且** MAX(trade_date) ≥ 今天-15 天 |

全部通过 → `all_ready = True`，显示状态 C。

## 初始化流程 `_run_initialization(progress_cb, log_cb)`

**核心原则**：智能补缺，不复拉已有数据；行业指数除外（链式复利要求连续）。

### Phase 1: K线

```
IF MIN(date) ≤ 2021-01-01 AND MAX(date) ≥ 今天-15天:
    跳过
ELSE:
    补拉 [2021-01-01, 今天] 中缺失的日期段
    复用 _ensure_daily_loaded() chunk 逻辑
```

### Phase 2: 市值

```
IF MIN(trade_date) ≤ 2021-01-01 AND MAX(trade_date) ≥ 今天-15天:
    跳过
ELSE:
    补拉缺失段
```

### Phase 3: 行业指数

```
IF MIN(trade_date) ≤ 2021-01-01:
    跳过（已完整）
ELSE:
    DELETE FROM industry_daily  ← 清空重算
    调用 _backfill_industry_range(2021-01-01, 今天, industries, ...)
    复用已有的 6 线程 ThreadPoolExecutor 并行计算
```

**行业指数必须清空重算的原因**：链式复利 `close_today = base_close × (1 + w_ret)`，
前面的数据缺失会导致后续所有日期的 base_close 错误（从 1000 起算而非真实前值）。

### Phase 4: 3浪3

```
增量扫描缺失日期
复用现有 ensure_wave33_computed() 逻辑
```

### 完成后

- 写 `init_status` 标记位
- UI 自动切换到状态 C
- 日志打印总耗时

## 日志规范

每个 phase 开始/结束/跳过必须打日志，格式 `[INIT] Phase X/4 名称: 动作`。

示例：
```
[INIT] Phase 1/4 K线: 检测中...
[INIT] K线: 已有 2023-06-01~2026-06-18, 缺口 2021-01-01~2023-05-31
[INIT] K线: 开始补拉 2021-01-01~2021-03-15 (chunk 1/10)...
[INIT] K线: chunk 1/10 完成, 耗时 45.2s
[INIT] K线: 全部完成, 10 段, 总耗时 234.5s
[INIT] Phase 2/4 市值: 已完整, 跳过
[INIT] Phase 3/4 行业指数: MIN=2025-02-05 > 2021-01-01, 清空重算
[INIT] 行业指数: 已清空 industry_daily (原 20040 行)
[INIT] 行业指数: 60 行业, 1340 天待算, 开始回填（6 线程并行）...
[INIT] 行业指数: 全部完成, 80400 行, 耗时 487.3s
[INIT] Phase 4/4 3浪3: 缺失 30 天, 开始扫描...
[INIT] 3浪3: 全部完成, 30 天, 耗时 45.2s
[INIT] ✅ 全部完成! 总耗时 812.0s (13.5min)
```

## 文件变更

| 文件 | 变更 |
|---|---|
| `dashboard/pages/00_控制台.py` | 三态 UI + 初始化按钮 + 日期选择器灰掉逻辑 |
| `dashboard/services/dashboard_service.py` | 新增 `check_db_ready()` + `run_initialization()` |
| `src/marketreview/data/data_provider.py` | 新增 `ensure_full_init()` 封装 4 阶段初始化 |
| `src/marketreview/data/cache_manager.py` | 新增 `get_init_status()` / `set_init_status()` |
| `src/marketreview/data/schema.sql` | 新增 `init_status` 表 |

不复用已删除的 `check_db_status()` 草案版本。

## 约束

- 初始化不弹确认框，直接跑
- 不复用相对日期窗口（_FETCH_DAYS 等），初始化固定起点 2021-01-01
- 复用现有并发计算（行业指数 6 线程 ThreadPoolExecutor）
- 日常增量逻辑（ensure_data_loaded）不受影响
