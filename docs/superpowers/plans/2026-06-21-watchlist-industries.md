# 自选行业功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ⭐ 自选行业 (watchlist industries) block to the sector analysis page, driven by a local config file.

**Architecture:** Configuration-driven — user edits `config/watchlist_industries.txt` (git‑ignored, `.example` tracked). Console auto‑matches industry names against `industry_classify`, pulls missing daily data, and validates. Sector page renders the watchlist block with shared `render_ohlcv_section()`. Watchlist industries get AI summaries in the same pipeline as the analysis set.

**Tech Stack:** Python, Streamlit, SQLite (existing), Tushare `sw_daily`

## Global Constraints

- Date format: YYYYMMDD everywhere (no dashes in DB queries)
- Red = bullish / Green = bearish (never flip)
- Log levels: INFO for flow, DEBUG for data, WARNING for anomalies
- Bump `_AI_VERSION` Z‑patch for every change round
- Config file path: `config/watchlist_industries.txt` (project‑relative)
- Git: track `.example`, ignore actual config
- Industry matching: exact name match against `industry_classify` table (SW2021, ~511 names, all unique)

---

## File Structure

```
config/
  watchlist_industries.example.txt   ← NEW: example config (tracked)
  watchlist_industries.txt           ← NEW: user config (git‑ignored)

dashboard/
  pages/
    00_控制台.py                     ← MODIFY: add watchlist expander + data load
    02_板块分析.py                   ← MODIFY: add watchlist UI block + dedup

dashboard/services/
  dashboard_service.py              ← MODIFY: add watchlist read/parse methods

src/marketreview/data/
  data_provider.py                  ← MODIFY: extend _ensure_industry_daily()
```

---

### Task 1: Config Scaffolding

**Files:**
- Create: `config/watchlist_industries.example.txt`
- Modify: `.gitignore:10` (append line)

**Interfaces:**
- Produces: Config file `config/watchlist_industries.txt` (user creates from example)

- [ ] **Step 1: Create example config file**

```txt
# 自选行业列表示例
# 使用方法：
#   1. 复制本文件为 watchlist_industries.txt
#   2. 删除不需要的行，添加你想关注的行业名称
#   3. 名称需与申万 SW2021 行业分类完全一致
#   4. 支持 L1/L2/L3 任意层级（如：半导体、光伏设备、白酒）
#
# 提示：可在控制台的「行业分类规则」展开栏查看完整行业列表
# 或查询数据库：
#   SELECT industry_name, level FROM industry_classify ORDER BY level, industry_name;
```

- [ ] **Step 2: Add to .gitignore**

```
config/watchlist_industries.txt
```

- [ ] **Step 3: Commit**

```bash
git add config/watchlist_industries.example.txt .gitignore
git commit -m "chore: add watchlist industries config scaffolding"
```

---

### Task 2: DashboardService — Config Read + Parse

**Files:**
- Modify: `dashboard/services/dashboard_service.py`

**Interfaces:**
- Produces: `DashboardService.get_watchlist_industries() -> list[dict]`

- [ ] **Step 1: Add method to DashboardService**

Add after `get_industry_list()` (around line 246):

```python
def get_watchlist_industries(self) -> list[dict]:
    """
    Read config/watchlist_industries.txt, match names against
    industry_classify, return matched industries.

    Returns list of dicts: {code, name, level, status}.
    status is "matched" for successfully resolved names.
    Unmatched names are logged as warnings and excluded.
    """
    import os as _os

    config_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
        "config", "watchlist_industries.txt",
    )
    result: list[dict] = []
    if not _os.path.exists(config_path):
        log.info("get_watchlist_industries: config file not found at %s", config_path)
        return result

    with open(config_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    names = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        names.append(stripped)

    if not names:
        return result

    # Match against industry_classify
    self._dp._ensure_industry_classify()  # lazy-init if needed
    classify_map = self._dp.cache.get_industry_classify_map()

    # Build name → code lookup
    name_to_info: dict[str, dict] = {}
    for code, info in classify_map.items():
        name_to_info[info.get("industry_name", "")] = {**info, "code": code}

    matched = 0
    for name in names:
        if name in name_to_info:
            info = name_to_info[name]
            result.append({
                "code": info["code"],
                "name": name,
                "level": info.get("level", ""),
            })
            matched += 1
        else:
            log.warning("get_watchlist_industries: name '%s' not found in classification", name)

    log.info("get_watchlist_industries: %d/%d names matched", matched, len(names))
    return result
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: add get_watchlist_industries() to DashboardService"
```

---

### Task 3: DataProvider — Extend Industry Daily Fetch

**Files:**
- Modify: `src/marketreview/data/data_provider.py:1049-1103`

**Interfaces:**
- Consumes: `DashboardService.get_watchlist_industries()` codes
- Produces: `_ensure_industry_daily()` extended to accept optional extra codes

- [ ] **Step 1: Extend `_ensure_industry_daily` to accept extra codes**

Change method signature and Step 2 logic in `_ensure_industry_daily()` (lines 1049-1103):

```python
def _ensure_industry_daily(self, end_date: str, progress_cb=None,
                           extra_codes: list[str] | None = None
                           ) -> tuple[int, int]:
    """
    Ensure industry_daily table has data for all display industries
    AND any extra_codes (e.g., watchlist industries not in display set).

    Returns (classify_rows, daily_industries_fetched).
    """
    # ... existing lazy-init (Step 1) unchanged ...

    # ── Step 2: compute display codes + merge extra ──
    codes = self._get_display_industry_codes()
    if extra_codes:
        # Merge: add extra codes not already in display set
        existing = set(codes)
        for ec in extra_codes:
            if ec not in existing:
                codes = list(codes) + [ec]
                existing.add(ec)

    # ... rest unchanged (check range, find to_fetch, concurrent fetch) ...
```

- [ ] **Step 2: Commit**

```bash
git add src/marketreview/data/data_provider.py
git commit -m "feat: extend _ensure_industry_daily to accept extra_codes"
```

---

### Task 4: Console — Watchlist Data Loading + UI

**Files:**
- Modify: `dashboard/pages/00_控制台.py`

**Interfaces:**
- Consumes: `DashboardService.get_watchlist_industries()`
- Produces: Console expander showing watchlist status + data loading trigger

- [ ] **Step 1: Add watchlist expander in console UI**

Insert after `_service = DashboardService()` (line 75), before the date display section:

```python
# ── 自选行业 ──
with st.expander("⭐ 自选行业", expanded=False):
    st.markdown("**配置文件：** `config/watchlist_industries.txt`")

    _watchlist = _service.get_watchlist_industries()
    if not _watchlist:
        st.caption("暂无自选行业，请在 `config/watchlist_industries.txt` 中配置")
        st.caption("（参考 `config/watchlist_industries.example.txt`）")
    else:
        _wl_rows = ""
        for _i, _w in enumerate(_watchlist):
            _wl_rows += (
                f"<tr>"
                f"<td style='text-align:center;'>{_i + 1}</td>"
                f"<td>{_w['name']}</td>"
                f"<td style='text-align:center;'>{_w['level']}</td>"
                f"<td style='text-align:center;color:#888;font-size:13px;'>{_w['code']}</td>"
                f"<td style='text-align:center;'>✅</td>"
                f"</tr>"
            )
        st.html(f"""
        <table style="width:100%;font-size:15px;border-collapse:collapse;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                <th style="text-align:center;width:30px;">#</th>
                <th style="text-align:left;">行业名称</th>
                <th style="text-align:center;">Level</th>
                <th style="text-align:center;">Code</th>
                <th style="text-align:center;">状态</th>
            </tr></thead>
            <tbody>{_wl_rows}</tbody>
        </table>
        """)
        st.caption("（后续将支持自选个股）")
```

- [ ] **Step 2: Wire watchlist codes through ensure_data_loaded**

In `DashboardService.ensure_data_loaded()` (line 36-47), add watchlist code resolution:

```python
def ensure_data_loaded(self, trade_date: str, progress_cb=None) -> dict:
    """..."""
    # Resolve watchlist industry codes for extra fetch
    extra_codes: list[str] = []
    try:
        wl = self.get_watchlist_industries()
        extra_codes = [w["code"] for w in wl if w.get("code")]
    except Exception as e:
        log.warning("ensure_data_loaded: failed to read watchlist: %s", e)

    return self._dp.ensure_data_loaded(
        trade_date, progress_cb=progress_cb,
        extra_industry_codes=extra_codes,
    )
```

In `DataProvider.ensure_data_loaded()` (line 73-75), update signature and pass through to `_ensure_industry_daily()`:

```python
def ensure_data_loaded(
    self, end_date: str, progress_cb=None,
    extra_industry_codes: list[str] | None = None,
) -> dict:
    # ... existing code unchanged ...

    # Find the _ensure_industry_daily call (around line 136-138 in fast path,
    # around line 209-211 in slow path) and add extra_codes=extra_industry_codes
    ind_class, ind_daily = self._ensure_industry_daily(
        end_date, progress_cb=progress_cb,
        extra_codes=extra_industry_codes,
    )
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/pages/00_控制台.py dashboard/services/dashboard_service.py src/marketreview/data/data_provider.py
git commit -m "feat: add watchlist expander to console, hook into data loading"
```

---

### Task 5: Sector Page — Watchlist UI Block

**Files:**
- Modify: `dashboard/pages/02_板块分析.py:121-167`

**Interfaces:**
- Consumes: `DashboardService.get_watchlist_industries()`, `get_industry_daily()`
- Produces: ⭐ 自选行业 block rendered between TOP5/BOTTOM5 and 行业详细分析

- [ ] **Step 1: Load watchlist data**

After line 56 (`_analysis_set = _service.get_industry_analysis_set(_trade_date)`), add:

```python
# ── 自选行业 ──
_watchlist = _service.get_watchlist_industries()
if _watchlist:
    _watchlist_codes = {w["code"] for w in _watchlist}
    # Enrich with daily data
    _watchlist_enriched = []
    for _w in _watchlist:
        _df = _service.get_industry_daily(_w["code"], end_date=_trade_date, lookback=1)
        if not _df.empty:
            _row = _df.iloc[-1]
            _row_td = str(_row.get("trade_date", ""))
            if _row_td == _trade_date:
                _watchlist_enriched.append({
                    **_w,
                    "pct_change": float(_row.get("pct_change", 0) or 0),
                    "close": float(_row.get("close", 0) or 0),
                    "amount": float(_row.get("amount", 0) or 0),
                })
    # Sort by pct_change desc
    _watchlist_enriched.sort(key=lambda x: x["pct_change"], reverse=True)
else:
    _watchlist_enriched = []
    _watchlist_codes = set()
```

- [ ] **Step 2: Render watchlist block**

Insert between the TOP5/BOTTOM5 divider (line 121) and the 行业详细分析 header (line 127):

```python
# ═══════════════════════════════════════════════════════════
#  3. ⭐ 自选行业
# ═══════════════════════════════════════════════════════════

st.subheader(f"⭐ 自选行业（共 {len(_watchlist_enriched)} 个）")
st.caption("配置文件：config/watchlist_industries.txt")

if not _watchlist_enriched:
    st.info("暂无自选行业，请在 `config/watchlist_industries.txt` 中配置行业名称")
else:
    for _entry in _watchlist_enriched:
        _code = _entry["code"]
        _name = _entry["name"]
        _level = _entry["level"]
        _pct = _entry["pct_change"]

        _pct_color = up_down_color(_pct)
        _level_tag = {"L1": "一级", "L2": "二级", "L3": "三级"}.get(_level, _level)

        _info_line = (
            f"{_name}  ·  "
            f"<span style='color:{_pct_color};font-weight:bold;'>{_pct:+.2f}%</span>"
            f"  <span style='font-size:13px;color:#888;'>[{_level_tag}] ⭐ 自选</span>"
        )
        st.html(f"<div style='margin-bottom:2px;font-size:15px;'>{_info_line}</div>")

        with st.expander(f"{_name} ({_code})", expanded=False):
            # AI guide
            _guide_key = f"sector/{_code}"
            _guide = _sector_ai.get(_guide_key, {}).get("content", "")
            if _guide and _guide != "AI 摘要暂时不可用":
                st.info(f"🤖 {_guide}")

            _df = _service.get_industry_daily(_code, end_date=_trade_date, lookback=360)
            if _df.empty:
                st.warning(f"暂无 {_name}（{_code}）的日线数据")
                continue

            render_ohlcv_section(_df, _code, _name, _service, "industry",
                                 industry_level=_level)

st.divider()
```

- [ ] **Step 3: Apply dedup to analysis set**

After the watchlist block, when rendering 行业详细分析 section (line 127), add watchlist dedup. Change the loop to skip watchlist codes:

Replace the `for _entry in _analysis_set:` loop condition:

```python
for _entry in _analysis_set:
    # Skip industries already shown in watchlist
    if _entry["code"] in _watchlist_codes:
        continue
    # ... rest of existing loop unchanged ...
```

Also update the section header count:

```python
_analysis_count = sum(1 for e in _analysis_set if e["code"] not in _watchlist_codes)
st.subheader(f"🔍 行业详细分析（共 {_analysis_count} 个）")
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/pages/02_板块分析.py
git commit -m "feat: add watchlist block to sector page with dedup"
```

---

### Task 6: AI Generation — Include Watchlist Industries

**Files:**
- Modify: `dashboard/services/dashboard_service.py` — `generate_ai_sector_analysis()`

**Interfaces:**
- Consumes: `get_watchlist_industries()`
- Produces: AI summaries for watchlist industries stored as `sector/{code}` in `ai_summary`

- [ ] **Step 1: Merge watchlist into sector AI generation candidates**

In `generate_ai_sector_analysis()` (around line 1378), after getting `candidates` from `get_industry_analysis_set()`, merge watchlist industries:

```python
# ── 2. Prepare industry tasks ──
candidates = self.get_industry_analysis_set(trade_date)

# Merge watchlist industries (dedup by code)
watchlist = self.get_watchlist_industries()
seen_codes: set[str] = {c["code"] for c in candidates}
if watchlist:
    for w in watchlist:
        if w["code"] not in seen_codes:
            # Build a minimal candidate entry for the watchlist industry
            # We need pct_change and amount for the data JSON
            df_1d = self._dp.get_industry_daily(
                w["code"], end_date=trade_date, lookback=1
            )
            pct = 0.0
            if not df_1d.empty:
                row = df_1d.iloc[-1]
                if str(row.get("trade_date", "")) == trade_date:
                    pct = float(row.get("pct_change", 0) or 0)

            candidates.append({
                "code": w["code"],
                "name": w["name"],
                "level": w["level"],
                "pct_change": pct,
                "reasons": ["⭐ 自选"],
            })
            seen_codes.add(w["code"])

log.info("stage=sector_candidates candidates=%d (with watchlist)", len(candidates))
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: include watchlist industries in sector AI generation"
```

---

### Task 7: Version Bump

**Files:**
- Modify: `dashboard/services/dashboard_service.py` — `_AI_VERSION`

- [ ] **Step 1: Bump version**

Find `_AI_VERSION` in `DashboardService` and increment Z (patch):

```python
_AI_VERSION = "1.7.X"  # increment the patch number
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "chore: bump AI version to X.Y.Z"
```

---

### Task 8: Verification

- [ ] **Step 1: Create `config/watchlist_industries.txt` with test data**

```txt
半导体
光伏设备
白酒
```

- [ ] **Step 2: Start dashboard, open console, click apply**

```bash
cd dashboard && bash start_dashboard.sh
# or: streamlit run dashboard/app.py
```

Verify: Console shows ⭐ 自选行业 expander with matched industries ✅.

- [ ] **Step 3: Open sector analysis page**

Verify:
- ⭐ 自选行业 block appears between TOP5/BOTTOM5 and 行业详细分析
- Watchlist industries show correct pct_change
- Expanding an item shows full technical analysis
- Watchlist industries are NOT duplicated in 行业详细分析

- [ ] **Step 4: Verify AI summaries**

After AI generation completes, check that watchlist industries have AI guide content in their expanders.
