"""MA55 突破拉回 + 成交量观察 战法 — 买入原因附成交额上下文，不做过滤判断."""
from .ma_breakthrough import MABreakthroughStrategy, register_strategy, safe_float
from ..strategy_base import DayContext, BuySignal


@register_strategy("ma55_volume")
class MA55VolumeStrategy(MABreakthroughStrategy):
    """MA55 突破拉回 + 成交额观察.

    与纯 MA55 策略买卖逻辑完全一致，仅在买入信号的 reason 中附带成交额信息：
      - 昨日成交额（买入当天不可知）
      - MA55 扣抵量（55 天前的单日成交额）
      - 扣抵 5 日均值（扣抵日 + 后续 4 天均值，与市场全景指数约定一致）
      - 昨 / 扣抵 对比百分比
      - 昨 / 扣抵5日均 对比百分比
    """

    ma_period = 55

    @property
    def name(self) -> str:
        return "MA55成交量观察战法"

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        signal = super().check_buy(ctx)
        if signal is None:
            return None

        hist = ctx.kline_history
        # 至少需要: 昨日 + 扣抵日 + 扣抵窗口
        if len(hist) < self.ma_period + 6:
            return signal  # 数据不足，返回原始信号

        # ── 昨日成交额（千元 → 亿）──
        yesterday_amount = safe_float(hist[-2].get("amount")) / 1e5

        # ── MA55 扣抵量（55 天前的单日成交额）──
        deduct_idx = -(self.ma_period + 1)  # 今日[-1], 55天前即[-56]
        if abs(deduct_idx) > len(hist):
            return signal
        deduct_amount = safe_float(hist[deduct_idx].get("amount")) / 1e5

        # ── 扣抵 5 日均值（与市场全景 get_offset_info 约定一致: MA20/60/120/240 → window=5）──
        window = 5
        window_start = deduct_idx
        window_end = min(deduct_idx + window, 0)
        window_amounts = [
            safe_float(hist[i].get("amount")) / 1e5
            for i in range(window_start, window_end)
        ]
        avg_deduct = sum(window_amounts) / len(window_amounts) if window_amounts else 0.0

        # ── 对比百分比 ──
        vs_deduct = (yesterday_amount / deduct_amount - 1) * 100 if deduct_amount > 0 else 0.0
        vs_avg = (yesterday_amount / avg_deduct - 1) * 100 if avg_deduct > 0 else 0.0

        signal.reason = (
            f"{signal.reason}"
            f"(昨额:{yesterday_amount:.1f}亿, "
            f"扣抵:{deduct_amount:.1f}亿, "
            f"扣抵5日均:{avg_deduct:.1f}亿, "
            f"昨/扣抵:{vs_deduct:+.0f}%, "
            f"昨/均:{vs_avg:+.0f}%)"
        )
        return signal
