---
name: data-layer-architecture
description: "Data access rule — all data through DataProvider, raw + adj_factor → qfq, incremental loading"
metadata:
  node_type: memory
  type: project
  originSessionId: 48ae945a-00c7-4ec6-86d9-41082ccc8e80
---

## Architecture (v3 — 2026-06-11)

```
存储层:   raw (不复权，永不变) + adj_factor (按日期) + asset_type ('stock'/'index')
读取层:   qfq = raw × adj_factor(T) / adj_factor(latest)
```

### Data Flow

```
Dashboard Console
  → check_cache_coverage(trade_date)  → True → 直接切换，无 spinner
  → ensure_data_loaded(trade_date)    → False → 增量拉取 + 进度条
    → api.daily(paginated, chunked by date)     → raw OHLCV 入库 (asset_type='stock')
    → api.adj_factor(paginated, chunked by date) → UPDATE adj_factor
    → api.index_daily(6 major indices)          → raw OHLCV 入库 (asset_type='index')
    → api.daily_basic(chunked by date)          → 市值入库
    → _validate_coverage()                       → ≥90% 覆盖率检查
    → _ensure_industry_daily()                   → 行业日线入库
      → index_classify(L1+L2+L3) → industry_classify 表 (一次)
      → sw_daily(63 展示行业) → industry_daily 表 (4 线程并发)
  → progress callback → UI 进度条

Dashboard Pages
  → get_daily(code)         → 读取缓存 (raw + adj)
  → get_daily_batch(codes)  → 读取缓存 (chg% = close / adjusted_prev_close)
  → raw_to_qfq(df)          → 展示层转换为前复权
  → get_industry_daily(code)→ 读取行业日线 DataFrame
```

### Industry Data

行业板块数据通过 tushare `sw_daily` 付费 API 获取，存储到独立的 `industry_daily` 表
（不需要 adj_factor 复权）。行业分类通过 `index_classify` API 获取，缓存到
`industry_classify` 表。

展示行业数由 `SPLIT_L1` / `SPLIT_L2` 递归拆分规则决定（当前 63 个），而非全量 439 个。

行业拉取为**按行业并发**（每行业 ~659 行，一页即可）而非按日期段 chunk。

### Key Parameters

| Param | Value | Purpose |
|-------|-------|---------|
| _FETCH_DAYS | 1000 | Calendar days to fetch (~670 trading days) |
| _CHECK_DAYS | 500 | Calendar days required for cache "complete" |
| _CHUNK_DAYS | 30 | Days per API chunk (~20 trading days) |
| _PAGE_SIZE | 5000 | Tushare API page limit |

### Incremental Loading

`ensure_data_loaded` only fetches MISSING ranges:
- **Tail gap**: cache latest < target date → fetch [latest+1, target]
- **Head gap**: cache earliest > check_start → fetch [fetch_start, earliest-1]
- **No gap**: return immediately, 0 API calls

`check_cache_coverage(end_date)` — fast read-only check (no API), used by console to decide whether to show spinner.

### Schema

```sql
tushare_cache (code, date, open, high, low, close, vol, amount, adj_factor, asset_type)
-- asset_type: 'stock' or 'index'
-- NO pre_close column (computed as prev_close × adj_prev / adj_today)
-- Indices have adj_factor=1.0 always
```

### Index Data

`api.daily()` does NOT return index data. Indices are fetched via `api.index_daily()` and stored in the same table with `asset_type='index'`, `adj_factor=1.0`.

Tracked indices: 000001.SH (上证), 399006.SZ (创业板), 000016.SH (上证50), 000300.SH (沪深300), 399001.SZ (深证成指), 399005.SZ (中小板)

### Key Rules

- **DataProvider is the single entry point** — Tushare must NOT be called outside
- **pro_bar is NOT used** — all data via `api.daily()` + `api.adj_factor()` + `api.index_daily()`
- **Raw pre_close is NOT stored** — change_pct computed via adj_factor ratio
- **Index adj_factor=1.0** — qfq conversion is a no-op for indices
- **Proxy code for cache check**: 000001.SZ (平安银行, a stock — NOT an index)
- **Don't casually delete the database** — only when schema changes or data is corrupted
- **ALL SQLite writes MUST go through `cache._get_conn()`** — never raw `sqlite3.connect()`. The connection factory sets `PRAGMA busy_timeout=30000` + `synchronous=NORMAL`. A raw connect() has no timeout and throws `database is locked` immediately under concurrency. This already bit us once (2026-06-20: `_upsert_adj_factors` used raw connect, 8 concurrent writers → spammed "database is locked").

### Related
- [[design-progress]]
- [[dashboard-setup]]
