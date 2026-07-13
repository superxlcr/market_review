---
name: date-format-convention
description: All DB dates are YYYYMMDD — never use _with_dashes for queries
metadata: 
  node_type: memory
  type: project
  originSessionId: ae5a34d2-5eaa-4293-8197-32a6358f9fcf
---

**Rule: ALL date strings in internal code MUST be YYYYMMDD (no dashes). Only convert to YYYY-MM-DD at the UI/display boundary.**

## DB format (verified 2026-06-19)

| Table | Date Column | Format |
|---|---|---|
| `tushare_cache` | `date` | YYYYMMDD |
| `industry_daily` | `trade_date` | YYYYMMDD |
| `daily_basic_cache` | `trade_date` | YYYYMMDD |
| `wave33_cache` | `trade_date` | YYYYMMDD |

## `_with_dashes()` is dangerous — never use it for DB queries

`_with_dashes("20260618")` → `"2026-06-18"`. Using this to query `tushare_cache` (where date = '20260618') returns **0 rows**.

Also breaks string comparison: `'20260618' > '2026-06-19'` because `'0'` (ASCII 48) > `'-'` (ASCII 45), so `get_previous_trade_date("2026-06-19")` can't find any 2026 dates.

## Safe methods (already strip dashes internally)

- `get_industry_daily_dates_in_range()` — does `start.replace("-", "")`
- `has_industry_daily()` — does `trade_date.replace("-", "")`

## Unsafe methods (pass date straight to SQL)

- `get_daily_snapshot(codes, date_str)` — `WHERE date = ?`
- `get_previous_trade_date(date_str)` — `WHERE date < ?`
- `get_daily(code, end, limit)` — `WHERE date <= ?`
- Pretty much everything else

## How to verify

```bash
# Run from project root:
.venv/Scripts/python -c "
import sqlite3; conn = sqlite3.connect('data/marketreview.db')
r = conn.execute(\"SELECT COUNT(*) FROM tushare_cache WHERE date = '2026-06-18'\").fetchone()
print(f'with dashes: {r[0]}')  # 0 — WRONG
r = conn.execute(\"SELECT COUNT(*) FROM tushare_cache WHERE date = '20260618'\").fetchone()
print(f'no dashes: {r[0]}')    # 5513 — CORRECT
"
```

**Why:** String comparison on YYYYMMDD is lexicographically equivalent to chronological order. Mixing formats breaks all date range queries.
