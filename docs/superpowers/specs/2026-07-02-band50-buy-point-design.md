# 波段50%买点 — 设计

**日期:** 2026-07-02
**分支:** feature/stock-tracking

## 背景

个股追踪页面的买点提示系统目前有两种买点类型：
- **回调一半** — 动态价格 `(P + running_low) / 2`，跌破62.5%后逐日计算
- **均线支撑** — MA60/MA120/MA240 向上且量能达标

现新增第三种：**波段50%**，使用静态趋势生命线 `line_50 = (P + V) / 2` 作为买点价格。

## 设计

### 新增类：`Band50Checker(BaseBuyPointChecker)`

| 属性 | 值 |
|------|-----|
| 文件 | `src/marketreview/tools/buy_points.py` |
| 基类 | `BaseBuyPointChecker` |
| 位置 | 在 `HalfRetraceChecker` 和 `MAChecker` 之间 |

### 触发条件（与 HalfRetraceChecker 完全一致）

1. `band.trigger_625_date` 非空 — 曾跌破62.5%
2. `band.v_qualified == True` — V/P < 3/7，波段幅度成立
3. `pullback_days >= 13` — 波峰距今至少13个交易日

### 类型判定（与 HalfRetraceChecker 一致）

- `cur < line_50` → type = `"突破"`
- `cur >= line_50` → type = `"重新突破"`

### 价格

固定 `band.line_50`（即 `(P + V) / 2`）。

### 原因文案

```
回调{pullback_days}天 ≥ 13天，且跌破过{line_625:.2f}
```

### 注册

在 `find_all_buy_points()` 的 `checkers` 列表中追加 `Band50Checker()`：

```python
checkers: list[BaseBuyPointChecker] = [
    HalfRetraceChecker(),
    Band50Checker(),      # 新增
    MAChecker(),
]
```

### 渲染

无需改动 — `render_buy_point_table()` 已支持 `"突破"` 和 `"重新突破"` 的颜色标签。

## 实现检查清单

- [ ] 新增 `Band50Checker` 类
- [ ] 在 `find_all_buy_points()` 中注册
- [ ] 重启 dashboard 验证新买点出现
- [ ] 检查日志 `logs/buy_points.log` 无异常
