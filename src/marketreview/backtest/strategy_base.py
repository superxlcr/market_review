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

    # ── 三级浮盈止盈阈值（子类可覆写）──
    TP_TIER3_MFP_THRESHOLD: float = 20.0   # 浮盈达此%触发 Tier 3
    TP_TIER3_PROTECT_PCT: float = 0.50     # Tier 3: 保留最高浮盈的50%
    TP_TIER2_MFP_THRESHOLD: float = 10.0   # 浮盈达此%触发 Tier 2
    TP_TIER2_PROTECT_PRICE_RATIO: float = 1.05  # Tier 2: 保护买入价的+5%

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

    def check_take_profit(self, ctx: DayContext) -> Optional[SellSignal]:
        """三级浮盈止盈（通用）— 用日内最低价判断盘中触发。

        各策略 check_sell 在自身特有逻辑之后调用本方法作为 fallback。
        子类可覆写 TP_TIER* 类属性调整阈值，或直接覆写本方法。
        """
        if ctx.position is None:
            return None

        pos = ctx.position
        mfp = pos.max_float_profit_pct

        if mfp >= self.TP_TIER3_MFP_THRESHOLD:
            # Tier 3: 保留最高浮盈的一定比例，日内最低价触及即卖出
            threshold_price = pos.buy_price * (1 + mfp * self.TP_TIER3_PROTECT_PCT / 100.0)
            if ctx.low <= threshold_price:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=threshold_price,
                    reason=f"止盈(浮盈曾达{mfp:.1f}%→保{self.TP_TIER3_PROTECT_PCT*100:.0f}%即{threshold_price:.2f})",
                )

        elif mfp >= self.TP_TIER2_MFP_THRESHOLD:
            # Tier 2: 保护买入价×ratio，日内最低价触及即卖出
            protect_price = pos.buy_price * self.TP_TIER2_PROTECT_PRICE_RATIO
            if ctx.low <= protect_price:
                pct = (self.TP_TIER2_PROTECT_PRICE_RATIO - 1) * 100
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=protect_price,
                    reason=f"止盈(浮盈曾达{mfp:.1f}%→保{pct:.0f}%即{protect_price:.2f})",
                )

        # Tier 1 (mfp < threshold): no take-profit, rely on stop-loss only
        return None


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
