# 买点胜率 3浪3 市场趋势维度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 买点胜率新增 3浪3 市场趋势维度——数据准备阶段预算每日 wave33 count，扫描时按 signal_date 算趋势状态回填 TradeResult 并写入 CSV，加 wave33 就绪门禁。

**Architecture:** 复用 `scan_wave33`（预算）+ `compute_trend`（状态）+ `get_wave33_range`（取序列）；`TradeResult` 加 3 字段；service 层 `check_winrate_coverage` 合并 kline+wave33 两门禁。

**Tech Stack:** Python 3.10, SQLite, Streamlit, pytest。

## Global Constraints

- 版本 `_AI_VERSION` 由 `9.8.0` → `9.9.0`（feature，Y+1）。
- 日期一律 YYYYMMDD。
- 日志：INFO 流程、DEBUG 数据、WARNING 异常。
- 缓存读取按 trade_date 过滤。
- 测试用真 SQLite 临时库，不触网。
- 复用 `scan_wave33` / `compute_trend` / `get_wave33_range`，不重写其逻辑。

**Spec:** [`docs/superpowers/specs/2026-07-13-winrate-wave33-dimension-design.md`](../specs/2026-07-13-winrate-wave33-dimension-design.md)

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `src/marketreview/winrate/trade_sim.py` | `TradeResult` 加 3 字段 | 加字段 |
| `src/marketreview/winrate/scan_engine.py` | `scan_stock` 加 cache 参数；`_tag` 回填；新增 `_wave33_state`；`run_scan` 传 cache | 改+加 |
| `src/marketreview/winrate/reporter.py` | `_EXPORT_FIELDS` 加 3 列 | 改 |
| `src/marketreview/data/data_provider.py` | 新增 `check_wave33_coverage` | 加 |
| `dashboard/services/dashboard_service.py` | `prepare_winrate_data` 加 scan_wave33；`check_winrate_coverage` 合并；版本 9.9.0 | 改 |
| `dashboard/pages/06_买点胜率.py` | 状态条细化 | 改 |
| `tests/winrate/test_wave33_state.py` | `_wave33_state` 测试 | 新建 |

依赖顺序：Task 1（TradeResult 字段）→ Task 2（scan_engine 回填）→ Task 3（reporter CSV）→ Task 4（provider 门禁）→ Task 5（service 集成+版本）→ Task 6（页面状态条）。

---

### Task 1: `TradeResult` 加 wave33 三字段

**Files:**
- Modify: `src/marketreview/winrate/trade_sim.py`（`TradeResult` dataclass，约 28-50 行）
- Test: `tests/winrate/test_trade_sim.py`（既有文件，追加）

**Interfaces:**
- Produces: `TradeResult.wave33_direction: str = ""` / `wave33_streak: int = 0` / `wave33_label: str = ""`

- [ ] **Step 1: Write the failing test**

Append to `tests/winrate/test_trade_sim.py`:

```python
def test_trade_result_wave33_fields_default_empty():
    """TradeResult 新增 wave33 三字段，默认空/0。"""
    from marketreview.winrate.trade_sim import TradeResult
    tr = TradeResult(
        buy_point="回调一半", code="600000.SH", name="测试",
        signal_date="20240101", entry_date="20240102", entry_price=10.0,
        exit_date="20240105", exit_price=10.5, exit_reason="小胜利",
        mfp_pct=12.0, hold_days=3, pnl_pct=5.0, success=True,
    )
    assert tr.wave33_direction == ""
    assert tr.wave33_streak == 0
    assert tr.wave33_label == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_trade_sim.py::test_trade_result_wave33_fields_default_empty -v`
Expected: FAIL `AttributeError: 'TradeResult' object has no attribute 'wave33_direction'`

- [ ] **Step 3: Add the three fields to TradeResult**

In `src/marketreview/winrate/trade_sim.py`, find the `TradeResult` dataclass (the field block ending with `industry_l1`/`industry_l2`). Add after `industry_l2`:

```python
    industry_l1: str = ""
    industry_l2: str = ""
    # 3浪3 市场趋势状态（按 signal_date 查 21 天 count 序列算，市场层标签）
    wave33_direction: str = ""   # "up" | "down" | "flat"
    wave33_streak: int = 0       # 连续天数
    wave33_label: str = ""       # "确认上升，连续上升 5 天" 等
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_trade_sim.py::test_trade_result_wave33_fields_default_empty -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/winrate/trade_sim.py tests/winrate/test_trade_sim.py
git commit -m "feat: TradeResult 加 wave33 direction/streak/label 三字段"
```

---

### Task 2: `scan_engine` 回填 wave33 状态

**Files:**
- Modify: `src/marketreview/winrate/scan_engine.py`
  - `scan_stock` 签名加 `cache=None`（38-40 行）
  - `_tag` 加 cache 参数 + 回填（105-111 行）
  - 新增 `_wave33_state` 函数
  - `run_scan._one` 调用处传 `cache=dp.cache`（138-142 行）
- Test: `tests/winrate/test_wave33_state.py`（新建）

**Interfaces:**
- Consumes: `cache.get_wave33_range(limit, end_date)`（返回 DESC list[{count,...}]）、`compute_trend(counts)`（返回 {direction, streak, label}）
- Produces: `scan_engine._wave33_state(cache, signal_date) -> dict`；`scan_stock(..., cache=None)`；`_tag(tr, df_upto, mv_yi, l1, l2, cache)`

- [ ] **Step 1: Write the failing tests**

Create `tests/winrate/test_wave33_state.py`:

```python
"""_wave33_state 测试：按 signal_date 查 21 天 count 序列算趋势状态。"""
from marketreview.data.cache_manager import CacheManager
from marketreview.winrate import scan_engine as SE


def _wave33_row(date, count):
    return {"trade_date": date, "count": count, "profit_count": 0,
            "profit_pct": 0.0, "stock_codes": "[]"}


def test_wave33_state_no_cache_returns_empty():
    """无 cache → 空状态（防御性，门禁已保证就绪）。"""
    res = SE._wave33_state(None, "20240105")
    assert res == {"direction": "", "streak": 0, "label": ""}


def test_wave33_state_insufficient_series_returns_empty(tmp_path):
    """序列不足 2 天 → 空状态。"""
    cm = CacheManager(str(tmp_path / "t.db"))
    cm.upsert_wave33("20240105", 10, 5, 50.0, "[]")   # 仅 1 天
    res = SE._wave33_state(cm, "20240105")
    assert res["direction"] == ""
    assert res["streak"] == 0


def test_wave33_state_confirmed_up(tmp_path):
    """连续 5 天 count 递增 → 确认上升。"""
    cm = CacheManager(str(tmp_path / "t.db"))
    # 20240101..20240105 每天递增（DESC 写入顺序无所谓，upsert 按 trade_date）
    for i, d in enumerate(["20240101", "20240102", "20240103", "20240104", "20240105"]):
        cm.upsert_wave33(d, 10 + i, 5, 50.0, "[]")
    res = SE._wave33_state(cm, "20240105")
    assert res["direction"] == "up"
    assert res["streak"] >= 5
    assert "确认上升" in res["label"]


def test_wave33_state_flat_when_equal(tmp_path):
    """count 全相等 → flat/盘整。"""
    cm = CacheManager(str(tmp_path / "t.db"))
    for d in ["20240101", "20240102", "20240103"]:
        cm.upsert_wave33(d, 10, 5, 50.0, "[]")
    res = SE._wave33_state(cm, "20240103")
    assert res["direction"] == "flat"
    assert "盘整" in res["label"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_wave33_state.py -v`
Expected: FAIL — `_wave33_state` 不存在。

- [ ] **Step 3: Add `_wave33_state` function**

In `src/marketreview/winrate/scan_engine.py`, add after `_tag` (after line 111), before `run_scan`:

```python
def _wave33_state(cache, signal_date: str) -> dict:
    """取 signal_date 及之前 21 天 wave33 count 序列，算趋势状态。
    缺数据 → 空状态（门禁已保证就绪；此处防御性返回空）。"""
    from marketreview.tools.wave33 import compute_trend
    if cache is None:
        return {"direction": "", "streak": 0, "label": ""}
    rows = cache.get_wave33_range(limit=21, end_date=signal_date)  # DESC
    if len(rows) < 2:
        log.warning("_wave33_state: signal_date=%s wave33 序列不足(%d)，留空",
                    signal_date, len(rows))
        return {"direction": "", "streak": 0, "label": ""}
    counts = [r["count"] for r in rows]   # most-recent-first（compute_trend 要求）
    return compute_trend(counts)
```

- [ ] **Step 4: Add `cache` param to `scan_stock` and `_tag`**

Change `scan_stock` signature (38-40 行):

```python
def scan_stock(code: str, name: str, rows_desc: list[dict], cfg: WinrateConfig,
               industry_l1: str, industry_l2: str, list_date: str,
               mv_series: dict[str, float], band_lookback: int = 300,
               cache=None) -> list[TradeResult]:
```

Find the `_tag(tr, ...)` call inside `scan_stock` (around line 87) and add `cache`:

```python
            _tag(tr, df_upto, mv_yi, industry_l1, industry_l2, cache)
```

Change `_tag` definition (105-111 行):

```python
def _tag(tr: TradeResult, df_upto, mv_yi, l1, l2, cache=None):
    tr.short_ma_state = ma_group_state(df_upto, [5, 10, 20])
    tr.long_ma_state = ma_group_state(df_upto, [60, 120, 240])
    tr.market_cap_yi = round(mv_yi, 1)
    tr.cap_bucket = cap_bucket(mv_yi) if mv_yi > 0 else ""
    tr.industry_l1 = l1
    tr.industry_l2 = l2
    w33 = _wave33_state(cache, tr.signal_date)
    tr.wave33_direction = w33["direction"]
    tr.wave33_streak = w33["streak"]
    tr.wave33_label = w33["label"]
```

- [ ] **Step 5: Pass `cache` from `run_scan._one`**

In `run_scan._one` (138-142 行), add `cache=dp.cache`:

```python
        return scan_stock(
            code, b.get("name", ""), rows_desc, cfg,
            ind.get("l1_name", ""), ind.get("l2_name", ""),
            b.get("list_date", ""), mv_series,
            cache=dp.cache,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_wave33_state.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Verify existing scan_engine tests still pass (regression)**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_scan_engine.py tests/winrate/test_smoke.py -v`
Expected: PASS — `cache=None` 默认值，既有测试不传 cache 仍工作（`_wave33_state(None,...)` 返回空）。

- [ ] **Step 8: Commit**

```bash
git add src/marketreview/winrate/scan_engine.py tests/winrate/test_wave33_state.py
git commit -m "feat: scan_engine 回填 wave33 趋势状态（_wave33_state + _tag）"
```

---

### Task 3: `reporter._EXPORT_FIELDS` 加 3 列

**Files:**
- Modify: `src/marketreview/winrate/reporter.py`（`_EXPORT_FIELDS`，约 50-55 行）
- Test: `tests/winrate/test_reporter.py`（既有，追加）

**Interfaces:**
- Consumes: Task 1 的 `TradeResult` 新字段
- Produces: CSV 导出含 `wave33_direction` / `wave33_streak` / `wave33_label`

- [ ] **Step 1: Write the failing test**

Append to `tests/winrate/test_reporter.py` (read the file first to match its existing import style):

```python
def test_export_fields_include_wave33():
    """CSV 导出字段含 wave33 三列。"""
    from marketreview.winrate.reporter import _EXPORT_FIELDS
    assert "wave33_direction" in _EXPORT_FIELDS
    assert "wave33_streak" in _EXPORT_FIELDS
    assert "wave33_label" in _EXPORT_FIELDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_reporter.py::test_export_fields_include_wave33 -v`
Expected: FAIL — 三字段不在 `_EXPORT_FIELDS`。

- [ ] **Step 3: Add the three fields to `_EXPORT_FIELDS`**

In `src/marketreview/winrate/reporter.py`, find `_EXPORT_FIELDS` and add the three fields after `industry_l2`:

```python
_EXPORT_FIELDS = [
    "buy_point", "reason", "code", "name", "signal_date", "entry_date", "entry_price",
    "exit_date", "exit_price", "exit_reason", "mfp_pct", "hold_days", "pnl_pct",
    "success", "short_ma_state", "long_ma_state", "market_cap_yi", "cap_bucket",
    "industry_l1", "industry_l2",
    "wave33_direction", "wave33_streak", "wave33_label",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_reporter.py -v`
Expected: PASS (含新测试 + 既有)

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/winrate/reporter.py tests/winrate/test_reporter.py
git commit -m "feat: reporter CSV 导出加 wave33 direction/streak/label 三列"
```

---

### Task 4: `DataProvider.check_wave33_coverage`

**Files:**
- Modify: `src/marketreview/data/data_provider.py`（追加方法，在 `check_kline_coverage` 之后）
- Test: `tests/winrate/test_data_prep.py`（追加）

**Interfaces:**
- Consumes: `cache.get_daily_dates_in_range`、`cache.has_wave33_date`
- Produces: `DataProvider.check_wave33_coverage(start, end) -> dict`，返回 `{ready, total_dates, missing_dates, error}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/winrate/test_data_prep.py`:

```python
def test_check_wave33_coverage_all_ready(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=3)
    # 两天都有 wave33
    for d in ["20240101", "20240102"]:
        dp.cache.upsert_wave33(d, 10, 5, 50.0, "[]")
        for i in range(3):
            dp.cache.upsert_daily(f"60000{i}.SH", [_row(f"60000{i}.SH", d)])
    res = dp.check_wave33_coverage("20240101", "20240102")
    assert res["ready"] is True
    assert res["missing_dates"] == []


def test_check_wave33_coverage_missing(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=3)
    # 20240101 有 wave33，20240102 有 K线但没 wave33
    dp.cache.upsert_wave33("20240101", 10, 5, 50.0, "[]")
    for d in ["20240101", "20240102"]:
        for i in range(3):
            dp.cache.upsert_daily(f"60000{i}.SH", [_row(f"60000{i}.SH", d)])
    res = dp.check_wave33_coverage("20240101", "20240102")
    assert res["ready"] is False
    assert res["missing_dates"] == ["20240102"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_data_prep.py -v -k wave33_coverage`
Expected: FAIL — `check_wave33_coverage` 不存在。

- [ ] **Step 3: Add `check_wave33_coverage` method**

In `src/marketreview/data/data_provider.py`, add after `check_kline_coverage` (find its end by the closing `}` of its return dict):

```python
    def check_wave33_coverage(self, start: str, end: str) -> dict:
        """检查 [start,end] 每个交易日是否都有 wave33 数据。
        供胜率数据准备门禁用：扫描窗每天都要有 wave33，否则 3浪3 标签会缺。

        返回:
          {ready, total_dates, missing_dates, error}
          - ready = (missing_dates 为空 且 total_dates > 0)
          - missing_dates = 有 K线但无 wave33 的交易日（升序，前50）
          - 分母 = K线覆盖的交易日数（避开非交易日）
        """
        start = start.replace("-", "")
        end = end.replace("-", "")
        trade_dates = self.cache.get_daily_dates_in_range(start, end)
        if not trade_dates:
            log.warning("check_wave33_coverage: [%s,%s] 无 K线交易日", start, end)
            return {"ready": False, "total_dates": 0, "missing_dates": [],
                    "error": f"[{start},{end}] 无 K线交易日，无法判定 wave33 覆盖"}

        missing = [d for d in trade_dates if not self.cache.has_wave33_date(d)]
        log.info("check_wave33_coverage [%s~%s]: total_dates=%d missing=%d",
                 start, end, len(trade_dates), len(missing))
        if missing:
            log.warning("check_wave33_coverage: wave33 缺算(前10)=%s 共%d天",
                        missing[:10], len(missing))
        return {
            "ready": len(missing) == 0,
            "total_dates": len(trade_dates),
            "missing_dates": missing[:50],
            "error": None,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_data_prep.py -v -k wave33_coverage`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/data_provider.py tests/winrate/test_data_prep.py
git commit -m "feat: DataProvider.check_wave33_coverage 门禁校验"
```

---

### Task 5: Service 层集成 scan_wave33 + 合并门禁 + 版本

**Files:**
- Modify: `dashboard/services/dashboard_service.py`
  - `prepare_winrate_data` 加 scan_wave33 阶段
  - `check_winrate_coverage` 合并 kline+wave33
  - `_AI_VERSION` 9.8.0 → 9.9.0

**Interfaces:**
- Consumes: Task 4 的 `check_wave33_coverage`、`scan_wave33(dates, dp, progress_cb)`
- Produces: `check_winrate_coverage` 返回 `{ready, kline, wave33}`（嵌套）

- [ ] **Step 1: Bump version**

Change `_AI_VERSION = "9.8.0"` → `_AI_VERSION = "9.9.0"`.

- [ ] **Step 2: Add scan_wave33 stage to `prepare_winrate_data`**

Replace the existing `prepare_winrate_data`:

```python
    def prepare_winrate_data(self, start: str, end: str, progress_cb=None) -> dict:
        """拉取/校验 [start,end] 全市场 K线+复权因子 + 预算 wave33。
        阶段1: ensure_data_loaded（K线+复权，min_fetch_start=预热缓冲）。
        阶段2: scan_wave33（幂等，已算日期跳过），写 wave33_cache 供扫描时查趋势。"""
        log.info("[AI v%s] prepare_winrate_data(%s~%s)", self._AI_VERSION, start, end)
        # 阶段1: K线 + 复权因子
        res = self._dp.ensure_data_loaded(end, progress_cb=progress_cb,
                                          min_fetch_start=start)
        # 阶段2: wave33 预算（幂等）
        log.info("prepare_winrate_data: 阶段2 预算 wave33 [%s~%s]", start, end)
        from marketreview.tools.wave33 import scan_wave33
        trade_dates = self._dp.cache.get_daily_dates_in_range(start, end)
        if trade_dates:
            scan_wave33(trade_dates, self._dp, progress_cb=progress_cb)
            log.info("prepare_winrate_data: wave33 预算完成 %d 天", len(trade_dates))
        else:
            log.warning("prepare_winrate_data: [%s~%s] 无交易日，跳过 wave33", start, end)
        return res
```

- [ ] **Step 3: Merge kline+wave33 in `check_winrate_coverage`**

Replace the existing `check_winrate_coverage`:

```python
    def check_winrate_coverage(self, start: str, end: str) -> dict:
        """返回数据就绪状态（K线 + wave33 双门禁），供页面用。"""
        kline = self._dp.check_kline_coverage(start, end)
        wave33 = self._dp.check_wave33_coverage(start, end)
        ready = bool(kline.get("ready") and wave33.get("ready"))
        log.info("check_winrate_coverage(%s~%s): kline_ready=%s wave33_ready=%s → ready=%s",
                 start, end, kline.get("ready"), wave33.get("ready"), ready)
        return {"ready": ready, "kline": kline, "wave33": wave33}
```

- [ ] **Step 4: Verify imports + version**

Run: `.venv/Scripts/python -c "import sys; sys.path.insert(0,'dashboard'); from services.dashboard_service import DashboardService; print(DashboardService._AI_VERSION)"`
Expected: `9.9.0`

- [ ] **Step 5: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: prepare_winrate_data 加 wave33 预算阶段 + 合并门禁, 版本 9.9.0"
```

---

### Task 6: 页面状态条细化

**Files:**
- Modify: `dashboard/pages/06_买点胜率.py`（状态条逻辑，读取嵌套 `kline`/`wave33`）

**Interfaces:**
- Consumes: Task 5 的 `check_winrate_coverage` 嵌套返回结构

- [ ] **Step 1: Update status-bar logic to read nested structure**

Find the status-bar block (the `if not _cov_cache: ... elif ...` chain and the `_data_ready` computation). Replace `_data_ready` and the status-bar `if/elif` chain:

```python
# 就绪状态：缓存 + 范围一致性
_cov_range = st.session_state.get("wr_cov_range")
_cov_cache = st.session_state.get("wr_cov_cache")
_range_match = (_cov_range == (prep_start, prep_end))
_kline_ready = bool(_cov_cache and _range_match and _cov_cache.get("kline", {}).get("ready"))
_wave33_ready = bool(_cov_cache and _range_match and _cov_cache.get("wave33", {}).get("ready"))
_data_ready = _kline_ready and _wave33_ready

# 状态条
if not _cov_cache:
    st.info("⏳ 数据未准备：请先点「数据准备」拉取扫描范围内的日 K + 3浪3 数据。")
elif not _range_match:
    st.warning("⚠️ 扫描日期已变更，数据准备结果失效，请重新点「数据准备」。")
elif _cov_cache.get("kline", {}).get("error") or _cov_cache.get("wave33", {}).get("error"):
    errs = [e for e in [_cov_cache.get("kline", {}).get("error"),
                        _cov_cache.get("wave33", {}).get("error")] if e]
    st.error(f"❌ 校验失败：{' / '.join(errs)}，请重试「数据准备」。")
elif _data_ready:
    kline_n = _cov_cache.get("kline", {}).get("total_dates", 0)
    st.success(f"✅ 数据就绪：K线覆盖 {kline_n} 个交易日，3浪3 全覆盖。")
else:
    kline_miss = _cov_cache.get("kline", {}).get("missing_dates", [])
    w33_miss = _cov_cache.get("wave33", {}).get("missing_dates", [])
    msgs = []
    if kline_miss:
        msgs.append(f"K线缺口 {len(kline_miss)} 天"
                    + (f"（{', '.join(kline_miss[:5])}…）" if kline_miss else ""))
    if w33_miss:
        msgs.append(f"3浪3 缺算 {len(w33_miss)} 天"
                    + (f"（{', '.join(w33_miss[:5])}…）" if w33_miss else ""))
    st.warning("⚠️ 数据未就绪：" + "，".join(msgs) + "。请重试「数据准备」补齐。")
```

- [ ] **Step 2: Restart Streamlit**

Run: `.venv/Scripts/python restart_streamlit.py`
Expected: `[OK] No startup errors`

- [ ] **Step 3: Headless render test via AppTest**

Run:
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
import sys; sys.path.insert(0,'dashboard'); sys.path.insert(0,'src')
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('dashboard/pages/06_买点胜率.py', default_timeout=60).run()
print('exception:', bool(at.exception))
print('buttons:', [b.label for b in at.button], 'disabled:', [b.disabled for b in at.button])
print('info:', [m.value for m in at.info])
" 2>&1 | grep -v "ScriptRunContext\|WARNING streamlit"
```
Expected: `exception: False`；buttons 含 `📦 数据准备`（可点）+ `▶ 运行扫描`（disabled=True）；info 显示数据未准备提示。

- [ ] **Step 4: Commit**

```bash
git add dashboard/pages/06_买点胜率.py
git commit -m "feat: 买点胜率状态条细化（K线/wave33 分别显示缺口）"
```

---

## Self-Review

**1. Spec coverage:**
- §3 数据流 → Task 2/5 ✓
- §4 数据准备 scan_wave33 → Task 5 Step 2 ✓
- §5 wave33 门禁 → Task 4 + Task 5 Step 3 + Task 6 ✓
- §6 TradeResult 字段 + _wave33_state + _tag + cache 传递 → Task 1 + Task 2 ✓
- §7 CSV 导出 → Task 3 ✓
- §8 日志 → Task 2 (WARNING) + Task 4 (INFO/WARNING) + Task 5 (INFO) ✓
- §9 测试 → Task 1/2/3/4 ✓
- §10 版本 9.9.0 → Task 5 Step 1 ✓

**2. Placeholder scan:** 无 TBD/TODO；每步含完整代码或命令。✓

**3. Type consistency:**
- `TradeResult.wave33_direction/streak/label` — Task 1 定义，Task 2 `_tag` 赋值，Task 3 导出 ✓
- `_wave33_state(cache, signal_date) -> {direction, streak, label}` — Task 2 定义+测试 ✓
- `check_wave33_coverage(start, end) -> {ready, total_dates, missing_dates, error}` — Task 4 定义，Task 5 调用 ✓
- `check_winrate_coverage -> {ready, kline, wave33}` — Task 5 定义，Task 6 读取 ✓
- `scan_stock(..., cache=None)` / `_tag(..., cache=None)` — Task 2 一致 ✓

**4. 既有测试回归:** Task 2 Step 7 验证 `test_scan_engine` / `test_smoke` 不受 `cache=None` 影响；Task 4 不改 `check_kline_coverage` 返回结构（只加新方法），`test_data_prep` 既有用例不破坏。

No gaps. Plan complete.
