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
    entry_ma_type: str = ""   # which MA triggered entry: "MA20"/"MA60"/"MA120"/"MA240"
    strategy_tag: str = ""    # which sub-strategy generated this position (composite use)
    # 浮盈加仓
    addon_shares: int = 0              # 加仓股数 (0=未加仓)
    addon_price: float = 0.0           # 加仓买入价
    addon_cost: float = 0.0            # 加仓总成本
    addon_date: str = ""               # 加仓日期 YYYYMMDD
    addon_mfp_pct: float = 0.0         # 加仓部分独立最大浮盈%
    addon_count: int = 0                # 已加仓次数（触发后自增，卖出不复位）


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
    ma20: float = 0.0              # today's MA20
    ma20_yesterday: float = 0.0    # yesterday's MA20
    ma60: float = 0.0              # today's MA60
    ma60_yesterday: float = 0.0    # yesterday's MA60
    ma120: float = 0.0             # today's MA120
    ma120_yesterday: float = 0.0   # yesterday's MA120
    ma240: float = 0.0             # today's MA240
    ma240_yesterday: float = 0.0   # yesterday's MA240
    ma55: float = 0.0              # today's MA55
    ma55_yesterday: float = 0.0    # yesterday's MA55
    ma144: float = 0.0             # today's MA144
    ma144_yesterday: float = 0.0   # yesterday's MA144
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
    entry_ma_type: str = ""  # which MA: "MA20"/"MA60"/"MA120"/"MA240"
    strategy_tag: str = ""   # which sub-strategy generated this signal (composite use)


@dataclass
class SellSignal:
    """Sell signal from strategy (not space stop — that's engine-layer)."""
    date: str
    symbol: str
    symbol_name: str
    price: float
    reason: str            # "止盈" | "战法止损" | "战法卖出"


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


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    # ── 时间止损参数（子类可覆写）──
    TIME_STOP_DAYS: int = 8         # 持仓 ≥N 日且最大浮盈从未达阈值 → 时间止损
    TIME_STOP_MIN_MFP: float = 10.0 # 时间止损浮盈阈值（%）

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

    def diagnose_buy(self, ctx: DayContext) -> Optional[str]:
        """Return a human-readable reason when check_buy returns None.

        Subclasses should override this to provide strategy-specific
        diagnostics.  Returns None if no detailed explanation is available.
        """
        return None

    @abstractmethod
    def check_sell(self, ctx: DayContext) -> Optional[SellSignal]:
        """Return a sell signal (strategy-level stop/take-profit) or None.
        Space stop-loss is handled by engine, NOT here."""
        ...

    def _trading_days_since_buy(self, ctx: DayContext) -> int:
        """持仓交易日数（买入日不计）."""
        if ctx.position is None:
            return 0
        buy_date = ctx.position.buy_date
        return sum(1 for bar in ctx.kline_history
                   if str(bar.get("date", "")) > buy_date)

    def check_time_stop(self, ctx: DayContext) -> Optional[SellSignal]:
        """时间止损（通用）：持仓 N 日浮盈未达阈值 → 收盘卖出.

        各策略 check_sell 可在自身特有逻辑之后调用本方法作为 fallback.
        子类可覆写 TIME_STOP_DAYS / TIME_STOP_MIN_MFP 调整阈值.
        """
        if ctx.position is None:
            return None

        pos = ctx.position
        trading_days = self._trading_days_since_buy(ctx)
        if trading_days >= self.TIME_STOP_DAYS and pos.max_float_profit_pct < self.TIME_STOP_MIN_MFP:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ctx.close,
                reason=f"时间止损(持仓{trading_days}日浮盈未达{self.TIME_STOP_MIN_MFP:.0f}%，收盘卖出)",
            )
        return None

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
