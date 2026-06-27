"""MA144 突破+拉回 完整版 — MA144止损 + 战法卖出 + 时间止损 + 三级止盈."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma144_breakthrough_full")
class MA144BreakthroughFullStrategy(BaseStrategy):

    TIME_STOP_DAYS: int = 8
    TIME_STOP_MIN_MFP: float = 10.0

    @property
    def name(self) -> str:
        return "MA144突破+拉回(完整版)"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma144 is None or ctx.ma144_yesterday is None:
            return None
        if ctx.ma144 <= 0 or ctx.ma144_yesterday <= 0:
            return None

        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close < ctx.ma144_yesterday and ctx.high >= ctx.ma144:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma144, reason="突破MA144",
                )

        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close > ctx.ma144_yesterday and ctx.low <= ctx.ma144:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma144, reason="拉回MA144",
                )

        return None

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        if ctx.ma144 is None or ctx.ma144 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        if ctx.ma144_yesterday > 0:
            ma144_stop = ctx.ma144_yesterday * 0.97
            if ctx.low <= ma144_stop:
                if ctx.open > 0 and ctx.open <= ma144_stop:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ctx.open,
                        reason=f"开盘价，MA144 3%空间止损(昨日MA144 {ctx.ma144_yesterday:.2f})",
                    )
                else:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ma144_stop,
                        reason=f"盘中价，MA144 3%空间止损(跌破昨日MA144 {ctx.ma144_yesterday:.2f})",
                    )

        if current_price < ctx.ma144:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA144)",
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
