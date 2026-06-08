# 指数权重贡献 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Dashboard 指数分析区新增"权重贡献"区块，展示当日对指数涨跌贡献最大的 Top-5 权重股。

**Architecture:** 数据层新增两张表（`index_weight_cache`、`stock_industry_cache`）+ DataProvider 三个新方法；业务层重写 `contribution.py` 的 `build_index_contribution()`；DashboardService 透传；app.py 在技术指标下方渲染左右并排领涨/领跌表格。

**Tech Stack:** Tushare Pro API (`index_weight`、`index_member_all`、`daily`)、SQLite、Streamlit

**Spec:** `docs/superpowers/specs/2026-06-08-index-contribution-design.md`

---

### File Structure

| 文件 | 变更 | 职责 |
|---|---|---|
| `src/marketreview/data/schema.sql` | 修改 | 新增 `index_weight_cache`、`stock_industry_cache` DDL |
| `src/marketreview/data/cache_manager.py` | 修改 | 新增两表的 CRUD 方法 |
| `src/marketreview/data/data_provider.py` | 修改 | 新增 `get_index_weights`、`get_daily_batch`、`get_stock_industries` |
| `src/marketreview/tools/contribution.py` | 重写 | `build_index_contribution()` 代替硬编码 |
| `dashboard/services/dashboard_service.py` | 修改 | 新增 `get_index_contribution()` |
| `dashboard/app.py` | 修改 | `render_index_section()` 中加贡献表格 |
| `src/marketreview/tools/market_tools.py` | 修改 | `GetIndexContributionTool` 适配新接口 |

---

### Task 1: Database Schema — 两张新表

**Files:**
- Modify: `src/marketreview/data/schema.sql`

- [ ] **Step 1: 在 schema.sql 末尾追加两张新表 DDL**

```sql
CREATE TABLE IF NOT EXISTS index_weight_cache (
    index_code   TEXT    NOT NULL,
    con_code     TEXT    NOT NULL,
    weight_date  TEXT    NOT NULL,
    weight       REAL    NOT NULL,
    PRIMARY KEY (index_code, con_code, weight_date)
);

CREATE INDEX IF NOT EXISTS idx_iwc_code_date
    ON index_weight_cache(index_code, weight_date DESC);

CREATE TABLE IF NOT EXISTS stock_industry_cache (
    ts_code   TEXT PRIMARY KEY,
    name      TEXT,
    l1_code   TEXT,
    l1_name   TEXT,
    l2_code   TEXT,
    l2_name   TEXT,
    l3_name   TEXT
);
```

- [ ] **Step 2: 验证 DDL 可执行**

```bash
python -c "
import sqlite3, os
os.makedirs('data', exist_ok=True)
conn = sqlite3.connect('data/marketreview.db')
with open('src/marketreview/data/schema.sql', 'r', encoding='utf-8') as f:
    conn.executescript(f.read())
conn.commit()
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()
print('Tables:', [t[0] for t in tables])
conn.close()
"
```

Expected: 输出包含 `index_weight_cache`、`stock_industry_cache`

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/data/schema.sql
git commit -m "feat(db): add index_weight_cache and stock_industry_cache tables"
```

---

### Task 2: CacheManager — 新表 CRUD 方法

**Files:**
- Modify: `src/marketreview/data/cache_manager.py`

- [ ] **Step 1: 在 CacheManager 类末尾（`code_has_data` 方法之后）追加以下方法**

```python
    # ------- index_weight_cache -------

    def upsert_index_weights(self, index_code: str, weight_date: str,
                              rows: list[dict]):
        """
        Batch upsert index weight rows.
        Each row: {con_code, weight}
        weight_date is the official publication date (from API trade_date field).
        """
        sql = """
            INSERT OR REPLACE INTO index_weight_cache
                (index_code, con_code, weight_date, weight)
            VALUES (?, ?, ?, ?)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, [
                (index_code, r["con_code"], weight_date, r["weight"])
                for r in rows
            ])
            conn.commit()

    def get_latest_weight_date(self, index_code: str,
                                trade_date: str) -> str | None:
        """
        Return the latest weight_date <= trade_date for an index.
        Returns None if no cache exists.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT MAX(weight_date) as d FROM index_weight_cache
                   WHERE index_code = ? AND weight_date <= ?""",
                [index_code, trade_date],
            ).fetchone()
        return row["d"] if row and row["d"] else None

    def get_index_weights(self, index_code: str,
                           weight_date: str) -> list[dict]:
        """
        Return all constituent weights for a given index_code + weight_date.
        Returns list of {con_code, weight}.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT con_code, weight FROM index_weight_cache
                   WHERE index_code = ? AND weight_date = ?
                   ORDER BY weight DESC""",
                [index_code, weight_date],
            ).fetchall()
        return [dict(r) for r in rows]

    # ------- stock_industry_cache -------

    def get_stock_industries(self, codes: list[str]) -> dict[str, dict]:
        """
        Return industry info for given ts_codes.
        Returns {ts_code: {name, l1_code, l1_name, l2_code, l2_name, l3_name}}.
        Only returns rows that exist in cache — caller must handle misses.
        """
        if not codes:
            return {}
        placeholders = ",".join(["?" for _ in codes])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT ts_code, name, l1_code, l1_name, l2_code, l2_name, l3_name
                    FROM stock_industry_cache
                    WHERE ts_code IN ({placeholders})""",
                codes,
            ).fetchall()
        return {r["ts_code"]: dict(r) for r in rows}

    def upsert_stock_industries(self, rows: list[dict]):
        """
        Batch upsert industry rows.
        Each row: {ts_code, name, l1_code, l1_name, l2_code, l2_name, l3_name}.
        """
        sql = """
            INSERT OR REPLACE INTO stock_industry_cache
                (ts_code, name, l1_code, l1_name, l2_code, l2_name, l3_name)
            VALUES (:ts_code, :name, :l1_code, :l1_name, :l2_code, :l2_name, :l3_name)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()
```

- [ ] **Step 2: 验证方法存在且语法正确**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from marketreview.data.cache_manager import CacheManager
cm = CacheManager()
# Verify new methods exist
for m in ['upsert_index_weights', 'get_latest_weight_date', 'get_index_weights',
          'get_stock_industries', 'upsert_stock_industries']:
    assert hasattr(cm, m), f'Missing method: {m}'
    print(f'{m}: OK')
print('All methods exist')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/data/cache_manager.py
git commit -m "feat(cache): add CRUD methods for index_weight and stock_industry tables"
```

---

### Task 3: DataProvider — get_index_weights()

**Files:**
- Modify: `src/marketreview/data/data_provider.py`（在 `get_market_breadth` 方法之后插入）

- [ ] **Step 1: 追加 `get_index_weights` 方法**

在 `get_market_breadth` 方法结束后（第 139 行 `return None` 之后，`# ------- internal -------` 区隔线之前）插入：

```python
    def get_index_weights(self, index_code: str,
                           trade_date: str) -> list[dict] | None:
        """
        Return all constituent weights for the given index as of trade_date.

        Uses the latest official weight publication whose weight_date
        is <= trade_date.  Index weights are published monthly (month-end)
        and take effect the following month.  The method checks cache first;
        if the cached weight_date is from before the prior month-end, it
        re-fetches from tushare to pick up any new publication.

        Returns list of {con_code, weight} sorted by weight DESC, or None.
        """
        trade_date = trade_date.replace("-", "")
        td = datetime.strptime(trade_date, "%Y%m%d")

        # Expected weight date: published at the end of the month *before*
        # the month containing trade_date.
        # e.g. trade_date="20260608" → prior_month_end = "20260531"
        #      the cached weight_date should be >= "202605"
        prior_month = (td.replace(day=1) - timedelta(days=1))
        expected_ym = prior_month.strftime("%Y%m")  # "202605"

        # Check cache
        cached_wd = self.cache.get_latest_weight_date(index_code, trade_date)

        if cached_wd and cached_wd[:6] >= expected_ym:
            # Cache is current enough
            return self.cache.get_index_weights(index_code, cached_wd)

        # Fetch from Tushare
        import time
        try:
            df = self._api.index_weight(
                index_code=self._normalize_code(index_code),
                trade_date=trade_date,
            )
        except Exception as e:
            print(f"[DataProvider] index_weight failed for {index_code} @ {trade_date}: {e}")
            return None

        if df is None or df.empty:
            return None

        # Normalize: the API returns 'trade_date' — rename to weight_date for storage
        weight_date = str(df["trade_date"].iloc[0])

        # If cache already has this exact weight_date, no need to re-insert
        if cached_wd == weight_date:
            return self.cache.get_index_weights(index_code, weight_date)

        rows = []
        for _, r in df.iterrows():
            rows.append({
                "con_code": r["con_code"],
                "weight": float(r["weight"]),
            })

        self.cache.upsert_index_weights(index_code, weight_date, rows)
        return self.cache.get_index_weights(index_code, weight_date)
```

- [ ] **Step 2: 验证方法语法**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from marketreview.data.cache_manager import CacheManager
from marketreview.data.data_provider import DataProvider
dp = DataProvider(tushare_token='dummy', cache=CacheManager())
assert hasattr(dp, 'get_index_weights')
print('get_index_weights: OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/data/data_provider.py
git commit -m "feat(data): add DataProvider.get_index_weights() using index_weight API"
```

---

### Task 4: DataProvider — get_daily_batch()

**Files:**
- Modify: `src/marketreview/data/data_provider.py`（在 `get_index_weights` 之后插入）

- [ ] **Step 1: 追加 `get_daily_batch` 方法**

```python
    def get_daily_batch(self, codes: list[str],
                         end_date: str) -> dict[str, dict]:
        """
        Return close/pre_close/change_pct for a batch of stocks on a single day.

        Checks tushare_cache first for each code.  Missing codes are fetched
        from tushare via a single api.daily() call (one round-trip for all
        stocks on that day).  Fetched data is upserted into the shared cache
        so future calls benefit.

        Returns {ts_code: {close, pre_close, change_pct}} for all codes that
        have data.  Stocks with no data on end_date are omitted.
        """
        end_date = end_date.replace("-", "")
        result = {}

        # ---- check cache for each code ----
        missing = []
        for code in codes:
            rows = self.cache.get_daily(code, start=end_date, end=end_date, limit=1)
            if rows:
                r = rows[0]
                close = float(r["close"])
                pre = float(r.get("pre_close", close))
                chg = round((close / pre - 1) * 100, 2) if pre else 0.0
                result[code] = {"close": close, "pre_close": pre, "change_pct": chg}
            else:
                missing.append(code)

        if not missing:
            return result

        # ---- fetch missing from Tushare ----
        try:
            df = self._api.daily(
                trade_date=end_date,
                fields="ts_code,close,pre_close,open,high,low,vol,amount",
            )
            if df is None or df.empty:
                return result

            # Normalize and upsert to cache for ALL stocks (not just missing)
            normalized = self._normalize_df(df)
            if normalized:
                self.cache.upsert_daily("BATCH", normalized)  # ← see note below
        except Exception as e:
            print(f"[DataProvider] get_daily_batch fetch failed for {end_date}: {e}")
            return result

        # ---- re-check cache for previously-missing codes ----
        for code in missing:
            rows = self.cache.get_daily(code, start=end_date, end=end_date, limit=1)
            if rows:
                r = rows[0]
                close = float(r["close"])
                pre = float(r.get("pre_close", close))
                chg = round((close / pre - 1) * 100, 2) if pre else 0.0
                result[code] = {"close": close, "pre_close": pre, "change_pct": chg}

        return result
```

> **IMPORTANT**: `self.cache.upsert_daily("BATCH", normalized)` — the current `upsert_daily` method expects a `code` parameter. Since we fetched the whole market, the normalized rows already contain `code` field (from `ts_code` → `code` renaming? No, `_normalize_df` renames `trade_date`→`date` but does NOT rename `ts_code`→`code`). We need to handle this: either normalize `ts_code`→`code` in the batch rows, or write a dedicated `upsert_daily_batch` method.

**修正方案：** 在 `_normalize_df` 调用之前，将 `ts_code` 列重命名为 `code`。或者用一个新的内部方法：

```python
# Inside get_daily_batch, after fetching df:
df = df.rename(columns={"ts_code": "code"})
normalized = self._normalize_df(df)
if normalized:
    for row in normalized:
        self.cache.upsert_daily(row["code"], [row])  # individual upsert per stock
```

Or better — just write them all at once. Since `upsert_daily` takes a code + list of rows and iterates:

```python
if normalized:
    # Group rows by code (each code has 1 row for a single day)
    for row in normalized:
        code = row.get("code", "")
        if code:
            self.cache.upsert_daily(code, [row])
```

This is correct but a bit slow for 5500 stocks. A bulk upsert approach:

```python
# Bulk upsert directly using CacheManager's internal connection
if normalized:
    # Ensure 'code' column exists (renamed from ts_code)
    self.cache.upsert_daily_bulk(normalized)
```

Let me add a `upsert_daily_bulk` method to CacheManager.

- [ ] **Step 2: 在 CacheManager 中追加 `upsert_daily_bulk` 方法**

In `cache_manager.py`, after the existing `upsert_daily` method:

```python
    def upsert_daily_bulk(self, rows: list[dict]):
        """
        Bulk upsert daily K-line rows from a full-market fetch.
        Each row: {code, date, open, high, low, close, vol, amount, adj_factor}.
        Uses executemany for efficiency with large datasets (~5000+ rows).
        """
        sql = """
            INSERT OR REPLACE INTO tushare_cache
                (code, date, open, high, low, close, vol, amount, adj_factor)
            VALUES (:code, :date, :open, :high, :low, :close, :vol, :amount, :adj_factor)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()
```

- [ ] **Step 3: 修正 `get_daily_batch` 使用批量 upsert**

```python
    def get_daily_batch(self, codes: list[str],
                         end_date: str) -> dict[str, dict]:
        end_date = end_date.replace("-", "")
        result = {}

        # ---- check cache for each code ----
        missing = []
        for code in codes:
            rows = self.cache.get_daily(code, start=end_date, end=end_date, limit=1)
            if rows:
                r = rows[0]
                close = float(r["close"])
                pre = float(r.get("pre_close", close))
                chg = round((close / pre - 1) * 100, 2) if pre else 0.0
                result[code] = {"close": close, "pre_close": pre, "change_pct": chg}
            else:
                missing.append(code)

        if not missing:
            return result

        # ---- fetch missing from Tushare (one call for all stocks on end_date) ----
        try:
            df = self._api.daily(
                trade_date=end_date,
                fields="ts_code,close,pre_close,open,high,low,vol,amount",
            )
            if df is not None and not df.empty:
                # Normalize: ts_code → code, trade_date → date
                df = df.rename(columns={"ts_code": "code", "trade_date": "date"})
                df["date"] = df["date"].astype(str)
                if "adj_factor" not in df.columns:
                    df["adj_factor"] = 1.0
                cols = ["code", "date", "open", "high", "low", "close",
                        "vol", "amount", "adj_factor"]
                df = df[[c for c in cols if c in df.columns]]
                self.cache.upsert_daily_bulk(df.to_dict(orient="records"))
        except Exception as e:
            print(f"[DataProvider] get_daily_batch fetch failed for {end_date}: {e}")
            return result

        # ---- re-check cache for previously-missing codes ----
        for code in missing:
            rows = self.cache.get_daily(code, start=end_date, end=end_date, limit=1)
            if rows:
                r = rows[0]
                close = float(r["close"])
                pre = float(r.get("pre_close", close))
                chg = round((close / pre - 1) * 100, 2) if pre else 0.0
                result[code] = {"close": close, "pre_close": pre, "change_pct": chg}

        return result
```

- [ ] **Step 4: 验证方法语法**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from marketreview.data.cache_manager import CacheManager
from marketreview.data.data_provider import DataProvider
dp = DataProvider(tushare_token='dummy', cache=CacheManager())
assert hasattr(dp, 'get_daily_batch')
assert hasattr(dp.cache, 'upsert_daily_bulk')
print('get_daily_batch + upsert_daily_bulk: OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/data_provider.py src/marketreview/data/cache_manager.py
git commit -m "feat(data): add DataProvider.get_daily_batch() with bulk upsert"
```

---

### Task 5: DataProvider — get_stock_industries()

**Files:**
- Modify: `src/marketreview/data/data_provider.py`（在 `get_daily_batch` 之后插入）

- [ ] **Step 1: 追加 `get_stock_industries` 方法**

```python
    def get_stock_industries(self, codes: list[str]) -> dict[str, dict]:
        """
        Return Shenwan 3-level industry classification for given ts_codes.

        Checks stock_industry_cache first.  Missing codes are fetched from
        tushare index_member_all (one API call per missing code) and cached.

        Returns {ts_code: {name, l1_code, l1_name, l2_code, l2_name, l3_name}}.
        Codes without industry data are omitted from the result.
        """
        if not codes:
            return {}

        # Check cache
        cached = self.cache.get_stock_industries(codes)
        missing = [c for c in codes if c not in cached]

        if not missing:
            return cached

        # Fetch missing codes from Tushare
        new_rows = []
        for code in missing:
            try:
                df = self._api.index_member_all(ts_code=code, is_new="Y")
                if df is not None and not df.empty:
                    r = df.iloc[0]
                    row = {
                        "ts_code": r["ts_code"],
                        "name": r.get("name", ""),
                        "l1_code": r.get("l1_code", ""),
                        "l1_name": r.get("l1_name", ""),
                        "l2_code": r.get("l2_code", ""),
                        "l2_name": r.get("l2_name", ""),
                        "l3_name": r.get("l3_name", ""),
                    }
                    new_rows.append(row)
                    cached[code] = row
            except Exception as e:
                print(f"[DataProvider] index_member_all failed for {code}: {e}")

        if new_rows:
            self.cache.upsert_stock_industries(new_rows)

        return cached
```

- [ ] **Step 2: 验证方法语法**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from marketreview.data.cache_manager import CacheManager
from marketreview.data.data_provider import DataProvider
dp = DataProvider(tushare_token='dummy', cache=CacheManager())
assert hasattr(dp, 'get_stock_industries')
print('get_stock_industries: OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/data/data_provider.py
git commit -m "feat(data): add DataProvider.get_stock_industries() using index_member_all"
```

---

### Task 6: contribution.py — 重写 build_index_contribution()

**Files:**
- Modify: `src/marketreview/tools/contribution.py`（全文替换）

- [ ] **Step 1: 用以下内容替换 `contribution.py`**

```python
"""
Index weight contribution analysis.

Computes how much each constituent stock contributed to the index's daily
point change.  Used by Dashboard (display) and Agent 1 (LLM analysis).

Contribution formula (derivation):
  Let W_i = stock i's weight in the index (percentage, e.g. 3.12)
  Let R_i = stock i's daily return (percentage, e.g. +3.30)
  Let C   = index closing price

  Index daily return (%) ≈ Σ (W_i / 100) × (R_i / 100)   ... in decimal
                          = Σ W_i × R_i / 10000           ... in percentage

  Contribution of stock i in points:
    contrib_i = (W_i / 100) × (R_i / 100) × C
              = W_i × R_i × C / 10000  ← used in the code below
"""

from datetime import datetime, timedelta
from ..data.data_provider import DataProvider


# TODO: L1 industries where the L1 name is specific enough — use L1 directly.
# For all other industries, the more granular L2 name is shown.
# Add/remove codes here as needed based on real-world observation.
L1_OVERRIDE_L1 = {"801780.SI"}  # 银行 → "银行" is sufficient


def pick_industry_label(l1_code: str, l1_name: str, l2_name: str) -> str:
    """Choose the display label for a stock's industry (L1 or L2)."""
    if l1_code in L1_OVERRIDE_L1:
        return l1_name
    return l2_name


def build_index_contribution(
    index_code: str,
    trade_date: str,
    dp: DataProvider,
    top_n: int = 5,
) -> dict | None:
    """
    Build contribution analysis for an index on a given trading date.

    Args:
        index_code:  '000001.SH' or '399006.SZ'
        trade_date:  YYYYMMDD or YYYY-MM-DD
        dp:          DataProvider instance (single entry point for all data)
        top_n:       number of top gainers/losers to return (default 5)

    Returns:
        {
          "index": {close, pre_close, chg_pts, chg_pct},
          "gainers": [{code, name, industry, weight, chg_pct, contrib}],
          "losers":  [{code, name, industry, weight, chg_pct, contrib}],
        }
        or None if index/weight data is unavailable.
    """
    trade_date = trade_date.replace("-", "")

    # 1. Index OHLC
    idx_rows = dp.get_daily(index_code, end_date=trade_date, lookback_days=2)
    if not idx_rows or len(idx_rows) < 2:
        return None
    latest = idx_rows[0]
    prev = idx_rows[1]
    close = float(latest["close"])
    pre_close = float(prev["close"])
    chg_pts = round(close - pre_close, 2)
    chg_pct = round((close / pre_close - 1) * 100, 2)

    # 2. Constituent weights
    weights = dp.get_index_weights(index_code, trade_date)
    if not weights:
        return None

    # 3. Stock prices for all constituents
    all_codes = [w["con_code"] for w in weights]
    prices = dp.get_daily_batch(all_codes, trade_date)

    # 4. Compute contribution for each constituent
    items = []
    for w in weights:
        code = w["con_code"]
        p = prices.get(code)
        if p is None:
            continue
        chg = p["change_pct"]
        # contrib = weight% × chg% × index_close / 10000
        contrib = round(w["weight"] * chg * close / 10000, 2)
        items.append({
            "code": code,
            "weight": round(w["weight"], 2),
            "chg_pct": chg,
            "contrib": contrib,
        })

    if not items:
        return None

    # Sort by contribution descending (largest positive = top gainer,
    # largest negative = top loser)
    items.sort(key=lambda x: x["contrib"], reverse=True)

    gainers = items[:top_n]
    losers = items[-top_n:][::-1]  # most negative first

    # 5. Industry labels (only for the displayed 2*top_n stocks)
    display_codes = [g["code"] for g in gainers] + [l["code"] for l in losers]
    industries = dp.get_stock_industries(display_codes)

    def _attach_name_industry(item: dict) -> dict:
        ind = industries.get(item["code"], {})
        l1_code = ind.get("l1_code", "")
        l1_name = ind.get("l1_name", "")
        l2_name = ind.get("l2_name", "")
        return {
            "code": item["code"],
            "name": ind.get("name", item["code"]),
            "industry": pick_industry_label(l1_code, l1_name, l2_name),
            "weight": item["weight"],
            "chg_pct": item["chg_pct"],
            "contrib": item["contrib"],
        }

    return {
        "index": {
            "close": close,
            "pre_close": pre_close,
            "chg_pts": chg_pts,
            "chg_pct": chg_pct,
        },
        "gainers": [_attach_name_industry(g) for g in gainers],
        "losers": [_attach_name_industry(l) for l in losers],
    }
```

- [ ] **Step 2: 删除旧的 `INDEX_WEIGHTS` 和 `compute_index_contribution`（已被新函数替代）**

确认文件只包含：docstring、`L1_OVERRIDE_L1`、`pick_industry_label()`、`build_index_contribution()`。

- [ ] **Step 3: 验证语法**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from marketreview.tools.contribution import (
    L1_OVERRIDE_L1, pick_industry_label, build_index_contribution
)
# Test industry label logic
assert pick_industry_label('801780.SI', '银行', '国有大型银行Ⅱ') == '银行'
assert pick_industry_label('801080.SI', '电子', '半导体') == '半导体'
assert pick_industry_label('801050.SI', '有色金属', '工业金属') == '工业金属'
print('pick_industry_label: OK')
print('All imports OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add src/marketreview/tools/contribution.py
git commit -m "feat(contrib): rewrite build_index_contribution with API-backed weights and industry"
```

---

### Task 7: DashboardService — get_index_contribution()

**Files:**
- Modify: `dashboard/services/dashboard_service.py`（在 `get_market_overview` 方法之后追加）

- [ ] **Step 1: 追加 `get_index_contribution` 方法**

在 `get_market_overview` 方法结束后（第 122 行 `}` 之后）插入：

```python
    # ---- index contribution ----

    def get_index_contribution(
        self, index_code: str, trade_date: str | None = None
    ) -> dict | None:
        """
        Fetch index weight contribution analysis.

        Delegates to build_index_contribution() in contribution.py.
        Returns {index, gainers, losers} or None.
        """
        try:
            # Lazy import to avoid circular dependency at module level
            from marketreview.tools.contribution import build_index_contribution
            return build_index_contribution(index_code, trade_date, self._dp)
        except Exception as e:
            print(f"[DashboardService] get_index_contribution failed: {e}")
            return None
```

- [ ] **Step 2: 验证语法**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
sys.path.insert(0, 'dashboard')
from services.dashboard_service import DashboardService
ds = DashboardService()
assert hasattr(ds, 'get_index_contribution')
print('get_index_contribution: OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat(service): add DashboardService.get_index_contribution()"
```

---

### Task 8: Dashboard UI — 权重贡献表格

**Files:**
- Modify: `dashboard/app.py`

- [ ] **Step 1: 在 import 区域追加 `pick_industry_label` 的引用（可选，实际不直接使用）**

无需新增导入——`build_index_contribution` 已经在 `DashboardService` 内部调用。

- [ ] **Step 2: 在 `render_index_section` 末尾（BIAS Card 的 `st.caption(...)` 之后，函数结尾之前）插入贡献区块**

在 `st.caption("10日乖离 > 10 短线超买...")` 之后、`render_index_section` 函数 `def` 闭合之前（约第 523 行）插入：

```python
    # --- 权重贡献 ---
    st.divider()
    st.markdown("**权重贡献**")
    contrib = service.get_index_contribution(code, end_date)

    if contrib is None:
        st.caption("暂无权重贡献数据")
    else:
        idx = contrib["index"]
        # Summary line
        chg_color = "#e53935" if idx["chg_pts"] >= 0 else "#43a047"
        sign = "+" if idx["chg_pts"] >= 0 else ""
        st.caption(
            f"指数收盘 {idx['close']:.2f} ｜ "
            f"涨跌 {sign}{idx['chg_pts']:.2f} 点 "
            f"({sign}{idx['chg_pct']:.2f}%)"
        )

        left_col, right_col = st.columns(2)

        # --- 领涨 Top 5 ---
        with left_col:
            st.markdown(
                '<span style="color:#e53935;font-size:16px;font-weight:bold;">'
                '🔥 领涨 Top 5</span>',
                unsafe_allow_html=True,
            )
            if contrib["gainers"]:
                rows_html = ""
                for g in contrib["gainers"]:
                    rows_html += f"""<tr>
                        <td style="color:#888;font-size:13px;">{g['code']}</td>
                        <td style="font-weight:600;">{g['name']}</td>
                        <td style="color:#888;">{g['industry']}</td>
                        <td style="text-align:right;">{g['weight']:.2f}</td>
                        <td style="text-align:right;color:#e53935;font-weight:bold;">+{g['chg_pct']:.2f}</td>
                        <td style="text-align:right;color:#e53935;font-weight:bold;">+{g['contrib']:.2f}</td>
                    </tr>"""
                st.html(f"""
                <table style="width:100%;font-size:14px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:12px;">
                        <th style="text-align:left;">代码</th>
                        <th style="text-align:left;">名称</th>
                        <th style="text-align:left;">行业</th>
                        <th style="text-align:right;">权重%</th>
                        <th style="text-align:right;">涨幅%</th>
                        <th style="text-align:right;">贡献</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
                """)
            else:
                st.caption("无数据")

        # --- 领跌 Top 5 ---
        with right_col:
            st.markdown(
                '<span style="color:#43a047;font-size:16px;font-weight:bold;">'
                '❄️ 领跌 Top 5</span>',
                unsafe_allow_html=True,
            )
            if contrib["losers"]:
                rows_html = ""
                for l in contrib["losers"]:
                    rows_html += f"""<tr>
                        <td style="color:#888;font-size:13px;">{l['code']}</td>
                        <td style="font-weight:600;">{l['name']}</td>
                        <td style="color:#888;">{l['industry']}</td>
                        <td style="text-align:right;">{l['weight']:.2f}</td>
                        <td style="text-align:right;color:#43a047;font-weight:bold;">{l['chg_pct']:.2f}</td>
                        <td style="text-align:right;color:#43a047;font-weight:bold;">{l['contrib']:.2f}</td>
                    </tr>"""
                st.html(f"""
                <table style="width:100%;font-size:14px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:12px;">
                        <th style="text-align:left;">代码</th>
                        <th style="text-align:left;">名称</th>
                        <th style="text-align:left;">行业</th>
                        <th style="text-align:right;">权重%</th>
                        <th style="text-align:right;">跌幅%</th>
                        <th style="text-align:right;">贡献</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
                """)
            else:
                st.caption("无数据")
```

> **Note**: 贡献区块插入在 `st.caption("10日乖离 > 10...")` 之后（约第 522 行），`render_index_section` 函数闭包之前。`end_date` 变量已在函数参数中可用。

- [ ] **Step 2: 验证语法**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
sys.path.insert(0, 'dashboard')
# Just check the file parses correctly
with open('dashboard/app.py', 'r', encoding='utf-8') as f:
    compile(f.read(), 'dashboard/app.py', 'exec')
print('app.py syntax: OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/app.py
git commit -m "feat(ui): add index contribution tables (top 5 gainers/losers) below technical indicators"
```

---

### Task 9: market_tools.py — 适配新接口

**Files:**
- Modify: `src/marketreview/tools/market_tools.py`

- [ ] **Step 1: 更新 `GetIndexContributionTool._run` 使用新的 `build_index_contribution`**

当前代码（第 90-113 行）：
```python
    def _run(self, index_code: str) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)

        weights = INDEX_WEIGHTS.get(index_code, {}).get("weight_codes", [])
        if not weights:
            return json.dumps({"error": f"无 {index_code} 权重数据"}, ensure_ascii=False)

        items = []
        for code, name, weight in weights:
            rows = _data_provider.get_daily(code, lookback_days=2)
            if len(rows) >= 2:
                prev_close = rows[1]["close"]
                latest_close = rows[0]["close"]
                change_pct = round((latest_close / prev_close - 1) * 100, 2)
            else:
                change_pct = 0
            items.append({
                "code": code, "name": name, "weight_pct": weight,
                "change_pct": change_pct,
            })

        result = compute_index_contribution(index_code, items)
        return json.dumps(result, ensure_ascii=False, indent=2)
```

替换为：
```python
    def _run(self, index_code: str) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)

        from .contribution import build_index_contribution

        result = build_index_contribution(index_code, trade_date=None, dp=_data_provider)
        if result is None:
            return json.dumps(
                {"error": f"无法获取 {index_code} 权重贡献数据"},
                ensure_ascii=False,
            )
        return json.dumps(result, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: 移除旧的 `INDEX_WEIGHTS` 和 `compute_index_contribution` 导入**

第 13 行：
```python
from .contribution import compute_index_contribution, INDEX_WEIGHTS
```
替换为：
```python
from .contribution import build_index_contribution
```

- [ ] **Step 3: 验证语法**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from marketreview.tools.market_tools import GetIndexContributionTool
print('GetIndexContributionTool: OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add src/marketreview/tools/market_tools.py
git commit -m "refactor(tools): adapt GetIndexContributionTool to use new build_index_contribution"
```

---

### Task 10: 端到端验证 + 清理

**Files:**
- No new files

- [ ] **Step 1: 清除所有 `__pycache__` 目录**

```bash
find /i/AIcode/marketreview -path "*/__pycache__/*.pyc" -delete
find /i/AIcode/marketreview -name "__pycache__" -type d | while read d; do rm -rf "$d"; done
```

- [ ] **Step 2: 在真实 token 下测试完整数据流**

```bash
python -c "
import os, sys
sys.path.insert(0, 'src')
sys.path.insert(0, 'dashboard')
from dotenv import load_dotenv
load_dotenv()

from marketreview.data.data_provider import DataProvider
from marketreview.tools.contribution import build_index_contribution

dp = DataProvider(tushare_token=os.environ['TUSHARE_TOKEN'])

# Test: SSE Composite contribution for 20260608
result = build_index_contribution('000001.SH', '20260608', dp)
if result:
    idx = result['index']
    print(f'上证指数: close={idx[\"close\"]} chg={idx[\"chg_pts\"]}pts ({idx[\"chg_pct\"]:+.2f}%)')
    print(f'领涨:')
    for g in result['gainers']:
        print(f'  {g[\"code\"]} {g[\"name\"]} [{g[\"industry\"]}] w={g[\"weight\"]}% chg={g[\"chg_pct\"]:+.2f}% contrib={g[\"contrib\"]:+.2f}')
    print(f'领跌:')
    for l in result['losers']:
        print(f'  {l[\"code\"]} {l[\"name\"]} [{l[\"industry\"]}] w={l[\"weight\"]}% chg={l[\"chg_pct\"]:+.2f}% contrib={l[\"contrib\"]:+.2f}')
else:
    print('ERROR: build_index_contribution returned None')
"
```

Expected: 输出上证指数的 close、chg_pts、chg_pct，领涨/领跌各 5 只，每只有行业标签。

- [ ] **Step 3: 重启 Dashboard 确认 UI 正常**

```bash
powershell -Command "Get-Process streamlit -ErrorAction SilentlyContinue | Stop-Process -Force"
sleep 1
find /i/AIcode/marketreview -path "*/__pycache__/*.pyc" -delete
python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true
```

打开 http://localhost:8501 → 展开"上证指数"expander → 拉到技术指标下方 → 确认看到"权重贡献"区块，左右两张表。

- [ ] **Step 4: Commit（如有残余改动）**

```bash
git status
# If clean → done. If there are changes → git add + commit.
```
