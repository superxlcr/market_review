"""MA144 突破+拉回 买入策略 — 跌破MA144/空间止损/三级浮盈止盈卖出."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma144_breakthrough")
class MA144BreakthroughStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA144突破+拉回"

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

        return self.check_take_profit(ctx)
