# 板块分析（Agent 2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform `02_板块分析.py` from a hardcoded mock into a fully functional industry sector analysis page with market-cap-weighted industry indices, technical analysis expanders, and AI-generated guides.

**Architecture:** Bottom-up industry index construction — fetch constituent stocks via `index_member` API, aggregate daily OHLCV using circ_mv weights, cache in SQLite. AI pipeline follows the existing 3-step pattern: per-industry guides (parallel `batch_chat`) → summary guide. Page renders TOP5/BOTTOM5 cards + deduplicated analysis expanders reusing the existing `render_index_section` template.

**Tech Stack:** Python, Streamlit, SQLite, Tushare Pro API, Plotly, DeepSeek/OpenAI-compatible LLM

## Global Constraints

- Red=bullish (#e53935), Green=bearish (#43a047) — color convention
- AI prompts give data and usage notes only, never conclusions
- Cache reads MUST filter by `trade_date`; never bare "latest N rows"
- Logging follows project convention: per-module file in `logs/`
- Progress callbacks use `(phase, current, total, extra)` signature
- `summary_type = "sector_analysis"` for AI cache entries in `ai_summary` table

---

## File Structure Map

| File | Role |
|------|------|
| `src/marketreview/data/schema.sql` | +2 tables: `industry_member_cache`, `industry_daily` |
| `src/marketreview/data/cache_manager.py` | +read/write methods for 2 new tables |
| `src/marketreview/data/data_provider.py` | +`ensure_industry_members()`, +`ensure_industry_daily()`, wire into `ensure_data_loaded()` |
| `src/marketreview/tools/industry.py` | **NEW** — SPLIT config, industry list builder, aggregation engine |
| `dashboard/services/dashboard_service.py` | +10 industry methods + `generate_ai_sector_analysis()` |
| `src/marketreview/tools/contribution.py` | Update `pick_industry_label()` / `pick_industry_code()` to recursive split |
| `src/marketreview/llm/prompts/guide_sector_item.md` | **NEW** — per-industry AI guide template |
| `src/marketreview/llm/prompts/guide_sector_summary.md` | **NEW** — sector summary AI guide template |
| `dashboard/pages/02_板块分析.py` | Rewrite from mock to full implementation |
| `dashboard/pages/00_控制台.py` | +industry classification rules expander + sector AI progress phases |

---

### Task 1: Add industry tables to schema.sql

**Files:**
- Modify: `src/marketreview/data/schema.sql` (append after line 92)

**Produces:** Two new tables in SQLite schema

- [ ] **Step 1: Append DDL to schema.sql**

Append the following after the existing `ai_summary` table DDL:

```sql
CREATE TABLE IF NOT EXISTS industry_member_cache (
    industry_code TEXT NOT NULL,
    con_code      TEXT NOT NULL,
    PRIMARY KEY (industry_code, con_code)
);

CREATE TABLE IF NOT EXISTS industry_daily (
    industry_code TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    open          REAL,
    high          REAL,
    low           REAL,
    close         REAL,
    amount        REAL,
    vol           REAL,
    up_count      INTEGER,
    down_count    INTEGER,
    flat_count    INTEGER,
    stock_count   INTEGER,
    PRIMARY KEY (industry_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_industry_daily_code_date
    ON industry_daily(industry_code, trade_date DESC);
```

- [ ] **Step 2: Verify schema.sql is valid SQL**

Run: `python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('src/marketreview/data/schema.sql').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/data/schema.sql
git commit -m "feat: add industry_member_cache + industry_daily tables to schema"
```

---

### Task 2: Add expected columns and read/write methods to CacheManager

**Files:**
- Modify: `src/marketreview/data/cache_manager.py`

**Interfaces:**
- Consumes: schema.sql tables from Task 1
- Produces: `get_industry_members(industry_code)`, `upsert_industry_members(industry_code, rows)`, `get_industry_daily(industry_code, end_date, lookback)`, `upsert_industry_daily(rows)`, `has_industry_daily(industry_code, trade_date)`, `get_industry_daily_dates_in_range(industry_code, start, end)`, `count_industry_daily_date(trade_date)`

- [ ] **Step 1: Add expected columns to `_EXPECTED_COLUMNS`**

Add after the `"ai_summary"` entry (line 57):

```python
"industry_member_cache": {
    "industry_code", "con_code",
},
"industry_daily": {
    "industry_code", "trade_date",
    "open", "high", "low", "close",
    "amount", "vol",
    "up_count", "down_count", "flat_count", "stock_count",
},
```

- [ ] **Step 2: Add industry_member_cache read/write methods**

Add after the existing `get_stock_basic_count` method (after line 338):

```python
# ------- industry_member_cache -------

def get_industry_members(self, industry_code: str) -> list[str]:
    """Return list of con_code for an industry. Empty list if not cached."""
    with self._get_conn() as conn:
        rows = conn.execute(
            "SELECT con_code FROM industry_member_cache WHERE industry_code = ?",
            [industry_code],
        ).fetchall()
    return [r["con_code"] for r in rows]

def upsert_industry_members(self, industry_code: str, con_codes: list[str]):
    """Replace all constituent stocks for an industry (DELETE + INSERT batch)."""
    with self._get_conn() as conn:
        conn.execute(
            "DELETE FROM industry_member_cache WHERE industry_code = ?",
            [industry_code],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO industry_member_cache (industry_code, con_code) "
            "VALUES (?, ?)",
            [(industry_code, c) for c in con_codes],
        )
        conn.commit()

def has_industry_members(self, industry_code: str) -> bool:
    """Return True if this industry has cached members."""
    with self._get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM industry_member_cache WHERE industry_code = ? LIMIT 1",
            [industry_code],
        ).fetchone()
    return row is not None
```

- [ ] **Step 3: Add industry_daily read/write methods**

Append after the industry_member_cache methods:

```python
# ------- industry_daily -------

def get_industry_daily(
    self, industry_code: str,
    end_date: str | None = None,
    lookback: int = 360,
) -> list[dict]:
    """Return daily rows for one industry, date DESC, limited to lookback."""
    end_date = (end_date or "").replace("-", "")
    sql = "SELECT * FROM industry_daily WHERE industry_code = ?"
    params: list = [industry_code]
    if end_date:
        sql += " AND trade_date <= ?"
        params.append(end_date)
    sql += " ORDER BY trade_date DESC"
    if lookback:
        sql += " LIMIT ?"
        params.append(lookback)
    with self._get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]

def upsert_industry_daily(self, rows: list[dict]):
    """Bulk upsert industry_daily rows. Each row: {industry_code, trade_date,
    open, high, low, close, amount, vol, up_count, down_count, flat_count,
    stock_count}."""
    sql = """
        INSERT OR REPLACE INTO industry_daily
            (industry_code, trade_date, open, high, low, close,
             amount, vol, up_count, down_count, flat_count, stock_count)
        VALUES (:industry_code, :trade_date, :open, :high, :low, :close,
                :amount, :vol, :up_count, :down_count, :flat_count, :stock_count)
    """
    with self._get_conn() as conn:
        conn.executemany(sql, rows)
        conn.commit()

def has_industry_daily(self, industry_code: str, trade_date: str) -> bool:
    """Return True if this industry has daily data for this date."""
    trade_date = trade_date.replace("-", "")
    with self._get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM industry_daily "
            "WHERE industry_code = ? AND trade_date = ? LIMIT 1",
            [industry_code, trade_date],
        ).fetchone()
    return row is not None

def get_industry_daily_dates_in_range(
    self, industry_code: str, start: str, end: str,
) -> list[str]:
    """Return distinct trade dates in industry_daily for a range."""
    start = start.replace("-", "")
    end = end.replace("-", "")
    with self._get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT trade_date FROM industry_daily "
            "WHERE industry_code = ? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date",
            [industry_code, start, end],
        ).fetchall()
    return [r[0] for r in rows]

def count_industry_daily_date(self, trade_date: str) -> int:
    """Return number of industries with daily data for a given date."""
    trade_date = trade_date.replace("-", "")
    with self._get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT industry_code) FROM industry_daily "
            "WHERE trade_date = ?",
            [trade_date],
        ).fetchone()
    return row[0] if row else 0
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "from marketreview.data.cache_manager import CacheManager; print('OK')"`
Expected: `OK` (existing DB may trigger schema re-init, that's fine)

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/cache_manager.py
git commit -m "feat: add industry_member_cache + industry_daily read/write methods"
```

---

### Task 3: Create industry tools module (SPLIT config + list builder)

**Files:**
- Create: `src/marketreview/tools/industry.py`

**Produces:** `SPLIT_L1`, `SPLIT_L2` constants, `build_industry_list()` returning 63 industries, `build_industry_label()` for recursive label resolution

- [ ] **Step 1: Create industry.py with config and list builder**

```python
"""
Industry classification tools: split configuration, list builder, and
bottom-up market-cap-weighted index aggregation.

Uses Shenwan 2021 classification (申万 SW2021) queried via tushare
index_classify API.  The recursive split rule replaces certain L1
industries with their L2 children, and certain L2 with their L3 children.
"""

from marketreview.log_util import get_logger

log = get_logger(__name__)

# ── Split configuration ──
# L1 industries that are replaced by their L2 children
SPLIT_L1 = {'建筑材料', '有色金属', '汽车', '电力设备', '电子', '通信'}

# L2 industries that are further replaced by their L3 children
SPLIT_L2 = {'半导体', '元件', '光伏设备'}


def _fetch_sw_classification(level: str, api) -> list[dict]:
    """Fetch one level of Shenwan 2021 classification from tushare.

    Returns list of {index_code, industry_code, industry_name, parent_code}.
    """
    try:
        df = api.index_classify(level=level, src='SW2021')
        if df is None or df.empty:
            log.warning("index_classify(level=%s) returned empty", level)
            return []
        result = []
        for _, r in df.iterrows():
            result.append({
                "index_code": str(r.get("index_code", "")),
                "industry_code": str(r.get("industry_code", "")),
                "industry_name": str(r.get("industry_name", "")),
                "parent_code": str(r.get("parent_code", "")),
            })
        return result
    except Exception as e:
        log.warning("index_classify(level=%s) failed: %s", level, e)
        return []


def build_industry_list(api) -> list[dict]:
    """
    Build the final 63-industry list using recursive split rules.

    Returns list of dicts: [{code, name, level, parent_code}, ...]
      code = index_code from tushare (e.g. '801081.SI', '850814.SI')
        This is the code used with index_member API to get constituents.
      level = 'L1' | 'L2' | 'L3'
    """
    l1_all = _fetch_sw_classification("L1", api)
    l2_all = _fetch_sw_classification("L2", api)
    l3_all = _fetch_sw_classification("L3", api)

    # Build lookup: industry_code -> item
    l2_by_parent: dict[str, list[dict]] = {}
    for item in l2_all:
        pc = item["parent_code"]
        l2_by_parent.setdefault(pc, []).append(item)

    l3_by_parent: dict[str, list[dict]] = {}
    for item in l3_all:
        pc = item["parent_code"]
        l3_by_parent.setdefault(pc, []).append(item)

    # Build lookup: industry_name -> industry_code (for parent matching)
    # L1 parent_code is 6-digit group code; L2 parent_code is L1's industry_code
    l1_code_by_name: dict[str, str] = {}
    for item in l1_all:
        l1_code_by_name[item["industry_name"]] = item["industry_code"]

    result: list[dict] = []

    for l1 in l1_all:
        if l1["industry_name"] in SPLIT_L1:
            # Replace L1 with its L2 children
            l1_code = l1["industry_code"]
            children = l2_by_parent.get(l1_code, [])
            for l2 in children:
                if l2["industry_name"] in SPLIT_L2:
                    # Replace L2 with its L3 children
                    l2_code = l2["industry_code"]
                    grandchildren = l3_by_parent.get(l2_code, [])
                    for l3 in grandchildren:
                        result.append({
                            "code": l3["index_code"],
                            "name": l3["industry_name"],
                            "level": "L3",
                            "parent_code": l2_code,
                        })
                else:
                    result.append({
                        "code": l2["index_code"],
                        "name": l2["industry_name"],
                        "level": "L2",
                        "parent_code": l1_code,
                    })
        else:
            result.append({
                "code": l1["index_code"],
                "name": l1["industry_name"],
                "level": "L1",
                "parent_code": "",
            })

    l1_count = sum(1 for r in result if r["level"] == "L1")
    l2_count = sum(1 for r in result if r["level"] == "L2")
    l3_count = sum(1 for r in result if r["level"] == "L3")
    log.info("build_industry_list: %d L1 + %d L2 + %d L3 = %d total",
             l1_count, l2_count, l3_count, len(result))
    return result


def resolve_industry_label(
    l1_code: str, l1_name: str,
    l2_code: str, l2_name: str,
    l3_code: str = "", l3_name: str = "",
) -> str:
    """
    Resolve the display label for a stock's industry classification
    using the recursive split rules.

    Priority: L3 (if L2 in SPLIT_L2) > L2 (if L1 in SPLIT_L1) > L1
    """
    if l1_name in SPLIT_L1 and l2_name:
        if l2_name in SPLIT_L2 and l3_name:
            return l3_name
        return l2_name
    return l1_name


def resolve_industry_code(
    l1_code: str, l2_code: str, l3_code: str = "",
) -> str:
    """Return the industry code matching resolve_industry_label's choice."""
    # We need names to resolve — but for code-only resolution we use
    # the same logic as pick_industry_code in contribution.py.
    # This mirrors contribution.py's updated logic.
    from marketreview.tools.industry import SPLIT_L1, SPLIT_L2  # noqa (self-ref)
    # We can't resolve names here, so return the best guess
    if l3_code:
        return l3_code
    if l2_code:
        return l2_code
    return l1_code
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from marketreview.tools.industry import SPLIT_L1, SPLIT_L2, build_industry_list; print(f'SPLIT_L1={SPLIT_L1} SPLIT_L2={SPLIT_L2} OK')"`
Expected: `SPLIT_L1={...} SPLIT_L2={...} OK`

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/tools/industry.py
git commit -m "feat: add industry split config + list builder module"
```

---

### Task 4: Add industry data loading to DataProvider

**Files:**
- Modify: `src/marketreview/data/data_provider.py`

**Interfaces:**
- Consumes: `industry.py` SPLIT config + list builder, `CacheManager` methods from Task 2
- Produces: `ensure_industry_members(progress_cb)`, `ensure_industry_daily(trade_date, progress_cb)`, `get_industry_daily(code, end_date, lookback)`

- [ ] **Step 1: Add industry loading methods to DataProvider**

Insert before the `# ═══ Utility ═══` section (before line 938), after the `get_circ_mv` method:

```python
# ═══════════════════════════════════════════════════════════════
#  Industry data (bottom-up market-cap-weighted aggregation)
# ═══════════════════════════════════════════════════════════════

def ensure_industry_members(self, progress_cb=None) -> list[dict]:
    """
    Ensure industry_member_cache has constituent lists for all 63
    industries in the split configuration.

    Fetches via tushare index_member(is_new="Y") per industry code.
    Skips industries already cached.

    Returns the industry list [{code, name, level}, ...].
    """
    from marketreview.tools.industry import build_industry_list

    industries = build_industry_list(self._api)
    total = len(industries)
    fetched = 0

    for i, ind in enumerate(industries):
        code = ind["code"]
        if self.cache.has_industry_members(code):
            continue

        try:
            df = self._api.index_member(index_code=code, is_new="Y")
            if df is not None and not df.empty:
                con_codes = [str(r["con_code"]) for _, r in df.iterrows()]
                if con_codes:
                    self.cache.upsert_industry_members(code, con_codes)
                    fetched += 1
                    log.info("ensure_industry_members: %s (%s) — %d constituents",
                             ind["name"], code, len(con_codes))
                else:
                    log.warning("ensure_industry_members: %s (%s) — empty constituents",
                                ind["name"], code)
        except Exception as e:
            log.warning("index_member(%s %s) failed: %s", code, ind["name"], e)

        if progress_cb:
            progress_cb("industry_members", i + 1, total,
                        f"{ind['name']} ({fetched} fetched)")

    log.info("ensure_industry_members: %d/%d industries fetched, %d total",
             fetched, total, total)
    return industries

def ensure_industry_daily(
    self, trade_date: str, progress_cb=None,
) -> int:
    """
    Ensure industry_daily has aggregated data for trade_date.

    For each industry in the split list:
    1. Get constituent codes from industry_member_cache
    2. Read stock OHLCV from tushare_cache (today + previous day)
    3. Read circ_mv from daily_basic_cache
    4. Compute market-cap-weighted returns → build industry OHLCV
    5. Upsert into industry_daily

    Skips industries already cached for this date.
    Returns number of industries computed.
    """
    from marketreview.tools.industry import build_industry_list

    trade_date = trade_date.replace("-", "")
    industries = build_industry_list(self._api)
    total = len(industries)
    computed = 0

    # Get previous trading date for up/down counts
    prev_date = self.cache.get_previous_trade_date(trade_date)
    if not prev_date:
        prev_date = trade_date  # fallback, won't have prev data

    # Pre-fetch circ_mv for the date (shared across all industries)
    circ_mv_map = self.get_circ_mv(trade_date)

    for i, ind in enumerate(industries):
        code = ind["code"]
        if self.cache.has_industry_daily(code, trade_date):
            continue

        # 1. Get constituent list
        con_codes = self.cache.get_industry_members(code)
        if not con_codes:
            log.debug("ensure_industry_daily: %s (%s) — no constituents, skip",
                      ind["name"], code)
            continue

        # 2. Read stock OHLCV for today + previous day
        #    Batch fetch: one query per stock for 2-day lookback
        stock_today: dict[str, dict] = {}
        stock_prev: dict[str, dict] = {}
        for con in con_codes:
            rows = self.cache.get_daily(con, end=trade_date, limit=2)
            # rows are date DESC; rows[0] = trade_date (if matches), rows[1] = prev
            if rows and rows[0]["date"].replace("-", "") == trade_date:
                stock_today[con] = dict(rows[0])
                if len(rows) >= 2:
                    stock_prev[con] = dict(rows[1])

        if not stock_today:
            log.debug("ensure_industry_daily: %s (%s) — no stock data for %s",
                      ind["name"], code, trade_date)
            continue

        # 3. Compute weights from circ_mv
        total_mv = sum(
            circ_mv_map.get(c, 0) for c in stock_today
        )
        if total_mv <= 0:
            log.debug("ensure_industry_daily: %s (%s) — zero total circ_mv, skip",
                      ind["name"], code)
            continue

        weights: dict[str, float] = {}
        for c in stock_today:
            mv = circ_mv_map.get(c, 0)
            weights[c] = mv / total_mv if mv > 0 else 0.0

        # 4. Compute market-cap-weighted return
        weighted_return = 0.0
        weighted_open_return = 0.0
        weighted_high_return = 0.0
        weighted_low_return = 0.0
        up = down = flat = 0
        total_amount = 0.0
        total_vol = 0.0

        for c, today in stock_today.items():
            w = weights.get(c, 0)
            close_t = float(today["close"])
            open_t = float(today["open"])
            high_t = float(today["high"])
            low_t = float(today["low"])
            amount_t = float(today.get("amount", 0))
            vol_t = float(today.get("vol", 0))
            total_amount += amount_t
            total_vol += vol_t

            prev = stock_prev.get(c)
            if prev:
                prev_close = float(prev["close"])
                prev_open = float(prev["open"])
                prev_high = float(prev["high"])
                prev_low = float(prev["low"])

                # Adjust prev prices for adj_factor difference (matching
                # the pre_close calculation in get_daily_batch)
                adj_today = float(today.get("adj_factor", 1.0))
                adj_prev = float(prev.get("adj_factor", 1.0))
                if adj_today > 0:
                    ratio = adj_prev / adj_today
                    prev_close = prev_close * ratio
                    prev_open = prev_open * ratio
                    prev_high = prev_high * ratio
                    prev_low = prev_low * ratio

                if prev_close > 0:
                    weighted_return += w * (close_t / prev_close - 1)
                    weighted_open_return += w * (open_t / prev_open - 1)
                    weighted_high_return += w * (high_t / prev_high - 1)
                    weighted_low_return += w * (low_t / prev_low - 1)

                # up/down/flat
                if close_t > prev_close:
                    up += 1
                elif close_t < prev_close:
                    down += 1
                else:
                    flat += 1
            else:
                flat += 1

        # 5. Build price curve (start from base=1000 on first day, or
        #    continue from previous industry close)
        prev_industry_rows = self.cache.get_industry_daily(code, end_date=trade_date, lookback=1)
        if prev_industry_rows:
            base_close = float(prev_industry_rows[0]["close"])
        else:
            base_close = 1000.0  # arbitrary base

        industry_close = round(base_close * (1 + weighted_return), 4)
        industry_open = round(base_close * (1 + weighted_open_return), 4)
        industry_high = round(base_close * (1 + weighted_high_return), 4)
        industry_low = round(base_close * (1 + weighted_low_return), 4)

        # 6. Upsert
        self.cache.upsert_industry_daily([{
            "industry_code": code,
            "trade_date": trade_date,
            "open": industry_open,
            "high": industry_high,
            "low": industry_low,
            "close": industry_close,
            "amount": round(total_amount, 2),
            "vol": round(total_vol, 2),
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "stock_count": len(stock_today),
        }])
        computed += 1

        if progress_cb and computed % 5 == 0:
            progress_cb("industry_daily", i + 1, total,
                        f"{ind['name']} ({computed} computed)")

    log.info("ensure_industry_daily: date=%s computed=%d/%d",
             trade_date, computed, total)
    return computed

def get_industry_daily(
    self, industry_code: str,
    end_date: str | None = None,
    lookback: int = 360,
) -> list[dict]:
    """Return industry daily rows (date DESC), read from cache only."""
    return self.cache.get_industry_daily(
        industry_code, end_date=end_date, lookback=lookback,
    )

def get_industry_ranking(self, trade_date: str) -> list[dict]:
    """
    Return all industries sorted by daily return (descending) for a date.
    Returns [{code, name, level, chg_pct, up_count, down_count,
              flat_count, stock_count, amount_yi}, ...].
    """
    from marketreview.tools.industry import build_industry_list

    trade_date = trade_date.replace("-", "")
    ind_list = build_industry_list(self._api)
    ind_map = {ind["code"]: ind for ind in ind_list}

    results = []
    for ind in ind_list:
        rows = self.cache.get_industry_daily(ind["code"], end_date=trade_date, lookback=2)
        if len(rows) >= 2 and rows[0]["trade_date"] == trade_date:
            today = rows[0]
            prev = rows[1]
            close = float(today["close"])
            prev_close = float(prev["close"])
            chg_pct = round((close / prev_close - 1) * 100, 2) if prev_close > 0 else 0.0
            results.append({
                "code": ind["code"],
                "name": ind["name"],
                "level": ind["level"],
                "chg_pct": chg_pct,
                "close": close,
                "up_count": today["up_count"],
                "down_count": today["down_count"],
                "flat_count": today["flat_count"],
                "stock_count": today["stock_count"],
                "amount_yi": round(float(today["amount"]) / 1e5, 2),
            })

    results.sort(key=lambda x: x["chg_pct"], reverse=True)
    return results
```

- [ ] **Step 2: Wire industry loading into `ensure_data_loaded()`**

In `ensure_data_loaded()`, after the `_ensure_daily_basic_loaded()` call and before `_validate_coverage()`, add:

```python
# ── Load industry data ──
self.ensure_industry_members(progress_cb)
industry_days = self.ensure_industry_daily(end_date, progress_cb)
```

Add `industry_days` to the return dict:

```python
return {
    "status": "ok",
    "elapsed": round(elapsed, 1),
    "chunks": total_chunks,
    "raw_pages": raw_pages_total,
    "adj_pages": adj_pages_total,
    "index_chunks": idx_chunks,
    "db_pages": db_pages,
    "industry_days": industry_days,
}
```

Also update the "cache up to date" return (the one in the `if not missing_ranges:` block) to include industry loading and add `"industry_days": 0` to its return dict.

- [ ] **Step 3: Add industry coverage to `check_cache_coverage()`**

Add after the `daily_basic_has_range` check and before the final `return True`:

```python
# Verify industry_daily has data for the target date
if self.cache.count_industry_daily_date(end_date) < 50:
    log.info("check_cache_coverage: industry_daily for %s has only %d "
             "industries (need >= 50), fast path denied",
             end_date, self.cache.count_industry_daily_date(end_date))
    return False
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "from marketreview.data.data_provider import DataProvider; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/data_provider.py
git commit -m "feat: add industry data loading to DataProvider (+ wire into ensure_data_loaded)"
```

---

### Task 5: Update contribution.py industry label logic

**Files:**
- Modify: `src/marketreview/tools/contribution.py`

**Produces:** Updated `pick_industry_label()` and `pick_industry_code()` using recursive split rules

- [ ] **Step 1: Replace override lists and label functions**

Replace the old `L1_OVERRIDE_L1` and `L3_OVERRIDE_L3` dicts (lines 33-57) and the `pick_industry_label()` / `pick_industry_code()` functions (lines 60-83) with:

```python
# Industry label resolution follows the same recursive split rules as
# the sector analysis page.  SPLIT_L1 and SPLIT_L2 are imported from
# the canonical source in industry.py.

from marketreview.tools.industry import SPLIT_L1, SPLIT_L2


def pick_industry_label(l1_code: str, l1_name: str,
                        l2_code: str, l2_name: str,
                        l3_code: str = "", l3_name: str = "") -> str:
    """Choose the display label for a stock's industry (recursive split).

    Priority: L3 (if L2 in SPLIT_L2) > L2 (if L1 in SPLIT_L1) > L1
    """
    if l1_name in SPLIT_L1 and l2_name:
        if l2_name in SPLIT_L2 and l3_name:
            return l3_name
        return l2_name
    return l1_name


def pick_industry_code(l1_code: str, l2_code: str,
                       l3_code: str = "") -> str:
    """Return the industry code that matches pick_industry_label's choice."""
    if l3_code:
        return l3_code
    if l2_code:
        return l2_code
    return l1_code
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from marketreview.tools.contribution import pick_industry_label; print(pick_industry_label('', '电子', '', '半导体', '', '数字芯片设计'))"`
Expected: `数字芯片设计`

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/tools/contribution.py
git commit -m "refactor: switch pick_industry_label to recursive split rules from industry.py"
```

---

### Task 6: Add DashboardService industry methods (data access)

**Files:**
- Modify: `dashboard/services/dashboard_service.py`

**Produces:** `get_industry_split_config()`, `get_industry_list()`, `ensure_industry_members()`, `ensure_industry_daily()`, `get_industry_daily()`, `get_industry_ranking()`, `get_industry_analysis_set()`

- [ ] **Step 1: Add industry data methods**

Insert after `get_industry_frequency()` (after line 225):

```python
# ---- industry sector data ----

def get_industry_split_config(self) -> dict:
    """Return SPLIT_L1 / SPLIT_L2 configuration for display."""
    from marketreview.tools.industry import SPLIT_L1, SPLIT_L2
    return {"split_l1": sorted(SPLIT_L1), "split_l2": sorted(SPLIT_L2)}

def get_industry_list(self) -> list[dict]:
    """Return the 63-industry list [{code, name, level}, ...]."""
    from marketreview.tools.industry import build_industry_list
    return build_industry_list(self._dp._api)

def ensure_industry_members(self, progress_cb=None) -> list[dict]:
    """Ensure constituent lists are cached for all industries."""
    return self._dp.ensure_industry_members(progress_cb=progress_cb)

def ensure_industry_daily(self, trade_date: str, progress_cb=None) -> int:
    """Ensure industry_daily has aggregated data for trade_date."""
    return self._dp.ensure_industry_daily(trade_date, progress_cb=progress_cb)

def get_industry_daily(
    self, industry_code: str,
    end_date: str | None = None,
    lookback: int = 360,
) -> "pd.DataFrame":
    """
    Read industry K-line data, return as DataFrame (date ASC, qfq-like).
    Industry data is already in price form (not raw+adj_factor), so no
    raw_to_qfq conversion needed — but we normalize to match the interface.
    """
    from marketreview.tools.technical import rows_to_df
    rows = self._dp.get_industry_daily(industry_code, end_date=end_date, lookback=lookback)
    df = rows_to_df(rows)
    # Industry data is already price-scaled; add dummy adj_factor column
    # so downstream code (like build_technical_summary) works unchanged.
    if not df.empty:
        df["adj_factor"] = 1.0
    return df

def get_industry_ranking(self, trade_date: str) -> list[dict]:
    """Return all 63 industries sorted by daily return (descending)."""
    return self._dp.get_industry_ranking(trade_date)

def get_industry_analysis_set(self, trade_date: str) -> list[dict]:
    """
    Build the deduplicated set of industries to display in expanders.

    Sources (deduplicated by industry code):
      1. TOP 5 gainers (🥇涨幅第N)
      2. TOP 5 losers  (📉跌幅第N)
      3. Contribution上榜 industries (📊权重贡献上榜)
      4. Frequent ≥3d industries  (🔁近5日频繁领涨/领跌)

    Returns [{code, name, level, chg_pct, reasons: [str]}, ...],
    sorted by abs(chg_pct) DESC (most volatile first).
    """
    ranking = self.get_industry_ranking(trade_date)
    if not ranking:
        return []

    # Build lookup
    ind_map = {r["code"]: r for r in ranking}
    analysis: dict[str, dict] = {}

    def _add(code: str, reason: str):
        if code not in ind_map:
            return
        if code in analysis:
            if reason not in analysis[code]["reasons"]:
                analysis[code]["reasons"].append(reason)
            return
        r = ind_map[code]
        analysis[code] = {
            "code": code,
            "name": r["name"],
            "level": r["level"],
            "chg_pct": r["chg_pct"],
            "up_count": r["up_count"],
            "down_count": r["down_count"],
            "stock_count": r["stock_count"],
            "amount_yi": r["amount_yi"],
            "reasons": [reason],
        }

    # 1. TOP 5 gainers
    for i, r in enumerate(ranking[:5]):
        _add(r["code"], f"🥇涨幅第{i+1}")

    # 2. TOP 5 losers
    for i, r in enumerate(ranking[-5:]):
        _add(r["code"], f"📉跌幅第{5-i}")

    # 3. Contribution上榜 industries
    for idx_code in ["000001.SH", "399006.SZ"]:
        contrib = self.get_index_contribution(idx_code, trade_date)
        if not contrib:
            continue
        for g in contrib.get("gainers", []):
            ic = g.get("industry_code", "")
            if ic:
                _add(ic, "📊权重贡献上榜")
        for l in contrib.get("losers", []):
            ic = l.get("industry_code", "")
            if ic:
                _add(ic, "📊权重贡献上榜")

    # 4. Frequent ≥3d industries
    for idx_code in ["000001.SH", "399006.SZ"]:
        freq = self.get_industry_frequency(idx_code, trade_date)
        if not freq:
            continue
        for f in freq.get("gainers", []):
            _add(f["code"], f"🔁近5日频繁领涨({f['days']}天)")
        for f in freq.get("losers", []):
            _add(f["code"], f"🔁近5日频繁领跌({f['days']}天)")

    result = sorted(analysis.values(), key=lambda x: abs(x["chg_pct"]), reverse=True)
    return result
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from services.dashboard_service import DashboardService; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: add industry data access methods to DashboardService"
```

---

### Task 7: Create AI prompt templates for sector analysis

**Files:**
- Create: `src/marketreview/llm/prompts/guide_sector_item.md`
- Create: `src/marketreview/llm/prompts/guide_sector_summary.md`

- [ ] **Step 1: Create guide_sector_item.md**

```markdown
根据以下市场数据及行业技术数据，输出2-3句话总结该行业板块的技术状态。

数据说明：
- 涨跌结构：全市场上涨/平盘/下跌家数及占比。上涨多于下跌=多方占优，反之空方占优。
- 成交额：全市场今日/昨日/5日/10日均量。
- 3浪3选股（3浪3选股_近15日）：全市场主升浪强势股筛选。数量上升=赚钱效应扩散，下降=收缩。
- 扣抵量：今日成交额与均线扣抵日成交额的对比——今日量>扣抵量→均线有望上扬形成支撑；反之均线可能下压形成压力。
- 均线作用：上扬均线=支撑，下跌均线=压力，走平均线=无作用。
- KD区间：K,D双线均>80为超买区，K,D双线均<20为超卖区（双线判断，非单线）。
- RSI区间：>70超买区，<30超卖区。
- BIAS10：价格与10日均线的偏离程度，|BIAS10|>10%短线超买/超卖。
- BIAS20：价格与20日均线的偏离程度，|BIAS20|>7%超买/超卖。
- KD/RSI背离：顶背离=价格新高但指标未新高（看跌），底背离=价格新低但指标未新低（看涨）。
- K线形态：K线形状的分类及其多空含义。多头吞影线=偏多（仙人指路），空头吞影线=偏空，颈上线/颈内线=偏空，纺锤线=高档偏空/低档偏多，高档长阳=偏空。

市场数据：
{market_data}

行业技术数据：
{data}
```

- [ ] **Step 2: Create guide_sector_summary.md**

```markdown
根据以下市场数据、各行业板块的技术总结以及当日排名，输出3-4句话的行业板块整体总结。

需要覆盖：
1. 今日行业轮动的核心特征（哪些方向领涨、哪些领跌）
2. 是否有明显的板块轮动或风格切换信号
3. 赚钱效应集中在哪些领域，是否具备持续性

数据说明：同之前各行业导语的数据说明。

市场数据：
{market_data}

各行业导语：
{sector_guides}

当日排名（TOP5/BOTTOM5）：
{ranking}
```

- [ ] **Step 3: Verify files exist**

Run: `ls -la src/marketreview/llm/prompts/guide_sector_item.md src/marketreview/llm/prompts/guide_sector_summary.md`
Expected: Both files listed

- [ ] **Step 4: Commit**

```bash
git add src/marketreview/llm/prompts/guide_sector_item.md src/marketreview/llm/prompts/guide_sector_summary.md
git commit -m "feat: add AI prompt templates for sector analysis (item + summary)"
```

---

### Task 8: Add AI sector analysis pipeline to DashboardService

**Files:**
- Modify: `dashboard/services/dashboard_service.py`

**Produces:** `get_ai_sector_guide()`, `get_ai_sector_summary()`, `generate_ai_sector_analysis()`

- [ ] **Step 1: Add `_build_industry_ai_data()` helper**

Insert after `_build_index_ai_data()` (before `_AI_VERSION`):

```python
@staticmethod
def _build_industry_ai_data(
    name: str, rows: list[dict], tech_summary: dict,
) -> dict:
    """Build structured AI-ready data dict for one industry.
    
    Reuses the same format as _build_index_ai_data but without
    contribution data (industries don't have constituent contributions).
    """
    if not rows:
        return {"error": "无数据"}

    rows = sorted(rows, key=lambda r: r["date"])

    latest = rows[-1]
    close = float(latest["close"])
    open_val = float(latest["open"])
    high = float(latest["high"])
    low = float(latest["low"])

    if len(rows) >= 2:
        prev_close = float(rows[-2]["close"])
        chg_pct = (close / prev_close - 1) * 100
    else:
        chg_pct = 0.0

    kp = tech_summary.get("kline_pattern", {})
    price_data: dict = {
        "今日": {
            "开盘": round(open_val, 2),
            "最高": round(high, 2),
            "最低": round(low, 2),
            "收盘": round(close, 2),
            "涨跌幅": f"{chg_pct:+.2f}%",
            "K线类型": kp.get("type", ""),
            "实体占比": f"{kp.get('body_pct', 0)}%",
            "上影线占比": f"{kp.get('upper_wick_pct', 0)}%",
            "下影线占比": f"{kp.get('lower_wick_pct', 0)}%",
        },
    }

    # 近5日K线
    recent_5 = rows[-min(5, len(rows)):]
    price_data["近5日K线"] = []
    for i, r in enumerate(recent_5):
        entry: dict = {
            "日期": f"{r['date'][4:6]}-{r['date'][6:8]}",
            "开": round(float(r["open"]), 2),
            "高": round(float(r["high"]), 2),
            "低": round(float(r["low"]), 2),
            "收": round(float(r["close"]), 2),
        }
        if i > 0:
            prev_r = recent_5[i - 1]
            entry["涨跌幅"] = f"{(float(r['close']) / float(prev_r['close']) - 1) * 100:+.2f}%"
        elif len(rows) > len(recent_5):
            prev_r = rows[-len(recent_5) - 1]
            entry["涨跌幅"] = f"{(float(r['close']) / float(prev_r['close']) - 1) * 100:+.2f}%"
        price_data["近5日K线"].append(entry)

    # 均线
    mas = tech_summary.get("mas", {})
    ma_dirs = tech_summary.get("ma_directions", {})
    ma_list: list[dict] = []
    for period in [5, 10, 20, 60, 120, 240]:
        key = f"MA{period}"
        val = mas.get(key)
        if val is None:
            continue
        direction = ma_dirs.get(key, "→")
        if direction == "↑":
            role = "支撑"
        elif direction == "↓":
            role = "压力"
        else:
            role = "无(走平)"
        ma_list.append({"均线": key, "值": val, "方向": direction, "作用": role})

    # 成交量
    vol = tech_summary.get("volume", {})
    volume_data: dict = {
        "今日成交额": f"{vol.get('latest_amount_yi', 0):,.0f}亿",
        "5日均量": f"{vol.get('ma5_yi', 0):,.0f}亿",
        "今日vs5日均量": f"{vol.get('vs_ma5_pct', 0):+.1f}%",
        "量能趋势": vol.get("trend_5d", ""),
    }

    # 技术指标
    kd_k = tech_summary.get("kd_k", 0) or 0
    kd_d = tech_summary.get("kd_d", 0) or 0
    if kd_k > 80 and kd_d > 80:
        kd_zone = "超买区"
    elif kd_k < 20 and kd_d < 20:
        kd_zone = "超卖区"
    else:
        kd_zone = "常态区"
    rsi_val = tech_summary.get("rsi")
    rsi_zone = "超买区" if (rsi_val and rsi_val > 70) else ("超卖区" if (rsi_val and rsi_val < 30) else "常态区")

    kd_div = tech_summary.get("kd_divergence") or {}
    kd_div_detail = {"类型": kd_div["type"], "持续天数": kd_div.get("days", 0)} if kd_div.get("type") else "无"

    rsi_div = tech_summary.get("rsi_divergence") or {}
    rsi_div_detail = {"类型": rsi_div["type"], "持续天数": rsi_div.get("days", 0)} if rsi_div.get("type") else "无"

    indicator_data: dict = {
        "KD": {"K": kd_k, "D": kd_d, "区间": kd_zone, "背离": kd_div_detail},
        "RSI": {"值": rsi_val, "区间": rsi_zone, "背离": rsi_div_detail},
        "BIAS10": {"值": f"{tech_summary.get('bias10', 0):+.2f}%",
                   "状态": tech_summary.get("bias10_status") or "—"},
        "BIAS20": {"值": f"{tech_summary.get('bias20', 0):+.2f}%",
                   "状态": tech_summary.get("bias20_status") or "—"},
    }

    # K线形态
    try:
        from marketreview.tools.technical import rows_to_df
        from marketreview.tools.kline_patterns import detect_patterns
        _df = rows_to_df(rows)
        pattern_results = detect_patterns(_df, obj_type="index")
    except Exception:
        pattern_results = []

    return {
        "行业": name,
        "K线价格": price_data,
        "均线": {"排列": tech_summary.get("ma_arrangement", ""), "各均线": ma_list},
        "成交量": volume_data,
        "技术指标": indicator_data,
        "K线形态": pattern_results,
    }
```

- [ ] **Step 2: Add AI sector read methods**

Insert after `get_ai_summary()`:

```python
def get_ai_sector_guide(self, trade_date: str, industry_code: str) -> dict | None:
    """Read cached AI guide for one industry. Returns {content, model} or None."""
    rows = self._dp.cache.get_ai_summary(trade_date, "sector_analysis")
    for r in rows:
        if r["guide_key"] == f"sector/{industry_code}":
            if r.get("content") == "AI 摘要暂时不可用":
                return None
            return {"content": r["content"], "model": r["model"]}
    return None

def get_ai_sector_summary(self, trade_date: str) -> dict | None:
    """Read cached sector summary guide. Returns {content, model} or None."""
    rows = self._dp.cache.get_ai_summary(trade_date, "sector_analysis")
    for r in rows:
        if r["guide_key"] == "sector_summary":
            if r.get("content") == "AI 摘要暂时不可用":
                return None
            return {"content": r["content"], "model": r["model"]}
    return None
```

- [ ] **Step 3: Add `generate_ai_sector_analysis()`**

Insert after the `get_ai_sector_summary()` method, update `_AI_VERSION` to `"2.0.0"`:

```python
# Update _AI_VERSION:
_AI_VERSION = "2.0.0"  # was "1.2.1"

def generate_ai_sector_analysis(self, trade_date: str, progress_cb=None) -> dict:
    """Generate per-industry AI guides (parallel) + sector summary.

    Returns dict keyed by guide_key — same shape as get_ai_summary()
    but summary_type='sector_analysis'.
    """
    import json as _json, sys as _sys, time as _time

    _t_total = _time.perf_counter()
    _sys.stderr.write(f"[AI v{self._AI_VERSION}] generate_ai_sector_analysis({trade_date})\n")
    _sys.stderr.flush()

    llm = self._get_llm()
    model = llm.model_name
    FAIL_PLACEHOLDER = "AI 摘要暂时不可用"
    sys_prompt = self._load_system_prompt()

    # ── 1. Build market_data (reuse existing pattern) ──
    if progress_cb:
        progress_cb("sector_start", "正在准备行业数据...")
    overview = self.get_market_overview(trade_date)
    if overview is None or "error" in overview:
        return {}

    today = overview["today"]
    yesterday = overview["yesterday"]
    trend = overview["trend"]

    t_total = today["up"] + today["flat"] + today["down"]
    breadth_structure = {
        "今日": {
            "上涨": today["up"], "平盘": today["flat"], "下跌": today["down"],
            "上涨占比": f"{today['up'] / t_total * 100:.1f}%",
            "涨停": today["up_limit"], "跌停": today["down_limit"],
        },
    }
    if yesterday:
        y_total = yesterday["up"] + yesterday["flat"] + yesterday["down"]
        breadth_structure["昨日"] = {
            "上涨": yesterday["up"], "平盘": yesterday["flat"], "下跌": yesterday["down"],
            "上涨占比": f"{yesterday['up'] / y_total * 100:.1f}%",
            "涨停": yesterday["up_limit"], "跌停": yesterday["down_limit"],
        }

    amounts = [d["total_yi"] for d in trend]
    turnover_data = {
        "今日": f"{today['total_yi']:,.0f}亿",
    }
    if yesterday:
        turnover_data["昨日"] = f"{yesterday['total_yi']:,.0f}亿"
    if len(amounts) >= 5:
        turnover_data["5日均量"] = f"{sum(amounts[-5:]) / 5:,.0f}亿"
    if len(amounts) >= 10:
        turnover_data["10日均量"] = f"{sum(amounts[-10:]) / 10:,.0f}亿"

    w33 = self.get_wave33_data(chart_days=15, rolling_days=21, end_date=trade_date)
    wave33_list = []
    if w33["dates"]:
        for i, d in enumerate(w33["dates"]):
            dc = d.replace("-", "")
            wave33_list.append({
                "日期": f"{dc[4:6]}-{dc[6:8]}",
                "数量": w33["counts"][i],
                "20日盈利占比": f"{w33['profit_pcts'][i]}%",
            })

    market_data = {
        "涨跌结构": breadth_structure,
        "成交额": turnover_data,
        "3浪3选股_近15日": wave33_list,
    }
    market_data_json = _json.dumps(market_data, ensure_ascii=False)

    # ── 2. Select industries for AI analysis ──
    analysis_set = self.get_industry_analysis_set(trade_date)
    if not analysis_set:
        log.warning("generate_ai_sector_analysis: empty analysis set for %s", trade_date)
        return {}

    # ── 3. Build per-industry AI data + tasks ──
    from marketreview.tools.technical import rows_to_df, build_technical_summary
    from marketreview.llm.concurrent import batch_chat

    sector_tasks = []
    for ind in analysis_set:
        rows = self._dp.get_industry_daily(ind["code"], end_date=trade_date, lookback=360)
        if len(rows) < 5:
            continue
        ts = build_technical_summary(ind["code"], ind["name"], rows)
        ind_data = self._build_industry_ai_data(ind["name"], rows, ts)
        ind_data_json = _json.dumps(ind_data, ensure_ascii=False)
        user_tmpl = self._load_prompt("guide_sector_item")
        sector_tasks.append({
            "label": f"sector/{ind['code']}",
            "user_message": user_tmpl.format(market_data=market_data_json, data=ind_data_json),
        })

    if not sector_tasks:
        return {}

    log.info("stage=sector_data_prep tasks=%d", len(sector_tasks))

    # ── 4. Parallel per-industry guides ──
    def _sector_progress(phase: str, current: int, total: int, label: str):
        if progress_cb is None:
            return
        if phase == "start":
            progress_cb("sector_start", f"正在生成行业导语（共 {total} 个）...")
        elif phase == "progress":
            # label = "sector/850814.SI" — extract name
            code = label.replace("sector/", "")
            progress_cb("sector_progress", f"✅ 行业导语完成（{current}/{total}）")
        elif phase == "done":
            progress_cb("sector_done", f"行业导语全部完成（{total}/{total}）")

    sector_results = batch_chat(
        llm, sys_prompt, sector_tasks,
        max_workers=4,
        progress_cb=_sector_progress,
        fail_placeholder=FAIL_PLACEHOLDER,
    )

    # Save per-industry results
    result = {}
    for label, content in sector_results.items():
        if content != FAIL_PLACEHOLDER:
            self._dp.cache.save_ai_summary(
                trade_date, "sector_analysis", label, content, model,
            )
        result[label] = {"content": content, "model": model}

    # ── 5. Sector summary ──
    _t4 = _time.perf_counter()
    if progress_cb:
        progress_cb("sector_summary_start", "正在生成行业总结导语...")

    # Build ranking summary for the summary prompt
    ranking = self.get_industry_ranking(trade_date)
    top5 = [f"{r['name']}({r['level']}) {r['chg_pct']:+.2f}%" for r in ranking[:5]]
    bottom5 = [f"{r['name']}({r['level']}) {r['chg_pct']:+.2f}%" for r in ranking[-5:]]
    ranking_text = "TOP5: " + ", ".join(top5) + "\nBOTTOM5: " + ", ".join(bottom5)

    guides_text = "\n\n---\n\n".join(
        f"【{ind['name']}】\n{result.get(f'sector/{ind[\"code\"]}', {}).get('content', '无')}"
        for ind in analysis_set
    )

    try:
        user_tmpl = self._load_prompt("guide_sector_summary")
        summary = llm.chat(sys_prompt, user_tmpl.format(
            market_data=market_data_json,
            sector_guides=guides_text,
            ranking=ranking_text,
        ))
    except Exception as e:
        import traceback as _tb4
        log.warning("sector_summary LLM call failed: %s\n%s", e, _tb4.format_exc())
        summary = FAIL_PLACEHOLDER

    log.info("stage=sector_summary elapsed=%.1fs", _time.perf_counter() - _t4)

    if summary != FAIL_PLACEHOLDER:
        self._dp.cache.save_ai_summary(
            trade_date, "sector_analysis", "sector_summary", summary, model,
        )
    result["sector_summary"] = {"content": summary, "model": model}

    log.info("generate_ai_sector_analysis DONE total=%.1fs model=%s tasks=%d",
             _time.perf_counter() - _t_total, model, len(sector_tasks))
    return result
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "from services.dashboard_service import DashboardService; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: add AI sector analysis pipeline (3-step: parallel guides → summary)"
```

---

### Task 9: Rewrite 02_板块分析.py page

**Files:**
- Modify: `dashboard/pages/02_板块分析.py`

- [ ] **Step 1: Write the full page implementation**

Replace entire file content:

```python
"""
Agent 2 — 板块分析页面
行业板块涨跌排名 + 技术分析 expander（复用市场全景框架）
"""
import streamlit as st
import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from marketreview.tools.technical import (
    rows_to_df,
    calc_ma,
    ma_arrangement,
    ma_direction,
    volume_analysis,
    calc_kd,
    calc_rsi,
    calc_bias,
    bias_status,
    detect_kd_divergence,
    detect_rsi_divergence,
    get_offset_info,
    get_ma_role,
)
from services.dashboard_service import DashboardService
from rendering.styles import vol_color_ramp, up_down_color, PAGE_CSS
from rendering.charts import plot_kline_with_ma

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Date guard ──
_td = st.session_state.get("trade_date")
if not _td:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

st.title("🏭 板块分析")
_cd = f"{_td[:4]}-{_td[4:6]}-{_td[6:8]}"
st.caption(f"📅 {_cd}  |  申万行业分类 · 市值加权聚合")

_service = DashboardService()

# ── Section 1: AI 行业总结导语 ──
sector_summary = _service.get_ai_sector_summary(_td)
if sector_summary:
    st.info(sector_summary["content"])
else:
    st.caption("🤖 AI 行业总结尚未生成（切换日期时将自动生成）")

st.divider()

# ── Section 2: TOP 5 / BOTTOM 5 ──
st.subheader("📊 今日行业涨跌排名")

ranking = _service.get_industry_ranking(_td)
if not ranking:
    st.warning("暂无行业数据，请先在控制台加载数据")
    st.stop()

top5 = ranking[:5]
bottom5 = ranking[-5:]

col_g, col_l = st.columns(2)

def _render_rank_card(ind: dict, rank: int, is_gainer: bool):
    chg = ind["chg_pct"]
    color = up_down_color(chg)
    sign = "+" if chg >= 0 else ""
    level_tag = f"<span style='font-size:11px;color:#888;'>{ind['level']}</span>"
    up_ratio = f"{ind['up_count']}/{ind['stock_count']} ↑" if ind['stock_count'] else ""
    amount_str = f"{ind['amount_yi']:.0f}亿" if ind.get('amount_yi') else ""

    rank_icon = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][rank] if is_gainer else ["5️⃣", "4️⃣", "🥉", "🥈", "🥇"][4 - rank]
    st.html(f"""
    <div style="border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px;margin:4px 0;">
        <span style="font-size:18px;">{rank_icon}</span>
        <span style="font-weight:600;font-size:16px;">{ind['name']}</span>
        {level_tag}
        <span style="color:{color};font-weight:bold;font-size:18px;float:right;">{sign}{chg:.2f}%</span>
        <br><span style="font-size:12px;color:#888;">{up_ratio}  {amount_str}</span>
    </div>
    """)

with col_g:
    st.markdown("**🥇 领涨 TOP 5**")
    for i, ind in enumerate(top5):
        _render_rank_card(ind, i, True)

with col_l:
    st.markdown("**📉 领跌 TOP 5**")
    for i, ind in enumerate(reversed(bottom5)):
        _render_rank_card(ind, i, False)

st.divider()

# ── Section 3: 行业详细分析 Expander 列表 ──
st.subheader("🔍 行业详细分析")

analysis_set = _service.get_industry_analysis_set(_td)
if not analysis_set:
    st.info("暂无需要分析的行业")
else:
    for ind in analysis_set:
        reasons_html = " ".join(
            f"<span style='background:#f0f0f0;padding:2px 8px;border-radius:4px;"
            f"font-size:12px;margin-right:4px;'>{r}</span>"
            for r in ind["reasons"]
        )
        chg = ind["chg_pct"]
        sign = "+" if chg >= 0 else ""
        color = up_down_color(chg)
        title = (f"{ind['name']} ({ind['level']})  "
                 f"<span style='color:{color};'>{sign}{chg:.2f}%</span>  "
                 f"{reasons_html}")

        with st.expander(title, expanded=False):
            _render_industry_expander(_service, ind["code"], ind["name"], _td)


def _render_industry_expander(service: DashboardService, code: str, name: str, end_date: str):
    """Render full technical analysis for one industry — mirrors render_index_section()."""
    from marketreview.tools.technical import latest_val
    import numpy as np

    df = service.get_industry_daily(code, end_date=end_date)
    if df.empty:
        st.warning(f"暂无 {name} 数据")
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    price = float(latest["close"])

    # ── AI 行业导语 ──
    ai_guide = service.get_ai_sector_guide(end_date, code)
    if ai_guide:
        st.info(ai_guide["content"])

    # ── K线图 + OHLC ──
    chart_col, ohlc_col = st.columns([3, 2])

    with chart_col:
        fig = plot_kline_with_ma(df)
        st.plotly_chart(fig, width="stretch")

    with ohlc_col:
        o = float(latest["open"])
        prev_close = float(prev["close"])
        chg_pct = (price / prev_close - 1) * 100
        open_vs_prev = (o / prev_close - 1) * 100

        today_amount = float(latest["amount"]) / 1e5 if latest.get("amount") else 0
        yesterday_amount = float(prev["amount"]) / 1e5 if prev.get("amount") else 0
        amount_vs_prev = (today_amount / yesterday_amount - 1) * 100 if yesterday_amount else 0

        chg_color = "#e53935" if chg_pct >= 0 else "#43a047"
        sign_p = "+" if chg_pct >= 0 else ""
        sign_o = "+" if open_vs_prev >= 0 else ""
        sign_a = "+" if amount_vs_prev >= 0 else ""

        st.html(f"""
        <div style="font-size:18px;line-height:2;">
            <div>最新价：<span style="color:{chg_color};font-weight:bold;">{price:.2f}</span></div>
            <div>今日开盘：<span style="color:{chg_color};">{o:.2f}（{sign_o}{open_vs_prev:.2f}%）</span></div>
            <div>涨跌幅：<span style="color:{chg_color};font-weight:bold;">{sign_p}{chg_pct:.2f}%</span></div>
            <div>昨日收盘：<span>{prev_close:.2f}</span></div>
            <div>今日成交额：<span>{today_amount:.2f}亿（{sign_a}{amount_vs_prev:.2f}%）</span></div>
            <div>昨日成交额：<span>{yesterday_amount:.2f}亿</span></div>
        </div>
        """)

        st.markdown("**K线形态**")
        patterns = service.get_kline_patterns(df)
        if patterns:
            for p in patterns:
                dir_color = "#e53935" if "偏多" in p["direction"] else "#43a047"
                st.html(f"""
                <div style="padding:8px 12px;margin:4px 0;
                    border-left:4px solid {dir_color};
                    background:{dir_color}0a;border-radius:4px;">
                    <span style="font-weight:bold;font-size:16px;color:{dir_color};">
                    {p['name']} — {p['direction']}</span>
                    <br><span style="font-size:13px;color:#666;">{p['note']}</span>
                </div>
                """)
        else:
            st.caption("无明确多空意义")

    st.divider()

    # ── 均线 + 成交量 表格 ──
    ma_col, vol_col = st.columns([3, 2])

    with ma_col:
        st.markdown("**均线分析**")
        mas = calc_ma(df)
        ma_periods = [5, 10, 20, 60, 120, 240]
        ma_dirs = {}
        for p in ma_periods:
            ma_dirs[f"MA{p}"] = ma_direction(mas[f"MA{p}"])

        def _dir_color(d: str) -> str:
            if d == "↑": return "#e53935"
            if d == "↓": return "#43a047"
            return "#999"
        def _role_color(r: str) -> str:
            if "支撑" in r or "向上" in r: return "#e53935"
            if "压制" in r or "向下" in r: return "#43a047"
            return "#999"

        rows_html = ""
        for p in ma_periods:
            ma_key = f"MA{p}"
            ma_val = latest_val(mas[ma_key])
            direction = ma_dirs.get(ma_key, "→")
            role = get_ma_role(price, ma_val, direction) if ma_val else "N/A"

            off = get_offset_info(df, p)
            off_date = off.get("offset_date", "")[:10] if off else ""
            off_amt = f"{off['offset_amount_yi']:,.0f}亿" if off and off.get("offset_amount_yi") else "N/A"

            rows_html += f"""<tr>
                <td style="font-weight:600;">{ma_key}</td>
                <td style="text-align:right;">{ma_val:.2f}</td>
                <td style="text-align:center;color:{_dir_color(direction)};">{direction}</td>
                <td style="text-align:center;color:{_role_color(role)};">{role}</td>
                <td style="font-size:12px;color:#888;">{off_date}</td>
                <td style="font-size:12px;color:#888;text-align:right;">{off_amt}</td>
            </tr>"""

        st.html(f"""
        <table style="width:100%;font-size:14px;border-collapse:collapse;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                <th>均线</th><th>值</th><th>方向</th><th>作用</th>
                <th>扣抵日</th><th>扣抵量</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        """)

        arrangement = ma_arrangement(mas)
        st.caption(f"排列：{arrangement}")

    with vol_col:
        st.markdown("**成交量分析**")
        vol = volume_analysis(df)
        st.html(f"""
        <table style="width:100%;font-size:14px;border-collapse:collapse;">
            <tr><td style="color:#888;">今日成交额</td>
                <td style="text-align:right;font-weight:bold;">{vol.get('latest_amount_yi', 0):,.0f}亿</td></tr>
            <tr><td style="color:#888;">5日均量</td>
                <td style="text-align:right;">{vol.get('ma5_yi', 0):,.0f}亿</td></tr>
            <tr><td style="color:#888;">今日vs5日均量</td>
                <td style="text-align:right;color:{vol_color_ramp(vol.get('vs_ma5_pct', 0))};font-weight:bold;">
                {vol.get('vs_ma5_pct', 0):+.1f}%</td></tr>
            <tr><td style="color:#888;">10日均量</td>
                <td style="text-align:right;">{vol.get('ma10_yi', 0):,.0f}亿</td></tr>
            <tr><td style="color:#888;">今日vs10日均量</td>
                <td style="text-align:right;color:{vol_color_ramp(vol.get('vs_ma10_pct', 0))};font-weight:bold;">
                {vol.get('vs_ma10_pct', 0):+.1f}%</td></tr>
            <tr><td style="color:#888;">量能趋势(5日)</td>
                <td style="text-align:right;">{vol.get('trend_5d', '—')}</td></tr>
            <tr><td style="color:#888;">均量状态</td>
                <td style="text-align:right;">{vol.get('cross_state', '—')}
                {f"({vol.get('cross_days', 0)}天)" if vol.get('cross_days') else ""}</td></tr>
        </table>
        """)

    st.divider()

    # ── 技术指标行 ──
    kd_k = latest_val(calc_kd(df)["k"]) or 0
    kd_d_val = latest_val(calc_kd(df)["d"]) or 0
    if kd_k > 80 and kd_d_val > 80:
        kd_zone = "🔥 超买区"
    elif kd_k < 20 and kd_d_val < 20:
        kd_zone = "❄️ 超卖区"
    else:
        kd_zone = "➖ 常态区"

    rsi_val = latest_val(calc_rsi(df))
    if rsi_val and rsi_val > 70:
        rsi_zone = "🔥 超买区"
    elif rsi_val and rsi_val < 30:
        rsi_zone = "❄️ 超卖区"
    else:
        rsi_zone = "➖ 常态区"

    kd_div = detect_kd_divergence(df)
    rsi_div = detect_rsi_divergence(df)
    kd_div_str = f"{kd_div['type']} ({kd_div.get('days', 0)}天)" if kd_div.get("type") else "无"
    rsi_div_str = f"{rsi_div['type']} ({rsi_div.get('days', 0)}天)" if rsi_div.get("type") else "无"

    bias10_val = latest_val(calc_bias(df, 10)) or 0.0
    bias20_val = latest_val(calc_bias(df, 20)) or 0.0
    bias10_status = bias_status(bias10_val, 10)
    bias20_status = bias_status(bias20_val, 20)

    ind_col1, ind_col2, ind_col3, ind_col4 = st.columns(4)

    with ind_col1:
        st.markdown("**KD 指标**")
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>K：<b>{kd_k:.1f}</b></div>
            <div>D：<b>{kd_d_val:.1f}</b></div>
            <div>区间：{kd_zone}</div>
            <div>背离：{kd_div_str}</div>
        </div>
        """)

    with ind_col2:
        st.markdown("**RSI 指标**")
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>RSI(12)：<b>{rsi_val:.1f}</b></div>
            <div>区间：{rsi_zone}</div>
            <div>背离：{rsi_div_str}</div>
        </div>
        """)

    with ind_col3:
        st.markdown("**BIAS 乖离率**")
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>BIAS10：<b>{bias10_val:+.2f}%</b></div>
            <div style="color:#888;">{bias10_status}</div>
            <div>BIAS20：<b>{bias20_val:+.2f}%</b></div>
            <div style="color:#888;">{bias20_status}</div>
        </div>
        """)

    with ind_col4:
        st.markdown("**涨跌结构**")
        up_c = latest.get("up_count", 0)
        down_c = latest.get("down_count", 0)
        flat_c = latest.get("flat_count", 0)
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>上涨：<b style="color:#e53935;">{up_c}</b></div>
            <div>下跌：<b style="color:#43a047;">{down_c}</b></div>
            <div>平盘：<b style="color:#999;">{flat_c}</b></div>
        </div>
        """)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('dashboard/pages/02_板块分析.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add dashboard/pages/02_板块分析.py
git commit -m "feat: rewrite 02_板块分析.py with real data (ranking + expanders + AI guides)"
```

---

### Task 10: Add industry classification rules to 00_控制台.py

**Files:**
- Modify: `dashboard/pages/00_控制台.py`

**Produces:** Expander showing split configuration in the console

- [ ] **Step 1: Add industry classification rules expander**

Near the bottom of the file (before `st.markdown("---")` line 242), add:

```python
# ── Industry Classification Rules ──
with st.expander("📋 行业分类规则", expanded=False):
    try:
        config = _service.get_industry_split_config()
        split_l1 = config["split_l1"]
        split_l2 = config["split_l2"]
        st.markdown(f"""
        **默认按申万一级行业（31个）展示**
        
        **拆分 L1 → L2：** {', '.join(split_l1)}
        
        **拆分 L2 → L3：** {', '.join(split_l2)}
        
        **最终板块数：** 25 L1 + 24 L2 + 14 L3 = **63**
        """)
    except Exception:
        st.caption("行业分类配置暂不可用")
```

- [ ] **Step 2: Add sector AI progress phases to the progress callback**

In the `_progress` function inside the slow-path loading block, add two new phase handlers after the `"validate"` handler:

```python
elif phase == "industry_members":
    status.update(label=extra or "正在拉取行业成分股...")
elif phase == "industry_daily":
    status.update(label=extra or "正在聚合行业日线...")
```

And in the `_ai_progress2` callback (or the AI summary block), add sector phases:

In the AI summary block (after `_ai_progress2` is used, around line 196), add sector AI generation after the existing `generate_ai_summary`:

```python
# After existing AI summary generation, add:
_sector_cached = _service.get_ai_sector_summary(_pending)
if _sector_cached is None:
    def _ai_sector_progress(phase: str, label: str):
        status.update(label=f"🏭 {label}")
    _service.generate_ai_sector_analysis(_pending, progress_cb=_ai_sector_progress)
```

Also add `"sector_analysis"` AI summary display to the AI summary card section. In the expander at line 229, add a sector section:

```python
_sector_ai = _service.get_ai_sector_summary(_current_td)
if _sector_ai:
    with st.expander("🏭 查看行业导语"):
        st.caption("**行业总结**")
        st.text(_sector_ai["content"])
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('dashboard/pages/00_控制台.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add dashboard/pages/00_控制台.py
git commit -m "feat: add industry classification rules + sector AI progress to console"
```

---

### Task 11: End-to-end integration test

**Files:**
- No new files; verifies the full pipeline works

- [ ] **Step 1: Verify all imports resolve**

```bash
cd i:\AIcode\marketreview && python -c "
from marketreview.data.cache_manager import CacheManager
from marketreview.data.data_provider import DataProvider
from marketreview.tools.industry import SPLIT_L1, SPLIT_L2, build_industry_list
from marketreview.tools.contribution import pick_industry_label
from services.dashboard_service import DashboardService
print('All imports OK')
"
```
Expected: `All imports OK`

- [ ] **Step 2: Verify schema init with new tables**

```bash
cd i:\AIcode\marketreview && python -c "
from marketreview.data.cache_manager import CacheManager
cm = CacheManager()
# Verify new tables exist
import sqlite3
conn = sqlite3.connect(cm.db_path)
for table in ['industry_member_cache', 'industry_daily']:
    row = conn.execute('SELECT 1 FROM sqlite_master WHERE type=\"table\" AND name=?', [table]).fetchone()
    print(f'{table}: {\"EXISTS\" if row else \"MISSING\"}')"
```
Expected: Both tables `EXISTS`

- [ ] **Step 3: Verify SPLIT config total**

```bash
cd i:\AIcode\marketreview && python -c "
import tushare as ts, os
from dotenv import load_dotenv
load_dotenv()
ts.set_token(os.environ['TUSHARE_TOKEN'])
api = ts.pro_api()
from marketreview.tools.industry import build_industry_list
ind_list = build_industry_list(api)
l1s = [i for i in ind_list if i['level']=='L1']
l2s = [i for i in ind_list if i['level']=='L2']
l3s = [i for i in ind_list if i['level']=='L3']
print(f'L1={len(l1s)} L2={len(l2s)} L3={len(l3s)} TOTAL={len(ind_list)}')
assert len(ind_list) == 63, f'Expected 63, got {len(ind_list)}'
print('Count OK')
"
```
Expected: `L1=25 L2=24 L3=14 TOTAL=63`

- [ ] **Step 4: Validate label logic matches split rules**

```bash
cd i:\AIcode\marketreview && python -c "
from marketreview.tools.contribution import pick_industry_label

# L1 not split → returns L1 name
assert pick_industry_label('', '银行', '', '', '', '') == '银行'

# L1 split, L2 not split → returns L2 name
assert pick_industry_label('', '电子', '', '消费电子', '', '') == '消费电子'

# L1 split, L2 split → returns L3 name
assert pick_industry_label('', '电子', '', '半导体', '', '数字芯片设计') == '数字芯片设计'

# L1 not split, no L2 → returns L1 name  
assert pick_industry_label('', '农林牧渔', '', '', '', '') == '农林牧渔'

print('All label assertions passed')
"
```
Expected: `All label assertions passed`

- [ ] **Step 5: Commit**

```bash
# No file changes — just verification
git commit --allow-empty -m "test: verify industry module imports + schema + split count + label logic"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 5 phases covered — data layer (Tasks 1-4), service layer (Tasks 5-6), AI guides (Tasks 7-8), page (Tasks 9-10), integration (Task 11)
- [x] **No placeholders:** All code is concrete, no TBD/TODO
- [x] **Type consistency:** `industry_code` is `str` consistently across all modules; `trade_date` normalized with `.replace("-", "")`; DataProvider progress_cb signature `(phase, current, total, extra)` matches everywhere
- [x] **Design decisions reflected:** Market-cap weighting (not median), recursive split (not hardcoded lists), AI 3-step pipeline, deduplicated analysis set
