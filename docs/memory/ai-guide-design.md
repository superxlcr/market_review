---
name: ai-guide-design
description: AI 导语设计共识 — 市场全景三大板块顶部加 AI 导读 + 每日总结，设计已定，实现待执行
metadata: 
  node_type: memory
  type: project
  tags: 
    - agent1
    - ai
    - dashboard
    - design
  originSessionId: eef93c42-d435-4bd5-83aa-0652884de2de
---

## AI 导语 — 市场全景板块导读

### 共识（已定）
- 市场全景三大板块（市场概览、上证指数、创业板指）各自顶部加 AI 导读
- 作用：导语/先导，帮使用者快速了解本板块核心要点，降低阅读负担
- 与日期绑定，存 SQLite `ai_summary` 表，控制台切换日期时直接查库渲染
- AI 角色：辅助填头，有更好，没有也不阻塞数据展示
- LLM 调用：DashboardService 直接调 LLM API（CrewAI 已删除）
- 生成时机：切日期 → 查DB无缓存 → 同步生成 → 入库渲染，失败显示"AI 摘要暂时不可用"
- 数据边界：固定维度喂数据（方式A），不给 AI 自由查询 tool
- 扩展性：未来 Agent 2/3 复用同一张表，`summary_type` 区分（market_overview / sector_analysis / stock_tracking）

### DB 表结构
```sql
CREATE TABLE ai_summary (
    trade_date   TEXT NOT NULL,
    summary_type TEXT NOT NULL,   -- 'market_overview' | 'sector_analysis' | 'stock_tracking'
    guide_key    TEXT NOT NULL,   -- 'guide/market_breadth' | 'guide/sh_index' | 'guide/cz_index' | 'summary'
    content      TEXT NOT NULL,
    model         TEXT,
    created_at   TEXT,
    PRIMARY KEY (trade_date, summary_type, guide_key)
);
```

### Prompt 模板（4 个）
- `src/marketreview/llm/prompts/guide_market_breadth.md`
- `src/marketreview/llm/prompts/guide_sh_index.md`
- `src/marketreview/llm/prompts/guide_cz_index.md`
- `src/marketreview/llm/prompts/summary.md`

### 实现计划
- `docs/superpowers/plans/2026-06-14-agent1-ai-summary.md`（5 个任务）
- 执行方式：当前会话串行执行（inline），用户选择
- 下次会话从 Task 1（DB migration）开始

### Related
- [[design-progress]]
- [[agent3-design-decisions]]
