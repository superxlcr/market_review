"""Virtual broker — cash accounting, position tracking, T+1 enforcement."""
from dataclasses import dataclass
from .strategy_base import Position


@dataclass
class TradeRecord:
    """One completed trade or signal."""
    date: str
    symbol: str
    symbol_name: str
    trade_type: str         # "买入" | "卖出" | "信号未成交"
    price: float
    shares: int = 0
    pnl_pct: float = 0.0    # profit/loss % for sells
    reason: str = ""        # exit reason or skip reason
    positions_after: str = ""  # snapshot of holdings after this trade


class Broker:
    """Manages cash, positions, and enforces T+1 + position cap."""

    def __init__(self, init_capital: float = 1_000_000,
                 position_pct: float = 20.0,
                 max_positions: int = 2,
                 space_stop_pct: float = 3.0,
                 new_position_threshold_pct: float = 0.0):
        self.init_capital = init_capital
        self.cash = init_capital
        self.position_pct = position_pct    # % per trade
        self.max_positions = max_positions
        self.space_stop_pct = space_stop_pct
        self.new_position_threshold_pct = new_position_threshold_pct
        self.positions: dict[str, Position] = {}   # symbol → Position
        self.trades: list[TradeRecord] = []

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def equity(self) -> float:
        """Total equity = cash + book value (成本) of all positions.
        Use get_market_equity() for mark-to-market valuation."""
        mv = sum(
            p.shares * p.buy_price for p in self.positions.values()
        )
        return self.cash + mv

    def get_market_equity(self, prices: dict[str, float] | None = None) -> float:
        """Total equity = cash + mark-to-market value of all positions.
        Prices dict: {symbol: current_price}. Missing symbols fall back to buy_price."""
        if not prices:
            return self.equity
        mv = 0.0
        for sym, pos in self.positions.items():
            cur_price = prices.get(sym, pos.buy_price)
            mv += pos.shares * cur_price
        return self.cash + mv

    def can_buy(self, symbol: str) -> tuple[bool, str]:
        """Check if a new buy is allowed. Returns (allowed, reason)."""
        if symbol in self.positions:
            return False, "已持仓"
        # 开仓上限 = 基础仓位 + 达标解锁仓位
        qualified = sum(
            1 for p in self.positions.values()
            if p.max_float_profit_pct >= self.new_position_threshold_pct
        )
        allowed = self.max_positions + qualified
        if self.position_count >= allowed:
            if qualified > 0:
                return False, (
                    f"已达开仓上限(基础{self.max_positions}只"
                    f"+达标解锁{qualified}只={allowed}只)"
                )
            return False, f"已达开仓上限({self.max_positions}只)"
        trade_amount = self.init_capital * self.position_pct / 100.0
        if self.cash < trade_amount:
            return False, "资金不足"
        return True, ""

    def _positions_detail(self, prices: dict[str, float]) -> str:
        """Build a string describing current positions with floating P&L."""
        if not self.positions:
            return ""
        parts = []
        for sym, pos in self.positions.items():
            cur_price = prices.get(sym, pos.buy_price)
            float_pnl = (cur_price - pos.buy_price) / pos.buy_price * 100.0
            parts.append(f"{pos.symbol_name}({float_pnl:+.1f}%)")
        return " | ".join(parts)

    def enrich_last_trade(self, prices: dict[str, float]):
        """Attach current positions snapshot to the most recent trade."""
        if self.trades:
            self.trades[-1].positions_after = self._positions_detail(prices)

    def buy(self, date: str, symbol: str, symbol_name: str,
            price: float, reason: str = "",
            position_prices: dict[str, float] | None = None) -> Position | None:
        """Execute a buy. Returns Position or None if rejected."""
        ok, reject_reason = self.can_buy(symbol)
        if not ok:
            # Enrich rejection reason with position details
            if reject_reason == "已达开仓上限" and position_prices:
                detail = self._positions_detail(position_prices)
                reject_reason = f"已达开仓上限({detail})"
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
            trade_type="买入", price=price, shares=shares, reason=reason,
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
                         today_low: float, today_open: float = 0.0) -> str:
        """Check if space stop-loss triggers intraday.
        If open already below stop → sell at open (gap down);
        otherwise sell at stop price (intraday trigger).
        Returns reason string if triggered, empty string otherwise.
        """
        pos = self.positions.get(symbol)
        if pos is None:
            return ""

        stop_price = pos.buy_price * (1 - self.space_stop_pct / 100.0)

        if today_low <= stop_price:
            if today_open > 0 and today_open <= stop_price:
                self.sell(date, symbol, today_open,
                          f"开盘价，{self.space_stop_pct:.0f}%空间止损")
            else:
                self.sell(date, symbol, stop_price,
                          f"盘中价，{self.space_stop_pct:.0f}%空间止损")
            return "空间止损"
        return ""

    def update_max_float_profit(self, symbol: str, today_high: float):
        """Update the max floating profit for a position."""
        pos = self.positions.get(symbol)
        if pos is None:
            return
        current_float = (today_high - pos.buy_price) / pos.buy_price * 100.0
        if current_float > pos.max_float_profit_pct:
            pos.max_float_profit_pct = current_float
