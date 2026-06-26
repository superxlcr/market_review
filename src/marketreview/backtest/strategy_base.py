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


def safe_float(v) -> float:
    """Convert a value to float, returning 0.0 on failure."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0
