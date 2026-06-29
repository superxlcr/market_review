"""MA60 突破拉回 ATR止损版 — 用 ATR(14)×2 替代固定百分比空间止损."""
from .ma_breakthrough import MABreakthroughStrategy, register_strategy
from ..strategy_base import DayContext, BuySignal, SellSignal, safe_float
from marketreview.tools.technical import rows_to_df, calc_atr


@register_strategy("ma60_breakthrough_atr")
class MA60BreakthroughATRStrategy(MABreakthroughStrategy):
    """MA60 突破拉回 + ATR(14)×2 止损.

    买入信号与 MA60 突破拉回完全一致，但在信号中附加 ATR 止损价。
    止损价在设条件单时固定，后续不再变化。
    """

    ma_period = 60
    ATR_PERIOD = 14
    ATR_STOP_MULTIPLIER = 2.0

    @property
    def name(self) -> str:
        return "MA60突破拉回战法(ATR止损)"

    # ── 买入：沿用父类逻辑，附加 ATR 止损信息 ──

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        signal = super().check_buy(ctx)
        if signal is None:
            return None

        atr = self._calc_latest_atr(ctx)
        if atr <= 0:
            return None  # ATR 数据不足，不发信号

        atr_stop_amount = atr * self.ATR_STOP_MULTIPLIER
        atr_stop_price = signal.price - atr_stop_amount
        atr_stop_pct = (atr_stop_amount / signal.price) * 100.0

        signal.atr_stop_price = atr_stop_price
        signal.atr_stop_pct = atr_stop_pct
        signal.reason = (
            f"{signal.reason} "
            f"ATR止损={atr_stop_amount:.2f}({atr_stop_pct:.1f}%)"
        )

        return signal

    # ── 卖出：ATR 止损(盘中) → 战法卖出(跌破MA) → 时间止损 → 三级止盈 ──

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
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

        # 2. 战法卖出：收盘价跌破当日 MA
        ma = self._ma(ctx)
        if ma > 0 and ctx.close < ma:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ctx.close,
                reason=f"战法卖出(跌破MA{self.ma_period})",
            )

        # 3. 时间止损
        time_stop = self.check_time_stop(ctx)
        if time_stop:
            return time_stop

        # 4. 三级浮盈止盈
        return self.check_take_profit(ctx)

    # ── ATR 计算 ──

    def _calc_latest_atr(self, ctx: DayContext) -> float:
        """从 K 线历史计算最新 ATR(14) 值."""
        if len(ctx.kline_history) < self.ATR_PERIOD + 1:
            return 0.0
        df = rows_to_df(ctx.kline_history[-(self.ATR_PERIOD + 1):])
        if df.empty or len(df) < self.ATR_PERIOD + 1:
            return 0.0
        atr_vals = calc_atr(df, period=self.ATR_PERIOD)
        if not atr_vals:
            return 0.0
        return safe_float(atr_vals[-1])
