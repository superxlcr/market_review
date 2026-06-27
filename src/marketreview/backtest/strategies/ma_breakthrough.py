"""突破战法 — 三条均线(60/120/240)突破买入，对应均线止损."""
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


@register_strategy("ma_breakthrough")
class MABreakthroughStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "突破战法(MA60/120/240)"

    # ── 买入：三条均线突破，短均线优先 ──
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
            # 突破条件: 昨日收盘 < 昨日MA AND 今日最高价 ≥ 今日MA
            if prev_close < ma_yest and ctx.high >= ma_today:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ma_today,
                    reason=f"突破{ma_label}",
                    entry_ma_type=ma_label,
                )

        return None

    # ── 卖出：MA止损 → 战法卖出 → 三级止盈 ──
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

        # ── 1. MA止损: 盘中最低价跌破昨日进场MA的3% ──
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

        # ── 2. 战法卖出: 收盘价跌破当日进场MA ──
        if current_price < ma_today:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"战法卖出(跌破{ma_type})",
            )

        # ── 3. 三级浮盈止盈（通用，基类实现）──
        return self.check_take_profit(ctx)

    @staticmethod
    def _ma_attrs(ma_type: str) -> tuple[str | None, str | None]:
        for label, today_attr, yest_attr in _MA_LIST:
            if label == ma_type:
                return today_attr, yest_attr
        return None, None
