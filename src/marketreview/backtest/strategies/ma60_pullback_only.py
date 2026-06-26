"""MA60 仅拉回买入策略 — 同突破拉回，但去掉突破信号."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma60_pullback_only")
class MA60PullbackOnlyStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA60仅拉回"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma60 is None or ctx.ma60_yesterday is None:
            return None
        if ctx.ma60 <= 0 or ctx.ma60_yesterday <= 0:
            return None

        # Only 拉回, no 突破
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
        """Identical sell logic to MA60BreakthroughStrategy."""
        if ctx.position is None:
            return None
        if ctx.ma60 is None or ctx.ma60 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        if current_price < ctx.ma60:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA60)",
            )

        mfp = pos.max_float_profit_pct

        if mfp >= 20.0:
            threshold_pct = mfp * 0.80
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < threshold_pct:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )
        elif mfp >= 10.0:
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < mfp - 5.0:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )

        return None
