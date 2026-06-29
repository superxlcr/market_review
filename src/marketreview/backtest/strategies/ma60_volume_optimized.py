"""MA60 成交量限制优化版 — 去掉收盘跌破 MA60 卖出条件."""
from .ma60_volume import VolumeStrategy, register_strategy
from ..strategy_base import DayContext, SellSignal


@register_strategy("ma60_volume_optimized")
class MA60VolumeOptimizedStrategy(VolumeStrategy):
    """MA60 成交量限制 + 去掉收盘跌破 MA60 卖出条件."""

    ma_period = 60

    @property
    def name(self) -> str:
        return "MA60成交量限制战法(优化版)"

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        """卖出逻辑：跳过战法卖出（不因跌破 MA60 卖出），ATR止损 → 时间止损 → 三级止盈."""
        if ctx.position is None:
            return None

        pos = ctx.position

        # 1. ATR 止损：盘中最低价跌破固定 ATR 止损价即卖出
        if pos.atr_stop_price > 0 and ctx.low <= pos.atr_stop_price:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=pos.atr_stop_price,
                reason=f"ATR止损(盘中跌破{pos.atr_stop_price:.2f})",
            )

        # 2. 时间止损
        time_stop = self.check_time_stop(ctx)
        if time_stop:
            return time_stop

        # 3. 三级浮盈止盈
        return self.check_take_profit(ctx)
