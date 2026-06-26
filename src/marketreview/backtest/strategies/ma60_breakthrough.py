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

        # ── 三级浮盈止盈（用日内最低价判断盘中触发）──
        mfp = pos.max_float_profit_pct

        if mfp >= 20.0:
            # Tier 3: 保留最高浮盈的80%，日内最低价触及即卖出
            threshold_price = pos.buy_price * (1 + mfp * 0.80 / 100.0)
            if ctx.low <= threshold_price:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=threshold_price,
                    reason=f"止盈(浮盈曾达{mfp:.1f}%→保80%即{threshold_price:.2f})",
                )

        elif mfp >= 10.0:
            # Tier 2: 保护5%浮盈，日内最低价触及买入价×1.05即卖出
            protect_price = pos.buy_price * 1.05
            if ctx.low <= protect_price:
                return SellSignal(
                    date=ctx.date, symbol=ctx.symbol,
                    symbol_name=ctx.symbol_name,
                    price=protect_price,
                    reason=f"止盈(浮盈曾达{mfp:.1f}%→保5%即{protect_price:.2f})",
                )

        # Tier 1 (mfp < 10%): no take-profit, rely on stop-loss only
        return None
