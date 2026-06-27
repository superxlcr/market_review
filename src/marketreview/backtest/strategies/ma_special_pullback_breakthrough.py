"""长期特殊均线突破拉回战法 — MA55/144 突破+拉回买入，对应均线止损."""
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

    @property
    def name(self) -> str:
        return "长期特殊均线突破拉回(MA55/144)"

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
        ma_yest = getattr(ctx, ma_yest_attr, 0.0)
        if ma_today <= 0:
            return None

        if ma_yest > 0:
            ma_stop = ma_yest * 0.97
            if ctx.low <= ma_stop:
                if ctx.open > 0 and ctx.open <= ma_stop:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ctx.open,
                        reason=f"开盘价，{ma_type} 3%空间止损(昨日{ma_type} {ma_yest:.2f})",
                    )
                else:
                    return SellSignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ma_stop,
                        reason=f"盘中价，{ma_type} 3%空间止损(跌破昨日{ma_type} {ma_yest:.2f})",
                    )

        if current_price < ma_today:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"战法卖出(跌破{ma_type})",
            )

        return self.check_take_profit(ctx)

    @staticmethod
    def _ma_attrs(ma_type: str) -> tuple[str | None, str | None]:
        for label, today_attr, yest_attr in _MA_LIST:
            if label == ma_type:
                return today_attr, yest_attr
        return None, None
