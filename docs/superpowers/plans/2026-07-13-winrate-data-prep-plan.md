# 买点胜率数据准备按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「买点胜率」页新增「数据准备」按钮，按下后按扫描窗拉取全市场日 K + 复权因子，并以覆盖率校验作为「运行扫描」的硬门禁。

**Architecture:** 复用 `ensure_data_loaded` 主路径（加 `min_fetch_start` 参数，头部缺口判断同步收紧），新增 `check_kline_coverage` 用一条 GROUP BY 查每日覆盖率；服务层包两个门面方法；页面加按钮 + 状态条 + 门禁。

**Tech Stack:** Python 3.10, SQLite (sqlite3 stdlib), Streamlit, pytest。

## Global Constraints

- 版本号 `_AI_VERSION`（`dashboard/services/dashboard_service.py`）由 `9.7.0` → `9.8.0`（feature，Y+1）。
- 日期一律 YYYYMMDD，不用带横杠格式做查询。
- 日志：INFO 流程、DEBUG 数据、WARNING 异常（项目 `logging-convention`）。
- 缓存读取按 trade_date 过滤，不用裸 `LIMIT N`（项目 `always-filter-by-date`）。
- 红涨绿跌（本功能不涉及配色，但不得违反）。
- 测试用真 SQLite 临时库（`CacheManager(tmp_path)`），不 mock DB。

**Spec:** [`docs/superpowers/specs/2026-07-13-winrate-data-prep-design.md`](../specs/2026-07-13-winrate-data-prep-design.md)

---

## File Structure

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `src/marketreview/data/cache_manager.py` | 新增 `count_daily_by_date_range`：一条 GROUP BY 查每日行数 | 加方法 |
| `src/marketreview/data/data_provider.py` | `ensure_data_loaded` 加 `min_fetch_start` + 头部收紧；新增 `check_kline_coverage` | 改+加 |
| `dashboard/services/dashboard_service.py` | 新增 `prepare_winrate_data` / `check_winrate_coverage`；bump 版本 | 改 |
| `dashboard/pages/06_买点胜率.py` | 数据准备按钮 + 状态条 + 运行扫描门禁 | 改 |
| `tests/winrate/test_data_prep.py` | cache + provider 新方法测试 | 新建 |

依赖顺序：Task 1（cache）→ Task 2（provider）→ Task 3（service）→ Task 4（page）。Task 1/2 各自带测试；Task 3/4 用冒烟/手动验证（service 是薄门面，page 是 Streamlit UI）。

---

### Task 1: `cache_manager.count_daily_by_date_range`

**Files:**
- Modify: `src/marketreview/data/cache_manager.py`（在 `get_daily_dates_in_range` 之后，约 200 行后插入）
- Test: `tests/winrate/test_data_prep.py`

**Interfaces:**
- Consumes: 无（直接查 `tushare_cache` 表）
- Produces: `CacheManager.count_daily_by_date_range(start: str, end: str) -> dict[str, int]`，返回 `{date_str: count}`，count 为该日 `DISTINCT code` 数（与现有 `count_daily_date` 口径一致）。无数据日期不出现在 dict 里。

- [ ] **Step 1: Write the failing test**

Create `tests/winrate/test_data_prep.py`:

```python
"""数据准备相关测试：cache 覆盖率查询 + provider check_kline_coverage。"""
import pytest

from marketreview.data.cache_manager import CacheManager


def _row(code, date):
    return {"date": date, "open": 10, "high": 10, "low": 10, "close": 10,
            "vol": 1.0, "amount": 1.0, "adj_factor": 1.0, "asset_type": "stock"}


def test_count_daily_by_date_range(tmp_path):
    cm = CacheManager(str(tmp_path / "t.db"))
    # 两个日期，各塞不同数量的票
    cm.insert_batch("600000.SH", [_row("600000.SH", "20240101"),
                                  _row("600000.SH", "20240102")], asset_type="stock")
    cm.insert_batch("600001.SH", [_row("600001.SH", "20240101")], asset_type="stock")
    cm.insert_batch("600002.SH", [_row("600002.SH", "20240101")], asset_type="stock")

    out = cm.count_daily_by_date_range("20240101", "20240102")
    assert out["20240101"] == 3      # 三只票
    assert out["20240102"] == 1      # 一只票
    assert "20240103" not in out     # 无数据日期不出现


def test_count_daily_by_date_range_empty(tmp_path):
    cm = CacheManager(str(tmp_path / "t.db"))
    out = cm.count_daily_by_date_range("20240101", "20240131")
    assert out == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_data_prep.py -v`
Expected: FAIL with `AttributeError: 'CacheManager' object has no attribute 'count_daily_by_date_range'`

- [ ] **Step 3: Write minimal implementation**

In `src/marketreview/data/cache_manager.py`, insert after `get_daily_dates_in_range` (after line ~200):

```python
    def count_daily_by_date_range(self, start: str, end: str) -> dict[str, int]:
        """一条 GROUP BY 查 [start,end] 每个交易日的 distinct code 数。
        返回 {date: count}；无数据的日期不出现在 dict 里。
        与 count_daily_date 同口径（DISTINCT code），避免 N 次单日查询。
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT date, COUNT(DISTINCT code) AS cnt FROM tushare_cache "
                "WHERE date >= ? AND date <= ? GROUP BY date",
                [start, end],
            ).fetchall()
        return {r["date"]: r["cnt"] for r in rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_data_prep.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/cache_manager.py tests/winrate/test_data_prep.py
git commit -m "feat: cache_manager.count_daily_by_date_range 一条 GROUP BY 查每日覆盖率"
```

---

### Task 2: `data_provider.ensure_data_loaded(min_fetch_start=)` + `check_kline_coverage`

**Files:**
- Modify: `src/marketreview/data/data_provider.py`
  - `ensure_data_loaded`（74-95 行签名 + 116-123 行头部缺口判断）
  - 文件末尾追加 `check_kline_coverage`
- Test: `tests/winrate/test_data_prep.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `CacheManager.count_daily_by_date_range`、`CacheManager.get_stock_basic_count`
- Produces:
  - `DataProvider.ensure_data_loaded(end_date, progress_cb=None, extra_industry_codes=None, min_fetch_start=None) -> dict`（新增可选参数）
  - `DataProvider.check_kline_coverage(start, end, threshold=0.9) -> dict`，返回 `{ready: bool, total_dates: int, covered_dates: int, missing_dates: list[str], min_ratio: float, error: str | None}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/winrate/test_data_prep.py`:

```python
from marketreview.data.data_provider import DataProvider


def _make_dp_with_basic(tmp_path, n_basic=10):
    """构造一个不触网的 DataProvider：直接往 stock_basic_cache 塞 N 只票。
    DataProvider 初始化会建 tushare client，但 check_kline_coverage 不调它。"""
    dp = DataProvider.__new__(DataProvider)   # 绕过 __init__（避免连 tushare）
    dp.cache = CacheManager(str(tmp_path / "t.db"))
    rows = [{"ts_code": f"60000{i}.SH", "name": f"票{i}", "list_date": "20200101",
             "is_st": 0} for i in range(n_basic)]
    dp.cache.upsert_stock_basic(rows)
    return dp


def test_check_kline_coverage_all_ready(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=10)
    # 20240101 这天 10 只票全有 → 覆盖率 100%
    for i in range(10):
        dp.cache.insert_batch(f"60000{i}.SH", [_row(f"60000{i}.SH", "20240101")],
                              asset_type="stock")
    res = dp.check_kline_coverage("20240101", "20240101")
    assert res["ready"] is True
    assert res["total_dates"] == 1
    assert res["covered_dates"] == 1
    assert res["missing_dates"] == []
    assert res["min_ratio"] >= 0.9


def test_check_kline_coverage_missing_date(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=10)
    # 20240101 全有，20240102 完全没数据
    for i in range(10):
        dp.cache.insert_batch(f"60000{i}.SH", [_row(f"60000{i}.SH", "20240101")],
                              asset_type="stock")
    res = dp.check_kline_coverage("20240101", "20240102")
    assert res["ready"] is False
    assert res["total_dates"] == 1            # 只有 20240101 有数据
    assert res["missing_dates"] == []         # 20240102 不在 count dict 里 → 不算"缺口日期"，而是 total_dates 少
    # 注：无数据的日期不出现在 count dict，故 total_dates 只数有数据日；
    # 这是期望行为——"缺口"指有数据但覆盖不足，完全没数据的日期由 total_dates < 期望天数体现。


def test_check_kline_coverage_partial_date(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=10)
    # 20240101 只塞 3 只（30% < 90%）→ 缺口
    for i in range(3):
        dp.cache.insert_batch(f"60000{i}.SH", [_row(f"60000{i}.SH", "20240101")],
                              asset_type="stock")
    res = dp.check_kline_coverage("20240101", "20240101")
    assert res["ready"] is False
    assert res["missing_dates"] == ["20240101"]
    assert res["min_ratio"] < 0.9


def test_check_kline_coverage_no_basic(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=0)   # stock_basic 空
    res = dp.check_kline_coverage("20240101", "20240101")
    assert res["ready"] is False
    assert res["error"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_data_prep.py -v`
Expected: FAIL — `check_kline_coverage` 不存在；`ensure_data_loaded` 无 `min_fetch_start` 参数。

- [ ] **Step 3: Modify `ensure_data_loaded` signature + fetch_start lowering**

In `src/marketreview/data/data_provider.py`, change the signature (74-77 行):

```python
    def ensure_data_loaded(
        self, end_date: str, progress_cb=None,
        extra_industry_codes: list[str] | None = None,
        min_fetch_start: str | None = None,
    ) -> dict:
```

And right after `fetch_start` is computed (90-91 行), insert the lowering:

```python
        fetch_start_dt = end_dt - timedelta(days=_FETCH_DAYS)
        fetch_start = fetch_start_dt.strftime("%Y%m%d")
        # 🆕 胜率数据准备：允许把 fetch_start 压到更早的下限（预热缓冲）
        if min_fetch_start:
            floor = min_fetch_start.replace("-", "")
            if floor < fetch_start:
                log.info("ensure_data_loaded: fetch_start lowered %s -> %s (min_fetch_start)",
                         fetch_start, floor)
                fetch_start = floor
```

- [ ] **Step 4: Tighten head-gap check to honor min_fetch_start**

Replace the head-gap block (116-123 行):

```python
        if proxy_earliest and proxy_latest:
            proxy_earliest_clean = proxy_earliest.replace("-", "")
            # Gap at head? Use check_start (360d) not fetch_start (500d)
            # so we don't re-fetch just because we're a few days short of 500.
            if proxy_earliest_clean > check_start:
                missing_ranges.append(
                    (fetch_start, _yesterday(proxy_earliest_clean))
                )
```

with:

```python
        if proxy_earliest and proxy_latest:
            proxy_earliest_clean = proxy_earliest.replace("-", "")
            # Gap at head? Use check_start (500d) not fetch_start (1000d)
            # so we don't re-fetch just because we're a few days short of 500.
            # 🆕 传了 min_fetch_start 时，门槛放宽到该下限，确保前置段缺口也被识别
            effective_floor = (min(min_fetch_start.replace("-", ""), check_start)
                               if min_fetch_start else check_start)
            if proxy_earliest_clean > effective_floor:
                missing_ranges.append(
                    (fetch_start, _yesterday(proxy_earliest_clean))
                )
```

- [ ] **Step 5: Add `check_kline_coverage` method**

Append to the `DataProvider` class (before the final blank line / after the last method). Find the end of the class by locating the last `def` at class indent; insert:

```python
    def check_kline_coverage(self, start: str, end: str,
                             threshold: float = 0.9) -> dict:
        """检查 [start,end] 每个交易日的 K线覆盖率，供胜率数据准备门禁用。

        分母 = stock_basic 总数（与 _validate_coverage 口径一致）。
        一条 GROUP BY 查回每日 count，避免 N 次单日查询。

        返回:
          {ready, total_dates, covered_dates, missing_dates, min_ratio, error}
          - ready = (missing_dates 为空 且 total_dates > 0)
          - missing_dates = ratio < threshold 的日期（升序，最多前 50 个）
          - 无数据的日期不出现在 count dict，故不计入 total_dates
            （完全没拉到的日期由 total_dates 偏少体现，调用方按范围判断）
          - stock_basic 为空 → ready=False, error 非空
        """
        start = start.replace("-", "")
        end = end.replace("-", "")
        total_stocks = self.cache.get_stock_basic_count()
        if total_stocks == 0:
            log.warning("check_kline_coverage: stock_basic 为空，无法判定覆盖率")
            return {"ready": False, "total_dates": 0, "covered_dates": 0,
                    "missing_dates": [], "min_ratio": 0.0,
                    "error": "stock_basic 为空，请先在控制台拉取基础数据"}

        counts = self.cache.count_daily_by_date_range(start, end)
        if not counts:
            log.warning("check_kline_coverage: [%s,%s] 无任何缓存数据", start, end)
            return {"ready": False, "total_dates": 0, "covered_dates": 0,
                    "missing_dates": [], "min_ratio": 0.0,
                    "error": f"[{start},{end}] 无任何缓存数据"}

        missing: list[str] = []
        min_ratio = 1.0
        for d in sorted(counts.keys()):
            ratio = counts[d] / total_stocks
            if ratio < min_ratio:
                min_ratio = ratio
            if ratio < threshold:
                missing.append(d)
        covered = len(counts) - len(missing)
        log.info("check_kline_coverage [%s~%s]: total_dates=%d covered=%d "
                 "missing=%d min_ratio=%.3f threshold=%.2f",
                 start, end, len(counts), covered, len(missing),
                 min_ratio, threshold)
        if missing:
            log.warning("check_kline_coverage: 缺口日期(前10)=%s 共%d天",
                        missing[:10], len(missing))
        return {
            "ready": len(missing) == 0,
            "total_dates": len(counts),
            "covered_dates": covered,
            "missing_dates": missing[:50],
            "min_ratio": round(min_ratio, 3),
            "error": None,
        }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_data_prep.py -v`
Expected: PASS (6 tests: 2 from Task 1 + 4 new)

- [ ] **Step 7: Verify existing data tests still pass (regression)**

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: PASS — no regressions from the `ensure_data_loaded` signature change (new param is optional, defaults to None = old behavior).

- [ ] **Step 8: Commit**

```bash
git add src/marketreview/data/data_provider.py tests/winrate/test_data_prep.py
git commit -m "feat: ensure_data_loaded 加 min_fetch_start + check_kline_coverage 覆盖率门禁"
```

---

### Task 3: Service layer — `prepare_winrate_data` / `check_winrate_coverage` + version bump

**Files:**
- Modify: `dashboard/services/dashboard_service.py`（`_AI_VERSION` 在 1857 行；`run_winrate_scan` 在 1859 行附近，在其后加两个方法）

**Interfaces:**
- Consumes: Task 2 的 `DataProvider.ensure_data_loaded(min_fetch_start=...)` / `check_kline_coverage`
- Produces:
  - `DashboardService.prepare_winrate_data(start, end, progress_cb=None) -> dict`
  - `DashboardService.check_winrate_coverage(start, end) -> dict`

- [ ] **Step 1: Bump version**

In `dashboard/services/dashboard_service.py` line 1857, change:

```python
    _AI_VERSION = "9.7.0"
```

to:

```python
    _AI_VERSION = "9.8.0"
```

- [ ] **Step 2: Add the two methods**

Insert immediately after `run_winrate_scan` (after line ~1865, before `generate_ai_summary`):

```python
    def prepare_winrate_data(self, start: str, end: str, progress_cb=None) -> dict:
        """拉取/校验 [start,end] 全市场 K线+复权因子，复用 ensure_data_loaded 主路径。

        start 通常 = winrate start_date − 600 日历日（预热缓冲，盖 band300+MA240+3浪3）。
        返回 ensure_data_loaded 的结果 dict。
        """
        log.info("[AI v%s] prepare_winrate_data(%s~%s)", self._AI_VERSION, start, end)
        return self._dp.ensure_data_loaded(end, progress_cb=progress_cb,
                                           min_fetch_start=start)

    def check_winrate_coverage(self, start: str, end: str) -> dict:
        """返回数据就绪状态，供页面门禁用。见 DataProvider.check_kline_coverage。"""
        res = self._dp.check_kline_coverage(start, end)
        log.info("check_winrate_coverage(%s~%s): ready=%s, missing=%d",
                 start, end, res.get("ready"), len(res.get("missing_dates", [])))
        return res
```

- [ ] **Step 3: Verify the service imports cleanly + version bumped**

Run: `.venv/Scripts/python -c "from services.dashboard_service import DashboardService; print(DashboardService._AI_VERSION); print(hasattr(DashboardService, 'prepare_winrate_data'), hasattr(DashboardService, 'check_winrate_coverage'))"`
Expected output:
```
9.8.0
True True
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: DashboardService 加 prepare_winrate_data/check_winrate_coverage, 版本 9.8.0"
```

---

### Task 4: Page — 数据准备按钮 + 状态条 + 运行扫描门禁

**Files:**
- Modify: `dashboard/pages/06_买点胜率.py`（按钮区在 73 行；配置 `cfg` 在 65-71 行）

**Interfaces:**
- Consumes: Task 3 的 `DashboardService.prepare_winrate_data` / `check_winrate_coverage`；`winrate_config` 的 `start_date`/`end_date`
- Produces: 页面行为（无新公共接口）

- [ ] **Step 1: Add date helpers + state computation, insert before the button block**

In `dashboard/pages/06_买点胜率.py`, replace the button block (lines 73-87, from `if st.button("▶ 运行扫描"...` through the `st.session_state.wr_saved_dir = saved_dir` line) with:

```python
# ── 数据准备（拉取/校验扫描范围内的日 K，作为运行扫描的前置门禁）──
from datetime import datetime, timedelta

_PREP_LOOKBACK_CAL = 600   # 预热缓冲日历日（盖 band300+MA240+3浪3，留余量）


def _prep_range(start_date: str, end_date: str) -> tuple[str, str]:
    """数据准备范围 = [start_date - 600日历日, end_date]。end_date='now' 用最新缓存日。"""
    sd = datetime.strptime(start_date.replace("-", ""), "%Y%m%d")
    prep_start = (sd - timedelta(days=_PREP_LOOKBACK_CAL)).strftime("%Y%m%d")
    prep_end = "" if end_date in ("", "now") else end_date.replace("-", "")
    if not prep_end:
        # now → 用代理股票最新缓存日（与主路径一致）
        prep_end = svc._dp.cache.get_latest_date("000001.SZ") or start_date
        prep_end = prep_end.replace("-", "")
    return prep_start, prep_end


prep_start, prep_end = _prep_range(start_date, end_date)
st.caption(f"📦 数据准备范围：`{prep_start}` ~ `{prep_end}` "
           f"（扫描窗前推 {_PREP_LOOKBACK_CAL} 日历日预热）")

# 就绪状态：缓存 + 范围一致性
_cov_range = st.session_state.get("wr_cov_range")
_cov_cache = st.session_state.get("wr_cov_cache")
_range_match = (_cov_range == (prep_start, prep_end))
_data_ready = bool(_cov_cache and _range_match and _cov_cache.get("ready")
                   and not _cov_cache.get("missing_dates"))

# 状态条
if not _cov_cache:
    st.info("⏳ 数据未准备：请先点「数据准备」拉取扫描范围内的日 K 数据。")
elif not _range_match:
    st.warning("⚠️ 扫描日期已变更，数据准备结果失效，请重新点「数据准备」。")
elif _cov_cache.get("error"):
    st.error(f"❌ 校验失败：{_cov_cache['error']}，请重试「数据准备」。")
elif _data_ready:
    st.success(f"✅ 数据就绪：覆盖 {_cov_cache['total_dates']} 个交易日，"
               f"最低覆盖率 {_cov_cache['min_ratio']:.0%}。")
else:
    miss = _cov_cache.get("missing_dates", [])
    st.warning(f"⚠️ 数据未就绪：缺口 {len(miss)} 天"
               + (f"（{', '.join(miss[:5])}…）" if miss else "")
               + "，请重试「数据准备」补齐。")

col_prep, _ = st.columns([1, 3])
with col_prep:
    if st.button("📦 数据准备", help="按上方范围拉取/校验全市场日 K + 复权因子"):
        prog = st.progress(0.0)
        status = st.empty()
        status.text("数据准备中（首次全市场可能十几分钟）…")

        def _prep_cb(*args):
            # ensure_data_loaded 的 progress_cb 签名可能是 (phase, cur, total) 或 (cur, total)
            # 兼容两种：取最后两个数字
            if len(args) >= 2 and isinstance(args[-2], (int, float)) and isinstance(args[-1], (int, float)):
                cur, total = args[-2], args[-1]
                if total:
                    prog.progress(min(cur / total, 1.0))
                    status.text(f"数据准备中… {cur}/{total}")
            elif args:
                status.text(f"数据准备中… {args[0]}")

        try:
            svc.prepare_winrate_data(prep_start, prep_end, progress_cb=_prep_cb)
        except Exception as e:
            st.error(f"数据准备出错：{e}")
        else:
            st.session_state.wr_cov_cache = svc.check_winrate_coverage(prep_start, prep_end)
            st.session_state.wr_cov_range = (prep_start, prep_end)
        prog.progress(1.0)
        status.empty()
        st.rerun()

# ── 运行扫描（数据未就绪时禁用）──
if st.button("▶ 运行扫描", type="primary",
             disabled=not (buy_points and _data_ready),
             help="数据就绪后可用" if _data_ready else "请先完成「数据准备」"):
    prog = st.progress(0.0)
    status = st.empty()

    def cb(done, total):
        prog.progress(done / total)
        status.text(f"已扫描 {done}/{total} 只股票")

    with st.spinner("全市场扫描中..."):
        stats, trades = svc.run_winrate_scan(cfg, progress_cb=cb)
    saved_dir = save_run(trades, cfg)
    prog.progress(1.0)
    status.empty()
    st.session_state.wr_stats = stats
    st.session_state.wr_saved_dir = saved_dir
```

- [ ] **Step 2: Restart Streamlit to clear cached modules**

Run: `.venv/Scripts/python restart_streamlit.py`
Expected: `[OK] No startup errors` + `Uvicorn server started on 0.0.0.0:8501`

- [ ] **Step 3: Manual smoke test of the page**

Open http://localhost:8501 → 买点胜率 page. Verify:
1. 「数据准备范围」caption 显示（如 `20220920 ~ 20260713`）。
2. 状态条显示 `⏳ 数据未准备`。
3. 「▶ 运行扫描」按钮**灰色禁用**（hover 提示「请先完成数据准备」）。
4. 点「数据准备」→ 进度条出现、文案更新；完成后状态条变 `✅ 数据就绪`（若已有数据）或 `⚠️ 缺口 N 天`（新机首次）。
5. 数据就绪后「▶ 运行扫描」变为可点。
6. 改「开始日期」→ 状态条变 `⚠️ 扫描日期已变更…`，运行扫描重新禁用。

- [ ] **Step 4: Commit**

```bash
git add dashboard/pages/06_买点胜率.py
git commit -m "feat: 买点胜率页加数据准备按钮 + 覆盖率门禁"
```

---

## Self-Review

**1. Spec coverage:**
- §2 滑动窗口/预热 600 日历日 → Task 4 `_PREP_LOOKBACK_CAL = 600` ✅
- §3 复用 ensure_data_loaded 主路径 → Task 2/3 ✅
- §4.1 min_fetch_start + 头部缺口收紧 → Task 2 Step 3/4 ✅
- §4.2 check_kline_coverage → Task 2 Step 5 ✅
- §4.3 count_daily_by_date_range → Task 1 ✅
- §4.4 日志埋点 → Task 2 Step 5 (INFO/WARNING/DEBUG) + Task 3 (INFO) ✅
- §5 服务层两方法 + 版本 → Task 3 ✅
- §6 页面按钮/状态条/门禁/缓存 → Task 4 ✅
- §7 错误处理（chunk 失败沿用主路径、查询异常、stock_basic 空、范围失效）→ Task 2 Step 5 + Task 4 ✅
- §8 测试 → Task 1/2 ✅
- §9 版本 9.8.0 → Task 3 Step 1 ✅

**2. Placeholder scan:** 无 TBD/TODO；每步含完整代码或确切命令。✅

**3. Type consistency:**
- `count_daily_by_date_range(start, end) -> dict[str, int]` — Task 1 定义，Task 2 Step 5 调用 ✅
- `check_kline_coverage(start, end, threshold=0.9) -> dict` 返回键 `ready/total_dates/covered_dates/missing_dates/min_ratio/error` — Task 2 定义，Task 3/4 使用一致 ✅
- `ensure_data_loaded(..., min_fetch_start=None)` — Task 2 定义，Task 3 调用 ✅
- `prepare_winrate_data(start, end, progress_cb=None)` / `check_winrate_coverage(start, end)` — Task 3 定义，Task 4 调用 ✅
- `wr_cov_cache` / `wr_cov_range` session_state 键 — Task 4 内部一致 ✅

**4. progress_cb 兼容性注记:** Task 4 的 `_prep_cb` 用 `args[-2], args[-1]` 兼容 `ensure_data_loaded` 可能的 `(phase, cur, total)` 与 `(cur, total)` 两种签名。若实际签名不同，实现时按真实签名调整——此点已在代码注释标明。

No gaps found. Plan is complete.
