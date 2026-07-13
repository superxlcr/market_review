# Memory Guide — 项目知识库使用说明

> **目标读者：公司电脑上的 AI（Claude Code / 其他 AI 编程助手）**
>
> 这份指南教你如何利用 `docs/memory/` 里的知识来理解和维护这个项目。

---

## 1. 什么是 Memory 系统

`docs/memory/` 是本项目的**持久化知识库**。它记录了：

| 类型 | 内容 | 示例 |
|------|------|------|
| **约定（convention）** | 强制遵守的规则 | 日期格式必须 YYYYMMDD、红色=看涨 |
| **设计决策（design）** | 为什么这么做，权衡了什么 | 数据层用 qfq 乘法不用通达信减法 |
| **参考（reference）** | 怎么操作、怎么调试 | 如何启动 Dashboard、DB schema |
| **用户偏好（feedback）** | 用户要求的输出格式、流程 | 改动后要输出变更总结表 |

每个 `.md` 文件 = 一条知识，由 `MEMORY.md` 做索引。

## 2. 工作流程

### 2.1 改代码前（强制）

`CLAUDE.md` 里写了完整流程，核心三步：

1. **先读 `docs/memory/MEMORY.md`** 找到相关的 memory 文件
2. **读那些文件**，引用规则
3. **说出你的计划**，等用户批准再写代码

**永远不能跳过。** 这是用户和上一个 AI 多次踩坑后定下的铁律。

### 2.2 改代码后

1. **Bump 版本号** → `_AI_VERSION` 在 `dashboard/services/dashboard_service.py`（Z+1 修 bug，Y+1 新功能）
2. **输出变更总结表** → 文件、改了什么、为什么
3. **验证** → 说清楚怎么验证的

### 2.3 重启 Dashboard

改完 Streamlit 代码后：

```bash
.venv/Scripts/python restart_streamlit.py --bind 127.0.0.1
```

原理见 `docs/memory/streamlit-cache-clear.md` — Windows 下 `.pyc` 缓存非常顽固。

## 3. 关键约定速查

| 约定 | 文件 | 一句话 |
|------|------|--------|
| 版本号 | `ai-version-number.md` | 每次改动都要 Bump Z |
| 日期格式 | `date-format-convention.md` | 永远 YYYYMMDD，DB 查询不能用 `_with_dashes` |
| 颜色 | `color-convention.md` | 红=看涨(bullish)，绿=看跌(bearish)，**不能反过来** |
| 缓存查询 | `always-filter-by-date.md` | 永远 `WHERE trade_date = ?`，不要裸 `LIMIT N` |
| 日志 | `logging-convention.md` | INFO=流程，DEBUG=数据，WARNING=异常 |
| 路径 | 本项目所有引用 | **用相对路径，不要用绝对路径** |

## 4. 项目结构

```
src/marketreview/     — 核心库（数据层、工具、渲染）
  data/               — DataProvider + SQLite cache
  tools/              — 技术指标、买点检测、波段分析、3浪3扫描
  winrate/            — 胜率回测引擎
dashboard/            — Streamlit UI
  pages/              — 各页面
  services/           — DashboardService（编排层）
docs/memory/          — 项目知识库（本目录）
scripts/              — 工具脚本（db_query, kill_port, debug_stock）
tests/                — pytest 测试
data/                 — SQLite 数据库（自动生成，gitignored）
logs/                 — 日志文件（自动生成，gitignored）
```

## 5. 记忆文件列表

以下是 `docs/memory/` 中所有文件的简要说明：

### 流程与约定
- `mandatory-pre-change-workflow.md` — **改代码前必读**：先列 memory、再说计划、等批准
- `ai-version-number.md` — X.Y.Z 版本号规则
- `change-summary-preference.md` — 用户要变更总结表
- `verify-before-commit.md` — 提交前验证清单

### 代码约定
- `date-format-convention.md` — 日期永远是 YYYYMMDD
- `color-convention.md` — 红涨绿跌
- `always-filter-by-date.md` — 缓存查询必须过滤日期
- `logging-convention.md` — 日志级别规范
- `calc-kd-dual-purpose.md` — calc_kd vs calc_kd_standard 用途区别

### Dashboard
- `dashboard-setup.md` — 如何启动/停止 Streamlit
- `dashboard-page-registration.md` — 页面注册方式（st.Page，非自动发现）
- `dashboard-test-workflow.md` — 测试流程
- `streamlit-cache-clear.md` — Windows 下正确清理 Streamlit 缓存
- `market-panorama-reference.md` — 市场全景页面完整参考
- `ai-guide-design.md` — AI 导语设计
- `ai-prompt-data-principle.md` — AI prompt 数据原则

### 数据层
- `data-layer-architecture.md` — v3：raw+adj_factor→qfq，增量加载
- `database-schema-reference.md` — 完整 DB schema（11 张表）
- `cache-levels-design.md` — 三级缓存设计
- `two-window-cache-design.md` — 双窗口缓存设计
- `data-gap-detection.md` — 数据缺口自动检测

### 交易系统
- `trading-system-design-goal.md` — 系统目标：捕捉 30%+ 趋势行情
- `trader-profile.md` — 用户画像
- `trading-time-boundaries.md` — 交易时间边界
- `agent3-design-decisions.md` — Agent 3 设计决策
- `design-progress.md` — 系统设计进度

### 指标与买点
- `band-vp-constraint.md` — 波段 V/P 约束推导
- `industry-label-override.md` — 行业标签覆盖机制
- `fundamental-analysis-design.md` — 基本面分析设计讨论

### 参考
- `utility-scripts.md` — 工具脚本使用说明
- `query-stock-industry.md` — 查个股行业分类
- `qfq-vs-tongdaxin.md` — 前复权口径差异说明（不是 bug）
- `visual-companion-setup.md` — 设计 mockup 服务器

## 6. 常见坑

1. **改完代码不生效** → 99% 是 Streamlit 进程没杀干净，旧 `.pyc` 还在跑。用 `restart_streamlit.py`。
2. **DB 查询返回 0 行** → 日期格式错了，检查是否用了 `_with_dashes`。
3. **3浪3 图表颜色乱跳** → 数据窗口不够大，trend computation 需要足够历史数据稳定。
4. **用绝对路径** → 本项目禁止，换电脑就炸。
