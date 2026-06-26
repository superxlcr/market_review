# 战法回测引擎 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Dashboard 中新增战法回测引擎，支持自定义股票池+策略，日线级回测买卖点成功率。

**Architecture:** 新增 `src/marketreview/backtest/` 包，策略通过抽象接口 `BaseStrategy` 定义，引擎统一处理 T+1/仓位/空间止损。所有数据走 `DataProvider` 复用现有层。Dashboard 新增第 4 页"战法回测"。

**Tech Stack:** Python 3.10+, Streamlit, Plotly, SQLite (existing), 无需新依赖

## Global Constraints

- Python >=3.10,<3.14 — per pyproject.toml
- 数据只能通过 DataProvider 访问，不直连 SQLite — per CLAUDE.md
- 所有 DB 日期 YYYYMMDD — per date-format-convention
- Red=bullish, Green=bearish — per color-convention
- 每次改动 bump `_AI_VERSION` in `dashboard/services/dashboard_service.py` — per ai-version-number
- Streamlit modules are cached — 修改代码后必须杀进程+清 pycache+重启
- Cache reads MUST filter by date — 不用 bare LIMIT N

---

### Task 1: Config Parser — 股票池 & 策略配置文件解析

**Files:**
- Create: `src/marketreview/backtest/__init__.py`
- Create: `src/marketreview/backtest/config.py`

**Interfaces:**
- Produces: `PoolConfig(name, stocks: list[StockEntry])`, `StockEntry(name, code, entry_date, exit_date)`
- Produces: `StrategyConfig(name, class_name, position_pct, max_positions, space_stop_pct)`
- Produces: `load_pools(dp: DataProvider) -> list[PoolConfig]`
- Produces: `load_strategies() -> list[StrategyConfig]`

- [ ] **Step 1: Create `__init__.py`**

```python
# src/marketreview/backtest/__init__.py
"""战法回测引擎 — strategy backtesting framework."""
```

- [ ] **Step 2: Create config.py with dataclasses and parsers**

```python
# src/marketreview/backtest/config.py
"""Parse backtest pool & strategy configuration files."""
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


@dataclass
class StockEntry:
    """A single stock in a pool with its discovery window."""
    name: str          # user-facing name, e.g. "顺络电子"
    code: str = ""     # resolved ts_code, e.g. "002138.SZ"
    entry_date: str = ""    # YYYYMMDD
    exit_date: str = ""     # YYYYMMDD or "now"


@dataclass
class PoolConfig:
    """A named stock pool."""
    name: str
    stocks: list[StockEntry] = field(default_factory=list)


@dataclass
class StrategyConfig:
    """A named strategy configuration."""
    name: str             # display name, e.g. "MA60_突破拉回_3止损"
    class_name: str       # strategy class key, e.g. "ma60_breakthrough"
    position_pct: float   # 0~100, e.g. 20 means 20% per trade
    max_positions: int    # max concurrent positions
    space_stop_pct: float # 0~100, e.g. 3 means -3% stop loss


def load_pools(dp) -> list[PoolConfig]:
    """Parse backtest_pools.txt, resolve stock names to ts_code via dp."""
    path = CONFIG_DIR / "backtest_pools.txt"
    if not path.exists():
        return []

    pools: list[PoolConfig] = []
    current_pool: PoolConfig | None = None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                name = line[1:-1]
                current_pool = PoolConfig(name=name)
                pools.append(current_pool)
                continue
            if current_pool is not None:
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    entry_date = parts[1]
                    exit_date = parts[2] if len(parts) > 2 else "now"
                    # resolve stock name → ts_code
                    code = _resolve_stock_name(dp, name)
                    current_pool.stocks.append(
                        StockEntry(name=name, code=code,
                                   entry_date=entry_date, exit_date=exit_date)
                    )
    return pools


def _resolve_stock_name(dp, name: str) -> str:
    """Resolve a Chinese stock name to ts_code via stock_basic_cache."""
    rows = dp.cache.fetch_all(
        "SELECT ts_code FROM stock_basic_cache WHERE name = ?", (name,)
    )
    if rows:
        return rows[0][0]
    # fallback: if name already looks like a code (e.g. "000001.SZ"), use as-is
    if "." in name and len(name) == 9:
        return name
    return ""  # unresolved — caller should check and report


def load_strategies() -> list[StrategyConfig]:
    """Parse backtest_strategies.txt.
    Format: 策略名 战法类名 仓位% 开仓上限 空间止损%
    """
    path = CONFIG_DIR / "backtest_strategies.txt"
    if not path.exists():
        return []

    strategies: list[StrategyConfig] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 5:
                strategies.append(StrategyConfig(
                    name=parts[0],
                    class_name=parts[1],
                    position_pct=float(parts[2]),
                    max_positions=int(parts[3]),
                    space_stop_pct=float(parts[4]),
                ))
    return strategies
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/backtest/__init__.py src/marketreview/backtest/config.py
git commit -m "feat: add backtest config parser — pool + strategy txt files"
```

---

### Task 2: Strategy Base Interface — dataclasses + ABC

**Files:**
- Create: `src/marketreview/backtest/strategy_base.py`

**Interfaces:**
- Produces: `DayContext`, `BuySignal`, `SellSignal`, `Position`, `BaseStrategy`

- [ ] **Step 1: Create strategy_base.py**

```python
# src/marketreview/backtest/strategy_base.py
"""Strategy interface — each 战法 implements check_buy and check_sell."""
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Optional


@dataclass
class Position:
    """Current holding — tracked by engine."""
    symbol: str
    symbol_name: str
    buy_date: str
    buy_price: float
    shares: int
    cost: float               # total cost = buy_price * shares
    max_float_profit_pct: float = 0.0  # highest intraday gain since buy


@dataclass
class DayContext:
    """Per-day context passed to strategy check methods."""
    date: str                      # YYYYMMDD
    symbol: str                    # ts_code
    symbol_name: str               # user-facing name
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    ma60: float                    # today's MA60
    ma60_yesterday: float          # yesterday's MA60
    kline_history: list = field(default_factory=list)  # list[dict] up to today
    in_pool_window: bool = True    # whether still within entry~exit window
    position: Optional[Position] = None  # current holding for this stock


@dataclass
class BuySignal:
    """Buy signal from strategy."""
    date: str
    symbol: str
    symbol_name: str
    price: float           # suggested entry price
    reason: str            # "突破MA60" | "拉回MA60"


@dataclass
class SellSignal:
    """Sell signal from strategy (not space stop — that's engine-layer)."""
    date: str
    symbol: str
    symbol_name: str
    price: float
    reason: str            # "止盈" | "战法止损" | "战法卖出"


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy display name."""
        ...

    @property
    def lookback_trading_days(self) -> int:
        """Min K-line bars needed before producing signals. Default 60 for MA60."""
        return 60

    @abstractmethod
    def check_buy(self, ctx: DayContext) -> Optional[BuySignal]:
        """Return a buy signal or None."""
        ...

    @abstractmethod
    def check_sell(self, ctx: DayContext) -> Optional[SellSignal]:
        """Return a sell signal (strategy-level stop/take-profit) or None.
        Space stop-loss is handled by engine, NOT here."""
        ...


# Registry of strategy class_name → class
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(name: str):
    """Decorator to register a strategy class."""
    def dec(cls):
        STRATEGY_REGISTRY[name] = cls
        return cls
    return dec


def create_strategy(class_name: str) -> Optional[BaseStrategy]:
    """Factory: instantiate a strategy by its registered class_name."""
    cls = STRATEGY_REGISTRY.get(class_name)
    if cls is None:
        return None
    return cls()
```

- [ ] **Step 2: Commit**

```bash
git add src/marketreview/backtest/strategy_base.py
git commit -m "feat: add strategy base interface — DayContext, BuySignal, SellSignal, BaseStrategy"
```

---

### Task 3: Broker — 虚拟券商（资金管理 + 持仓管理）

**Files:**
- Create: `src/marketreview/backtest/broker.py`

**Interfaces:**
- Consumes: `Position` from `strategy_base.py`
- Produces: `Broker(buy, sell, can_buy, positions, cash, equity)`

- [ ] **Step 1: Create broker.py**

```python
# src/marketreview/backtest/broker.py
"""Virtual broker — cash accounting, position tracking, T+1 enforcement."""
from dataclasses import dataclass, field
from .strategy_base import Position


@dataclass
class TradeRecord:
    """One completed trade or signal."""
    date: str
    symbol: str
    symbol_name: str
    trade_type: str       # "买入" | "卖出" | "信号未成交"
    price: float
    shares: int = 0
    pnl_pct: float = 0.0  # profit/loss % for sells
    reason: str = ""      # exit reason or skip reason


class Broker:
    """Manages cash, positions, and enforces T+1 + position cap."""

    def __init__(self, init_capital: float = 1_000_000,
                 position_pct: float = 20.0,
                 max_positions: int = 2,
                 space_stop_pct: float = 3.0):
        self.init_capital = init_capital
        self.cash = init_capital
        self.position_pct = position_pct    # % per trade
        self.max_positions = max_positions
        self.space_stop_pct = space_stop_pct
        self.positions: dict[str, Position] = {}   # symbol → Position
        self.trades: list[TradeRecord] = []

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def equity(self) -> float:
        """Total equity = cash + market value of all positions."""
        mv = sum(
            p.shares * p.buy_price for p in self.positions.values()
        )  # book value (not marked-to-market intraday)
        return self.cash + mv

    def can_buy(self, symbol: str) -> tuple[bool, str]:
        """Check if a new buy is allowed. Returns (allowed, reason)."""
        if symbol in self.positions:
            return False, "已持仓"
        if self.position_count >= self.max_positions:
            return False, "已达开仓上限"
        trade_amount = self.init_capital * self.position_pct / 100.0
        if self.cash < trade_amount:
            return False, "资金不足"
        return True, ""

    def buy(self, date: str, symbol: str, symbol_name: str,
            price: float, reason: str = "") -> Position | None:
        """Execute a buy. Returns Position or None if rejected."""
        ok, reject_reason = self.can_buy(symbol)
        if not ok:
            self.trades.append(TradeRecord(
                date=date, symbol=symbol, symbol_name=symbol_name,
                trade_type="信号未成交", price=price, reason=reject_reason,
            ))
            return None

        trade_amount = self.init_capital * self.position_pct / 100.0
        shares = int(trade_amount / price)
        if shares == 0:
            self.trades.append(TradeRecord(
                date=date, symbol=symbol, symbol_name=symbol_name,
                trade_type="信号未成交", price=price, reason="资金不足(整手不够)",
            ))
            return None

        cost = shares * price
        self.cash -= cost
        pos = Position(
            symbol=symbol, symbol_name=symbol_name,
            buy_date=date, buy_price=price,
            shares=shares, cost=cost,
        )
        self.positions[symbol] = pos
        self.trades.append(TradeRecord(
            date=date, symbol=symbol, symbol_name=symbol_name,
            trade_type="买入", price=price, shares=shares,
        ))
        return pos

    def sell(self, date: str, symbol: str, price: float,
             reason: str) -> Position | None:
        """Execute a sell. Returns the closed Position, or None."""
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None

        proceeds = pos.shares * price
        self.cash += proceeds
        pnl_pct = (price - pos.buy_price) / pos.buy_price * 100.0

        self.trades.append(TradeRecord(
            date=date, symbol=symbol, symbol_name=pos.symbol_name,
            trade_type="卖出", price=price, shares=pos.shares,
            pnl_pct=pnl_pct, reason=reason,
        ))
        return pos

    def check_space_stop(self, date: str, symbol: str,
                         today_low: float, today_open: float) -> str:
        """Check if space stop-loss triggers. Returns reason or ''."""
        pos = self.positions.get(symbol)
        if pos is None:
            return ""

        stop_price = pos.buy_price * (1 - self.space_stop_pct / 100.0)

        # Intraday stop: low touched stop price → sell at stop price
        if today_low <= stop_price:
            self.sell(date, symbol, stop_price, "空间止损")
            return "空间止损"
        return ""

    def check_delayed_stop(self, date: str, symbol: str,
                           today_open: float) -> str:
        """Execute yesterday's unexecuted space stop at today's open.
        Called at market open for positions flagged for delayed stop.
        Engine tracks which positions need this via a set.
        """
        pos = self.positions.get(symbol)
        if pos is None:
            return ""

        stop_price = pos.buy_price * (1 - self.space_stop_pct / 100.0)
        # If yesterday's low was above stop but today open gaps below → sell
        if today_open <= stop_price:
            self.sell(date, symbol, stop_price, "空间止损(次日开盘)")
            return "空间止损(次日开盘)"
        return ""

    def update_max_float_profit(self, symbol: str, today_high: float):
        """Update the max floating profit for a position."""
        pos = self.positions.get(symbol)
        if pos is None:
            return
        current_float = (today_high - pos.buy_price) / pos.buy_price * 100.0
        if current_float > pos.max_float_profit_pct:
            pos.max_float_profit_pct = current_float
```

- [ ] **Step 2: Commit**

```bash
git add src/marketreview/backtest/broker.py
git commit -m "feat: add Broker — virtual cash, T+1, position cap, space stop-loss"
```

---

### Task 4: Reporter — 统计报表

**Files:**
- Create: `src/marketreview/backtest/reporter.py`

**Interfaces:**
- Consumes: `TradeRecord` list from Broker
- Produces: `Report`, `StockSummary`

- [ ] **Step 1: Create reporter.py**

```python
# src/marketreview/backtest/reporter.py
"""Compute statistics from trade records."""
from dataclasses import dataclass, field
from .broker import TradeRecord


@dataclass
class StockSummary:
    """Per-stock trade statistics."""
    symbol_name: str
    symbol: str
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0.0
    cumulative_pnl_pct: float = 0.0
    avg_hold_days: float = 0.0
    profit_loss_ratio: float = 0.0


@dataclass
class Report:
    """Full backtest report."""
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_days: float = 0.0
    avg_win_pct: float = 0.0
    avg_lose_pct: float = 0.0
    profit_loss_ratio: float = 0.0
    stock_summaries: list[StockSummary] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)


def build_report(trades: list[TradeRecord],
                 equity_curve: list[dict]) -> Report:
    """Build a Report from trade records and equity curve."""
    report = Report(trades=trades, equity_curve=equity_curve)

    # Filter completed sell trades
    completed = [t for t in trades if t.trade_type == "卖出"]
    report.total_trades = len(completed)
    report.win_trades = sum(1 for t in completed if t.pnl_pct > 0)
    report.lose_trades = sum(1 for t in completed if t.pnl_pct <= 0)
    report.win_rate = report.win_trades / report.total_trades \
        if report.total_trades > 0 else 0.0

    # Aggregate PnL
    wins = [t for t in completed if t.pnl_pct > 0]
    losses = [t for t in completed if t.pnl_pct <= 0]
    report.avg_win_pct = sum(t.pnl_pct for t in wins) / len(wins) \
        if wins else 0.0
    report.avg_lose_pct = sum(abs(t.pnl_pct) for t in losses) / len(losses) \
        if losses else 0.0
    report.profit_loss_ratio = report.avg_win_pct / report.avg_lose_pct \
        if report.avg_lose_pct > 0 else 0.0

    # Total return from equity curve
    if equity_curve:
        report.total_return_pct = equity_curve[-1]["return_pct"]
        # Max drawdown
        peak = 0.0
        max_dd = 0.0
        for pt in equity_curve:
            if pt["equity"] > peak:
                peak = pt["equity"]
            dd = (peak - pt["equity"]) / peak * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        report.max_drawdown_pct = max_dd

    # Average hold days — match buy/sell pairs
    buys_by_symbol: dict[str, list[TradeRecord]] = {}
    for t in trades:
        if t.trade_type == "买入":
            buys_by_symbol.setdefault(t.symbol, []).append(t)
    hold_days_list = []
    for t in completed:
        symbol_buys = buys_by_symbol.get(t.symbol, [])
        # Find the most recent unmatched buy before this sell
        for b in reversed(symbol_buys):
            if b.date <= t.date:
                d1 = _date_to_int(b.date)
                d2 = _date_to_int(t.date)
                # crude calendar days; convert to trading days estimate
                hold_days_list.append(max(1, int((d2 - d1) / 1.0)))
                symbol_buys.remove(b)
                break
    report.avg_hold_days = sum(hold_days_list) / len(hold_days_list) \
        if hold_days_list else 0.0

    # Per-stock summaries
    stock_map: dict[str, list[TradeRecord]] = {}
    for t in trades:
        stock_map.setdefault(t.symbol, []).append(t)

    for symbol, sym_trades in stock_map.items():
        sym_completed = [t for t in sym_trades if t.trade_type == "卖出"]
        sym_wins = sum(1 for t in sym_completed if t.pnl_pct > 0)
        sym_losses = sum(1 for t in sym_completed if t.pnl_pct <= 0)
        sym_total = len(sym_completed)

        sum_win = sum(t.pnl_pct for t in sym_completed if t.pnl_pct > 0)
        sum_lose = sum(abs(t.pnl_pct) for t in sym_completed if t.pnl_pct <= 0)
        avg_win = sum_win / sym_wins if sym_wins > 0 else 0.0
        avg_lose = sum_lose / sym_losses if sym_losses > 0 else 0.0

        report.stock_summaries.append(StockSummary(
            symbol_name=sym_trades[0].symbol_name if sym_trades else "",
            symbol=symbol,
            total_trades=sym_total,
            win_trades=sym_wins,
            lose_trades=sym_losses,
            win_rate=sym_wins / sym_total if sym_total > 0 else 0.0,
            cumulative_pnl_pct=sum(t.pnl_pct for t in sym_completed),
            avg_hold_days=0.0,  # simplified
            profit_loss_ratio=avg_win / avg_lose if avg_lose > 0 else 0.0,
        ))

    return report


def _date_to_int(d: str) -> int:
    """Convert YYYYMMDD to int."""
    return int(d.replace("-", ""))
```

- [ ] **Step 2: Commit**

```bash
git add src/marketreview/backtest/reporter.py
git commit -m "feat: add Reporter — trade statistics + equity curve analysis"
```

---

### Task 5: DataProvider — 按代码+日期范围加载数据

**Files:**
- Modify: `src/marketreview/data/data_provider.py`

**Interfaces:**
- Produces: `ensure_data_loaded_for_codes(self, codes: list[str], start_date: str, end_date: str) -> None`

- [ ] **Step 1: Add `ensure_data_loaded_for_codes` method**

Open `data_provider.py`, find the end of the `ensure_data_loaded` method block (around line 200+), and add after it:

```python
    def ensure_data_loaded_for_codes(
        self, codes: list[str], start_date: str, end_date: str,
        progress_cb=None,
    ) -> None:
        """Ensure K-line data exists for specific codes in [start_date, end_date].

        Much lighter than ensure_data_loaded — only fetches the given codes,
        no indices, no stock_basic, no industry data.
        """
        import time as _time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        start_date = start_date.replace("-", "")
        end_date = end_date.replace("-", "")

        # Check which codes have coverage gaps
        missing: dict[str, tuple[str, str]] = {}  # code → (fetch_start, fetch_end)
        for code in codes:
            cache_start = self.cache.get_earliest_date(code)
            cache_end = self.cache.get_latest_date(code)

            fetch_start = start_date
            fetch_end = end_date

            if cache_start is None or cache_end is None:
                # No data at all
                missing[code] = (start_date, end_date)
                continue

            cstart = cache_start.replace("-", "")
            cend = cache_end.replace("-", "")

            if cstart > start_date or cend < end_date:
                # Has gaps — re-fetch the full range for simplicity
                missing[code] = (start_date, end_date)

        if not missing:
            return

        # Fetch each missing code
        total = len(missing)
        done = 0
        if progress_cb:
            progress_cb("init", 0, total)

        for code, (fs, fe) in missing.items():
            try:
                self._fetch_code_range(code, fs, fe)
            except Exception as e:
                log.warning("ensure_data_loaded_for_codes: fetch failed for %s: %s", code, e)
            done += 1
            if progress_cb:
                progress_cb("step", done, total)
```

- [ ] **Step 2: Add `_fetch_code_range` helper**

Add after the new method:

```python
    def _fetch_code_range(self, code: str, start_date: str, end_date: str):
        """Fetch K-line for one code over a date range. Minimal version."""
        from marketreview.tools.technical import rows_to_df
        import time as _time

        pages = []
        # Tushare daily API: paginate by date
        page = 0
        while True:
            page += 1
            try:
                if code.endswith(".SH") or code.endswith(".SZ"):
                    df = self._api.daily(
                        ts_code=code,
                        start_date=start_date,
                        end_date=end_date,
                        limit=5000,
                        offset=(page - 1) * 5000,
                    )
                else:
                    # Index
                    df = self._api.index_daily(
                        ts_code=code,
                        start_date=start_date,
                        end_date=end_date,
                        limit=5000,
                        offset=(page - 1) * 5000,
                    )
                if df is None or df.empty:
                    break
                rows = df.to_dict(orient="records")
                pages.extend(rows)
                if len(rows) < 5000:
                    break
                _time.sleep(0.15)  # rate limit
            except Exception:
                break

        if pages:
            self.cache.insert_batch(code, pages, asset_type="stock")
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/data/data_provider.py
git commit -m "feat: add ensure_data_loaded_for_codes — targeted K-line loading"
```

---

### Task 6: 战法实现 — ma60_breakthrough + ma60_pullback_only

**Files:**
- Create: `src/marketreview/backtest/strategies/__init__.py`
- Create: `src/marketreview/backtest/strategies/ma60_breakthrough.py`
- Create: `src/marketreview/backtest/strategies/ma60_pullback_only.py`
- Modify: `src/marketreview/backtest/strategy_base.py` — add imports for registration

**Interfaces:**
- Consumes: `BaseStrategy`, `register_strategy`, `DayContext`, `BuySignal`, `SellSignal`, `Position`
- Produces: `ma60_breakthrough`, `ma60_pullback_only` in registry

- [ ] **Step 1: Create strategies __init__.py**

```python
# src/marketreview/backtest/strategies/__init__.py
"""Strategy implementations. Import here to trigger registration."""
from . import ma60_breakthrough   # noqa: F401
from . import ma60_pullback_only  # noqa: F401
```

- [ ] **Step 2: Create ma60_breakthrough.py**

```python
# src/marketreview/backtest/strategies/ma60_breakthrough.py
"""MA60 突破+拉回 买入策略 — 跌破MA60/空间止损/三级浮盈止盈卖出."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal, Position,
    register_strategy,
)


@register_strategy("ma60_breakthrough")
class MA60BreakthroughStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA60突破+拉回"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma60 is None or ctx.ma60_yesterday is None:
            return None
        if ctx.ma60 <= 0 or ctx.ma60_yesterday <= 0:
            return None

        # 突破: yesterday close < yesterday MA60 AND today high >= today MA60
        if (ctx.kline_history and len(ctx.kline_history) >= 2):
            yesterday = ctx.kline_history[1]  # 2nd element = yesterday
            prev_close = yesterday.get("close", 0)
            if prev_close < ctx.ma60_yesterday and ctx.high >= ctx.ma60:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma60, reason="突破MA60",
                )

        # 拉回: yesterday close > yesterday MA60 AND today low <= today MA60
        if (ctx.kline_history and len(ctx.kline_history) >= 2):
            yesterday = ctx.kline_history[1]
            prev_close = yesterday.get("close", 0)
            if prev_close > ctx.ma60_yesterday and ctx.low <= ctx.ma60:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma60, reason="拉回MA60",
                )

        return None

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        if ctx.ma60 is None or ctx.ma60 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        # ── 战法卖出: 收盘价跌破当日MA60 ──
        if current_price < ctx.ma60:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA60)",
            )

        # ── 三级浮盈止盈 ──
        mfp = pos.max_float_profit_pct  # max float profit so far

        if mfp >= 20.0:
            # Tier 3: keep 80% of max, sell when drops below
            threshold_pct = mfp * 0.80
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < threshold_pct:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )

        elif mfp >= 10.0:
            # Tier 2: 回落 5% from max
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < mfp - 5.0:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )

        # Tier 1 (mfp < 10%): no take-profit, rely on stop-loss only
        return None
```

- [ ] **Step 3: Create ma60_pullback_only.py**

```python
# src/marketreview/backtest/strategies/ma60_pullback_only.py
"""MA60 仅拉回买入策略 — 同突破拉回，但去掉突破信号."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal, Position,
    register_strategy,
)


@register_strategy("ma60_pullback_only")
class MA60PullbackOnlyStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA60仅拉回"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma60 is None or ctx.ma60_yesterday is None:
            return None
        if ctx.ma60 <= 0 or ctx.ma60_yesterday <= 0:
            return None

        # Only 拉回, no 突破
        if (ctx.kline_history and len(ctx.kline_history) >= 2):
            yesterday = ctx.kline_history[1]
            prev_close = yesterday.get("close", 0)
            if prev_close > ctx.ma60_yesterday and ctx.low <= ctx.ma60:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma60, reason="拉回MA60",
                )

        return None

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        # Identical sell logic to MA60BreakthroughStrategy
        if ctx.position is None:
            return None
        if ctx.ma60 is None or ctx.ma60 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        if current_price < ctx.ma60:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA60)",
            )

        mfp = pos.max_float_profit_pct

        if mfp >= 20.0:
            threshold_pct = mfp * 0.80
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < threshold_pct:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )
        elif mfp >= 10.0:
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < mfp - 5.0:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )

        return None
```

- [ ] **Step 4: Commit**

```bash
git add src/marketreview/backtest/strategies/__init__.py \
        src/marketreview/backtest/strategies/ma60_breakthrough.py \
        src/marketreview/backtest/strategies/ma60_pullback_only.py
git commit -m "feat: add MA60 strategies — breakthrough+pullback, pullback-only"
```

---

### Task 7: BacktestEngine — 回测引擎

**Files:**
- Create: `src/marketreview/backtest/engine.py`

**Interfaces:**
- Consumes: `BaseStrategy`, `Broker`, `Report`, `build_report`
- Produces: `BacktestEngine(pool, strategy_cfg, dp).run() -> Report`

- [ ] **Step 1: Create engine.py**

```python
# src/marketreview/backtest/engine.py
"""Backtest engine — daily loop over stocks, orchestrate buy/sell."""
from datetime import datetime, timedelta
from .strategy_base import BaseStrategy, DayContext, create_strategy
from .broker import Broker
from .reporter import Report, build_report
from .config import PoolConfig, StrategyConfig
from marketreview.tools.technical import calc_ma


class BacktestEngine:
    """Runs a backtest for one pool × one strategy."""

    def __init__(self, dp, pool: PoolConfig, strategy_cfg: StrategyConfig):
        self.dp = dp
        self.pool = pool
        self.strategy_cfg = strategy_cfg

        # Create strategy instance
        self.strategy = create_strategy(strategy_cfg.class_name)
        if self.strategy is None:
            raise ValueError(
                f"Unknown strategy: {strategy_cfg.class_name}. "
                f"Available: {list(STRATEGY_REGISTRY.keys())}"
            )

        self.broker = Broker(
            position_pct=strategy_cfg.position_pct,
            max_positions=strategy_cfg.max_positions,
            space_stop_pct=strategy_cfg.space_stop_pct,
        )

        # K-line cache: {code: list[dict]} sorted date ASC
        self._klines: dict[str, list[dict]] = {}

    def run(self) -> Report:
        # 1. Determine date range
        lookback = self.strategy.lookback_trading_days

        all_entry = []
        all_exit = []
        for s in self.pool.stocks:
            if s.entry_date:
                all_entry.append(s.entry_date)
            if s.exit_date and s.exit_date != "now":
                all_exit.append(s.exit_date)

        if not all_entry:
            return Report()

        min_entry = min(all_entry)
        max_exit = max(all_exit) if all_exit else self._latest_trade_date()

        # Extend start by lookback trading days
        start_dt = datetime.strptime(min_entry, "%Y%m%d")
        # Rough: lookback * 1.5 calendar days
        buffer_dt = start_dt - timedelta(days=int(lookback * 1.6))
        start_date = buffer_dt.strftime("%Y%m%d")
        end_date = max_exit

        # 2. Load data
        codes = [s.code for s in self.pool.stocks if s.code]
        self.dp.ensure_data_loaded_for_codes(codes, start_date, end_date)

        # 3. Load K-lines into memory & precompute MA60
        for s in self.pool.stocks:
            if not s.code:
                continue
            rows = self.dp.get_daily(s.code, end_date=end_date,
                                     lookback_days=(int(
                                         (datetime.strptime(end_date, "%Y%m%d") -
                                          buffer_dt).days
                                     )))
            if not rows:
                self._klines[s.code] = []
                continue
            # rows come date DESC; reverse to ASC
            rows_asc = list(reversed(rows))
            # Precompute MA60
            closes = [r["close"] for r in rows_asc]
            ma60_vals = calc_ma(closes, 60)  # same length, NaN for first 59
            for i, r in enumerate(rows_asc):
                r["ma60"] = ma60_vals[i]
            self._klines[s.code] = rows_asc

        # 4. Get trading date range
        trade_dates = self._trading_day_range(start_date, end_date)

        # 5. Daily loop
        equity_curve = []
        delayed_stop_symbols: set[str] = set()  # need next-open stop

        for date in trade_dates:
            for s in self.pool.stocks:
                if not s.code:
                    continue
                klines = self._klines.get(s.code, [])
                today_row = self._get_day(klines, date)
                if today_row is None:
                    continue

                # Check if in discovery window
                in_window = self._in_window(s, date)

                # Build context
                ctx = self._build_ctx(date, s, today_row, klines, in_window)

                # ── Sell checks (if holding) ──
                if s.code in self.broker.positions:
                    # a) Delayed stop from yesterday
                    if s.code in delayed_stop_symbols:
                        triggered = self.broker.check_delayed_stop(
                            date, s.code, today_row["open"]
                        )
                        if triggered:
                            delayed_stop_symbols.discard(s.code)
                            continue  # sold, next stock

                    # b) Update max float profit
                    self.broker.update_max_float_profit(
                        s.code, today_row["high"]
                    )

                    # c) Strategy sell
                    ctx.position = self.broker.positions.get(s.code)
                    sell_sig = self.strategy.check_sell(ctx)
                    if sell_sig:
                        self.broker.sell(date, s.code, sell_sig.price,
                                         sell_sig.reason)
                        continue

                    # d) Space stop (intraday)
                    triggered = self.broker.check_space_stop(
                        date, s.code, today_row["low"], today_row["open"]
                    )
                    if triggered:
                        # Check if stop was actually executable intraday
                        # (space_stop already executed in check_space_stop)
                        pass
                    else:
                        # Check if we need a delayed stop:
                        # if stop price is below today's low, flag for next open
                        pos = self.broker.positions.get(s.code)
                        if pos:
                            stop_price = pos.buy_price * (
                                1 - self.broker.space_stop_pct / 100.0
                            )
                            if stop_price > today_row["low"]:
                                delayed_stop_symbols.add(s.code)

                # ── Buy check (if not holding + in window) ──
                else:
                    if in_window:
                        ctx.position = None
                        buy_sig = self.strategy.check_buy(ctx)
                        if buy_sig:
                            self.broker.buy(
                                date, s.code, s.name,
                                buy_sig.price, buy_sig.reason,
                            )

            # Record daily equity
            equity_curve.append({
                "date": date,
                "equity": self.broker.equity,
                "return_pct": (self.broker.equity / self.broker.init_capital - 1) * 100.0,
            })

        # 6. Build report
        return build_report(self.broker.trades, equity_curve)

    def _build_ctx(self, date, stock_entry, today_row, klines, in_window) -> DayContext:
        """Build DayContext for a given stock on a given date."""
        # Find today's index in klines
        idx = None
        for i, r in enumerate(klines):
            if r.get("trade_date", "") == date:
                idx = i
                break
        if idx is None:
            idx = len(klines) - 1

        yesterday_idx = idx - 1
        yesterday_ma60 = 0.0
        if yesterday_idx >= 0 and yesterday_idx < len(klines):
            yesterday_ma60 = klines[yesterday_idx].get("ma60", 0.0) or 0.0

        return DayContext(
            date=date,
            symbol=stock_entry.code,
            symbol_name=stock_entry.name,
            open=today_row.get("open", 0) or 0,
            high=today_row.get("high", 0) or 0,
            low=today_row.get("low", 0) or 0,
            close=today_row.get("close", 0) or 0,
            volume=today_row.get("vol", 0) or 0,
            amount=today_row.get("amount", 0) or 0,
            ma60=today_row.get("ma60", 0) or 0,
            ma60_yesterday=yesterday_ma60,
            kline_history=klines[:idx + 1] if idx is not None else klines,
            in_pool_window=in_window,
        )

    def _in_window(self, stock_entry, date: str) -> bool:
        """Check if date is within stock's discovery window."""
        if stock_entry.entry_date and date < stock_entry.entry_date:
            return False
        if stock_entry.exit_date and stock_entry.exit_date != "now":
            if date > stock_entry.exit_date:
                return False
        return True

    def _latest_trade_date(self) -> str:
        """Get latest trading day from cache."""
        return self.dp.get_latest_trade_date() or datetime.now().strftime("%Y%m%d")

    def _trading_day_range(self, start: str, end: str) -> list[str]:
        """Return all available trading dates between start and end."""
        rows = self.dp.cache.fetch_all(
            "SELECT DISTINCT date FROM tushare_cache "
            "WHERE date >= ? AND date <= ? ORDER BY date",
            (start, end),
        )
        return [r[0] for r in rows]

    def _get_day(self, klines: list[dict], date: str) -> dict | None:
        """Find a K-line row by date."""
        for r in klines:
            if r.get("trade_date", "") == date:
                return r
        return None
```

- [ ] **Step 2: Commit**

```bash
git add src/marketreview/backtest/engine.py
git commit -m "feat: add BacktestEngine — daily loop, orchestration, T+1"
```

---

### Task 8: DashboardService — 新增回测方法

**Files:**
- Modify: `dashboard/services/dashboard_service.py`

**Interfaces:**
- Produces: `load_backtest_pools()`, `load_backtest_strategies()`, `run_backtest(pool, strategy)`

- [ ] **Step 1: Add imports at top of dashboard_service.py**

After existing imports (around line 15), add:

```python
from marketreview.backtest.config import load_pools, load_strategies, PoolConfig, StrategyConfig
from marketreview.backtest.engine import BacktestEngine
from marketreview.backtest.reporter import Report
```

- [ ] **Step 2: Add methods to DashboardService class**

Find a logical place in the class (e.g., before or after the AI summary methods), add:

```python
    def load_backtest_pools(self) -> list[PoolConfig]:
        """Parse config/backtest_pools.txt."""
        return load_pools(self._dp)

    def load_backtest_strategies(self) -> list[StrategyConfig]:
        """Parse config/backtest_strategies.txt."""
        return load_strategies()

    def run_backtest(self, pool: PoolConfig,
                     strategy_cfg: StrategyConfig) -> Report:
        """Create engine, run backtest, return report."""
        engine = BacktestEngine(self._dp, pool, strategy_cfg)
        return engine.run()
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: add backtest methods to DashboardService"
```

---

### Task 9: Dashboard 页面 — 04_战法回测.py

**Files:**
- Create: `dashboard/pages/04_战法回测.py`

- [ ] **Step 1: Create the page**

```python
# dashboard/pages/04_战法回测.py
"""战法回测 — 股票池 × 策略日线回测."""
import streamlit as st
import plotly.graph_objects as go
from services.dashboard_service import DashboardService

st.set_page_config(page_title="战法回测", page_icon="🔬", layout="wide")

svc = DashboardService()

st.title("🔬 战法回测")

# ── Step 1: Load configs ──
pools = svc.load_backtest_pools()
strategies = svc.load_backtest_strategies()

if not pools:
    st.warning("未找到股票池配置，请在 config/backtest_pools.txt 中配置。")
    st.stop()

if not strategies:
    st.warning("未找到策略配置，请在 config/backtest_strategies.txt 中配置。")
    st.stop()

pool_names = [p.name for p in pools]
strategy_names = [s.name for s in strategies]

col1, col2 = st.columns(2)
with col1:
    selected_pool_name = st.selectbox("股票池", pool_names)
with col2:
    selected_strategy_name = st.selectbox("策略", strategy_names)

# ── Expander: 股票池详情 ──
selected_pool = next(p for p in pools if p.name == selected_pool_name)
with st.expander("📋 股票池详情", expanded=False):
    for s in selected_pool.stocks:
        if s.code:
            exit_display = s.exit_date if s.exit_date != "now" else f"至今({svc._dp.get_latest_trade_date()})"
            st.markdown(f"✅ **{s.name}** → `{s.code}`  {s.entry_date} ~ {exit_display}")
        else:
            st.markdown(f"❌ **{s.name}** → 未找到代码")

# ── Step 2: Load Data ──
if st.button("📥 加载数据", type="primary"):
    selected_strategy_cfg = next(s for s in strategies if s.name == selected_strategy_name)
    codes = [s.code for s in selected_pool.stocks if s.code]

    if not codes:
        st.error("股票池中没有有效代码。")
    else:
        with st.spinner("正在加载K线数据..."):
            try:
                import datetime as _dt
                # Determine date range
                all_dates = [s.entry_date for s in selected_pool.stocks if s.entry_date]
                min_entry = min(all_dates) if all_dates else "20240101"
                max_exit = svc._dp.get_latest_trade_date()
                # lookback buffer
                from marketreview.backtest.strategy_base import STRATEGY_REGISTRY, create_strategy
                strategy_cls = STRATEGY_REGISTRY.get(selected_strategy_cfg.class_name)
                lookback = strategy_cls().lookback_trading_days if strategy_cls else 60
                buff_dt = _dt.datetime.strptime(min_entry, "%Y%m%d") - _dt.timedelta(days=int(lookback * 1.6))
                start_date = buff_dt.strftime("%Y%m%d")

                svc._dp.ensure_data_loaded_for_codes(codes, start_date, max_exit)
                st.session_state.bt_data_loaded = True
                st.session_state.bt_codes = codes
                st.session_state.bt_start = start_date
                st.session_state.bt_end = max_exit
                st.success(f"✅ 已加载 {len(codes)} 只股票, 缓冲{lookback}交易日, {start_date}~{max_exit}")
            except Exception as e:
                st.error(f"加载失败: {e}")

# ── Step 3: Run Backtest ──
if st.button("▶ 运行回测", type="primary", disabled=not st.session_state.get("bt_data_loaded", False)):
    with st.spinner("回测运行中..."):
        try:
            selected_strategy_cfg = next(s for s in strategies if s.name == selected_strategy_name)
            report = svc.run_backtest(selected_pool, selected_strategy_cfg)
            st.session_state.bt_report = report
            st.session_state.bt_has_report = True
        except Exception as e:
            st.error(f"回测运行失败: {e}")
            import traceback
            st.code(traceback.format_exc())

# ── Step 4: Display Results ──
if st.session_state.get("bt_has_report"):
    report = st.session_state.bt_report
    if report.total_trades == 0:
        st.info("未产生任何交易。")
    else:
        # Summary cards
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("总交易笔数", report.total_trades,
                      delta=f"赢{report.win_trades} / 亏{report.lose_trades}")
        with col2:
            st.metric("胜率", f"{report.win_rate:.1%}")
        with col3:
            color = "normal"  # Streamlit default
            st.metric("总收益率", f"{report.total_return_pct:+.2f}%")

        col4, col5, col6 = st.columns(3)
        with col4:
            st.metric("最大回撤", f"{report.max_drawdown_pct:.2f}%")
        with col5:
            st.metric("平均持仓天", f"{report.avg_hold_days:.1f}天")
        with col6:
            st.metric("盈亏比", f"{report.profit_loss_ratio:.2f}:1")

        # Equity curve
        if report.equity_curve:
            dates = [pt["date"] for pt in report.equity_curve]
            returns = [pt["return_pct"] for pt in report.equity_curve]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates, y=returns, mode="lines",
                line=dict(color="#cf2c2c", width=2),  # red per convention
                name="累计收益率",
            ))
            fig.update_layout(
                title="盈亏曲线", xaxis_title="日期", yaxis_title="收益率 (%)",
                height=400, margin=dict(l=40, r=20, t=40, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

        # Per-stock summary + trade detail
        st.subheader("股票明细")
        for ss in report.stock_summaries:
            with st.expander(f"{ss.symbol_name} — {ss.total_trades}笔 胜率{ss.win_rate:.1%} 累计{ss.cumulative_pnl_pct:+.2f}%"):
                # Filter trades for this stock
                stock_trades = [t for t in report.trades if t.symbol == ss.symbol]
                rows = []
                for t in stock_trades:
                    pnl_str = f"{t.pnl_pct:+.2f}%" if t.trade_type == "卖出" else ""
                    rows.append({
                        "日期": t.date, "类型": t.trade_type,
                        "价格": f"{t.price:.2f}", "盈亏": pnl_str,
                        "原因": t.reason,
                    })
                st.dataframe(rows, use_container_width=True, hide_index=True)
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/pages/04_战法回测.py
git commit -m "feat: add 战法回测 dashboard page — select, load, run, display"
```

---

### Task 10: Navigation + Version Bump + Config Samples

**Files:**
- Modify: `dashboard/app.py`
- Modify: `dashboard/services/dashboard_service.py` — bump `_AI_VERSION`
- Create: `config/backtest_pools.txt` (sample)
- Create: `config/backtest_strategies.txt` (sample)

- [ ] **Step 1: Add nav entry in dashboard/app.py**

```python
# In dashboard/app.py, add to st.navigation() list:
st.Page("pages/04_战法回测.py", title="战法回测", icon="🔬"),
```

- [ ] **Step 2: Bump AI version**

Find `_AI_VERSION` in `dashboard/services/dashboard_service.py` and bump Z (patch → minor since this is a feature):

```python
# Change from:
_AI_VERSION = "1.10.7"
# To:
_AI_VERSION = "1.11.0"
```

- [ ] **Step 3: Create sample config files**

```txt
# config/backtest_pools.txt
# 格式: [池名]
#       股票名 entry_date exit_date

[测试池]
顺络电子 20250102 now
```

```txt
# config/backtest_strategies.txt
# 格式: 策略名 战法类名 仓位% 开仓上限 空间止损%

MA60_突破拉回_3止损 ma60_breakthrough 20 2 3
MA60_仅拉回_5止损 ma60_pullback_only 20 2 5
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/app.py dashboard/services/dashboard_service.py \
        config/backtest_pools.txt config/backtest_strategies.txt
git commit -m "feat: add nav entry, bump AI version to 1.11.0, sample configs"
```

---

### Task 11: Integration Smoke Test

- [ ] **Step 1: Restart dashboard**

```bash
# Kill + clear + start
cd "i:/AIcode/marketreview"
python -c "import subprocess as sp; out = sp.check_output('wmic process where \"name=\\\"python.exe\\\"\" get processid,commandline', shell=True).decode('utf-8', errors='ignore'); [sp.run(f'taskkill /F /PID {l.strip().split()[-1]}', shell=True, capture_output=True) for l in out.split('\n') if 'streamlit' in l.lower()]"
python -c "import os,shutil; [shutil.rmtree(os.path.join(r,d)) for r,ds,f in os.walk('.') for d in ds if '__pycache__' == d and '.venv' not in r]" 2>/dev/null
nohup .venv/Scripts/python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true > /tmp/streamlit.log 2>&1 &
sleep 4 && curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:8501
```

Expected: HTTP 200

- [ ] **Step 2: Verify the page loads**

Open browser → navigate to 战法回测 page → verify:
- Two dropdowns visible with pool + strategy options
- Stock pool expander shows stocks with ✅/❌ status
- Load data button works
- Run backtest button enabled after load

- [ ] **Step 3: Run a quick backtest**

Configure pool with 1-2 stocks you know have data, run, verify:
- Summary cards show numbers
- Equity curve chart renders
- Stock detail expanders work

- [ ] **Step 4: Fix any issues + commit**

```bash
git add -A
git commit -m "fix: integration fixes from smoke test"
```

---
