"""MA120 突破+拉回 买入策略 — 跌破MA120/空间止损/三级浮盈止盈卖出."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma120_breakthrough")
class MA120BreakthroughStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA120突破+拉回"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma120 is None or ctx.ma120_yesterday is None:
            return None
        if ctx.ma120 <= 0 or ctx.ma120_yesterday <= 0:
            return None

        # 突破: yesterday close < yesterday MA120 AND today high >= today MA120
        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close < ctx.ma120_yesterday and ctx.high >= ctx.ma120:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma120, reason="突破MA120",
                )

        # 拉回: yesterday close > yesterday MA120 AND today low <= today MA120
        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close > ctx.ma120_yesterday and ctx.low <= ctx.ma120:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma120, reason="拉回MA120",
                )

        return None

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        if ctx.ma120 is None or ctx.ma120 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        # ── MA120止损: 盘中最低价跌破昨日MA120的3% ──
        if ctx.ma120_yesterday > 0:
            ma120_stop = ctx.ma120_yesterday * 0.97
            if ctx.low <= ma120_stop:
                if ctx.open > 0 and ctx.open <= ma120_stop:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ctx.open,
                        reason=f"开盘价，MA120 3%空间止损(昨日MA120 {ctx.ma120_yesterday:.2f})",
                    )
                else:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ma120_stop,
                        reason=f"盘中价，MA120 3%空间止损(跌破昨日MA120 {ctx.ma120_yesterday:.2f})",
                    )

        # ── 战法卖出: 收盘价跌破当日MA120 ──
        if current_price < ctx.ma120:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA120)",
            )

        # ── 三级浮盈止盈（通用，基类实现）──
        return self.check_take_profit(ctx)
