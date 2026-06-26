"""MA60 突破+拉回 买入策略 — 跌破MA60/空间止损/三级浮盈止盈卖出."""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("ma60_breakthrough")
class MA60BreakthroughStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MA60突破+拉回"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        if ctx.ma60 is None or ctx.ma60_yesterday is None:
            return None
        if ctx.ma60 <= 0 or ctx.ma60_yesterday <= 0:
            return None

        # 突破: yesterday close < yesterday MA60 AND today high >= today MA60
        if len(ctx.kline_history) >= 2:
            yesterday = ctx.kline_history[-2]
            prev_close = safe_float(yesterday.get("close"))
            if prev_close > 0 and prev_close < ctx.ma60_yesterday and ctx.high >= ctx.ma60:
                return BuySignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=ctx.ma60, reason="突破MA60",
                )

        # 拉回: yesterday close > yesterday MA60 AND today low <= today MA60
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

    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        if ctx.ma60 is None or ctx.ma60 <= 0:
            return None

        pos = ctx.position
        current_price = ctx.close

        # ── 战法卖出: 收盘价跌破当日MA60 ──
        if current_price < ctx.ma60:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price, reason="战法卖出(跌破MA60)",
            )

        # ── 三级浮盈止盈 ──
        mfp = pos.max_float_profit_pct

        if mfp >= 20.0:
            # Tier 3: keep 80% of max, sell when drops below
            threshold_pct = mfp * 0.80
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < threshold_pct:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )

        elif mfp >= 10.0:
            # Tier 2: 回落 5% from max
            current_float = (current_price - pos.buy_price) / pos.buy_price * 100.0
            if current_float < mfp - 5.0:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=current_price,
                    reason=f"止盈(浮盈{mfp:.1f}%回落至{current_float:.1f}%)",
                )

        # Tier 1 (mfp < 10%): no take-profit, rely on stop-loss only
        return None
