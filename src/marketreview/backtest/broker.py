"""Virtual broker — cash accounting, position tracking, T+1 enforcement."""
from dataclasses import dataclass
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
        """Total equity = cash + book value of all positions."""
        mv = sum(
            p.shares * p.buy_price for p in self.positions.values()
        )
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
                         today_low: float) -> str:
        """Check if space stop-loss triggers intraday.
        Returns reason string if triggered, empty string otherwise.
        """
        pos = self.positions.get(symbol)
        if pos is None:
            return ""

        stop_price = pos.buy_price * (1 - self.space_stop_pct / 100.0)

        if today_low <= stop_price:
            self.sell(date, symbol, stop_price, "空间止损")
            return "空间止损"
        return ""

    def check_delayed_stop(self, date: str, symbol: str,
                           today_open: float) -> str:
        """Execute yesterday's unexecuted space stop at today's open.
        Called at market open for positions flagged for delayed stop.
        """
        pos = self.positions.get(symbol)
        if pos is None:
            return ""

        stop_price = pos.buy_price * (1 - self.space_stop_pct / 100.0)
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
