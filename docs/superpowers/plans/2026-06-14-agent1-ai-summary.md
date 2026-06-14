# Agent 1 AI 导语 & 总结 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在市场全景和控制台页面集成 AI 导语与每日总结，去除 CrewAI 后用 LLM 抽象层直接调 API。

**Architecture:** DashboardService → LLMClient (抽象) → OpenAI-compatible API → 结果写入 ai_summary 表。导语和总结与日期绑定，切日期时查缓存、无则同步生成。Prompt 模板独立存放于 `llm/prompts/`。

**Tech Stack:** Python, Streamlit, plotly, openai SDK, SQLite

---

## File Structure

```
Create:
  src/marketreview/llm/__init__.py          # LLMClient 抽象类 + 工厂函数
  src/marketreview/llm/openai_client.py     # OpenAI 兼容实现
  src/marketreview/llm/prompts/
    guide_market_breadth.md                 # 市场概览导语 prompt
    guide_sh_index.md                       # 上证指数导语 prompt
    guide_cz_index.md                       # 创业板指导语 prompt
    summary.md                              # 每日总结 prompt

Modify:
  src/marketreview/data/schema.sql          # 新增 ai_summary 表
  src/marketreview/data/cache_manager.py    # 新增 get/save ai_summary 方法
  dashboard/services/dashboard_service.py   # 新增 AI 生成 + 查询方法
  dashboard/pages/00_控制台.py              # 新增总结卡片展示
  dashboard/pages/01_市场全景.py            # 新增导语 + 总结渲染
```

---

### Task 1: DB Migration — ai_summary 表

**Files:**
- Modify: `src/marketreview/data/schema.sql`
- Modify: `src/marketreview/data/cache_manager.py`

- [ ] **Step 1: 在 schema.sql 中新增 ai_summary 表**

在 `schema.sql` 末尾追加：

```sql
CREATE TABLE IF NOT EXISTS ai_summary (
    trade_date   TEXT NOT NULL,
    summary_type TEXT NOT NULL,
    guide_key    TEXT NOT NULL,
    content      TEXT NOT NULL,
    model        TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (trade_date, summary_type, guide_key)
);
```

- [ ] **Step 2: 在 CacheManager._EXPECTED_COLUMNS 中注册新表**

在 `cache_manager.py` 的 `_EXPECTED_COLUMNS` 字典末尾追加：

```python
"ai_summary": {
    "trade_date", "summary_type", "guide_key",
    "content", "model", "created_at",
},
```

并在 `_init_schema` 方法的 DROP TABLE 列表和 `_schema_ok` 保持一致（现有逻辑已通过 `_EXPECTED_COLUMNS` 字典驱动 schema 校验，如果 schema 不匹配会自动 DROP 全部重建）。

- [ ] **Step 3: 在 _init_schema 中添加 ai_summary 的 DROP**

在 `_init_schema` 的 `executescript` DROP 列表中加入：

```python
conn.executescript("DROP TABLE IF EXISTS ai_summary")
```

位置：紧接 `DROP TABLE IF EXISTS wave33_cache` 之后。

- [ ] **Step 4: 新增 get_ai_summary 方法**

在 `CacheManager` 类中添加：

```python
def get_ai_summary(self, trade_date: str, summary_type: str) -> list[dict]:
    """Get all AI summary rows for a given date and type.
    Returns list of dicts with keys: guide_key, content, model, created_at.
    """
    with self._get_conn() as conn:
        rows = conn.execute(
            "SELECT guide_key, content, model, created_at "
            "FROM ai_summary WHERE trade_date = ? AND summary_type = ?",
            (trade_date, summary_type),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: 新增 save_ai_summary 方法**

在 `CacheManager` 类中添加：

```python
def save_ai_summary(self, trade_date: str, summary_type: str,
                    guide_key: str, content: str, model: str = ""):
    """Insert or replace one AI summary row."""
    with self._get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO ai_summary "
            "(trade_date, summary_type, guide_key, content, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (trade_date, summary_type, guide_key, content, model),
        )
        conn.commit()
```

- [ ] **Step 6: 验证 DB 迁移**

Run:

```bash
cd "i:/AIcode/marketreview" && python -c "
from marketreview.data.cache_manager import CacheManager
cm = CacheManager()
# Test write
cm.save_ai_summary('20260612', 'market_overview', 'test', 'hello', 'test-model')
# Test read
rows = cm.get_ai_summary('20260612', 'market_overview')
print('Read back:', rows)
# Cleanup test
import sqlite3
conn = sqlite3.connect(cm.db_path)
conn.execute(\"DELETE FROM ai_summary WHERE trade_date='20260612'\")
conn.commit()
conn.close()
print('OK: ai_summary table works')
"
```

Expected: `Read back: [{'guide_key': 'test', 'content': 'hello', ...}]` then `OK`.

- [ ] **Step 7: Commit**

```bash
git add src/marketreview/data/schema.sql src/marketreview/data/cache_manager.py
git commit -m "feat(db): add ai_summary table with get/save methods in CacheManager"
```

---

### Task 2: LLM 抽象层

**Files:**
- Create: `src/marketreview/llm/__init__.py`
- Create: `src/marketreview/llm/openai_client.py`
- Create: `src/marketreview/llm/prompts/guide_market_breadth.md`
- Create: `src/marketreview/llm/prompts/guide_sh_index.md`
- Create: `src/marketreview/llm/prompts/guide_cz_index.md`
- Create: `src/marketreview/llm/prompts/summary.md`

- [ ] **Step 1: 创建 LLMClient 抽象类**

Write `src/marketreview/llm/__init__.py`:

```python
"""
LLM abstraction layer. Hides vendor differences behind a single interface.
"""
from abc import ABC, abstractmethod
import os


class LLMClient(ABC):
    """Unified interface for LLM API calls."""

    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Send a chat request and return the response text."""


def create_llm_client() -> LLMClient:
    """Factory: return an LLMClient based on LLM_PROVIDER env var.
    
    Supported providers: 'openai' (default, covers DeepSeek/OpenAI/any
    OpenAI-compatible endpoint).
    """
    # Import here to avoid circular imports at module level
    from marketreview.llm.openai_client import OpenAIClient
    return OpenAIClient()
```

- [ ] **Step 2: 创建 OpenAI 兼容客户端**

Write `src/marketreview/llm/openai_client.py`:

```python
"""OpenAI-compatible LLM client (DeepSeek, OpenAI, etc.)."""
import os
from openai import OpenAI

from marketreview.llm import LLMClient
from marketreview.log_util import get_logger

log = get_logger(__name__)


class OpenAIClient(LLMClient):
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com")
        # Normalize: ensure base_url ends with /v1
        if not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        self._model = os.environ.get("MODEL", "deepseek-chat")
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        log.info("OpenAIClient init: model=%s base_url=%s", self._model, base_url)

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()
```

- [ ] **Step 3: 创建 Prompt 模板文件**

Write `src/marketreview/llm/prompts/guide_market_breadth.md`:

```markdown
你是A股大盘分析师。根据以下今日市场概览数据，用2-3句话总结市场情绪与资金状态。
要求：简洁、有结论倾向（偏多/偏空/震荡），提及关键数字变化。只输出原文，不要多余文字或标题。

数据：
{data}
```

Write `src/marketreview/llm/prompts/guide_sh_index.md`:

```markdown
你是A股大盘分析师。根据以下上证指数技术数据，用2-3句话总结该指数的技术状态。
要求：覆盖趋势方向、量能变化、关键信号（均线/KD/RSI/BIAS中的异常值）。只输出原文，不要多余文字或标题。

上证指数技术数据：
{data}
```

Write `src/marketreview/llm/prompts/guide_cz_index.md`:

```markdown
你是A股大盘分析师。根据以下创业板指技术数据，用2-3句话总结该指数的技术状态。
要求：覆盖趋势方向、量能变化、关键信号（均线/KD/RSI/BIAS中的异常值）。只输出原文，不要多余文字或标题。

创业板指技术数据：
{data}
```

Write `src/marketreview/llm/prompts/summary.md`:

```markdown
你是A股大盘分析师。根据以下三个维度的导语，提炼一份市场总览总结（4-5句话）。
要求：覆盖整体市场定性（偏多/偏空/震荡）、今日关键信号、需要关注的风险点。只输出原文，不要多余文字或标题。

市场概览：
{guide_breadth}

上证指数：
{guide_sh}

创业板指：
{guide_cz}
```

- [ ] **Step 4: 验证 LLM 抽象层**

Run:

```bash
cd "i:/AIcode/marketreview" && python -c "
from marketreview.llm import create_llm_client
client = create_llm_client()
print('LLM client type:', type(client).__name__)
print('Model:', client.model_name)
# Quick smoke test — a trivial prompt
resp = client.chat('你是一个助手', '回复OK')
print('Response:', resp[:50])
"
```

Expected: prints client type + model name + `Response: OK` (or similar short reply).

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/llm/
git commit -m "feat(llm): add LLMClient abstraction + OpenAI-compatible implementation + prompts"
```

---

### Task 3: DashboardService AI 方法

**Files:**
- Modify: `dashboard/services/dashboard_service.py`

- [ ] **Step 1: 添加 import 和 LLM client 懒加载**

在 `dashboard_service.py` 顶部 import 区域追加：

```python
from marketreview.tools.technical import build_technical_summary
```

（`rows_to_df` 已从 `technical` 导入，`build_technical_summary` 在同一模块。）

在 `DashboardService.__init__` 末尾添加：

```python
self._llm_client = None  # lazy init
```

- [ ] **Step 2: 添加 _load_prompt 辅助方法**

```python
@staticmethod
def _load_prompt(name: str) -> str:
    """Load a prompt template from llm/prompts/<name>.md."""
    import os as _os
    prompt_dir = _os.path.join(
        _os.path.dirname(__file__),
        "..", "..", "src", "marketreview", "llm", "prompts",
    )
    filepath = _os.path.join(prompt_dir, f"{name}.md")
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
```

- [ ] **Step 3: 添加 _get_llm 方法**

```python
def _get_llm(self):
    """Lazy-init the LLM client."""
    if self._llm_client is None:
        from marketreview.llm import create_llm_client
        self._llm_client = create_llm_client()
    return self._llm_client
```

- [ ] **Step 4: 添加 get_ai_summary 方法（读缓存）**

```python
def get_ai_summary(self, trade_date: str) -> dict:
    """
    Read cached AI summaries for a given trade_date.
    Returns dict keyed by guide_key, each value is {content, model, created_at}.
    Returns empty dict if nothing cached.
    """
    rows = self._dp.cache.get_ai_summary(trade_date, "market_overview")
    return {r["guide_key"]: r for r in rows}
```

- [ ] **Step 5: 添加 generate_ai_summary 方法（同步生成 + 入库）**

```python
def generate_ai_summary(self, trade_date: str) -> dict:
    """
    Generate AI guides + summary for market_overview, store in DB, return result.
    Same dict shape as get_ai_summary().

    If all LLM calls fail, returns dict with a single 'error' key.
    Individual guide failures are replaced with a placeholder string.
    """
    import json as _json
    from marketreview.tools.technical import build_technical_summary

    llm = self._get_llm()
    model = llm.model_name
    result = {}
    FAIL_PLACEHOLDER = "AI 摘要暂时不可用"

    # --- 1. Market overview data ---
    overview = self.get_market_overview(trade_date)
    if overview is None or "error" in overview:
        return {"error": "无法获取市场概览数据"}

    # --- 2. Guide: market breadth ---
    breadth_data = {
        "今日涨跌比": f"{overview['today']['up']}:{overview['today']['flat']}:{overview['today']['down']}",
        "涨停": overview["today"]["up_limit"],
        "跌停": overview["today"]["down_limit"],
        "今日成交额": f"{overview['today']['total_yi']:,.0f}亿",
    }
    if overview["yesterday"]:
        breadth_data["昨日成交额"] = f"{overview['yesterday']['total_yi']:,.0f}亿"
        breadth_data["昨日涨跌比"] = f"{overview['yesterday']['up']}:{overview['yesterday']['flat']}:{overview['yesterday']['down']}"

    try:
        prompt = self._load_prompt("guide_market_breadth")
        guide_breadth = llm.chat("", prompt.format(data=_json.dumps(breadth_data, ensure_ascii=False)))
    except Exception as e:
        log.warning("guide_market_breadth LLM call failed: %s", e)
        guide_breadth = FAIL_PLACEHOLDER

    self._dp.cache.save_ai_summary(
        trade_date, "market_overview", "guide/market_breadth",
        guide_breadth, model,
    )
    result["guide/market_breadth"] = {"content": guide_breadth, "model": model}

    # --- 3. Guide: SH index ---
    sh_rows = self._dp.get_daily("000001.SH", end_date=trade_date, lookback_days=360)
    sh_summary = build_technical_summary("000001.SH", "上证指数", sh_rows)

    try:
        prompt = self._load_prompt("guide_sh_index")
        guide_sh = llm.chat("", prompt.format(data=_json.dumps(sh_summary, ensure_ascii=False)))
    except Exception as e:
        log.warning("guide_sh_index LLM call failed: %s", e)
        guide_sh = FAIL_PLACEHOLDER

    self._dp.cache.save_ai_summary(
        trade_date, "market_overview", "guide/sh_index",
        guide_sh, model,
    )
    result["guide/sh_index"] = {"content": guide_sh, "model": model}

    # --- 4. Guide: CZ index ---
    cz_rows = self._dp.get_daily("399006.SZ", end_date=trade_date, lookback_days=360)
    cz_summary = build_technical_summary("399006.SZ", "创业板指", cz_rows)

    try:
        prompt = self._load_prompt("guide_cz_index")
        guide_cz = llm.chat("", prompt.format(data=_json.dumps(cz_summary, ensure_ascii=False)))
    except Exception as e:
        log.warning("guide_cz_index LLM call failed: %s", e)
        guide_cz = FAIL_PLACEHOLDER

    self._dp.cache.save_ai_summary(
        trade_date, "market_overview", "guide/cz_index",
        guide_cz, model,
    )
    result["guide/cz_index"] = {"content": guide_cz, "model": model}

    # --- 5. Summary ---
    try:
        prompt = self._load_prompt("summary")
        summary = llm.chat("", prompt.format(
            guide_breadth=guide_breadth,
            guide_sh=guide_sh,
            guide_cz=guide_cz,
        ))
    except Exception as e:
        log.warning("summary LLM call failed: %s", e)
        summary = FAIL_PLACEHOLDER

    self._dp.cache.save_ai_summary(
        trade_date, "market_overview", "summary",
        summary, model,
    )
    result["summary"] = {"content": summary, "model": model}

    return result
```

- [ ] **Step 6: 验证**

Run:

```bash
cd "i:/AIcode/marketreview" && python -c "
from services.dashboard_service import DashboardService
svc = DashboardService()
# Generate for 0612
result = svc.generate_ai_summary('20260612')
print('Keys:', sorted(result.keys()))
for k, v in result.items():
    print(f'--- {k} ---')
    print(v['content'][:120])
    print()
"
```

Expected: 4 keys (`guide/market_breadth`, `guide/sh_index`, `guide/cz_index`, `summary`) with AI-generated Chinese text. Also verify DB:

```bash
cd "i:/AIcode/marketreview" && python -c "
from services.dashboard_service import DashboardService
svc = DashboardService()
cached = svc.get_ai_summary('20260612')
print('Cached keys:', sorted(cached.keys()))
print('Has content:', all(v['content'] for v in cached.values()))
"
```

Expected: same 4 keys loaded from cache (no LLM call).

- [ ] **Step 7: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: add generate_ai_summary + get_ai_summary in DashboardService"
```

---

### Task 4: 控制台总结卡片

**Files:**
- Modify: `dashboard/pages/00_控制台.py`

- [ ] **Step 1: 在日期确认加载完成后触发 AI 生成**

在 `00_控制台.py` 中，`st.session_state.trade_date = _pending` 设置之后（当前代码约第 139 行和第 189 行，两处将 `_pending` 写入 `st.session_state.trade_date` 的位置），追加 AI 生成调用。

找到第一个位置（fast path，约第 139 行 `st.session_state.trade_date = _pending`）：

```python
# After st.session_state.trade_date = _pending (fast path, line ~139)
# Ensure AI summary exists for this date
_cached = _service.get_ai_summary(_pending)
if not _cached:
    _service.generate_ai_summary(_pending)
```

找到第二个位置（slow path，约第 189 行 `st.session_state.trade_date = _pending`）：

```python
# After st.session_state.trade_date = _pending (slow path, line ~189)
# Ensure AI summary exists for this date
with st.status("正在生成 AI 总结...", expanded=False) as _ai_status:
    _cached = _service.get_ai_summary(_pending)
    if not _cached:
        _service.generate_ai_summary(_pending)
    _ai_status.update(label="✅ AI 总结已就绪", state="complete")
```

**注意**：fast path 处（缓存已覆盖，只做 wave33 扫描）也要加，改用 `st.status` 包裹 AI 生成部分，和 slow path 保持一致。

完整的 fast path 修改（约第 114-141 行）：

```python
if _service.check_cache_coverage(_pending):
    with st.status("正在扫描 3浪3...", expanded=True) as status:
        # ... existing wave33 progress callbacks unchanged ...
        w33_result = _service.ensure_wave33_computed(_pending, progress_cb=_w33_progress)
        status.update(
            label=f"✅ 3浪3 扫描完成（扫描 {w33_result['scanned']} 天，"
                  f"已缓存 {w33_result['cached']} 天，{w33_result['elapsed']}秒）",
            state="complete",
        )
    # ── AI summary ──
    with st.status("正在生成 AI 总结...", expanded=False) as _ai_status:
        _cached = _service.get_ai_summary(_pending)
        if not _cached:
            _service.generate_ai_summary(_pending)
        _ai_status.update(label="✅ AI 总结已就绪", state="complete")
    st.session_state.trade_date = _pending
    st.cache_data.clear()
    st.rerun()
```

- [ ] **Step 2: 在控制台底部展示总结卡片**

在 `00_控制台.py` 末尾（`st.markdown("---")`  + `st.caption("快速跳转...")` 之前）添加总结卡片渲染：

```python
# ── AI Summary Card ──
_current_td = st.session_state.get("trade_date")
if _current_td:
    _ai = _service.get_ai_summary(_current_td)
    if _ai and "summary" in _ai:
        st.markdown("---")
        st.markdown("### 🤖 当日复盘总结")
        _summary_content = _ai["summary"]["content"]
        st.info(_summary_content)
        # Also show individual guides collapsed
        with st.expander("📋 查看各板块导语"):
            for _gk in ["guide/market_breadth", "guide/sh_index", "guide/cz_index"]:
                if _gk in _ai:
                    _label = {
                        "guide/market_breadth": "市场概览",
                        "guide/sh_index": "上证指数",
                        "guide/cz_index": "创业板指",
                    }.get(_gk, _gk)
                    st.caption(f"**{_label}**")
                    st.text(_ai[_gk]["content"])
    elif _ai and "error" not in _ai:
        st.markdown("---")
        st.caption("🤖 AI 总结尚未生成（切换日期时将自动生成）")
```

- [ ] **Step 3: 验证控制台**

启动 dashboard，切到 0612，观察：
1. 数据加载 status 后出现 "正在生成 AI 总结..."
2. 完成后显示总结卡片
3. 展开可以看到三个导语
4. 切到另一个已有缓存的日期，总结直接显示不重复生成

手动验证：刷新 http://localhost:8501 并切换日期。

- [ ] **Step 4: Commit**

```bash
git add dashboard/pages/00_控制台.py
git commit -m "feat: add AI summary card to control panel with auto-generation on date switch"
```

---

### Task 5: 市场全景导语 + 总结

**Files:**
- Modify: `dashboard/pages/01_市场全景.py`

- [ ] **Step 1: 在 render_index_section 前添加导语插入逻辑**

在 `01_市场全景.py` 中需要添加一个辅助函数，用于在指数 section 的 K 线图之前渲染导语。

在 `render_index_section` 函数定义的后面（约第 58 行之前），但为了代码整洁，直接在市场概览、上证指数、创业板指三个区域的展开之前各自加导语。

市场全景页的渲染结构当前是：

```python
# Row 1: 涨跌比 + 成交额 (约第 752 行)
# Row 2: 10日趋势 (约第 859 行)
# Row 3: 3浪3 (约第 933 行)
# expander: 上证指数 (约第 1028 行)
# expander: 创业板指 (约第 1034 行)
# report.md (约第 1039 行)
```

修改方案：

**a) 在市场概览标题后（约第 731 行 `st.header("📈 市场概览")`）之后加导语**：

在 `st.header("📈 市场概览")` 之后、`load_market_overview` 的 `@st.cache_data` 装饰函数之前，插入：

```python
# AI 导语：市场概览
_ai_cache = _service.get_ai_summary(_trade_date_yyyymmdd)
if _ai_cache and "guide/market_breadth" in _ai_cache:
    st.info(f"🤖 {_ai_cache['guide/market_breadth']['content']}")
```

**b) 在上证指数 expander 内（约第 1028 行）**：

```python
with st.expander("📈 上证指数 000001.SH", expanded=True):
    # AI 导语
    if _ai_cache and "guide/sh_index" in _ai_cache:
        st.info(f"🤖 {_ai_cache['guide/sh_index']['content']}")
    render_index_section(_service, "000001.SH", "上证指数", end_date=_trade_date_yyyymmdd)
```

**c) 在创业板指 expander 内（约第 1034 行）**：

```python
with st.expander("📉 创业板指 399006.SZ", expanded=True):
    # AI 导语
    if _ai_cache and "guide/cz_index" in _ai_cache:
        st.info(f"🤖 {_ai_cache['guide/cz_index']['content']}")
    render_index_section(_service, "399006.SZ", "创业板指", end_date=_trade_date_yyyymmdd)
```

**d) 删除旧的 report.md 展示区域**（约第 1038-1045 行）：

删除：
```python
# ============ Agent 1 分析报告 ============
st.divider()
st.header("🤖 Agent 1 最新分析报告")
report_path = os.path.join(os.path.dirname(__file__), "..", "report.md")
if os.path.exists(report_path):
    with open(report_path, "r", encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("尚未生成分析报告。运行 `python -m src.marketreview.main YYYYMMDD` 后此处会显示 Agent 1 的 LLM 输出。")
```

**e) 在市场全景页面底部添加每日总结**：

替换刚才删除的 report.md 展示区域：

```python
# ============ AI 每日总结 ============
st.divider()
st.header("🤖 每日总结")
if _ai_cache and "summary" in _ai_cache:
    st.info(_ai_cache["summary"]["content"])
elif _ai_cache and "error" in _ai_cache:
    st.caption("AI 总结生成失败，请稍后重试")
else:
    st.caption("AI 总结尚未生成（切换日期时将自动生成）")
```

- [ ] **Step 2: 注意 _ai_cache 变量作用域**

`_ai_cache` 在 Step 1a 首次使用，需要确保它在后续的上证和创业板 expander 中可见。由于都在同一函数作用域内（page 主体），`_ai_cache` 只需在第一次使用前定义即可。实际上 Step 1a 中已经定义了 `_ai_cache = _service.get_ai_summary(_trade_date_yyyymmdd)`，后续直接复用。

**但要注意**：`_service` 在第 717 行定义，而市场概览部分的 `load_market_overview` 使用了 `@st.cache_data` 装饰的函数，该函数内部有 `DashboardService()` 的独立实例。这不影响 `_ai_cache` 的读取——`_service` 是页面级的实例，`get_ai_summary` 只读缓存不调 API。

- [ ] **Step 3: 移除未使用的 import**

若 `from rendering.charts import plot_turnover_trend` 不再使用（检查确认），可以移除。当前 `plot_turnover_trend` 在代码中未使用，10日趋势图是直接在页面内用 `go.Figure()` 构建的。移除该 import。

- [ ] **Step 4: 验证完整流程**

```bash
# Full restart
netstat -ano | grep ":8501.*LISTENING" | awk '{print $NF}' | while read pid; do taskkill //pid $pid //f 2>/dev/null; done
sleep 2
cd "i:/AIcode/marketreview" && python -c "import os,shutil;[shutil.rmtree(os.path.join(r,d),ignore_errors=True) for r,ds,f in os.walk('.') if '__pycache__' in ds and '.venv' not in r]" 2>/dev/null
nohup .venv/Scripts/python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true > /tmp/streamlit.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "%{http_code}" http://localhost:8501
```

然后浏览器验证：
1. 打开 http://localhost:8501，进入控制台
2. 切到 2026-06-12，观察 AI 生成过程
3. 切到市场全景页，检查三个导语 + 底部总结
4. 切控制台，确认总结卡片
5. 切回 0612 或另一个日期，确认缓存命中不再重新生成

- [ ] **Step 5: Commit**

```bash
git add dashboard/pages/01_市场全景.py
git commit -m "feat: add AI guides to market panorama sections + daily summary at bottom"
```
