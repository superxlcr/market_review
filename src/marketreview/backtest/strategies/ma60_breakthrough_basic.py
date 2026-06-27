"""MA60 突破+拉回 买入策略（无MA60空间止损）— 战法卖出 + 三级浮盈止盈."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma60_breakthrough_basic")
class MA60BreakthroughBasicStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA60突破+拉回(无MA60止损)"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma60 is None or ctx.ma60_yesterday is None:
            return None
        if ctx.ma60 <= 0 or ctx.ma60_yesterday <= 0:
            return None

        # 突破: yesterday close < yesterday MA60 AND today high >= today MA60
        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close < ctx.ma60_yesterday and ctx.high >= ctx.ma60:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma60, reason="突破MA60",
                )

        # 拉回: yesterday close > yesterday MA60 AND today low <= today MA60
        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close > ctx.ma60_yesterday and ctx.low <= ctx.ma60:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma60, reason="拉回MA60",
                )

        return None

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        if ctx.ma60 is None or ctx.ma60 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        # ── 战法卖出: 收盘价跌破当日MA60 ──
        if current_price < ctx.ma60:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA60)",
            )

        # ── 三级浮盈止盈（通用，基类实现）──
        return self.check_take_profit(ctx)
