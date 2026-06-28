"""MA 突破+拉回 通用战法基类 — 子类只需覆写 ma_period."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


class MABreakthroughStrategy(BaseStrategy):
    """参数化 MA 突破拉回战法 — 所有 MA 周期共用同一套买卖逻辑.

    子类示例::

        @register_strategy("ma60_breakthrough")
        class MA60BreakthroughStrategy(MABreakthroughStrategy):
            ma_period = 60
    """

    ma_period: int = 60  # 子类覆写此值

    @property
    def name(self) -> str:
        return f"MA{self.ma_period}突破拉回战法"

    @property
    def lookback_trading_days(self) -> int:
        """确保有足够 K 线计算 MA 值."""
        return max(60, self.ma_period)

    # ── 动态 MA 字段访问 ──

    def _ma(self, ctx: DayContext, yesterday: bool = False) -> float:
        """读取 ctx 上的当日/昨日 MA 值."""
        suffix = "_yesterday" if yesterday else ""
        return safe_float(getattr(ctx, f"ma{self.ma_period}{suffix}"))

    # ── 买入：突破预期 + 拉回预期（条件单预判，不做确认）──

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        ma = self._ma(ctx)
        if ma <= 0:
            return None

        if len(ctx.kline_history) < 2:
            return None

        # 收盘价在MA下方 → 预期突破，明天可能上穿MA
        if ctx.close > 0 and ctx.close < ma:
            return BuySignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ma, reason=f"突破MA{self.ma_period}",
            )

        # 收盘价在MA上方 → 预期拉回，明天可能回踩MA
        if ctx.close > 0 and ctx.close > ma:
            return BuySignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ma, reason=f"拉回MA{self.ma_period}",
            )

        return None

    def diagnose_buy(self, ctx: DayContext) -> str | None:
        ma = self._ma(ctx)
        if ma <= 0:
            return f"MA{self.ma_period} 数据不可用（K线不足或计算异常）"
        return f"收盘价 {ctx.close:.2f} 与 MA{self.ma_period}（{ma:.2f}）相等，无法判定方向"

    # ── 卖出：战法卖出 → 时间止损 → 三级止盈 ──

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None

        ma = self._ma(ctx)
        if ma <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        # 1. 战法卖出: 收盘价跌破当日 MA
        if current_price < ma:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"战法卖出(跌破MA{self.ma_period})",
            )

        # 2. 时间止损
        time_stop = self.check_time_stop(ctx)
        if time_stop:
            return time_stop

        # 3. 三级浮盈止盈（通用，基类实现）
        return self.check_take_profit(ctx)
