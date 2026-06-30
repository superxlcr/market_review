"""突破回调一半战法(简化版) — 固定V=P/2.33，不找历史前低.

买入逻辑:
  1. 找到波段新高 P（近半年内最高 high）
  2. V = P / 2.33（固定倍数，不查历史数据）
  3. 62.5% 线 = V + 0.625×(P−V)
  4. 股价从 P 回调，必须先跌破 62.5% 线，才开始监控
  5. 跌破后，找 P 至今的最低 low L，半分位 = (P+L)/2
  6. 上穿触发: 昨日收盘 < 半分位 且 今日最高 ≥ 半分位 → 以半分位买入

卖出逻辑: 空间止损(引擎) → 收盘跌破突破价 → 时间止损 → 三级止盈

===========================================================================
回测结论 (51轮 × 20250201~20260630, 白大与nga池-仅主板):
  25.4笔/轮  胜率11.8%  总收益-7.62%  持仓4.4天  盈亏比2.58

  卖出分布: 战法卖出(收盘跌破突破价) 75.0% | 止盈 11.8% | 盘中止损 8.3%

  失败原因:
  - 半分位是下降趋势中的数学中点(P+L)/2，无实际支撑意义
  - 买入后股票仍在下跌惯性中，80%交易死在1-3天内
  - Tier3止盈均仅+10.1%（vs MA60的+25.5%），趋势股跑不远
  - 时间止损从未触发，仓位活不到8天
  - 二级保护(0%/3%/5%)对结果几乎无影响

  结论: 信号端问题——突破半分位进场偏晚，选出的股票趋势强度不足。
        对比MA60_突破拉回(28.3%胜率/+12.07%收益)，核心差距不在卖出端，
        而在MA60是动态支撑（60日均线随趋势上移），半分位是静态数学线。
        已从策略配置中移除，保留代码供参考。
===========================================================================
"""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, safe_float,
)


@register_strategy("half_retrace_simple")
class HalfRetraceSimpleStrategy(BaseStrategy):
    """突破回调一半战法(简化版 — 固定V=P/2.33)."""

    # ── 参数 ──
    PEAK_LOOKBACK_DAYS: int = 300   # 波峰回溯 ~14个月(交易日)
    PULLBACK_MIN_DAYS: int = 13     # 回调最小交易日数
    V_DIVISOR: float = 2.33         # P / V_DIVISOR = 前低 V

    @property
    def name(self) -> str:
        return "突破回调一半战法(简化版)"

    # ── 买入 ──
    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        history = ctx.kline_history
        if len(history) < self.PULLBACK_MIN_DAYS + 2:
            return None

        today_idx = len(history) - 1

        # ── 1. 找波段新高 P ──
        lookback_start = max(0, today_idx - self.PEAK_LOOKBACK_DAYS)
        peak_high = 0.0
        peak_idx = -1

        for i in range(lookback_start, today_idx + 1):
            h = safe_float(history[i].get("high"))
            if h > peak_high:
                peak_high = h
                peak_idx = i

        # P 必须距今 ≥ 13 天
        if today_idx - peak_idx < self.PULLBACK_MIN_DAYS:
            return None

        # ── 2. 固定 V = P / 2.33 ──
        valley_low = peak_high / self.V_DIVISOR

        # ── 3. 算 62.5% 线 ──
        line_625 = valley_low + 0.625 * (peak_high - valley_low)

        # ── 4. 股价必须已跌破过 62.5% 线 ──
        has_broken_625 = False
        for i in range(peak_idx, today_idx + 1):
            l = safe_float(history[i].get("low"))
            if l <= line_625:
                has_broken_625 = True
                break

        if not has_broken_625:
            return None  # 还没跌破 62.5%，不监控

        # ── 5. 找 P 至今的最低 low L，算半分位 ──
        lowest_low = float('inf')
        for i in range(peak_idx, today_idx + 1):
            l = safe_float(history[i].get("low"))
            if l < lowest_low:
                lowest_low = l

        midpoint = (peak_high + lowest_low) / 2.0

        # ── 6. 预判上穿（条件单：收盘在半分位下方，明天可能突破）──
        yesterday = history[today_idx - 1]
        yesterday_close = safe_float(yesterday.get("close"))

        if yesterday_close < midpoint:
            peak_date = str(history[peak_idx].get("date", "?"))
            return BuySignal(
                date=ctx.date,
                symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=round(midpoint, 2),
                reason=(
                    f"简化版回调半分位{round(midpoint,2)} "
                    f"(P={peak_high:.2f} V=P/{self.V_DIVISOR}={valley_low:.2f} L={lowest_low:.2f})"
                ),
            )

        return None

    def diagnose_buy(self, ctx: DayContext) -> str | None:
        history = ctx.kline_history
        if len(history) < self.PULLBACK_MIN_DAYS + 2:
            return f"K线不足（需≥{self.PULLBACK_MIN_DAYS + 2}日，当前{len(history)}日）"

        today_idx = len(history) - 1

        # 1. 找波峰 P
        lookback_start = max(0, today_idx - self.PEAK_LOOKBACK_DAYS)
        peak_high, peak_idx = 0.0, -1
        for i in range(lookback_start, today_idx + 1):
            h = safe_float(history[i].get("high"))
            if h > peak_high:
                peak_high, peak_idx = h, i

        if peak_idx < 0:
            return "近半年内未找到有效波峰"

        days_since = today_idx - peak_idx
        if days_since < self.PULLBACK_MIN_DAYS:
            peak_date = str(history[peak_idx].get("date", "?"))
            return (f"波峰（{peak_date} {peak_high:.2f}）距今仅{days_since}日，"
                    f"需≥{self.PULLBACK_MIN_DAYS}日")

        # 2. 固定 V = P / 2.33
        valley_low = peak_high / self.V_DIVISOR

        # 3. 算 62.5% 线
        line_625 = valley_low + 0.625 * (peak_high - valley_low)

        # 4. 跌破 62.5% 线？
        has_broken = any(
            safe_float(history[i].get("low")) <= line_625
            for i in range(peak_idx, today_idx + 1))
        if not has_broken:
            return f"尚未跌破62.5%回调线（{line_625:.2f}），不触发监控"

        # 5. 最低低点 L → 半分位
        lowest_low = min(
            (safe_float(history[i].get("low")) for i in range(peak_idx, today_idx + 1)),
            default=float('inf'))
        midpoint = (peak_high + lowest_low) / 2.0

        # 6. 触发条件
        yesterday_close = safe_float(history[today_idx - 1].get("close"))
        if yesterday_close >= midpoint:
            return (f"昨日收盘{yesterday_close:.2f} ≥ 半分位{midpoint:.2f}，"
                    f"未触发上穿条件")

        return None

    # ── 卖出: 收盘跌破突破价 → 时间止损 → 三级止盈 ──
    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None

        pos = ctx.position
        current_price = ctx.close

        # ── 0. 收盘跌破突破价 ──
        if current_price < pos.buy_price:
            return SellSignal(
                date=ctx.date, symbol=ctx.symbol,
                symbol_name=ctx.symbol_name,
                price=current_price,
                reason=f"战法卖出(收盘跌破突破价{pos.buy_price:.2f})",
            )

        # ── 1. 时间止损 ──
        time_stop = self.check_time_stop(ctx)
        if time_stop:
            return time_stop

        # ── 2. 三级浮盈止盈（基类实现）──
        return self.check_take_profit(ctx)
