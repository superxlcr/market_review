# Agent 1 AI 导语 & 总结 — 设计文档

## 背景

市场全景页面功能充裕但数据量大，用户全量阅读压力重。引入 AI 在板块顶部生成导读，帮助快速了解核心要点。同时每日生成总结供控制台和历史回溯使用。

## 核心设计决策

| 决策 | 结论 |
|------|------|
| AI 角色 | 辅助填头，有更好，没有也不阻塞数据展示 |
| LLM 调用 | 去除 CrewAI，DashboardService 直接调 LLM API |
| 生成时机 | 切日期 → 查DB无缓存 → 同步生成 → 入库渲染 |
| 失败策略 | 显示"AI 摘要暂时不可用"，页面其余正常 |
| 数据边界 | 固定维度喂数据（方式A），不给 AI 自由查询 tool |
| 扩展性 | 未来 Agent 2/3 复用同一张表，`summary_type` 区分 |

## 数据库

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

## 页面渲染

### 市场全景页
- 市场概览板块顶部：插入导语区块（`guide/market_breadth`）
- 上证指数板块顶部：插入导语区块（`guide/sh_index`）
- 创业板指板块顶部：插入导语区块（`guide/cz_index`）
- 页面底部：每日总结区块（`summary`）

### 控制台
- 日期选择器下方：展示所有已生成的总结卡片
- 点击可跳转对应板块详情

## 文件结构

```
src/marketreview/llm/
├── __init__.py              # LLMClient 抽象基类 + 工厂函数
├── openai_client.py         # OpenAI 兼容实现（DeepSeek 等）
└── prompts/                 # Prompt 模板（Markdown，可独立修改）
    ├── guide_market_breadth.md
    ├── guide_sh_index.md
    ├── guide_cz_index.md
    └── summary.md

dashboard/
├── app.py                   # 不变
├── pages/
│   ├── 00_控制台.py          # 新增：总结卡片展示
│   └── 01_市场全景.py         # 新增：导语 + 总结渲染
├── services/
│   └── dashboard_service.py  # 新增：generate_ai_summary() / get_ai_summary()
└── rendering/
    └── charts.py             # 不变
```

## LLM 抽象层

```python
class LLMClient(ABC):
    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> str: ...

def create_llm_client() -> LLMClient:
    # 按 LLM_PROVIDER 环境变量选择实现
    # 默认: openai 兼容（覆盖 DeepSeek / OpenAI / 其他）
```

配置从 `.env` 读取：`LLM_PROVIDER`、`MODEL`、`OPENAI_API_KEY`、`OPENAI_API_BASE`。

## 生成流程

```
DashboardService.generate_ai_summary(trade_date, summary_type="market_overview")
├─ 1. 加载市场数据（get_market_overview + get_index_data × 2）
├─ 2. 依次生成 3 个导语：
│   ├─ guide_market_breadth ← prompt 模板 + 市场概览数据
│   ├─ guide_sh_index       ← prompt 模板 + 上证技术摘要
│   └─ guide_cz_index       ← prompt 模板 + 创指技术摘要
├─ 3. 提炼总结：
│   └─ summary ← prompt 模板 + 3个导语
├─ 4. 写入 ai_summary 表
└─ 5. 返回结果
```

## 清理范围

删除以下文件/目录（无 Dashboard 依赖）：
- `src/marketreview/crew.py`
- `src/marketreview/main.py`
- `src/marketreview/config/`（agents.yaml + tasks.yaml）
- `src/marketreview/tools/market_tools.py`
- `README.crewai.md`
- `pyproject.toml` / `requirements.txt` 中的 `crewai` 依赖

保留：
- `src/marketreview/tools/technical.py` 中的 `build_technical_summary()`（DashboardService 用它拼数据喂 LLM）
- `src/marketreview/tools/contribution.py`（同上）

## 非交易日处理

控制台已有交易日校验（`st.session_state.trade_date` + `is_trading_day()`），非交易日不触发生成，无需额外处理。

## 未来扩展

Agent 2 板块分析和 Agent 3 个股追踪完成后，按同样模式：
- 新增 `sector_analysis`、`stock_tracking` 的 `summary_type`
- 各板块顶部加 AI 导语
- 控制台展示对应总结卡片
