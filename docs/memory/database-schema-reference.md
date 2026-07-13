---
name: database-schema-reference
description: "Complete database schema, table columns, data flow, and how to query for debugging"
metadata: 
  node_type: memory
  type: reference
  originSessionId: e1ab23ab-b5f6-4f34-a6f2-289c36829c6c
---

# Database Schema & Data Flow Reference

## Database

Single SQLite DB at `data/marketreview.db` (WAL mode, synchronous=NORMAL).

## Key Tables

### `tushare_cache` — primary OHLCV store
Columns: `code, date, open, high, low, close, vol, amount, adj_factor, asset_type`
- `code`: stock/index code (e.g. `000001.SZ`, `000001.SH`)
- `date`: YYYYMMDD
- `amount`: 千元 (divide by 1e5 → 亿)
- `adj_factor`: adjustment factor for qfq; indices = 1.0
- `asset_type`: `'stock'` or `'index'`
- PK: `(code, date)`, index: `idx_cache_code_date` on `(code, date DESC)`
- **All prices are 不复权 (raw)** — use `DataProvider.raw_to_qfq()` for qfq conversion

### `stock_industry_cache` — SW industry classification
Columns: `ts_code (PK), name, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name`

### `stock_basic_cache` — A-share stock list
Columns: `ts_code (PK), name, list_date, is_st`

### `daily_basic_cache` — market cap
Columns: `ts_code, trade_date, total_mv, circ_mv`, PK: `(ts_code, trade_date)`

### `industry_daily` — industry OHLCV
Columns: `industry_code, trade_date, open, high, low, close, vol, amount, pct_change`
PK: `(industry_code, trade_date)`

### Other tables (less frequently queried)
`index_weight_cache`, `wave33_cache`, `index_contribution_cache`, `stk_limit_cache`, `ai_summary`, `industry_classify`

## Data Flow

```
tushare API → DataProvider.ensure_data_loaded() → CacheManager.upsert_daily()
  → data/marketreview.db (raw prices, date DESC)
  → DataProvider.get_daily() → list[dict] (date DESC)
  → rows_to_df() → pd.DataFrame (date ASC)
  → raw_to_qfq() → qfq-adjusted DataFrame
  → calc_ma/calc_kd/etc → technical indicators
  → dashboard rendering
```

## How to Query for Debugging

**Direct SQLite (always works):**
```python
import sqlite3
conn = sqlite3.connect("data/marketreview.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM tushare_cache WHERE code=? ORDER BY date DESC LIMIT 800", (code,)).fetchall()
conn.close()
# rows are date DESC — reverse for TA
```

**Via DataProvider (requires tushare_token):**
```python
from dotenv import load_dotenv; load_dotenv()
dp = DataProvider(tushare_token=os.getenv("TUSHARE_TOKEN"))
dp.ensure_data_loaded_for_codes([code], start_date, end_date)
rows = dp.get_daily(code, lookback_days=800, end_date=end_date)
```

**Via CacheManager directly (no tushare needed, just read):**
```python
from marketreview.data.cache_manager import CacheManager
cache = CacheManager("data/marketreview.db")
rows = cache.get_daily(code, limit=800)  # list[dict], date DESC
```

## Column Name Gotchas

- In DB: `date` (not `trade_date`), `vol` (not `volume`)
- In `get_daily()` return: keys are `date, open, high, low, close, vol, amount, adj_factor, asset_type`
- Amount is in **千元** — divide by 1e5 to get 亿
- `get_daily()` returns date **DESC** — always sort ASC before TA
