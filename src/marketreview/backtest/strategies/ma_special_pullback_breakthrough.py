"""长期特殊均线(MA55/144)突破拉回 战法（空间止损 + 战法卖出 + 时间止损 + 三级止盈）."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


_MA_LIST = [
    ("MA55", "ma55", "ma55_yesterday"),
    ("MA144", "ma144", "ma144_yesterday"),
]


@register_strategy("ma_special_pullback_breakthrough")
class MASpecialPullbackBreakthroughStrategy(BaseStrategy):

    TIME_STOP_DAYS: int = 8
    TIME_STOP_MIN_MFP: float = 10.0

    @property
    def name(self) -> str:
        return "长期特殊均线突破拉回战法"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if len(ctx.kline_history) < 2:
            return None
        yesterday = ctx.kline_history[-2]
        prev_close = safe_float(yesterday.get("close"))
        if prev_close <= 0:
            return None

        for ma_label, ma_today_key, ma_yest_key in _MA_LIST:
            ma_today = getattr(ctx, ma_today_key, 0.0)
            ma_yest = getattr(ctx, ma_yest_key, 0.0)
            if ma_today <= 0 or ma_yest <= 0:
                continue

            if prev_close > ma_yest and ctx.low <= ma_today:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ma_today,
                    reason=f"拉回{ma_label}",
                    entry_ma_type=ma_label,
                )

            if prev_close < ma_yest and ctx.high >= ma_today:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ma_today,
                    reason=f"突破{ma_label}",
                    entry_ma_type=ma_label,
                )

        return None

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None

        pos = ctx.position
        current_price = ctx.close
        ma_type = pos.entry_ma_type

        ma_attr, ma_yest_attr = self._ma_attrs(ma_type)
        if ma_attr is None:
            return None

        ma_today = getattr(ctx, ma_attr, 0.0)
        if ma_today <= 0:
            return None

        if current_price < ma_today:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"战法卖出(跌破{ma_type})",
            )

        trading_days = self._trading_days_since_buy(ctx)
        if trading_days >= self.TIME_STOP_DAYS and pos.max_float_profit_pct < self.TIME_STOP_MIN_MFP:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"时间止损(持仓{trading_days}日浮盈未达{self.TIME_STOP_MIN_MFP:.0f}%，收盘卖出)",
            )

        return self.check_take_profit(ctx)

    def _trading_days_since_buy(self, ctx: DayContext) -> int:
        if ctx.position is None:
            return 0
        buy_date = ctx.position.buy_date
        return sum(1 for bar in ctx.kline_history
                   if str(bar.get("date", "")) > buy_date)

    @staticmethod
    def _ma_attrs(ma_type: str) -> tuple[str | None, str | None]:
        for label, today_attr, yest_attr in _MA_LIST:
            if label == ma_type:
                return today_attr, yest_attr
        return None, None
