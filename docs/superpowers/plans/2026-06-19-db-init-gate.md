# DB Initialization Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the draft `check_db_status()` with a proper three-state UI gate (uninitialized → initializing → ready) and a 4-phase smart-gap-filling initialization flow.

**Architecture:** A new `init_status` key-value table records whether full initialization has completed. On page load, `check_db_ready()` runs 4 quick SQL queries (<1s) to determine state. When the user clicks "Start Initialization", `run_initialization()` drives a 4-phase pipeline (K-line → market cap → industry index → wave33) with smart gap detection — only fetching missing data, except industry which must be wiped and recomputed from scratch due to chain compounding. Progress is streamed to the UI via `st.status` (same pattern as existing data-loading flows).

**Tech Stack:** Python, Streamlit, SQLite WAL, ThreadPoolExecutor (already in use), Tushare API

## Global Constraints

- Fixed start date: **2021-01-01** (not relative)
- Date picker minimum: **2023-01-01**
- Freshness threshold: **15 days** (MAX(date) ≥ today − 15 days)
- Log prefix: `[INIT]` for all initialization log lines
- Industry check: `COUNT(*) > 0` (not hardcoded 60)
- Industry must be `DELETE FROM` + recompute if MIN > 2021-01-01
- 6 workers for ThreadPoolExecutor (already in data_provider)
- No confirmation dialogs — init runs immediately on button click
- Existing daily-use flow (`ensure_data_loaded` + date picker) untouched
- Draft `check_db_status()` is fully replaced (not extended)

---

### Task 1: `init_status` table + CacheManager methods

**Files:**
- Modify: `src/marketreview/data/schema.sql` (append table)
- Modify: `src/marketreview/data/cache_manager.py` (add `_EXPECTED_COLUMNS` entry + 2 methods)

**Interfaces:**
- Produces: `CacheManager.get_init_status() -> dict[str, str]`
- Produces: `CacheManager.set_init_status(key: str, value: str) -> None`
- Consumed by: Task 3 (`DashboardService.check_db_ready()`, `run_initialization()`)

- [ ] **Step 1: Add `init_status` to schema.sql**

Append after the last `CREATE INDEX` statement (line 117):

```sql
CREATE TABLE IF NOT EXISTS init_status (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

- [ ] **Step 2: Add `init_status` to `_EXPECTED_COLUMNS` in cache_manager.py**

In `CacheManager._EXPECTED_COLUMNS` dict (after `industry_daily` entry around line 66), add:

```python
"init_status": {
    "key", "value",
},
```

- [ ] **Step 3: Add `get_init_status()` and `set_init_status()` methods to CacheManager**

Insert after the last method (before the end of the class, around line 726):

```python
# ------- init_status -------

def get_init_status(self) -> dict:
    """Return all init_status rows as {key: value}. Empty dict if uninitialized."""
    with self._get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM init_status").fetchall()
    return {r["key"]: r["value"] for r in rows}

def set_init_status(self, key: str, value: str):
    """Set one init_status key-value pair (INSERT OR REPLACE)."""
    with self._get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO init_status (key, value) VALUES (?, ?)",
            [key, value],
        )
        conn.commit()
```

- [ ] **Step 4: Verify schema init is idempotent**

Run:
```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.data.cache_manager import CacheManager; c = CacheManager(); print(c.get_init_status())"
```
Expected: `{}` (empty dict, no error)

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/schema.sql src/marketreview/data/cache_manager.py
git commit -m "feat: add init_status table + CacheManager get/set methods"
```

---

### Task 2: `DataProvider.ensure_full_init()` — 4-phase initialization

**Files:**
- Modify: `src/marketreview/data/data_provider.py` (add constants + method)

**Interfaces:**
- Consumes: `CacheManager.get_init_status()`, `set_init_status()` (Task 1)
- Consumes: existing `_fetch_chunk()`, `_ensure_indices_loaded()`, `_ensure_daily_basic_loaded()`, `_backfill_industry_range()`, `_fetch_stock_basic_once()`
- Produces: `DataProvider.ensure_full_init(progress_cb=None, log_cb=None) -> dict`
- Consumed by: Task 3 (`DashboardService.run_initialization()`)

**Callback signatures:**
- `progress_cb(phase: str, label: str)` — phase ∈ {"phase_start", "phase_progress", "phase_done"}
- `log_cb(message: str)` — called for each `[INIT]` log line

- [ ] **Step 1: Add constants**

Insert after `_PROXY_CODE = "000001.SZ"` (line 49):

```python
# ── DB initialization constants ──
_INIT_START = "20210101"        # fixed start date for full init
_INIT_FRESHNESS_DAYS = 15       # MAX(date) within 15d of today → fresh
```

- [ ] **Step 2: Add `ensure_full_init()` method to DataProvider**

Insert after `check_cache_coverage()` (after line 253, before `_COVERAGE_WARN_THRESHOLD`):

```python
def ensure_full_init(self, progress_cb=None, log_cb=None) -> dict:
    """
    4-phase DB initialization from 2021-01-01 to today.

    Smart gap-filling: only fetches missing date ranges, except
    industry_daily which is wiped and recomputed due to chain compounding.

    progress_cb(phase: str, label: str):
      phase = "phase_start" | "phase_progress" | "phase_done"
    log_cb(message: str):
      called for each [INIT] log line

    Returns {"status": "ok"|"error", "elapsed": float, "phases": dict}
    """
    import time as _time

    t0 = _time.time()
    today = datetime.now().strftime("%Y%m%d")
    today_dt = datetime.strptime(today, "%Y%m%d")
    freshness_cutoff = (today_dt - timedelta(days=_INIT_FRESHNESS_DAYS)).strftime("%Y%m%d")

    phases_result = {}

    def _log(msg: str):
        log.info(msg)
        if log_cb:
            log_cb(msg)

    # ═══════════════════════════════════════════════════════════
    # Phase 1: K-line (tushare_cache stock + indices)
    # ═══════════════════════════════════════════════════════════
    _log("[INIT] Phase 1/4 K线: 检测中...")
    if progress_cb:
        progress_cb("phase_start", "K线 — 检测缓存覆盖...")

    _t1 = _time.time()
    with self.cache._get_conn() as conn:
        kl_min_max = conn.execute(
            "SELECT MIN(date), MAX(date) FROM tushare_cache "
            "WHERE asset_type='stock'"
        ).fetchone()

    kl_min = kl_min_max[0] or ""
    kl_max = kl_min_max[1] or ""
    kline_ok = (
        kl_min and kl_min <= _INIT_START
        and kl_max and kl_max >= freshness_cutoff
    )

    kline_chunks = 0
    if kline_ok:
        _log(f"[INIT] K线: 已完整 ({kl_min}~{kl_max}), 跳过")
    else:
        _log(f"[INIT] K线: MIN={kl_min or '无'} MAX={kl_max or '无'}, 需要补拉")

        # Determine missing ranges
        missing_ranges: list[tuple[str, str]] = []
        if not kl_max or kl_max < today:
            gap_start = _next_day(kl_max) if kl_max else _INIT_START
            missing_ranges.append((gap_start, today))
        if kl_min and kl_min > _INIT_START:
            missing_ranges.append((_INIT_START, _yesterday(kl_min)))

        # Flatten chunks for progress tracking
        all_chunks = []
        for ms, me in missing_ranges:
            all_chunks.extend(_date_chunks(ms, me, _CHUNK_DAYS))
        total_chunks = len(all_chunks)

        for ci, (cs, ce) in enumerate(all_chunks, 1):
            _log(f"[INIT] K线: 开始补拉 {cs}~{ce} (chunk {ci}/{total_chunks})...")
            if progress_cb:
                progress_cb(
                    "phase_progress",
                    f"K线 — {cs[:4]}-{cs[4:6]}-{cs[6:8]}~{ce[:4]}-{ce[4:6]}-{ce[6:8]} ({ci}/{total_chunks})",
                )
            _tc = _time.time()
            self._fetch_chunk(cs, ce)
            kline_chunks += 1
            _log(f"[INIT] K线: chunk {ci}/{total_chunks} 完成, 耗时 {_time.time() - _tc:.1f}s")

        # Ensure indices are also loaded for the full range
        idx_pages = self._ensure_indices_loaded(_INIT_START, today, None)
        _log(f"[INIT] K线: 指数数据 {idx_pages} 页")
        _log(f"[INIT] K线: 全部完成, {total_chunks} 段, 总耗时 {_time.time() - _t1:.1f}s")

    kline_elapsed = round(_time.time() - _t1, 1)
    phases_result["kline"] = {"ok": kline_ok, "chunks": kline_chunks, "elapsed": kline_elapsed}
    if progress_cb:
        progress_cb("phase_done", f"✅ K线 完成 ({kline_elapsed:.0f}s)")

    # ═══════════════════════════════════════════════════════════
    # Phase 2: Market cap (daily_basic_cache)
    # ═══════════════════════════════════════════════════════════
    _log("[INIT] Phase 2/4 市值: 检测中...")
    if progress_cb:
        progress_cb("phase_start", "市值 — 检测缓存覆盖...")

    _t2 = _time.time()
    with self.cache._get_conn() as conn:
        db_min_max = conn.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM daily_basic_cache"
        ).fetchone()

    db_min = db_min_max[0] or ""
    db_max = db_min_max[1] or ""
    db_ok = (
        db_min and db_min <= _INIT_START
        and db_max and db_max >= freshness_cutoff
    )

    db_pages = 0
    if db_ok:
        _log(f"[INIT] 市值: 已完整 ({db_min}~{db_max}), 跳过")
    else:
        _log(f"[INIT] 市值: MIN={db_min or '无'} MAX={db_max or '无'}, 需要补拉")
        db_pages = self._ensure_daily_basic_loaded(_INIT_START, today, None)
        _log(f"[INIT] 市值: 全部完成, {db_pages} 页, 耗时 {_time.time() - _t2:.1f}s")

    db_elapsed = round(_time.time() - _t2, 1)
    phases_result["market_cap"] = {"ok": db_ok, "pages": db_pages, "elapsed": db_elapsed}
    if progress_cb:
        progress_cb("phase_done", f"✅ 市值 完成 ({db_elapsed:.0f}s)")

    # ═══════════════════════════════════════════════════════════
    # Phase 3: Industry index (industry_daily)
    # ═══════════════════════════════════════════════════════════
    _log("[INIT] Phase 3/4 行业指数: 检测中...")
    if progress_cb:
        progress_cb("phase_start", "行业指数 — 检测缓存覆盖...")

    _t3 = _time.time()
    from marketreview.tools.industry import build_industry_list

    industries = build_industry_list(self._api)
    total_ind = len(industries)

    with self.cache._get_conn() as conn:
        ind_min_max = conn.execute(
            "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM industry_daily"
        ).fetchone()

    ind_min = ind_min_max[0] or ""
    ind_max = ind_min_max[1] or ""
    ind_rows_before = ind_min_max[2] or 0
    ind_ok = (
        ind_rows_before > 0
        and ind_min and ind_min <= _INIT_START
        and ind_max and ind_max >= freshness_cutoff
    )

    ind_computed = 0
    if ind_ok:
        _log(f"[INIT] 行业指数: 已完整 ({ind_min}~{ind_max}, {total_ind} 行业), 跳过")
    else:
        if ind_min and ind_min > _INIT_START:
            _log(f"[INIT] 行业指数: MIN={ind_min} > {_INIT_START}, 清空重算")
            with self.cache._get_conn() as conn:
                conn.execute("DELETE FROM industry_daily")
                conn.commit()
            _log(f"[INIT] 行业指数: 已清空 industry_daily (原 {ind_rows_before} 行)")
        else:
            _log(f"[INIT] 行业指数: MIN={ind_min or '无'} MAX={ind_max or '无'}, 需补算")

        _log(f"[INIT] 行业指数: {total_ind} 行业, 开始回填（6 线程并行）...")

        # Build a progress adapter that forwards industry_daily progress
        def _ind_progress(phase: str, current: int, total: int, extra: str = None):
            if progress_cb and phase == "industry_daily":
                progress_cb(
                    "phase_progress",
                    f"行业指数 — {extra or f'{current}/{total}'}",
                )

        ind_computed = self._backfill_industry_range(
            _INIT_START, today, industries, total_ind,
            progress_cb=_ind_progress,
        )
        _log(f"[INIT] 行业指数: 全部完成, {ind_computed} 行, 耗时 {_time.time() - _t3:.1f}s")

    ind_elapsed = round(_time.time() - _t3, 1)
    phases_result["industry"] = {
        "ok": ind_ok, "rows_before": ind_rows_before,
        "rows_computed": ind_computed, "elapsed": ind_elapsed,
    }
    if progress_cb:
        progress_cb("phase_done", f"✅ 行业指数 完成 ({ind_elapsed:.0f}s)")

    # ═══════════════════════════════════════════════════════════
    # Phase 4: Wave33
    # ═══════════════════════════════════════════════════════════
    _log("[INIT] Phase 4/4 3浪3: 检测中...")
    if progress_cb:
        progress_cb("phase_start", "3浪3 — 扫描缺失日期...")

    _t4 = _time.time()
    from marketreview.tools.wave33 import scan_wave33

    # Get all trading dates from K-line cache (already loaded in Phase 1).
    # ~2000 calendar days since 2021-01-01 (~1350 trading days).
    sh_rows = self.get_daily("000001.SH", end_date=today, lookback_days=2000)
    all_trading_dates = sorted(set(
        r["date"].replace("-", "") for r in sh_rows
        if r["date"].replace("-", "") >= _INIT_START
    ))

    # Find which dates are missing from wave33_cache
    missing_dates = []
    for d in all_trading_dates:
        if not self.cache.has_wave33_date(d):
            missing_dates.append(d)

    w33_scanned = 0
    if not missing_dates:
        _log(f"[INIT] 3浪3: 已完整 ({len(all_trading_dates)} 天), 跳过")
    else:
        _log(f"[INIT] 3浪3: 缺失 {len(missing_dates)} 天, 开始扫描...")
        if progress_cb:
            progress_cb("phase_progress", f"3浪3 — {len(missing_dates)} 天待扫描")

        scan_wave33(missing_dates, self, progress_cb=progress_cb)
        w33_scanned = len(missing_dates)
        _log(f"[INIT] 3浪3: 全部完成, {w33_scanned} 天, 耗时 {_time.time() - _t4:.1f}s")

    w33_elapsed = round(_time.time() - _t4, 1)
    phases_result["wave33"] = {
        "total_dates": len(all_trading_dates),
        "scanned": w33_scanned, "elapsed": w33_elapsed,
    }
    if progress_cb:
        progress_cb("phase_done", f"✅ 3浪3 完成 ({w33_elapsed:.0f}s)")

    # ── Done ──
    total_elapsed = round(_time.time() - t0, 1)
    _log(f"[INIT] ✅ 全部完成! 总耗时 {total_elapsed:.1f}s ({total_elapsed / 60:.1f}min)")

    # Ensure stock_basic is cached (needed by downstream checks)
    self._fetch_stock_basic_once()

    return {
        "status": "ok",
        "elapsed": total_elapsed,
        "phases": phases_result,
    }
```

- [ ] **Step 3: Verify compilation**

Run:
```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.data.data_provider import DataProvider; print('OK')"
```
Expected: `OK` (no syntax errors)

- [ ] **Step 4: Commit**

```bash
git add src/marketreview/data/data_provider.py
git commit -m "feat: add DataProvider.ensure_full_init() 4-phase initialization"
```

---

### Task 3: `DashboardService.check_db_ready()` + `run_initialization()`

**Files:**
- Modify: `dashboard/services/dashboard_service.py` (replace `check_db_status()` + add `run_initialization()`)

**Interfaces:**
- Consumes: `CacheManager` (Task 1), `DataProvider.ensure_full_init()` (Task 2)
- Produces: `DashboardService.check_db_ready() -> dict`
- Produces: `DashboardService.run_initialization(progress_cb=None, log_cb=None) -> dict`
- Consumed by: Task 4 (three-state UI in `00_控制台.py`)

- [ ] **Step 1: Add constants to DashboardService**

Add these class-level constants right after the `__init__` method (around line 27):

```python
# Fixed start date for DB initialization
_INIT_START = "20210101"
# MAX(date) must be within this many days of today
_INIT_FRESHNESS_DAYS = 15
```

- [ ] **Step 2: Replace `check_db_status()` (lines 61-147) with `check_db_ready()`**

Delete the entire `check_db_status()` method and insert:

```python
# ---- DB initialization readiness check ----

def check_db_ready(self) -> dict:
    """
    4 quick read-only SQL queries to determine if the DB is fully initialized.

    Runs in <1s. Called automatically on page load.
    No API calls, no heavy computation.

    Returns:
      {"all_ready": bool, "details": {
          "kline": {"min": str, "max": str, "ok": bool},
          "daily_basic": {"min": str, "max": str, "ok": bool},
          "industry_daily": {"min": str, "max": str, "count": int, "ok": bool},
          "wave33": {"count": int, "max": str, "ok": bool},
      }}
    """
    import sqlite3
    from datetime import datetime, timedelta

    db = self._dp.cache.db_path
    today = datetime.now().strftime("%Y%m%d")
    freshness_cutoff = (
        datetime.now() - timedelta(days=self._INIT_FRESHNESS_DAYS)
    ).strftime("%Y%m%d")

    def _query(sql, params=()):
        with sqlite3.connect(db) as conn:
            return conn.execute(sql, params).fetchone()

    details = {}

    # 1. K-line (tushare_cache, stocks only)
    kl = _query(
        "SELECT MIN(date), MAX(date) "
        "FROM tushare_cache WHERE asset_type='stock'"
    )
    kline_ok = bool(
        kl[0] and kl[0] <= self._INIT_START
        and kl[1] and kl[1] >= freshness_cutoff
    )
    details["kline"] = {
        "min": (kl[0] or "-").replace("-", ""),
        "max": (kl[1] or "-").replace("-", ""),
        "ok": kline_ok,
    }

    # 2. Market cap (daily_basic_cache)
    db_info = _query(
        "SELECT MIN(trade_date), MAX(trade_date) FROM daily_basic_cache"
    )
    db_ok = bool(
        db_info[0] and db_info[0] <= self._INIT_START
        and db_info[1] and db_info[1] >= freshness_cutoff
    )
    details["daily_basic"] = {
        "min": db_info[0] or "-",
        "max": db_info[1] or "-",
        "ok": db_ok,
    }

    # 3. Industry daily
    ind = _query(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) "
        "FROM industry_daily"
    )
    ind_ok = bool(
        ind[2] > 0
        and ind[0] and ind[0] <= self._INIT_START
        and ind[1] and ind[1] >= freshness_cutoff
    )
    details["industry_daily"] = {
        "min": ind[0] or "-",
        "max": ind[1] or "-",
        "count": ind[2] or 0,
        "ok": ind_ok,
    }

    # 4. Wave33
    w33 = _query(
        "SELECT COUNT(*), MAX(trade_date) FROM wave33_cache"
    )
    w33_ok = bool(
        w33[0] > 0
        and w33[1] and w33[1] >= freshness_cutoff
    )
    details["wave33"] = {
        "count": w33[0] or 0,
        "max": w33[1] or "-",
        "ok": w33_ok,
    }

    all_ready = all(d["ok"] for d in details.values())

    return {"all_ready": all_ready, "details": details}
```

- [ ] **Step 3: Add `run_initialization()` method**

Insert after `check_db_ready()`:

```python
def run_initialization(self, progress_cb=None, log_cb=None) -> dict:
    """
    Run the full 4-phase DB initialization.

    Thin wrapper around DataProvider.ensure_full_init().
    On success, writes init_status marker via CacheManager.

    progress_cb(phase: str, label: str):
      phase = "phase_start" | "phase_progress" | "phase_done"
    log_cb(message: str):
      called for each [INIT] log line

    Returns {"status": "ok"|"error", "elapsed": float, "phases": dict}
    """
    from datetime import datetime

    result = self._dp.ensure_full_init(
        progress_cb=progress_cb, log_cb=log_cb,
    )

    if result["status"] == "ok":
        self._dp.cache.set_init_status("initialized", "1")
        self._dp.cache.set_init_status(
            "completed_at", datetime.now().isoformat(),
        )
        if log_cb:
            log_cb("[INIT] init_status 标记已写入")

    return result
```

- [ ] **Step 4: Verify external callers of old `check_db_status()`**

Run:
```bash
cd i:/AIcode/marketreview && grep -rn "check_db_status" dashboard/ src/ --include="*.py"
```
Expected: only the old definition in dashboard_service.py (being deleted). If other files call it, those files will be updated in Task 4.

- [ ] **Step 5: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: replace check_db_status with check_db_ready + run_initialization"
```

---

### Task 4: Three-state UI in `00_控制台.py`

**Files:**
- Modify: `dashboard/pages/00_控制台.py` (replace draft DB status block + gate date picker)

**Interfaces:**
- Consumes: `DashboardService.check_db_ready()` (Task 3)
- Consumes: `DashboardService.run_initialization()` (Task 3)
- Produces: Three-state UI (A: uninitialized → B: initializing → C: ready)

**Design:** Uses the same `with st.status(...) as status:` + `status.update(label=...)` pattern already used in the codebase (lines 179-221, 223-295). The status label combines phase icons with current progress, updating in real-time during the synchronous init call.

- [ ] **Step 1: Delete draft DB status block (lines 77-125)**

Remove lines 77-125: the "DB status check button" section (from `_service = DashboardService()` through the `st.caption("💡 ...")` line). Keep `_service = DashboardService()` itself.

- [ ] **Step 2: Insert three-state UI gate after `_service = DashboardService()`**

The new code goes right after `_service = DashboardService()` (which was previously on line 75, now around line 75):

```python
_service = DashboardService()

# ═══════════════════════════════════════════════════════════════
# DB Initialization Gate (three-state: A → B → C)
# ═══════════════════════════════════════════════════════════════

# Run quick check on every page load (<1s, 4 SQL queries)
_db_ready = _service.check_db_ready()

# Session-state flags for init flow
if "_init_start" not in st.session_state:
    st.session_state["_init_start"] = False
if "_init_logs" not in st.session_state:
    st.session_state["_init_logs"] = []

st.markdown("---")

# ═══════════════════════════════════════════════════════════════
# STATE B: Initialization in progress
# ═══════════════════════════════════════════════════════════════
# This block runs BEFORE state A/C rendering. When the user clicks
# the init button, we set _init_start=True and st.rerun(). On the
# next execution, this block catches the flag, runs the sync init
# (which may take ~15 min), then clears the flag and reruns again.
#
# During the sync init, st.status streams label updates to the
# browser in real-time (same pattern as lines 179-221, 223-295).

if st.session_state["_init_start"]:
    with st.status("🔄 数据库初始化进行中...", expanded=True) as status:
        # Track per-phase status for the combined label
        _ps = {"kline": "⏸", "market_cap": "⏸", "industry": "⏸", "wave33": "⏸"}
        _phase_name = {
            "kline": "K线", "market_cap": "市值",
            "industry": "行业", "wave33": "3浪3",
        }

        def _init_progress(phase: str, label: str):
            if phase == "phase_start":
                # label starts with "K线 — ...", "市值 — ...", etc.
                for pk, name in _phase_name.items():
                    if label.startswith(name):
                        _ps[pk] = "⏳"
                        break
            elif phase == "phase_done":
                for pk, name in _phase_name.items():
                    if label.startswith(f"✅ {name}"):
                        _ps[pk] = "✅"
                        break
            # Build combined status label
            _combined = (
                f"📈{_ps['kline']}  💰{_ps['market_cap']}  "
                f"🏭{_ps['industry']}  🌊{_ps['wave33']}  |  {label}"
            )
            status.update(label=_combined)

        def _init_log(msg: str):
            st.session_state["_init_logs"].append(msg)

        result = _service.run_initialization(
            progress_cb=_init_progress, log_cb=_init_log,
        )

        if result["status"] == "ok":
            status.update(
                label=f"✅ 初始化完成! 总耗时 {result['elapsed']:.0f}s "
                      f"({result['elapsed'] / 60:.1f}min)",
                state="complete",
            )
        else:
            status.update(
                label=f"❌ 初始化失败: {result.get('msg', '未知错误')}",
                state="error",
            )

    # Show log after completion
    if st.session_state["_init_logs"]:
        with st.expander("📋 初始化日志", expanded=False):
            st.code("\n".join(st.session_state["_init_logs"]), language="text")

    if result["status"] == "ok":
        st.session_state["_init_start"] = False
        st.session_state["_init_logs"] = []
        st.cache_data.clear()
        st.rerun()
    else:
        # Allow retry
        st.session_state["_init_start"] = False
        st.stop()

# ═══════════════════════════════════════════════════════════════
# STATE A: Uninitialized
# ═══════════════════════════════════════════════════════════════

elif not _db_ready["all_ready"]:
    st.markdown("### 🔧 数据库初始化")

    # Per-table status lines
    _details = _db_ready["details"]
    for _key, _label in [
        ("kline", "📈 K线数据"),
        ("daily_basic", "💰 市值数据"),
        ("industry_daily", "🏭 行业指数"),
        ("wave33", "🌊 3浪3"),
    ]:
        _d = _details[_key]
        _icon = "✅" if _d["ok"] else "❌"
        if _key == "wave33":
            _info = f"{_d['count']} 天 · 最新 {_d['max']}"
        elif _key == "industry_daily":
            _info = f"{_d['count']} 行 · {_d['min']}~{_d['max']}"
        else:
            _info = f"{_d['min']}~{_d['max']}"
        st.markdown(f"{_icon} **{_label}**: {_info}")

    _missing_count = sum(1 for d in _details.values() if not d["ok"])
    st.warning(
        f"⚠️ {_missing_count}/4 数据表未就绪。"
        f"需要拉取 2021-01-01 ~ 今天 的历史数据。"
    )

    st.caption(
        "预计耗时：K线 ~4min · 市值 ~2min · 行业指数 ~8min · 3浪3 ~1min  "
        "· 总计约 **15 分钟**"
    )

    _init_btn = st.button(
        "🔄 开始初始化", type="primary", use_container_width=True,
    )

    if _init_btn:
        st.session_state["_init_start"] = True
        st.session_state["_init_logs"] = []
        st.rerun()

    # Date picker grayed out (unusable until init completes)
    st.markdown("---")
    st.caption("📅 日期选择器（初始化完成后可用）")
    st.date_input(
        "📅 选择交易日",
        value=datetime.now(),
        disabled=True,
        format="YYYY-MM-DD",
        key="ctrl_date_picker_disabled",
    )

    # Stop — don't show normal date picker or AI card
    st.stop()

# ═══════════════════════════════════════════════════════════════
# STATE C: Ready (normal use)
# ═══════════════════════════════════════════════════════════════

else:
    _d = _db_ready["details"]
    _kl_min = _d["kline"]["min"]
    _kl_max = _d["kline"]["max"]
    _ind_count = _d["industry_daily"]["count"]
    st.markdown(
        f"✅ **数据库已就绪** · "
        f"{_kl_min} ~ {_kl_max} · "
        f"行业指数 {_ind_count} 行"
    )

# ═══════════════════════════════════════════════════════════════
# (end of init gate)
# ═══════════════════════════════════════════════════════════════
```

- [ ] **Step 3: Gate the date picker — set min_value to 2023-01-01**

Find the `st.date_input(...)` in the form (around line 152 after edits) and add `min_value`:

```python
selected_date = st.date_input(
    "📅 选择交易日",
    value=_default_date,
    min_value=datetime(2023, 1, 1),
    max_value=datetime.now(),
    format="YYYY-MM-DD",
    key="ctrl_date_picker",
)
```

- [ ] **Step 4: Verify the page structure is correct**

Read the full file and mentally trace the three code paths:
- Path A: `_db_ready["all_ready"]` is False, `_init_start` is False → shows init button + gray date picker, `st.stop()`
- Path B: `_init_start` is True → runs init in `st.status` block, then reruns
- Path C: `_db_ready["all_ready"]` is True, `_init_start` is False → shows green bar, falls through to normal date picker + AI card

- [ ] **Step 5: Commit**

```bash
git add dashboard/pages/00_控制台.py
git commit -m "feat: three-state DB init gate UI (uninitialized/initializing/ready)"
```

---

### Task 5: Integration verification

**Files:** None (dashboard smoke test)

**Verification through dashboard UI (per user preference: `dashboard-test-workflow`).**

- [ ] **Step 1: Clear the init_status marker (simulate uninitialized state)**

Run:
```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.data.cache_manager import CacheManager; c = CacheManager(); c.set_init_status('initialized', '0')"
```

Then open `http://localhost:8501` → 控制台 page.

Expected: STATE A — shows 4-table status with ❌/✅ icons, big "开始初始化" button, grayed-out date picker.

- [ ] **Step 2: Test the quick check (all_ready determination)**

If the DB already has data (from previous use), verify `check_db_ready()` returns correct results:

```bash
cd i:/AIcode/marketreview && python -c "
from dashboard.services.dashboard_service import DashboardService
s = DashboardService()
r = s.check_db_ready()
print('all_ready:', r['all_ready'])
for k, v in r['details'].items():
    print(f'  {k}: ok={v[\"ok\"]} min={v.get(\"min\",\"?\")} max={v.get(\"max\",\"?\")}')
"
```

- [ ] **Step 3: Test the init button (if DB is not fully initialized)**

Click "🔄 开始初始化" in the dashboard.

Expected: STATE B — `st.status` shows with 4-phase icons (📈💰🏭🌊), label updates in real-time during the sync call, phases transition ⏸→⏳→✅, final status shows total elapsed time, then auto-reruns to STATE C.

- [ ] **Step 4: Test STATE C (normal use)**

After init completes (or if DB was already ready):
- Green status bar: "✅ 数据库已就绪 · 2021-01-04 ~ 2026-06-18 · 行业指数 XXXXX 行"
- Date picker is enabled with min 2023-01-01
- Select a date, click "应用" → normal data loading works

- [ ] **Step 5: Test date picker lower bound**

Try to select a date before 2023-01-01 in the date picker.

Expected: Date picker prevents selection of dates before 2023-01-01 (grayed out in calendar widget).

---

## Self-Review Checklist

Before marking the plan as complete:

1. **Spec coverage:** Each spec section maps to a task:
   - `init_status` table → Task 1
   - `CacheManager.get_init_status()/set_init_status()` → Task 1
   - `DataProvider.ensure_full_init()` → Task 2
   - `DashboardService.check_db_ready()` → Task 3
   - `DashboardService.run_initialization()` → Task 3
   - Three-state UI (A/B/C) → Task 4
   - Date picker min 2023-01-01 → Task 4 Step 3
   - `[INIT]` log convention → Task 2 (log lines)
   - Smart gap-filling → Task 2 (phase logic)
   - Industry DELETE + recompute → Task 2 Phase 3
   - 6-thread reuse → Task 2 (calls existing `_backfill_industry_range`)
   - No confirmation dialog → Task 4 (button directly triggers)
   - Replaces draft `check_db_status()` → Tasks 3, 4

2. **No placeholders:** No TBD, TODO, or "add error handling" without code.

3. **Type consistency:** 
   - `check_db_ready()` returns `{"all_ready": bool, "details": {...}}` — consumed by Task 4
   - `run_initialization()` returns `{"status": "ok"|"error", ...}` — consumed by Task 4
   - `ensure_full_init()` returns same shape — consumed by Task 3
   - Progress callback signature `(phase: str, label: str)` consistent across Tasks 2, 3, 4
   - Log callback signature `(message: str)` consistent across Tasks 2, 3, 4
