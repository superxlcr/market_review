---
name: color-convention
description: "Unified color convention for all UI signals — red=bullish, green=bearish"
metadata: 
  node_type: memory
  type: project
  originSessionId: d164b60f-9366-4e2d-a074-900bd0d24c3e
---

## Color Convention

所有信号颜色统一标准：

| 含义 | 颜色 | 色值 |
|------|------|------|
| **看多** (bullish) | 🔴 红色 | `#e53935` / `#c62828` |
| **看空** (bearish) | 🟢 绿色 | `#43a047` / `#2e7d32` |
| 中性/警告 | 🟠 橙色 | `#ef6c00` |
| 无信号 | ⚫ 灰色 | `#999` / `#888` |

### 具体应用

| 信号 | 颜色 | 原因 |
|------|------|------|
| 多头趋势 | 红色 | 看多 |
| 空头趋势 | 绿色 | 看空 |
| 超买区 | 绿色 | 超买=可能见顶=看空 |
| 超卖区 | 红色 | 超卖=可能见底=看多 |
| 顶背离 | 绿色 | 看跌信号 |
| 底背离 | 红色 | 看涨信号 |
| KD 差值过大 | 橙色 | 警告（方向不确定） |
| 上涨/涨家数多 | 红色 | 看多 |
| 下跌/跌家数多 | 绿色 | 看空 |

**Why:** 统一颜色语义，避免混淆。之前超买超卖颜色搞反了几次。
**How to apply:** 每次新增 UI 信号时按此表选色。相关：[[design-progress]]
