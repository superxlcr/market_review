"""MA55 突破+拉回 买入策略 — 跌破MA55/空间止损/三级浮盈止盈卖出."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma55_breakthrough")
class MA55BreakthroughStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA55突破+拉回"

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

        if ctx.ma55_yesterday > 0:
            ma55_stop = ctx.ma55_yesterday * 0.97
            if ctx.low <= ma55_stop:
                if ctx.open > 0 and ctx.open <= ma55_stop:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ctx.open,
                        reason=f"开盘价，MA55 3%空间止损(昨日MA55 {ctx.ma55_yesterday:.2f})",
                    )
                else:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ma55_stop,
                        reason=f"盘中价，MA55 3%空间止损(跌破昨日MA55 {ctx.ma55_yesterday:.2f})",
                    )

        if current_price < ctx.ma55:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA55)",
            )

        return self.check_take_profit(ctx)
