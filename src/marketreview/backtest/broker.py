"""Virtual broker — cash accounting, position tracking, T+1 enforcement."""
from dataclasses import dataclass
import random
from .strategy_base import Position, ConditionalOrder
from marketreview.log_util import get_logger

log = get_logger(__name__)


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
                 new_position_threshold_pct: float = 0.0,
                 tp_tier3_mfp: float = 20.0,
                 tp_tier3_protect: float = 0.50,
                 tp_tier2_mfp: float = 10.0,
                 tp_tier2_protect_ratio: float = 1.05,
                 strategy_name: str = ""):
        self.init_capital = init_capital
        self.cash = init_capital
        self.strategy_name = strategy_name
        self.position_pct = position_pct    # % per trade
        self.max_positions = max_positions
        self.space_stop_pct = space_stop_pct
        self.new_position_threshold_pct = new_position_threshold_pct
        # 三级止盈阈值（用于加仓部分）
        self.tp_tier3_mfp = tp_tier3_mfp
        self.tp_tier3_protect = tp_tier3_protect
        self.tp_tier2_mfp = tp_tier2_mfp
        self.tp_tier2_protect_ratio = tp_tier2_protect_ratio
        self.positions: dict[str, Position] = {}   # symbol → Position
        self.trades: list[TradeRecord] = []
        self.pending_orders: list[ConditionalOrder] = []

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def equity(self) -> float:
        """Total equity = cash + book value (成本) of all positions + addons."""
        mv = sum(
            p.shares * p.buy_price + p.addon_shares * (p.addon_price or 0)
            for p in self.positions.values()
        )
        return self.cash + mv

    def get_market_equity(self, prices: dict[str, float] | None = None) -> float:
        """Total equity = cash + mark-to-market value of all positions + addons."""
        if not prices:
            return self.equity
        mv = 0.0
        for sym, pos in self.positions.items():
            cur_price = prices.get(sym, pos.buy_price)
            mv += pos.shares * cur_price
            if pos.addon_shares > 0:
                mv += pos.addon_shares * cur_price
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
            return False, "已达开仓上限"
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

    def report_volume_filter(self, date: str, symbol: str, symbol_name: str,
                             price: float, reason: str):
        """记录一条量能过滤（买入信号被量能条件拦截）."""
        self.trades.append(TradeRecord(
            date=date, symbol=symbol, symbol_name=symbol_name,
            trade_type="量能过滤", price=price, reason=reason,
        ))

    # ── 条件单 ──

    def add_order(self, order: ConditionalOrder):
        """设置一个明日条件单."""
        self.pending_orders.append(order)

    def clear_orders(self):
        """清空所有未触发条件单."""
        self.pending_orders.clear()

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

    def buy(self, date: str, symbol: str, symbol_name: str,
            price: float, reason: str = "",
            position_prices: dict[str, float] | None = None,
            entry_ma_type: str = "",
            strategy_tag: str = "") -> Position | None:
        """Execute a buy. Returns Position or None if rejected."""
        ok, reject_reason = self.can_buy(symbol)
        if not ok:
            # Prepend signal reason, enrich rejection with position details
            prefix = f"{reason}，" if reason else ""
            if reject_reason.startswith("已达开仓上限") and position_prices:
                pos_detail = self._positions_detail(position_prices)
                if pos_detail:
                    reject_reason = f"{reject_reason} | {pos_detail}"
            self.trades.append(TradeRecord(
                date=date, symbol=symbol, symbol_name=symbol_name,
                trade_type="信号未成交", price=price,
                reason=f"{prefix}{reject_reason}",
            ))
            return None

        trade_amount = self.init_capital * self.position_pct / 100.0
        shares = int(trade_amount / price)
        if shares == 0:
            self.trades.append(TradeRecord(
                date=date, symbol=symbol, symbol_name=symbol_name,
                trade_type="信号未成交", price=price,
                reason=f"{reason}，资金不足(整手不够)" if reason else "资金不足(整手不够)",
            ))
            return None

        cost = shares * price
        self.cash -= cost
        pos = Position(
            symbol=symbol, symbol_name=symbol_name,
            buy_date=date, buy_price=price,
            shares=shares, cost=cost,
            entry_ma_type=entry_ma_type,
            strategy_tag=strategy_tag,
        )
        self.positions[symbol] = pos
        self.trades.append(TradeRecord(
            date=date, symbol=symbol, symbol_name=symbol_name,
            trade_type="买入", price=price, shares=shares, reason=reason,
        ))
        log.info("[%s] 买入 %s %s @ %.2f × %d股 成本%.0f (%s)",
                 self.strategy_name, date, symbol_name, price, shares, cost, reason)
        return pos

    def sell(self, date: str, symbol: str, price: float,
             reason: str) -> Position | None:
        """Execute a sell. Also sells addon if present. Returns the closed Position."""
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None

        # 基础仓位
        proceeds = pos.shares * price
        self.cash += proceeds
        pnl_pct = (price - pos.buy_price) / pos.buy_price * 100.0
        total_shares = pos.shares

        self.trades.append(TradeRecord(
            date=date, symbol=symbol, symbol_name=pos.symbol_name,
            trade_type="卖出", price=price, shares=pos.shares,
            pnl_pct=pnl_pct, reason=reason,
        ))
        log.info("[%s] 卖出 %s %s @ %.2f × %d股 %+.2f%% (%s)",
                 self.strategy_name, date, pos.symbol_name, price, pos.shares, pnl_pct, reason)

        # 加仓部分（如果还在）
        if pos.addon_shares > 0:
            addon_proceeds = pos.addon_shares * price
            self.cash += addon_proceeds
            addon_pnl = (price - pos.addon_price) / pos.addon_price * 100.0
            total_shares += pos.addon_shares
            self.trades.append(TradeRecord(
                date=date, symbol=symbol, symbol_name=pos.symbol_name,
                trade_type="加仓卖出", price=price, shares=pos.addon_shares,
                pnl_pct=addon_pnl, reason=f"跟随卖出({reason})",
            ))
            log.info("[%s] 加仓卖出(跟随) %s %s @ %.2f × %d股 %+.2f%%",
                     self.strategy_name, date, pos.symbol_name, price, pos.addon_shares, addon_pnl)

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

    # ── 浮盈加仓 ──

    def addon_buy(self, date: str, symbol: str, price: float, shares: int) -> bool:
        """Execute add-on buy at trigger price. Bypasses position limit.
        Once triggered, never re-triggers even if addon is later sold.
        Returns True if successful, False if insufficient cash."""
        pos = self.positions.get(symbol)
        if pos is None or pos.addon_count >= 1:
            return False
        cost = shares * price
        if self.cash < cost:
            return False
        self.cash -= cost
        pos.addon_shares = shares
        pos.addon_price = price
        pos.addon_cost = cost
        pos.addon_date = date
        pos.addon_count += 1         # 不可逆，卖出后不复位
        self.trades.append(TradeRecord(
            date=date, symbol=symbol, symbol_name=pos.symbol_name,
            trade_type="加仓买入", price=price, shares=shares,
            reason=f"浮盈加仓(MFP≥{pos.max_float_profit_pct:.1f}%)",
        ))
        log.info("[%s] 加仓买入 %s %s @ %.2f × %d股 成本%.0f (MFP≥%.1f%%)",
                 self.strategy_name, date, pos.symbol_name, price, shares, cost,
                 pos.max_float_profit_pct)
        return True

    def sell_addon(self, date: str, symbol: str, price: float, reason: str) -> bool:
        """Sell only the add-on shares, keep base position. Returns True if sold."""
        pos = self.positions.get(symbol)
        if pos is None or pos.addon_shares == 0:
            return False
        proceeds = pos.addon_shares * price
        self.cash += proceeds
        pnl_pct = (price - pos.addon_price) / pos.addon_price * 100.0
        self.trades.append(TradeRecord(
            date=date, symbol=symbol, symbol_name=pos.symbol_name,
            trade_type="加仓卖出", price=price, shares=pos.addon_shares,
            pnl_pct=pnl_pct, reason=reason,
        ))
        log.info("[%s] 加仓卖出 %s %s @ %.2f × %d股 %+.2f%% (%s)",
                 self.strategy_name, date, pos.symbol_name, price, pos.addon_shares, pnl_pct, reason)
        pos.addon_shares = 0
        pos.addon_price = 0.0
        pos.addon_cost = 0.0
        pos.addon_date = ""
        pos.addon_mfp_pct = 0.0
        return True

    def update_addon_mfp(self, symbol: str, today_high: float):
        """Update add-on max float profit."""
        pos = self.positions.get(symbol)
        if pos is None or pos.addon_shares == 0:
            return
        addon_float = (today_high - pos.addon_price) / pos.addon_price * 100.0
        if addon_float > pos.addon_mfp_pct:
            pos.addon_mfp_pct = addon_float

    def check_addon_take_profit(self, date: str, symbol: str,
                                today_low: float) -> str | None:
        """Three-tier take-profit for add-on. Returns reason if triggered."""
        pos = self.positions.get(symbol)
        if pos is None or pos.addon_shares == 0:
            return None
        mfp = pos.addon_mfp_pct

        if mfp >= self.tp_tier3_mfp:
            threshold = pos.addon_price * (1 + mfp * self.tp_tier3_protect / 100.0)
            if today_low <= threshold:
                self.sell_addon(date, symbol, threshold,
                    f"加仓止盈(浮盈曾达{mfp:.1f}%→保{self.tp_tier3_protect*100:.0f}%即{threshold:.2f})")
                return "加仓T3止盈"

        elif mfp >= self.tp_tier2_mfp:
            protect_price = pos.addon_price * self.tp_tier2_protect_ratio
            if today_low <= protect_price:
                pct = (self.tp_tier2_protect_ratio - 1) * 100
                self.sell_addon(date, symbol, protect_price,
                    f"加仓止盈(浮盈曾达{mfp:.1f}%→保{pct:.0f}%即{protect_price:.2f})")
                return "加仓T2止盈"

        return None

    def check_addon_space_stop(self, date: str, symbol: str,
                               today_low: float, today_open: float = 0.0) -> str:
        """Space stop-loss for add-on. Returns reason if triggered."""
        pos = self.positions.get(symbol)
        if pos is None or pos.addon_shares == 0:
            return ""
        stop_price = pos.addon_price * (1 - self.space_stop_pct / 100.0)
        if today_low <= stop_price:
            if today_open > 0 and today_open <= stop_price:
                self.sell_addon(date, symbol, today_open,
                    f"加仓空间止损(开盘{self.space_stop_pct:.0f}%)")
            else:
                self.sell_addon(date, symbol, stop_price,
                    f"加仓空间止损(盘中{self.space_stop_pct:.0f}%)")
            return "加仓空间止损"
        return ""


def _safe_f(v) -> float:
    """Safely convert a value to float."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0
