# 条件单化改造 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 回测引擎从"当天判断当天买"改为"前一天设条件单第二天触发"，卖出分开盘/盘中两阶段。

**Architecture:** Engine 日循环拆为 5 步（开盘卖→开盘买→盘中买→盘中卖→设条件单）。Broker 管理条件单生命周期 + 卖出阶段分离。策略 check_buy 简化为只返回目标价（MA 值），不再处理高开追高逻辑。

**Tech Stack:** Python 3.12, dataclasses, 现有 Streamlit dashboard

## Global Constraints

- 条件单 target_price = MA 值，open_price_cap = target × 配置的 open_chase_cap_pct / 100
- 开盘买入条件: open > target AND open ≤ open_price_cap
- 盘中买入条件: target ∈ [low, high]
- 涨跌停限制按板块动态查（主板 10%，创业板/科创板 20%，北交所 30%）
- 卖出开盘 vs 盘中区分: open ≤ 触发价 → 开盘，否则盘中/收盘
- ④阶段释放的仓位当天不用于买入
- 颜色: 买入系红 #cf2c2c，卖出系绿 #2c9f4f，信号系灰 #888

---

### Task 1: StrategyConfig + 配置文件 — 加 open_chase_cap_pct

**Files:**
- Modify: `src/marketreview/backtest/config.py`
- Modify: `config/backtest_strategies.txt`

**Interfaces:**
- Produces: `StrategyConfig.open_chase_cap_pct: float = 102.0`

- [ ] **Step 1: 加 dataclass 字段 + 默认值**

```python
# config.py — StrategyConfig 加字段
@dataclass
class StrategyConfig:
    ...
    addon_threshold_pct: float = 999.0
    open_chase_cap_pct: float = 102.0   # 开盘追高上限%
```

- [ ] **Step 2: 加 KEY_MAP / FIELD_TYPES / DEFAULTS + constructor 传参**

在 `load_strategies()` 中:

```python
KEY_MAP = {
    ...
    "开盘追高上限%": "open_chase_cap_pct",
}
FIELD_TYPES = {
    ...
    "open_chase_cap_pct": float,
}
DEFAULTS = {
    ...
    "open_chase_cap_pct": 102.0,
}

# _commit_current() 中 strategy 构造加字段:
strategies.append(StrategyConfig(
    ...
    open_chase_cap_pct=cfg["open_chase_cap_pct"],
))
```

- [ ] **Step 3: 配置文件加全局默认项**

在 `backtest_strategies.txt` 的全局段加一行:
```
开盘追高上限%=102
```

- [ ] **Step 4: 验证解析**

```bash
cd i:/AIcode/marketreview && python -c "import sys,io; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8'); from src.marketreview.backtest.config import load_strategies; s=load_strategies()[0]; print(f'open_chase_cap_pct={s.open_chase_cap_pct}')"
```
Expected: `open_chase_cap_pct=102.0`

- [ ] **Step 5: 提交**

```bash
git add src/marketreview/backtest/config.py config/backtest_strategies.txt
git commit -m "feat: StrategyConfig 加 open_chase_cap_pct + 配置文件新增开盘追高上限%"
```

---

### Task 2: ConditionalOrder dataclass

**Files:**
- Modify: `src/marketreview/backtest/strategy_base.py`

**Interfaces:**
- Produces: `ConditionalOrder(date_set, symbol, symbol_name, target_price, open_price_cap, reason, strategy_tag="")`

- [ ] **Step 1: 加 dataclass**

在 `BuySignal` 定义附近（约 line 67 后）加:

```python
@dataclass
class ConditionalOrder:
    """条件单：前一天收盘后设置，第二天触发."""
    date_set: str           # 设置日期 YYYYMMDD
    symbol: str
    symbol_name: str
    target_price: float         # 目标买入价
    open_price_cap: float       # 开盘追高上限
    reason: str                 # 信号原因（来自策略）
    strategy_tag: str = ""
```

- [ ] **Step 2: 验证导入**

```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.backtest.strategy_base import ConditionalOrder; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/marketreview/backtest/strategy_base.py
git commit -m "feat: 新增 ConditionalOrder dataclass"
```

---

### Task 3: Broker — 条件单基础设施

**Files:**
- Modify: `src/marketreview/backtest/broker.py`

**Interfaces:**
- Produces: `Broker.pending_orders`, `Broker.add_order(order)`, `Broker.clear_orders()`, `Broker.process_open_orders(date, today_rows, rng)`, `Broker.process_intraday_orders(date, today_rows, rng)`
- Consumes: `ConditionalOrder` from Task 2

- [ ] **Step 1: 加 import + pending_orders 初始化**

```python
# broker.py 顶部 import
from .strategy_base import Position, ConditionalOrder
from marketreview.log_util import get_logger
import random

# Broker.__init__() 末尾加:
self.pending_orders: list[ConditionalOrder] = []
```

- [ ] **Step 2: 加 add_order + clear_orders**

```python
def add_order(self, order: ConditionalOrder):
    """设置一个明日条件单."""
    self.pending_orders.append(order)

def clear_orders(self):
    """清空所有未触发条件单."""
    self.pending_orders.clear()
```

- [ ] **Step 3: 加 process_open_orders**

```python
def process_open_orders(self, date: str, today_rows: dict[str, dict],
                        rng: random.Random) -> None:
    """② 开盘买入：遍历 shuffled 条件单，仅判断 open 触发."""
    orders = list(self.pending_orders)
    rng.shuffle(orders)
    remaining: list[ConditionalOrder] = []

    for order in orders:
        row = today_rows.get(order.symbol)
        if row is None:
            remaining.append(order)
            continue

        ok, _ = self.can_buy(order.symbol)
        if not ok:
            remaining.append(order)
            continue

        open_p = _safe_f(row.get("open"))
        if open_p > order.target_price and open_p <= order.open_price_cap:
            shares = int(self.init_capital * self.position_pct / 100.0 / open_p)
            if shares == 0:
                remaining.append(order)
                continue
            cost = shares * open_p
            self.cash -= cost
            pos = Position(
                symbol=order.symbol, symbol_name=order.symbol_name,
                buy_date=date, buy_price=open_p,
                shares=shares, cost=cost,
            )
            self.positions[order.symbol] = pos
            self.trades.append(TradeRecord(
                date=date, symbol=order.symbol,
                symbol_name=order.symbol_name,
                trade_type="开盘买入", price=open_p, shares=shares,
                reason=f"追高买入(开盘≤上限{order.open_price_cap:.2f})，{order.reason}",
            ))
            log.info("[%s] 开盘买入 %s %s @ %.2f × %d股 (%s)",
                     self.strategy_name, date, order.symbol_name,
                     open_p, shares, order.reason)
        else:
            remaining.append(order)

    self.pending_orders = remaining
```

- [ ] **Step 4: 加 process_intraday_orders**

```python
def process_intraday_orders(self, date: str, today_rows: dict[str, dict],
                            rng: random.Random) -> None:
    """③ 盘中买入：剩余条件单 target ∈ [low, high] 触发."""
    orders = list(self.pending_orders)
    rng.shuffle(orders)
    remaining: list[ConditionalOrder] = []

    for order in orders:
        row = today_rows.get(order.symbol)
        if row is None:
            remaining.append(order)
            continue

        ok, _ = self.can_buy(order.symbol)
        if not ok:
            remaining.append(order)
            continue

        low_p = _safe_f(row.get("low"))
        high_p = _safe_f(row.get("high"))
        if low_p <= order.target_price <= high_p:
            price = order.target_price
            shares = int(self.init_capital * self.position_pct / 100.0 / price)
            if shares == 0:
                remaining.append(order)
                continue
            cost = shares * price
            self.cash -= cost
            pos = Position(
                symbol=order.symbol, symbol_name=order.symbol_name,
                buy_date=date, buy_price=price,
                shares=shares, cost=cost,
            )
            self.positions[order.symbol] = pos
            self.trades.append(TradeRecord(
                date=date, symbol=order.symbol,
                symbol_name=order.symbol_name,
                trade_type="盘中买入", price=price, shares=shares,
                reason=order.reason,
            ))
            log.info("[%s] 盘中买入 %s %s @ %.2f × %d股 (%s)",
                     self.strategy_name, date, order.symbol_name,
                     price, shares, order.reason)
        else:
            remaining.append(order)

    self.pending_orders = remaining
```

- [ ] **Step 5: 验证语法**

```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.backtest.broker import Broker; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add src/marketreview/backtest/broker.py
git commit -m "feat: Broker 条件单基础设施 — add/clear/process_open/process_intraday"
```

---

### Task 4: Broker — 卖出阶段分离 + 文案细化

**Files:**
- Modify: `src/marketreview/backtest/broker.py`

**Interfaces:**
- Produces: `Broker.execute_open_sells(date, today_rows)`, `Broker.execute_intraday_sells(date, today_rows)`
- Called by engine ① and ④ phases

- [ ] **Step 1: 加 _safe_f import (如未导入)**

检查 broker.py 顶部是否有 `_safe_f` 辅助函数。如果没有，加在文件尾部或设成模块级函数:

```python
def _safe_f(v) -> float:
    if v is None: return 0.0
    try: return float(v)
    except (ValueError, TypeError): return 0.0
```

- [ ] **Step 2: 加 execute_open_sells**

```python
def execute_open_sells(self, date: str, today_rows: dict[str, dict]) -> None:
    """① 开盘卖出：检查所有持仓，open ≤ 止损/止盈触发价则卖出."""
    for sym in list(self.positions.keys()):
        pos = self.positions.get(sym)
        if pos is None:
            continue
        row = today_rows.get(sym)
        if row is None:
            continue
        open_p = _safe_f(row.get("open"))
        if open_p <= 0:
            continue

        # ── 加仓部分（先判断，因为卖出是独立的）──
        if pos.addon_shares > 0:
            addon_stop = pos.addon_price * (1 - self.space_stop_pct / 100.0)
            if open_p <= addon_stop:
                self.sell_addon(date, sym, open_p,
                    f"开盘止损(加仓{self.space_stop_pct:.0f}%)")
            else:
                self._check_addon_open_tp(date, sym, open_p)

        # ── 基础仓位空间止损 ──
        if sym not in self.positions:
            continue  # 加仓卖出不影响基础仓位
        stop_price = pos.buy_price * (1 - self.space_stop_pct / 100.0)
        if open_p <= stop_price:
            self.sell(date, sym, open_p,
                f"开盘止损({self.space_stop_pct:.0f}%)")

def _check_addon_open_tp(self, date: str, sym: str, open_p: float) -> None:
    """加仓开盘止盈检查."""
    pos = self.positions.get(sym)
    if pos is None or pos.addon_shares == 0:
        return
    mfp = pos.addon_mfp_pct
    if mfp >= self.tp_tier3_mfp:
        threshold = pos.addon_price * (1 + mfp * self.tp_tier3_protect / 100.0)
        if open_p <= threshold:
            self.sell_addon(date, sym, open_p,
                f"开盘止盈(浮盈曾达{mfp:.1f}%)")
    elif mfp >= self.tp_tier2_mfp:
        protect = pos.addon_price * self.tp_tier2_protect_ratio
        if open_p <= protect:
            pct = (self.tp_tier2_protect_ratio - 1) * 100
            self.sell_addon(date, sym, open_p,
                f"开盘止盈(浮盈曾达{mfp:.1f}%→保{pct:.0f}%)")
```

- [ ] **Step 3: 加 execute_intraday_sells**

```python
def execute_intraday_sells(self, date: str, today_rows: dict[str, dict]) -> None:
    """④ 盘中卖出：低价触及止损/止盈 → 盘中止损/止盈."""
    for sym in list(self.positions.keys()):
        pos = self.positions.get(sym)
        if pos is None:
            continue
        row = today_rows.get(sym)
        if row is None:
            continue
        open_p = _safe_f(row.get("open"))
        low_p = _safe_f(row.get("low"))
        if low_p <= 0:
            continue

        # ── 加仓部分 ──
        if pos.addon_shares > 0:
            addon_stop = pos.addon_price * (1 - self.space_stop_pct / 100.0)
            if low_p <= addon_stop:
                # 如果开盘已经触发则跳过（已在 execute_open_sells 处理）
                if open_p <= 0 or open_p > addon_stop:
                    self.sell_addon(date, sym, addon_stop,
                        f"盘中止损(加仓{self.space_stop_pct:.0f}%)")
                continue
            self._check_addon_intraday_tp(date, sym, open_p, low_p)

        # ── 基础仓位空间止损 ──
        if sym not in self.positions:
            continue
        stop_price = pos.buy_price * (1 - self.space_stop_pct / 100.0)
        if low_p <= stop_price:
            if open_p <= 0 or open_p > stop_price:
                self.sell(date, sym, stop_price,
                    f"盘中止损({self.space_stop_pct:.0f}%)")

def _check_addon_intraday_tp(self, date: str, sym: str,
                              open_p: float, low_p: float) -> None:
    """加仓盘中止盈检查."""
    pos = self.positions.get(sym)
    if pos is None or pos.addon_shares == 0:
        return
    mfp = pos.addon_mfp_pct
    triggered = False
    if mfp >= self.tp_tier3_mfp:
        threshold = pos.addon_price * (1 + mfp * self.tp_tier3_protect / 100.0)
        if low_p <= threshold and (open_p <= 0 or open_p > threshold):
            self.sell_addon(date, sym, threshold,
                f"盘中止盈(浮盈曾达{mfp:.1f}%)")
            triggered = True
    if not triggered and mfp >= self.tp_tier2_mfp:
        protect = pos.addon_price * self.tp_tier2_protect_ratio
        if low_p <= protect and (open_p <= 0 or open_p > protect):
            pct = (self.tp_tier2_protect_ratio - 1) * 100
            self.sell_addon(date, sym, protect,
                f"盘中止盈(浮盈曾达{mfp:.1f}%→保{pct:.0f}%)")
```

- [ ] **Step 4: 删除旧的 check_space_stop / check_addon_space_stop / check_addon_take_profit**

这几方法不再需要（逻辑已迁入 execute_open_sells / execute_intraday_sells）。也删掉 engine.py 中对它们的调用（Task 6 处理）。

在 broker.py 中删除: `check_space_stop`, `check_addon_take_profit`, `check_addon_space_stop`（约 204-335 行）

- [ ] **Step 5: 验证语法**

```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.backtest.broker import Broker; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add src/marketreview/backtest/broker.py
git commit -m "refactor: 卖出分拆为开盘/盘中两阶段 + 文案细化(开盘止损/盘中止损/开盘止盈/盘中止盈)"
```

---

### Task 5: Engine — 工具函数 + MABreakthroughStrategy 简化

**Files:**
- Modify: `src/marketreview/backtest/engine.py`
- Modify: `src/marketreview/backtest/strategies/ma_breakthrough.py`

**Interfaces:**
- Produces: `get_limit_pct(code) -> float`, `_build_today_rows(date) -> dict[str, dict]`
- Changes: `MABreakthroughStrategy.check_buy` 移除高开追高逻辑，只返回 `price=ma`

- [ ] **Step 1: 加 get_limit_pct 函数**

在 engine.py 模块级别（`class BacktestEngine` 之前）:

```python
def get_limit_pct(code: str) -> float:
    """根据股票代码返回涨跌停幅度."""
    if code.startswith(("600", "601", "603", "605",
                        "000", "001", "002", "003")):
        return 0.10
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith("8"):
        return 0.30
    return 0.10
```

- [ ] **Step 2: 加 _build_today_rows 方法**

在 BacktestEngine 类中:

```python
def _build_today_rows(self, date: str) -> dict[str, dict]:
    """构建 {symbol: kline_row} 字典，供 broker 方法使用."""
    result: dict[str, dict] = {}
    for code, klines in self._klines.items():
        row = self._get_day(klines, date)
        if row is not None:
            result[code] = row
    return result
```

- [ ] **Step 3: 简化 MABreakthroughStrategy.check_buy — 移除高开追高**

当前 `ma_breakthrough.py` 的 check_buy 中，突破分支有复杂的高开判断。简化为只返回 `price=ma`:

```python
# 突破：昨收在MA下方，今日最高价上穿MA
if prev_close > 0 and prev_close < ma_yest and ctx.high >= ma:
    return BuySignal(
        date=ctx.date, symbol=ctx.symbol,
        symbol_name=ctx.symbol_name,
        price=ma, reason=f"突破MA{self.ma_period}",
    )
```

删除之前加入的高开/追高/跌回判断（约 10 行 → 5 行）。

- [ ] **Step 4: 验证语法**

```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.backtest.engine import BacktestEngine, get_limit_pct; print(get_limit_pct('600000.SH')); print(get_limit_pct('300750.SZ'))"
```
Expected: `0.1` 和 `0.2`

- [ ] **Step 5: 提交**

```bash
git add src/marketreview/backtest/engine.py src/marketreview/backtest/strategies/ma_breakthrough.py
git commit -m "feat: get_limit_pct + _build_today_rows + MABreakthroughStrategy 简化为只返回 MA 目标价"
```

---

### Task 6: Engine — 日循环重构

**Files:**
- Modify: `src/marketreview/backtest/engine.py`

**Interfaces:**
- Consumes: Broker 新方法 (process_open_orders, process_intraday_orders, execute_open_sells, execute_intraday_sells, clear_orders, add_order)
- Changes: 日循环从旧 4 步改为新 5 步

- [ ] **Step 1: 重构 sell 部分（① + ④ 替代原有 sell checks）**

替换原有 sell block (约 lines 176-265)，新结构如下。

原有代码位置参考 (engine.py 约 158-268 行的日循环主体):

```python
for date in trade_dates:
    stocks_today = list(self.pool.stocks)
    rng.shuffle(stocks_today)

    # 构建今日行情快照
    today_rows = self._build_today_rows(date)

    # ── ① 开盘卖出 ──
    # 先更新 MFP（用于止盈判断）
    for sym in list(self.broker.positions.keys()):
        row = today_rows.get(sym)
        if row:
            self.broker.update_max_float_profit(sym, _safe_f(row.get("high")))
            pos = self.broker.positions.get(sym)
            if pos and pos.addon_shares > 0:
                self.broker.update_addon_mfp(sym, _safe_f(row.get("high")))
    self.broker.execute_open_sells(date, today_rows)
    self._enrich_positions(date)

    # ── ② 开盘买入 ──
    self.broker.process_open_orders(date, today_rows, rng)
    self._enrich_positions(date)

    # ── ③ 盘中买入 ──
    self.broker.process_intraday_orders(date, today_rows, rng)
    self._enrich_positions(date)

    # ── 浮盈加仓（④之前，因为加仓可能是盘中触发）──
    for sym in list(self.broker.positions.keys()):
        pos = self.broker.positions.get(sym)
        if pos is None or pos.addon_count >= 1:
            continue
        if self._addon_threshold_pct >= 999:
            continue
        if pos.max_float_profit_pct < self._addon_threshold_pct:
            continue
        row = today_rows.get(sym)
        if row is None:
            continue
        trigger_price = pos.buy_price * (1 + self._addon_threshold_pct / 100.0)
        today_open = _safe_f(row.get("open"))
        today_high = _safe_f(row.get("high"))
        if today_open > trigger_price:
            entry_price = today_open
        elif today_high >= trigger_price:
            entry_price = trigger_price
        else:
            entry_price = 0.0
        if entry_price > 0:
            addon_shares = pos.shares // 2
            self.broker.addon_buy(date, sym, entry_price, addon_shares)
            self._enrich_positions(date)

    # ── ④ 盘中+收盘卖出 ──
    self.broker.execute_intraday_sells(date, today_rows)
    self._enrich_positions(date)

    # 策略卖出（收盘） + 时间止损
    for s in stocks_today:
        if not s.code or s.code not in self.broker.positions:
            continue
        ctx = self._build_ctx(date, s,
            today_rows.get(s.code, {}), self._klines.get(s.code, []),
            self._in_window(s, date))
        if ctx.position is None:
            ctx.position = self.broker.positions.get(s.code)
        sell_sig = self.strategy.check_sell(ctx)
        if sell_sig:
            # 战法卖出和时间止损都是收盘价
            label = "收盘卖出"
            self.broker.sell(date, s.code, sell_sig.price,
                f"{label}({sell_sig.reason})")
            self._enrich_positions(date)

    # ── ⑤ 条件单设置 ──
    self.broker.clear_orders()
    for s in stocks_today:
        if not s.code:
            continue
        if s.code in self.broker.positions:
            continue
        if not self._in_window(s, date):
            continue
        klines = self._klines.get(s.code, [])
        today_row = today_rows.get(s.code)
        if today_row is None:
            continue
        ctx = self._build_ctx(date, s, today_row, klines, True)
        ctx.position = None
        buy_sig = self.strategy.check_buy(ctx)
        if buy_sig is None:
            # 检查量能过滤
            vol_filter = getattr(self.strategy, '_last_volume_filter', None)
            if vol_filter:
                self.broker.report_volume_filter(
                    vol_filter["date"], vol_filter["symbol"],
                    vol_filter["symbol_name"], vol_filter["price"],
                    vol_filter["reason"],
                )
                self.strategy._last_volume_filter = None
            continue

        # 判断明天能不能到（涨跌停限制）
        today_close = _safe_f(today_row.get("close"))
        target = buy_sig.price
        limit = get_limit_pct(s.code)
        if today_close * (1 - limit) > target or target > today_close * (1 + limit):
            continue  # 明天到不了，不设单

        # 设条件单
        open_cap = target * self.strategy_cfg.open_chase_cap_pct / 100.0
        order = ConditionalOrder(
            date_set=date,
            symbol=s.code,
            symbol_name=s.name,
            target_price=target,
            open_price_cap=open_cap,
            reason=buy_sig.reason,
        )
        self.broker.add_order(order)
        self.broker.trades.append(TradeRecord(
            date=date, symbol=s.code, symbol_name=s.name,
            trade_type="设置条件单", price=target,
            reason=f"目标价={target:.2f} 开盘上限≤{open_cap:.2f} {buy_sig.reason}",
        ))

    # ── 日终权益快照 ──
    pos_prices_daily = {}
    for pcode in self.broker.positions:
        prow = today_rows.get(pcode)
        if prow:
            pos_prices_daily[pcode] = _safe_f(prow.get("close"))
    market_eq = self.broker.get_market_equity(pos_prices_daily)
    equity_curve.append({
        "date": date,
        "equity": market_eq,
        "return_pct": (market_eq / self.broker.init_capital - 1) * 100.0,
    })
```

- [ ] **Step 2: 确保 ConditionalOrder 已 import**

engine.py 顶部 import 加 `ConditionalOrder`:
```python
from .strategy_base import (
    BaseStrategy, DayContext, create_strategy, Position,
    ConditionalOrder,  # 新增
)
```

- [ ] **Step 3: 删除 _enrich_positions 中的冗余调用**

`_enrich_positions` 保留不动——它在关键成交点后附加持仓快照。

- [ ] **Step 4: 验证语法 + 导入**

```bash
cd i:/AIcode/marketreview && python -c "from src.marketreview.backtest.engine import BacktestEngine; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add src/marketreview/backtest/engine.py
git commit -m "refactor: Engine 日循环重构为 5 步 — 开盘卖→开盘买→盘中买→盘中卖→设条件单"
```

---

### Task 7: Dashboard — 交易明细颜色渲染

**Files:**
- Modify: `dashboard/pages/04_战法回测.py`

- [ ] **Step 1: 改造 _render_html_table 加颜色逻辑**

在 `_render_html_table` 函数中，按 trade_type 染色。找到 cell 渲染行（约 line 26-31），改为:

```python
# 颜色分类
def _trade_color(trade_type: str) -> str:
    if trade_type in ("开盘买入", "盘中买入", "加仓买入", "买入"):
        return "#cf2c2c"  # 红色 买入系
    if "卖出" in trade_type or "止损" in trade_type or "止盈" in trade_type:
        return "#2c9f4f"  # 绿色 卖出系
    return "#888"  # 灰色 信号系

for i, row in enumerate(rows):
    bg = "#fafafa" if i % 2 == 0 else "#fff"
    cells = "".join(
        f'<td style="white-space:normal;word-wrap:break-word;overflow-wrap:break-word;'
        f'padding:4px 8px;vertical-align:top;width:{widths.get(k, "auto")};'
        f'color:{_trade_color(row.get("类型", ""))}">'
        f'{row.get(k, "")}</td>'
        for k in keys
    )
    body_rows.append(f'<tr style="background:{bg}">{cells}</tr>')
```

- [ ] **Step 2: 验证语法**

```bash
cd i:/AIcode/marketreview && python -c "from dashboard.pages import 04_战法回测; print('OK')" 2>&1 || echo "(streamlit 模块在非 streamlit 环境导入可能报错，忽略)"
```

- [ ] **Step 3: 提交**

```bash
git add dashboard/pages/04_战法回测.py
git commit -m "feat: 交易明细颜色渲染 — 买入红/卖出绿/信号灰"
```

---

### Task 8: 版本 bump + 完整重启验证

**Files:**
- Modify: `dashboard/services/dashboard_service.py`

- [ ] **Step 1: Bump 版本**

```python
_AI_VERSION = "1.34.0"  # 大重构 bump Y
```

- [ ] **Step 2: 重启验证**

```bash
cd i:/AIcode/marketreview && python restart_streamlit.py
```

- [ ] **Step 3: 页面冒烟测试**

在 04_战法回测 页面加载数据、回测，检查:
- 交易明细里有「设置条件单」「开盘买入」「盘中买入」新类型
- 颜色正确（买入红/卖出绿/信号灰）
- 卖出标注 开盘止损/盘中止损/开盘止盈/盘中止盈/收盘卖出
- 量能过滤记录正常

- [ ] **Step 4: 提交**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "chore: bump AI version to 1.34.0 — 条件单化大重构"
```
