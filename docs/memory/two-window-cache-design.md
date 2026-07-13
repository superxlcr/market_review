---
name: two-window-cache-design
description: "Dual-window cache strategy: USE window checks cache, CACHE window over-fetches on miss"
metadata: 
  node_type: memory
  type: project
  tags: 
    - cache
    - design-pattern
    - wave33
    - performance
  originSessionId: d5b5fcbe-874c-4d18-be12-119c43253fc5
---

# Two-Window Cache Design

## Principle

All caches use two window sizes:
- **USE window** — what's actually needed for display/query (e.g., 40 trading days for chart + rolling window)
- **CACHE window** — what gets computed on a cache miss (e.g., 80 trading days, ~2x USE)

**Key rule:** USE < CACHE. The USE window checks whether cache is sufficient; the CACHE window determines how much to over-fetch when it's not.

## Why

If USE == CACHE, switching dates by even 1 day shifts the window and always triggers a full recompute. With USE < CACHE, nearby date switches stay within the buffer and hit cache instantly.

## Pattern

```
def ensure_xxx_computed(target_date):
    USE_DAYS = N       # needed for the feature
    CACHE_DAYS = M     # over-fetch, M > N (typically ~2x)

    use_dates = [last USE_DAYS trading days up to target_date]
    missing_use = [d for d in use_dates if not cached(d)]

    if not missing_use:
        return  # fast path — within buffer

    # Slow path — scan CACHE window
    cache_dates = [last CACHE_DAYS trading days up to target_date]
    scan(cache_dates)
```

## In Practice (wave33)

| Window | Size | Purpose |
|--------|------|---------|
| USE | 40 trading days | 15 chart bars + 21 rolling window + 4 buffer |
| CACHE | 80 trading days | ~4 months, 2x USE |

Switching within ~40 trading days (~2 calendar months) of the originally-loaded date hits cache instantly.

## Related

[[data-layer-architecture]] [[dashboard-setup]]
