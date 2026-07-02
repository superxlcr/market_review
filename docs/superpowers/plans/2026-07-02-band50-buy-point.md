# 波段50%买点 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在买点提示系统中新增"波段50%"买点类型，与回调一半条件一致，价格使用静态趋势生命线 `line_50`。

**Architecture:** 新增 `Band50Checker(BaseBuyPointChecker)` 子类，与 `HalfRetraceChecker` 平行，在 `find_all_buy_points()` 中注册。

**Tech Stack:** Python, numpy, dataclasses, ABC

## Global Constraints

- 修改文件: `src/marketreview/tools/buy_points.py` only
- 三类条件与 `HalfRetraceChecker` 完全一致: V合格 + 跌破过62.5% + 回调≥13天
- 类型判定: 现价 < line_50 → "突破"，现价 ≥ line_50 → "重新突破"
- 价格: `band.line_50`
- 渲染层无需改动（`render_buy_point_table` 已支持两种类型颜色）

---

### Task 1: 新增 Band50Checker 类 + 注册

**Files:**
- Modify: `src/marketreview/tools/buy_points.py`

**Interfaces:**
- Consumes: `BandResult` (field: `trigger_625_date`, `v_qualified`, `p_idx`, `rows_count`, `line_50`, `line_625`, `current_price`)
- Produces: `list[BuyPoint]` — 零个或一个买点

- [ ] **Step 1: 在 HalfRetraceChecker 之后、MAChecker 之前插入 Band50Checker 类**

```python
# ── 波段50%买点 ─────────────────────────────────────────────

class Band50Checker(BaseBuyPointChecker):
    """波段50%位置买点.

    条件: 已跌破62.5%（trigger_625_date 非空）+ 波段幅度成立 + 回调≥13天.
    价格: band.line_50（趋势生命线，静态 = (P+V)/2）
    """

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if not band.trigger_625_date:
            return []
        if not band.v_qualified:
            return []
        pullback_days = band.rows_count - 1 - band.p_idx
        if pullback_days < 13:
            return []

        line_50 = band.line_50
        if line_50 <= 0:
            return []

        cur = band.current_price
        dist = round((line_50 / cur - 1) * 100, 1)

        if cur < line_50:
            bp_type = "突破"
        else:
            bp_type = "重新突破"

        reason = f"回调{pullback_days}天 ≥ 13天，且跌破过{band.line_625:.2f}"

        return [BuyPoint(
            type=bp_type,
            position="波段50%",
            price=line_50,
            distance_pct=dist,
            reason=reason,
        )]
```

- [ ] **Step 2: 在 find_all_buy_points() 的 checkers 列表中注册**

找到:
```python
    checkers: list[BaseBuyPointChecker] = [
        HalfRetraceChecker(),
        MAChecker(),
    ]
```

改为:
```python
    checkers: list[BaseBuyPointChecker] = [
        HalfRetraceChecker(),
        Band50Checker(),
        MAChecker(),
    ]
```

- [ ] **Step 3: 清除 pycache 并重启 dashboard 验证**

```bash
# 清除缓存
rm -rf src/marketreview/tools/__pycache__/buy_points.cpython-312.pyc

# 重启 dashboard（实际命令按项目习惯来）
```

验证: 打开个股追踪页面，查看任意有波段的个股，确认"波段50%"买点出现在买点提示表格中。

- [ ] **Step 4: 检查日志无异常**

```bash
tail -20 logs/buy_points.log
```

确认无 ERROR 或异常 WARNING。

- [ ] **Step 5: Bump AI version**

在 `dashboard/services/dashboard_service.py` 中找到 `_AI_VERSION`，递增 Y（minor — 新功能）。

- [ ] **Step 6: Commit**

```bash
git add src/marketreview/tools/buy_points.py dashboard/services/dashboard_service.py
git commit -m "feat: 新增波段50%买点 — Band50Checker，条件同回调一半，价格=line_50"
```
