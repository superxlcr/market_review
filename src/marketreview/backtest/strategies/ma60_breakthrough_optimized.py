"""MA60 突破拉回优化版 — 去掉收盘跌破 MA60 卖出条件，仅保留时间止损 + 三级止盈."""
from .ma_breakthrough import MABreakthroughStrategy, register_strategy
from ..strategy_base import DayContext, SellSignal


@register_strategy("ma60_breakthrough_optimized")
class MA60BreakthroughOptimizedStrategy(MABreakthroughStrategy):
    ma_period = 60

    @property
    def name(self) -> str:
        return "MA60突破拉回战法(优化版)"

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        """卖出逻辑：跳过战法卖出（不因跌破 MA60 卖出），仅保留时间止损 + 三级止盈."""
        if ctx.position is None:
            return None

        # 1. 时间止损
        time_stop = self.check_time_stop(ctx)
        if time_stop:
            return time_stop

        # 2. 三级浮盈止盈
        return self.check_take_profit(ctx)
