---
name: calc-kd-dual-purpose
description: "Two KD functions — calc_kd for display, calc_kd_standard for formula screening"
metadata: 
  node_type: memory
  type: reference
  originSessionId: d5b5fcbe-874c-4d18-be12-119c43253fc5
---

# Two KD Functions

## `calc_kd()` — display KD (non-standard, high-based)

Uses a high-based RSV correction: `K_final = (RSV_high + 2 * K_close[-1]) / 3`. Better at capturing breakout strength in overbought territory. Used by `01_市场全景.py` for K-line overlay display.

**Do NOT use for formula screening** — produces different K values from 通达信.

## `calc_kd_standard()` — exact TDX K(9,3,3)

Standard 通达信 formula: `RSV = (C - LLV(L,9)) / (HHV(H,9) - LLV(L,9)) * 100`, `K = SMA(RSV, 3, 1)`. Matches 通达信 condition-screening output exactly. Used by `wave33.py` for 33 formula scanning.

**Always use this for any formula that needs to match 通达信 results.**

## History

Initially only `calc_kd` existed. During 33 formula verification, we found K values diverged from TDX by 5+ points. Root cause: `calc_kd` uses a non-standard high-RSV blend. After fixing data gaps (missing trading days 0506-0507), we created `calc_kd_standard` specifically for screening while preserving `calc_kd` for display.

## Related

[[data-gap-detection]] — the other half of the fix
