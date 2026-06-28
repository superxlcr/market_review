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

    # ── 时间止损参数（子类可覆写）──
    TIME_STOP_DAYS: int = 8
    TIME_STOP_MIN_MFP: float = 10.0

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

    # ── 买入：突破 + 拉回 ──

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        ma = self._ma(ctx)
        ma_yest = self._ma(ctx, yesterday=True)
        if ma <= 0 or ma_yest <= 0:
            return None

        if len(ctx.kline_history) < 2:
            return None

        yesterday = ctx.kline_history[-2]
        prev_close = safe_float(yesterday.get("close"))

        # 突破：昨收在MA下方，今日最高价上穿MA
        if prev_close > 0 and prev_close < ma_yest and ctx.high >= ma:
            if ctx.open > ma:
                if ctx.open <= ma * 1.02:
                    # 高开≤2%：直接追高买入
                    return BuySignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ctx.open,
                        reason=f"追高买入，突破MA{self.ma_period}",
                    )
                elif ctx.low <= ma:
                    # 高开>2%但盘中跌回MA：仍可买到MA价格
                    return BuySignal(
                        date=ctx.date, symbol=ctx.symbol,
                        symbol_name=ctx.symbol_name,
                        price=ma, reason=f"突破MA{self.ma_period}",
                    )
                return None  # 高开>2%且全天在MA上方：放弃
            # 低开/平开：盘中突破，可买到MA价格
            return BuySignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ma, reason=f"突破MA{self.ma_period}",
            )

        # 拉回：昨收在MA上方，今日最低价回踩MA
        if prev_close > 0 and prev_close > ma_yest and ctx.low <= ma:
            return BuySignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=ma, reason=f"拉回MA{self.ma_period}",
            )

        return None

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

        # 2. 时间止损: N 个交易日内浮盈从未达阈值 → 收盘卖出
        trading_days = self._trading_days_since_buy(ctx)
        if trading_days >= self.TIME_STOP_DAYS and pos.max_float_profit_pct < self.TIME_STOP_MIN_MFP:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"时间止损(持仓{trading_days}日浮盈未达{self.TIME_STOP_MIN_MFP:.0f}%，收盘卖出)",
            )

        # 3. 三级浮盈止盈（通用，基类实现）
        return self.check_take_profit(ctx)

    def _trading_days_since_buy(self, ctx: DayContext) -> int:
        """持仓交易日数（买入日不计）."""
        if ctx.position is None:
            return 0
        buy_date = ctx.position.buy_date
        return sum(1 for bar in ctx.kline_history
                   if str(bar.get("date", "")) > buy_date)
