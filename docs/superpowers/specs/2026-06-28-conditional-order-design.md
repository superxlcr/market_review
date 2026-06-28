# 条件单化改造 — 设计文档

日期: 2026-06-28 | 状态: 已审批

---

## 动机

回测引擎从"当天判断当天买"改为"前一天设条件单、第二天触发"。为后续接入每日实时行情做铺垫。

---

## 1. ConditionalOrder dataclass

```python
@dataclass
class ConditionalOrder:
    date_set: str         # 设置日期 YYYYMMDD
    symbol: str
    symbol_name: str
    target_price: float       # 目标买入价
    open_price_cap: float     # 开盘追高上限 (= target × open_chase_cap_pct / 100)
    reason: str               # 信号原因（来自策略 check_buy）
    strategy_tag: str = ""
```

## 2. StrategyConfig 新增配置

`open_chase_cap_pct: float = 102.0` — 开盘追高上限百分比。

配置文件新增全局项：`开盘追高上限%=102`。

## 3. Broker 改造

| 新增 | 说明 |
|------|------|
| `pending_orders: list[ConditionalOrder]` | 待触发条件单 |
| `add_order(order)` | 收盘后设条件单 |
| `process_open_orders(...)` | ①b 开盘买入：遍历 shuffled 条件单，仅判断 open 触发 |
| `process_intraday_orders(...)` | ②b 盘中买入：剩余条件单，仅判断 target ∈ [low,high] |
| `clear_orders()` | 清空未触发条件单（日末） |

卖出也拆分为开盘+盘中两阶段：
| `process_open_sells(...)` | ① 仅判断 open ≤ 触发价 |
| `process_intraday_close_sells(...)` | ⑤ 盘中 + 收盘触发 |

### 条件单成交逻辑

```
①b 开盘买入:
  for order in shuffled(orders, rng):
      if not can_buy(): continue
      if open > target and open ≤ open_price_cap: → 开盘买入 @open
      else: → 保留到盘中阶段

②b 盘中买入:
  for order in shuffled(remaining, rng):
      if not can_buy(): continue
      if target in [low, high]: → 盘中买入 @target
      else: → 过期，跳过
```

### 新增 TradeRecord 类型

- `开盘买入` — reason: `追高买入(开盘≤上限X.XX)，突破MA60`
- `盘中买入` — reason: `突破MA60(昨额:...)`
- `设置条件单` — reason: `目标价=X.XX 开盘上限≤X.XX 突破MA60(量能过关)`

## 4. Engine 日循环改造（最终顺序）

```
Day N:
  ① 开盘卖出 → broker.process_open_sells()
       开盘价已触发止损/止盈 → 开盘止损 / 开盘止盈
       释放仓位后，开盘买入可用

  ② 开盘买入 → broker.process_open_orders(rng)
       open > target AND open ≤ open_price_cap → 开盘买入 @open

  ③ 盘中买入 → broker.process_intraday_orders(rng)
       剩余条件单 target ∈ [low, high] → 盘中买入 @target

  ④ 盘中+收盘卖出 → broker.process_intraday_close_sells()
       盘中止损/止盈 + 收盘卖出（战法卖出/时间止损）
       注意：此处释放的仓位当天不再用于买入

  ⑤ 条件单设置:
     for 未持仓 + in_window 股票:
       buy_sig = strategy.check_buy(ctx)
       if buy_sig is None: continue
       # 量能过滤（MA55Volume 等战法内部 _last_volume_filter）
       if vol_filter_failed: 记录「量能过滤」; continue
       # 判断明天能不能到
       limit = get_limit_pct(s.code)
       if today_close × (1-limit) ≤ target ≤ today_close × (1+limit):
         order = ConditionalOrder(
           target_price=buy_sig.price,
           open_price_cap=buy_sig.price × cfg.open_chase_cap_pct / 100,
           reason=buy_sig.reason,
         )
         broker.add_order(order)
         记录「设置条件单」
```

## 5. 涨跌停限制

```python
def get_limit_pct(code: str) -> float:
    if code.startswith(("600","601","603","605","000","001","002","003")):
        return 0.10
    if code.startswith(("300","301","688")):
        return 0.20
    if code.startswith("8"):
        return 0.30
    return 0.10  # 默认主板
```

## 6. 卖出文案细化

| 原逻辑 | 触发条件 | 新文案 |
|--------|----------|--------|
| 空间止损 @开盘 | open ≤ stop_price | 开盘止损 |
| 空间止损 @盘中 | low ≤ stop_price | 盘中止损 |
| T3加仓止盈 @开盘 | open ≤ threshold | 开盘止盈 |
| T3加仓止盈 @盘中 | low ≤ threshold | 盘中止盈 |
| T2加仓止盈 @开盘 | open ≤ protect | 开盘止盈 |
| T2加仓止盈 @盘中 | low ≤ protect | 盘中止盈 |
| 战法卖出 | close < MA | 收盘卖出 |
| 时间止损 | trading_days ≥ N | 收盘卖出 |
| 加仓空间止损 @开盘 | open ≤ stop | 开盘止损 |
| 加仓空间止损 @盘中 | low ≤ stop | 盘中止损 |
| 回测结束清仓 | — | 回测结束(清仓) |

区分逻辑：对每个 sell，比较 `today_open` 和卖出触发价 — 如果 open 已经触发 → 开盘，否则盘中。

## 7. 颜色方案

- **买入系**（开盘买入/盘中买入/加仓买入）→ 红色 `#cf2c2c`
- **卖出系**（开盘止损/盘中止损/开盘止盈/盘中止盈/收盘卖出）→ 绿色 `#2c9f4f`
- **信号系**（设置条件单/量能过滤/信号未成交）→ 灰色 `#888`

HTML 表格渲染时按 trade_type 染对应行的文本颜色。

## 8. 量能过滤迁移

量能过滤从 `check_buy` 移出，在设置条件单阶段处理：

- `check_buy` 返回信号 → 正常
- 策略内部（MA55Volume）量能不通过 → `_last_volume_filter` 设值，`check_buy` 返回 None
- Engine 检测到 `_last_volume_filter` → 记录「量能过滤」→ 不设条件单

## 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `strategy_base.py` | 新增 ConditionalOrder dataclass |
| `config.py` | StrategyConfig 加 open_chase_cap_pct |
| `broker.py` | 条件单管理 + 卖出文案细化 + 颜色 logic |
| `engine.py` | 日循环改造 + 涨跌停函数 |
| `config/backtest_strategies.txt` | 加开盘追高上限% |
| `dashboard/pages/04_战法回测.py` | 交易明细颜色渲染 |
| `ma55_volume.py` | 量能过滤挪位（check_buy 恢复纯信号） |
