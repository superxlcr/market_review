# 买点系统优化 — 止损 + 涨幅过滤 + MA 跌破统计

**日期:** 2026-07-02
**分支:** feature/stock-tracking

## 一、BuyPoint 数据结构扩展

新增止损字段：

```
intraday_stop: float       # 盘中止损价
intraday_stop_pct: float   # 盘中止损跌幅%
intraday_stop_reason: str  # "ATR 2.3%" | "10%上限" | "5%固定"
close_stop: float          # 收盘止损价
close_stop_pct: float      # 收盘止损跌幅%
close_stop_reason: str     # "跌破买入价" | "跌破MA3%" | "跌破MA"
```

## 二、涨幅过滤

| 板块 | ts_code 特征 | 2x 涨跌幅 = 过滤阈值 |
|------|-------------|---------------------|
| 主板 | 60/00 开头 | 20% |
| 创业板 | 30 开头 | 40% |
| 科创板 | 68 开头 | 40% |

`distance_pct > 阈值` → 不显示。

## 三、止损规则

**盘中止损：**
- 回调一半/波段50%: `min(ATR%, 10%)`，原因标注 `ATR X.X%` 或 `10%上限`
- 均线支撑: 固定 5%

**收盘止损：**
- 回调一半/波段50%: 跌破买入价
- 均线支撑: 行情好 (trend=up) → 跌破 MA×0.97 且连续≤3天 / 行情不好 (trend=down/flat) → 跌破 MA

## 四、MA 跌破 Episode 统计

从 P 到今日，逐日重算均线，按 episode 分组：

- 开始: `low < MA`（当天跌破）
- 结束: `close ≥ MA`（收盘站回去）
- 穿透: episode 期间 `max((MA - low) / MA)` 每天重算 MA

渲染为独立统计区块，无阈值判断，纯数据参考。

## 五、配置新增

```
ATR盘中止损上限=10
均线盘中止损=5
```

## 六、渲染

- 买点表格新增"盘中止损""收盘止损"两列
- 标题旁小字: "已过滤涨幅超2倍涨跌幅的买点"
- 表格下方 MA episode 统计区块
