---
name: agent3-design-decisions
description: Key design decisions for Agent 3 made on 2026-06-04
metadata: 
  node_type: memory
  type: project
  originSessionId: ce9ebd5d-9eba-4ebd-bcd3-4377f2c4bf1e
---

## Agent 3 Design Decisions (Revised 2026-06-04)

### Fundamental vs Technical Separation
- **基本面判定**: Done ONCE when adding stock to watchlist. Uses valuation.py (PE/PB分位, DCF, 财报交叉验证). Result stored as `tradable_type` field in watchlist: `left` / `right` / `skip`. Only re-done when new financial report comes out or major event.
- **技术面分析**: Done EVERY daily review. Uses shared technical.py tools.

### Agent 3 Role (Revised)
- **Role**: A股个股技术分析师
- **Goal**: 判定个股技术状态 + 识别关键点位 + 持仓管理
- **Tools**: technical.py (shared), position_manager.py (new, for cost-tier stop-loss/take-profit)
- **NOT responsible for**: Fundamental analysis, position sizing (follows Agent 2)

### Four Technical States
| State | Condition | Action |
|-------|-----------|--------|
| 🔴 上升中(不能介入) | 多头+MA5上方+无回调 | Wait |
| 🟢 已回调X天 | 多头未破+回调+X<13 | Look for pullback entry |
| 🟡 等待突破 | 回调≥13天 | Only breakout entry |
| ⚫ 下跌中 | MA60↓+全均线下 | Ignore |

### 13-Day Rule
User's rule: After 13 days of pullback, the "pullback buy" mode expires and switches to "wait for breakout" mode.

### Two Analysis Paths
1. **未持仓**: Output key technical levels (MA20/MA60/volume node/gap/previous low support, previous high resistance, breakout_50 if in 等待突破 state). Stop loss in parentheses.
2. **已持仓**: Cost-tiered stop-loss/take-profit:
   - 0-10% profit: Stop loss at cost -3~5%, no take-profit
   - 10-20% profit: Trailing stop at cost +3% (protect principal), trailing take-profit at -5% from peak
   - 20%+ profit: Trailing stop at MA20, no hard take-profit

### Dashboard Display
- Header: name, industry, price, change%, 持仓 status badge, 技术 state badge, 基本面 type badge
- K-line chart (same component as index/sector)
- Right panel: 关键技术点位 table (未持仓) OR 持仓管理 tier card (已持仓)
- NO: valuation display, alert notifications

### Flow State Output Fields
- stock_analysis: str (markdown)
- stock_signals: list[dict] with state, key_levels, position_tier
- watchlist_updates: list[dict] (tech_points snapshot)
- pending_items: list[dict] (cross-day tracking)

**Status:** ✅ Finalized on 2026-06-04. User confirmed design, combined dashboard mockup approved (light theme).
**Additional decision:** `valuation.py` for fundamental screening is a pure code tool (NOT an Agent), triggered once at watchlist-add time, not part of daily Flow.
**Spec:** Written to `docs/superpowers/specs/2026-06-04-market-review-system-design.md`

**Why:** Key decisions were confirmed after visual mockup iteration.
**How to apply:** Proceed to implementation via writing-plans skill.
