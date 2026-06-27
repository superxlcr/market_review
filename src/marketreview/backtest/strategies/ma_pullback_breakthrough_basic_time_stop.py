"""长期均线突破拉回 + 时间止损策略（无MA空间止损）."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


# MA列表，优先级从短到长
_MA_LIST = [
    ("MA60", "ma60", "ma60_yesterday"),
    ("MA120", "ma120", "ma120_yesterday"),
    ("MA240", "ma240", "ma240_yesterday"),
]


@register_strategy("ma_pullback_breakthrough_basic_time_stop")
class MAPullbackBreakthroughBasicTimeStopStrategy(BaseStrategy):

    # ── 时间止损参数 ──
    TIME_STOP_DAYS: int = 8            # 持仓交易日数（买入日不算）
    TIME_STOP_MIN_MFP: float = 10.0    # 期间最大浮盈未达此%则触发

    @property
    def name(self) -> str:
        return "长期均线突破拉回+时间止损(无MA止损)"

    # ── 买入：同突破拉回（三条均线，拉回优先，其次突破，短均线优先）──
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

            # 拉回条件
            if prev_close > ma_yest and ctx.low <= ma_today:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ma_today,
                    reason=f"拉回{ma_label}",
                    entry_ma_type=ma_label,
                )

            # 突破条件
            if prev_close < ma_yest and ctx.high >= ma_today:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ma_today,
                    reason=f"突破{ma_label}",
                    entry_ma_type=ma_label,
                )

        return None

    # ── 卖出：战法卖出 → 时间止损 → 三级止盈 ──
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
        if ma_today <= 0:
            return None

        # ── 1. 战法卖出: 收盘价跌破当日进场MA ──
        if current_price < ma_today:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"战法卖出(跌破{ma_type})",
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

    @staticmethod
    def _ma_attrs(ma_type: str) -> tuple[str | None, str | None]:
        for label, today_attr, yest_attr in _MA_LIST:
            if label == ma_type:
                return today_attr, yest_attr
        return None, None
