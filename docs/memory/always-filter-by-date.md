---
name: always-filter-by-date
description: "Cached data reads must always filter by trade_date — never just \"latest N rows\""
metadata: 
  node_type: memory
  type: project
  tags: 
    - bug-pattern
    - cache
    - data
  originSessionId: d5b5fcbe-874c-4d18-be12-119c43253fc5
---

# Always Filter Cache Reads by Date

## Rule

**Every read from a date-keyed cache table MUST include a date filter (`WHERE trade_date <= ?`).** Never use bare `LIMIT N` / "latest N rows" — the dashboard always operates on a user-selected trade date, and "latest" is almost never the right answer.

## Why

This has bitten us at least twice. A query that returns "the most recent N rows" silently ignores the user's selected date, showing wrong data without any error. The bug is subtle because it only manifests when looking at historical dates.

## Pattern to avoid

```sql
-- WRONG: ignores selected date
SELECT * FROM xxx_cache ORDER BY trade_date DESC LIMIT ?
```

## Pattern to use

```sql
-- RIGHT: always scoped to the selected date
SELECT * FROM xxx_cache WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?
```

## Code-level check

When reviewing any new cache read function, ask:
- Does it take an `end_date` (or equivalent) parameter?
- If not, is "latest" truly correct for ALL callers? (Almost never.)
- When in doubt, add the date filter.

## Related

[[two-window-cache-design]] [[data-layer-architecture]]
