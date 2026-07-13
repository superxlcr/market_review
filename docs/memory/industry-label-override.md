---
name: industry-label-override
description: Recursive L1/L2/L3 industry split rules for display in contribution tables
metadata: 
  node_type: memory
  type: project
  tags: 
    - contribution
    - industry
    - split
  originSessionId: 562434d4-216b-4bec-8992-0ef2fa32705d
---

# Industry Split Rules (Recursive)

Defined in `src/marketreview/tools/industry.py`.

**Logic** — recursive replacement, not hard-coded overrides:

1. Default: show at **L1** level (31 industries)
2. **SPLIT_L1**: these L1 are replaced by their L2 children (6 → 24 L2)
3. **SPLIT_L2**: these L2 are further replaced by their L3 children (3 → 14 L3)

Resolution functions: `resolve_industry_label()` and `resolve_industry_code()`.

## Split Configuration

**SPLIT_L1** — L1→L2 (6 industries):
`建筑材料`, `有色金属`, `汽车`, `电力设备`, `电子`, `通信`

**SPLIT_L2** — L2→L3 (3 industries):
`半导体`, `元件`, `光伏设备`

**Final count**: 25 L1 + 24 L2 + 14 L3 = **63** industries

## How to Adjust

Edit `SPLIT_L1` and `SPLIT_L2` sets in `src/marketreview/tools/industry.py`. The resolution functions are generic — they don't need to change when the sets change.

Related: [[color-convention]]
