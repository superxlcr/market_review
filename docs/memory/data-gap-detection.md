---
name: data-gap-detection
description: Data integrity check — detect and auto-fix silent gaps in tushare daily data
metadata: 
  node_type: memory
  type: reference
  originSessionId: d5b5fcbe-874c-4d18-be12-119c43253fc5
---

# Data Gap Detection

## Problem

Tushare's `daily` API can silently return fewer stocks than expected for certain dates. For example, after an initial data load, 20260506 had only 6 stocks out of 5518 (0.1%), and 20260507 had only 505 (9.2%). 20260509 had 0 because it was a Saturday (not a trading day).

A single missing date breaks path-dependent indicators (SMA, EMA) and produces wrong screening results that are very hard to diagnose — the only symptom is mismatched K values with no obvious cause.

## Solution

Added `_validate_coverage()` in DataProvider that runs after every `ensure_data_loaded()`:

1. Counts stocks per date in the fetch range
2. Compares to `stock_basic_cache` total
3. If any date has <90% coverage → logs warning + re-fetches (up to 2 attempts)
4. If still gapped after retries → logs persistent gap (may be non-trading-day or unpublished data)

Implementation: `CacheManager.count_daily_date()`, `get_daily_dates_in_range()`, `get_stock_basic_count()`

## Related

[[calc-kd-dual-purpose]] — two KD functions for different use cases
