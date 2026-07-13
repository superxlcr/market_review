# 量价节点严格版 设计文档

日期：2026-07-13
状态：待实现
版本：v9.9.0 → **v9.10.0**（feature，Y+1）
关联：[2026-07-11-buypoint-winrate-design.md](./2026-07-11-buypoint-winrate-design.md) §7 量价节点买点

---

## 1. 背景与目标

现有「量价节点」买点（`VolPriceNodeChecker`，live，上浮4%）+ 变体「量价节点上浮2%」（trial）。

新增**严格版**两个：
- 「量价节点严格」（trial，上浮4%）
- 「量价节点严格上浮2%」（trial，上浮2%）

### 核心新增规则
**波段比例判断领先于量价节点**：严格模式下，节点 target 价 < 波段50%线（`line_50`）则作废。

> 直觉：波段50%线是趋势生命线。节点（支撑位）若落在50%线下方，说明该支撑位已属"下半区"，趋势结构已弱化，不应作为买点。严格版只保留波段上半区（≥50%线）的节点。

### 实现口径
**始终过滤**：不管 `l_price`（回调最低点）在哪，只要 `target < line_50` 就过滤。规则统一简单。保留现有激活门（`l_price < line_75`）及其它节点筛选逻辑不变。

---

## 2. 改动

### 2.1 `src/marketreview/tools/buy_points.py`

**`VolPriceNodeChecker.__init__` 加 `strict` 参数**（523-526 行）：

```python
def __init__(self, entry_premium: float = 1.04, strict: bool = False):
    self.ENTRY_PREMIUM = entry_premium
    self.strict = strict
    # live 仅当默认上浮4% 且 非严格；其余（上浮2% 或 严格）均 trial
    self.STAGE = "live" if (abs(entry_premium - 1.04) < 1e-9 and not strict) else "trial"
```

**`check()` 加 50% 线过滤**（target 算出后，约 582 行）：

```python
target = round(cost * self.ENTRY_PREMIUM, 2)
# 严格版：节点落在波段50%线下方 → 趋势结构已弱化，作废
if self.strict and band.line_50 > 0 and target < band.line_50:
    log.debug("VolNode strict: target=%.2f < line_50=%.2f, skip", target, band.line_50)
    continue
```

**`find_all_buy_points` checkers 列表加两个**（722-730 行）：

```python
VolPriceNodeChecker(entry_premium=1.04, strict=True),   # trial（严格，上浮4%）
VolPriceNodeChecker(entry_premium=1.02, strict=True),   # trial（严格，上浮2%）
```

> 与 `HalfRetraceChecker(strict=True)` 一致：开"显示试验买点=1"时个股页也可见，否则仅胜率页可见。

### 2.2 `src/marketreview/winrate/buypoint_defs.py`

`_NAME_MAP` 加两条：

```python
"量价节点严格": ("volnode", VolPriceNodeChecker(entry_premium=1.04, strict=True)),
"量价节点严格上浮2%": ("volnode", VolPriceNodeChecker(entry_premium=1.02, strict=True)),
```

kind 仍是 `"volnode"` → 走现有 `code=` 分支 + `close_stop_kind="fixed"`（节点成本止损），逻辑不变 ✓。

### 2.3 `src/marketreview/winrate/config.py`

`BUY_POINT_STAGE` + `_BUY_POINT_ORDER` 加两条（trial）：

```python
"量价节点严格": "trial",
"量价节点严格上浮2%": "trial",
```

`_BUY_POINT_ORDER` 加在"量价节点上浮2%"之后。`ALL_BUY_POINTS` 自动含（非 disabled）。

### 2.4 `dashboard/services/dashboard_service.py`

`_AI_VERSION` 9.9.0 → **9.10.0**。

---

## 3. 测试

`tests/winrate/test_volnode.py`（既有）追加：
- strict 下 `target < line_50` 的节点被过滤
- strict 下 `target >= line_50` 的节点保留
- 非 strict 行为不变（回归）
- STAGE：strict 实例 = trial，非严格默认上浮4% = live

`tests/winrate/test_buypoint_defs.py`（既有）追加：
- `_NAME_MAP` 含两个新名字，kind="volnode"
- `ALL_BUY_POINTS` 含两个新名字

---

## 4. 约定

- 版本 9.9.0 → 9.10.0（feature，Y+1）。
- 复用 `VolPriceNodeChecker`，加参数而非新类（DRY）。
- 严格版标 trial，不污染实盘个股页默认视图。
- 日志：strict 过滤用 DEBUG（数据级），与现有节点筛选日志级别一致。

---

## 5. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/marketreview/tools/buy_points.py` | `VolPriceNodeChecker` 加 `strict` + 50%线过滤 + checkers 列表加两实例 |
| `src/marketreview/winrate/buypoint_defs.py` | `_NAME_MAP` 加两条 |
| `src/marketreview/winrate/config.py` | `BUY_POINT_STAGE` + `_BUY_POINT_ORDER` 加两条 |
| `dashboard/services/dashboard_service.py` | 版本 9.10.0 |
| `tests/winrate/test_volnode.py` | strict 过滤测试 |
| `tests/winrate/test_buypoint_defs.py` | 注册测试 |
