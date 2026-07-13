---
name: band-vp-constraint
description: V/P < 3/7 约束的推导与含义 — 波段深度必须 ≥ 2.33 倍
metadata: 
  node_type: memory
  type: reference
  originSessionId: e1ab23ab-b5f6-4f34-a6f2-289c36829c6c
---

# 波段 V/P 约束：3/7 的由来

## 公式推导

设计要求：**波段 50% 线的 1.1 倍必须小于波段 62.5% 线**，确保两条趋势线之间有足够间距。

```
50% 线  = (P+V)/2
62.5%线 = V + 0.625 × (P-V) = 0.625P + 0.375V

条件: 50% × 1.1 < 62.5%

→ (P+V)/2 × 1.1 < 0.625P + 0.375V
→ 0.55P + 0.55V < 0.625P + 0.375V
→ 0.55V - 0.375V < 0.625P - 0.55P
→ 0.175V < 0.075P
→ V/P < 0.075/0.175
→ V/P < 3/7 ≈ 0.4286
```

## 等价表述

- **V/P < 3/7** ≈ 0.4286
- **P/V > 7/3** ≈ 2.333
- 波段幅度至少 **2.33 倍**（从谷底到峰顶涨了不止一倍）

简化版策略里 `V = P / 2.33` 就是取极限情况（V/P = 1/2.33 = 3/7）。

## 为什么要这个约束

如果波段太窄（V 太高），50% 线和 62.5% 线会挤在一起，两条支撑位几乎重叠，没有"回调深度"的区分意义，买入信号也不可靠。

## 代码位置

- `src/marketreview/tools/band_analysis.py` — `analyze_band()` 中 V 选取时使用
- `src/marketreview/backtest/strategies/half_retrace.py:6` — 原始注释

## 相关

[[band-analysis-logic]]
