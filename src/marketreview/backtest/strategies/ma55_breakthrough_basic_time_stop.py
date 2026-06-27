"""MA55 突破+拉回 + 时间止损策略（无MA55空间止损）."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma55_breakthrough_basic_time_stop")
class MA55BreakthroughBasicTimeStopStrategy(BaseStrategy):

    TIME_STOP_DAYS: int = 8
    TIME_STOP_MIN_MFP: float = 10.0

    @property
    def name(self) -> str:
        return "MA55突破+拉回+时间止损(无MA55止损)"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma55 is None or ctx.ma55_yesterday is None:
            return None
        if ctx.ma55 <= 0 or ctx.ma55_yesterday <= 0:
            return None

        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close < ctx.ma55_yesterday and ctx.high >= ctx.ma55:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma55, reason="突破MA55",
                )

        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close > ctx.ma55_yesterday and ctx.low <= ctx.ma55:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma55, reason="拉回MA55",
                )

        return None

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        if ctx.ma55 is None or ctx.ma55 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        if current_price < ctx.ma55:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA55)",
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
