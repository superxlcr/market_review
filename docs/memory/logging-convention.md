---
name: logging-convention
description: Standard logging levels and placement rules for the project
metadata: 
  node_type: memory
  type: project
  tags: 
    - logging
    - convention
    - debugging
  originSessionId: d5b5fcbe-874c-4d18-be12-119c43253fc5
---

# Logging Convention

## Setup

Every module that touches data or business logic imports:

```python
from marketreview.log_util import get_logger
log = get_logger(__name__)
```

Logs write to `logs/{module_name}_{YYYYMMDD}.log` under repo root. UTF-8, daily rotation.

## Levels

| Level | When | Example |
|-------|------|---------|
| **INFO** | Data reads/writes, cache hits/misses, scan start/end, pattern detected | `log.info("get_daily: code=%s end=%s → %d rows", ...)` |
| **DEBUG** | Internal filtering decisions, effective-end calculation, per-stock details | `log.debug("effective_end=%s latest_cached=%s", ...)` |
| **WARNING** | Missing data, empty results, degraded operation | `log.warning("no qualifying stocks for date=%s", ...)` |
| **ERROR** | (rare) Unexpected failures | |

## Required Log Points

Every module that accesses cached data MUST log at these points:

1. **Data read entry** — INFO: key params (code, end_date, limit) and result count
2. **Data write** — INFO: key params and what was written
3. **Date filtering** — DEBUG: effective_end, filtered range
4. **Pattern/scan results** — INFO: what was detected/computed
5. **Empty/short results** — WARNING: when data is missing

## What NOT to log

- Per-row/per-stock details at INFO (use DEBUG)
- Stack traces from expected exceptions (log the message only)
- Sensitive data (tokens, credentials)

## Related

[[always-filter-by-date]] [[two-window-cache-design]]
