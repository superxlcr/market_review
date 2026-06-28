"""成交量限制战法 — VolumeStrategy 基类 + MA60 具名子类."""
from .ma_breakthrough import MABreakthroughStrategy, register_strategy, safe_float
from ..strategy_base import DayContext, BuySignal


class VolumeStrategy(MABreakthroughStrategy):
    """成交量限制基类 — 在 MA 突破拉回基础上叠加量能过滤.

    子类只需覆写 ma_period 即可，量能阈值从配置读取（VOLUME_5D/10D_THRESHOLD_PCT）.
    """

    VOLUME_5D_THRESHOLD_PCT: float = -10.0   # 昨额 vs 5日均量 最低%（可被引擎覆盖）
    VOLUME_10D_THRESHOLD_PCT: float = -5.0   # 昨额 vs 10日均量 最低%（可被引擎覆盖）

    def _yesterday_limit_flag(self, hist: list[dict]) -> str:
        """检测昨日是否涨停（一字板 / 换手板），返回标记字符串或空.

        涨停日成交额极低是正常的（封板无量），标记出来避免误判缩量.
        """
        if len(hist) < 3:
            return ""
        yest = hist[-2]
        prev = hist[-3]
        yest_close = safe_float(yest.get("close"))
        yest_high = safe_float(yest.get("high"))
        yest_open = safe_float(yest.get("open"))
        yest_low = safe_float(yest.get("low"))
        prev_close = safe_float(prev.get("close"))
        if prev_close <= 0:
            return ""
        chg_pct = (yest_close - prev_close) / prev_close * 100
        if chg_pct < 9.5:
            return ""
        # 涨幅 ≥9.5% 且 收盘 ≈ 最高价 → 涨停
        if abs(yest_close - yest_high) / max(yest_close, 0.01) < 0.001:
            if yest_open == yest_high and yest_low == yest_high:
                return "⚠一字板"
            return "⚠涨停"
        return ""

    def _avg_amount_str(self, hist: list[dict], yesterday_amount: float) -> str:
        """构建均额对比: '5均:2.8亿(+14%) 10均:2.5亿(+28%)'.

        5/10 日均额 = 最近 5/10 个交易日（不含今日）的成交额均值.
        """
        parts = []
        for days, label in [(5, "5均"), (10, "10均")]:
            if len(hist) < days + 1:
                parts.append(f"{label}:?")
                continue
            window_amounts = [
                safe_float(hist[-(i + 2)].get("amount")) / 1e5
                for i in range(days)
            ]
            avg = sum(window_amounts) / days if window_amounts else 0.0
            if avg > 0:
                vs = (yesterday_amount / avg - 1) * 100
                parts.append(f"{label}:{avg:.1f}亿({vs:+.0f}%)")
            else:
                parts.append(f"{label}:0")
        return " ".join(parts)

    def _check_volume_pass(self, hist: list[dict]) -> tuple[bool, str]:
        """量能过滤：昨额 vs 5/10 日均量，阈值从类属性读取.

        Returns (passed, detail_str). detail_str 仅在不过关时有内容.
        """
        if len(hist) < 12:
            return True, ""

        yesterday_amount = safe_float(hist[-2].get("amount")) / 1e5

        # 5日均量
        amounts_5 = [
            safe_float(hist[-(i + 2)].get("amount")) / 1e5
            for i in range(5)
        ]
        avg_5 = sum(amounts_5) / 5 if amounts_5 else 0.0

        # 10日均量
        amounts_10 = [
            safe_float(hist[-(i + 2)].get("amount")) / 1e5
            for i in range(10)
        ]
        avg_10 = sum(amounts_10) / 10 if amounts_10 else 0.0

        if avg_5 <= 0 or avg_10 <= 0:
            return True, ""

        vs_5 = (yesterday_amount / avg_5 - 1) * 100
        vs_10 = (yesterday_amount / avg_10 - 1) * 100

        fails = []
        if vs_5 < self.VOLUME_5D_THRESHOLD_PCT:
            fails.append(f"昨额vs5均{vs_5:+.0f}%(需≥{self.VOLUME_5D_THRESHOLD_PCT:.0f}%)")
        if vs_10 < self.VOLUME_10D_THRESHOLD_PCT:
            fails.append(f"昨额vs10均{vs_10:+.0f}%(需≥{self.VOLUME_10D_THRESHOLD_PCT:.0f}%)")

        if fails:
            return False, " | ".join(fails)
        return True, ""

    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        signal = super().check_buy(ctx)
        if signal is None:
            self._last_volume_filter = None
            return None

        hist = ctx.kline_history
        if len(hist) < 2:
            self._last_volume_filter = None
            return signal

        # ── 量能过滤 ──
        vol_pass, vol_fail_reason = self._check_volume_pass(hist)
        if not vol_pass:
            yesterday_amount = safe_float(hist[-2].get("amount")) / 1e5
            avg_str = self._avg_amount_str(hist, yesterday_amount)
            detail = (
                f"{signal.reason}"
                f"(昨额:{yesterday_amount:.1f}亿"
                f" | {avg_str})"
                f" — ❌量能过滤({vol_fail_reason})"
            )
            self._last_volume_filter = {
                "date": ctx.date,
                "symbol": ctx.symbol,
                "symbol_name": ctx.symbol_name,
                "price": signal.price,
                "reason": detail,
            }
            return None

        self._last_volume_filter = None

        # ── 昨日涨停检测 ──
        limit_flag = self._yesterday_limit_flag(hist)

        # ── 昨日成交额（千元 → 亿）──
        yesterday_amount = safe_float(hist[-2].get("amount")) / 1e5

        # ── 5日/10日均额对比 ──
        avg_str = self._avg_amount_str(hist, yesterday_amount)

        signal.reason = (
            f"{signal.reason}"
            f"(昨额:{yesterday_amount:.1f}亿{limit_flag}"
            f" | {avg_str})"
        )
        return signal

    def diagnose_buy(self, ctx: DayContext) -> str | None:
        vol_filter = getattr(self, '_last_volume_filter', None)
        if vol_filter:
            self._last_volume_filter = None
            return f"量能不足 — {vol_filter['reason']}"
        return super().diagnose_buy(ctx)


@register_strategy("ma60_volume")
class MA60VolumeStrategy(VolumeStrategy):
    """MA60 突破拉回 + 成交量限制."""

    ma_period = 60

    @property
    def name(self) -> str:
        return "MA60成交量限制战法"
