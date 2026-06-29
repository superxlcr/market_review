"""MA 突破+拉回 通用战法基类 — 子类只需覆写 ma_period."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)
from marketreview.tools.technical import rows_to_df, calc_atr


class MABreakthroughStrategy(BaseStrategy):
    """参数化 MA 突破拉回战法 — 所有 MA 周期共用同一套买卖逻辑.

    子类示例::

        @register_strategy("ma60_breakthrough")
        class MA60BreakthroughStrategy(MABreakthroughStrategy):
            ma_period = 60

    ATR 止损: 配置 ATR倍数 > 0 启用，买入时固定止损价，盘中跌破触发.
    """

    ma_period: int = 60  # 子类覆写此值
    atr_stop_multiplier: float = 0.0  # >0 启用 ATR 止损，引擎从配置注入
    ATR_PERIOD: int = 14

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

        signal = None

        # 收盘价在MA下方 → 预期突破，明天可能上穿MA
        if ctx.close > 0 and ctx.close < ma:
            signal = BuySignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ma, reason=f"突破MA{self.ma_period}",
            )

        # 收盘价在MA上方 → 预期拉回，明天可能回踩MA
        elif ctx.close > 0 and ctx.close > ma:
            signal = BuySignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ma, reason=f"拉回MA{self.ma_period}",
            )

        if signal is None:
            return None

        # ATR 止损：倍数 > 0 时附加 ATR 止损价
        if self.atr_stop_multiplier > 0:
            atr = self._calc_latest_atr(ctx)
            if atr <= 0:
                return None  # ATR 数据不足，不发信号
            atr_stop_amount = atr * self.atr_stop_multiplier
            atr_stop_price = signal.price - atr_stop_amount
            atr_stop_pct = (atr_stop_amount / signal.price) * 100.0
            signal.atr_stop_price = atr_stop_price
            signal.atr_stop_pct = atr_stop_pct
            signal.reason = (
                f"{signal.reason} "
                f"ATR止损={atr_stop_amount:.2f}({atr_stop_pct:.1f}%)"
            )

        return signal

    def diagnose_buy(self, ctx: DayContext) -> str | None:
        ma = self._ma(ctx)
        if ma <= 0:
            return f"MA{self.ma_period} 数据不可用（K线不足或计算异常）"
        return f"收盘价 {ctx.close:.2f} 与 MA{self.ma_period}（{ma:.2f}）相等，无法判定方向"

    # ── 卖出：ATR止损(盘中) → 战法卖出 → 时间止损 → 三级止盈 ──

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

        ma = self._ma(ctx)
        if ma <= 0:
            return None

        current_price = ctx.close

        # 2. 战法卖出: 收盘价跌破当日 MA
        if current_price < ma:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"战法卖出(跌破MA{self.ma_period})",
            )

        # 3. 时间止损
        time_stop = self.check_time_stop(ctx)
        if time_stop:
            return time_stop

        # 4. 三级浮盈止盈（通用，基类实现）
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
