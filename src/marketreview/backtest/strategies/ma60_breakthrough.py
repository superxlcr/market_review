"""MA60 突破+拉回 战法（空间止损 + 战法卖出 + 时间止损 + 三级止盈）."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma60_breakthrough")
class MA60BreakthroughStrategy(BaseStrategy):

    # ── 时间止损参数 ──
    TIME_STOP_DAYS: int = 8            # 持仓交易日数（买入日不算）
    TIME_STOP_MIN_MFP: float = 10.0    # 期间最大浮盈未达此%则触发

    @property
    def name(self) -> str:
        return "MA60突破拉回战法"

    # ── 买入：突破 + 拉回 ──
    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma60 is None or ctx.ma60_yesterday is None:
            return None
        if ctx.ma60 <= 0 or ctx.ma60_yesterday <= 0:
            return None

        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close < ctx.ma60_yesterday and ctx.high >= ctx.ma60:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma60, reason="突破MA60",
                )

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

    # ── 卖出：战法卖出 → 时间止损 → 三级止盈 ──
    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        if ctx.ma60 is None or ctx.ma60 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        # ── 1. 战法卖出: 收盘价跌破当日MA60 ──
        if current_price < ctx.ma60:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA60)",
            )

        # ── 2. 时间止损: N个交易日内浮盈从未达阈值 → 收盘卖出 ──
        trading_days = self._trading_days_since_buy(ctx)
        if trading_days >= self.TIME_STOP_DAYS and pos.max_float_profit_pct < self.TIME_STOP_MIN_MFP:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"时间止损(持仓{trading_days}日浮盈未达{self.TIME_STOP_MIN_MFP:.0f}%，收盘卖出)",
            )

        # ── 3. 三级浮盈止盈（通用，基类实现）──
        return self.check_take_profit(ctx)

    def _trading_days_since_buy(self, ctx: DayContext) -> int:
        """持仓交易日数（买入日不计）."""
        if ctx.position is None:
            return 0
        buy_date = ctx.position.buy_date
        return sum(1 for bar in ctx.kline_history
                   if str(bar.get("date", "")) > buy_date)
