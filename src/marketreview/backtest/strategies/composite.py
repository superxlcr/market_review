"""组合战法 — 多个子战法按优先级组合，买/卖同源.

工作原理:
  - check_buy: 按 SUB_STRATEGIES 顺序遍历子策略，首个触发者胜
  - check_sell: 读 Position.strategy_tag 找到入库时的子策略，委托卖给它
  - 以哪个战法买入，就以哪个战法卖出（止盈/止损逻辑同源）

用法（子类只需覆写 SUB_STRATEGIES）:
  class MyCombo(CompositeStrategy):
      SUB_STRATEGIES = ["half_retrace", "ma60_breakthrough"]  # 优先回调一半
"""
from ..strategy_base import (
    BaseStrategy, DayContext, BuySignal, SellSignal,
    register_strategy, create_strategy,
)


class CompositeStrategy(BaseStrategy):
    """多战法优先级组合基类 — 子类覆写 SUB_STRATEGIES 即可."""

    # 子战法注册名列表，按优先级排列（越靠前越优先）
    SUB_STRATEGIES: list[str] = []

    def __init__(self):
        if not self.SUB_STRATEGIES:
            raise ValueError(f"{self.__class__.__name__}: SUB_STRATEGIES must not be empty")
        self._subs: list[tuple[str, BaseStrategy]] = []
        for name in self.SUB_STRATEGIES:
            inst = create_strategy(name)
            if inst is None:
                raise ValueError(f"{self.__class__.__name__}: unknown sub-strategy '{name}'")
            self._subs.append((name, inst))

    @property
    def name(self) -> str:
        return "组合战法"

    @property
    def lookback_trading_days(self) -> int:
        return max((s.lookback_trading_days for _, s in self._subs), default=60)

    # ── 买入: 按优先级遍历，首个触发者胜 ──
    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        for tag, sub in self._subs:
            sig = sub.check_buy(ctx)
            if sig is not None:
                sig.strategy_tag = tag
                return sig
        return None

    def diagnose_buy(self, ctx: DayContext) -> str | None:
        lines = []
        for tag, sub in self._subs:
            diag = sub.diagnose_buy(ctx)
            if diag:
                lines.append(f"• {sub.name}：{diag}")
            else:
                lines.append(f"• {sub.name}：未触发")
        return "\n".join(lines) if lines else None

    # ── 卖出: 找到入库时的子策略，委托给它 ──
    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        if ctx.position is None:
            return None
        tag = ctx.position.strategy_tag
        for t, sub in self._subs:
            if t == tag:
                return sub.check_sell(ctx)
        # 兜底：tag 不匹配时用第一个子策略（不应发生）
        return self._subs[0][1].check_sell(ctx)


# ── 具名组合 ──

@register_strategy("ma60_ma120")
class MA60MA120Strategy(CompositeStrategy):
    """MA60 + MA120 双均线组合 — 优先 MA60."""

    SUB_STRATEGIES = ["ma60_breakthrough", "ma120_breakthrough"]

    @property
    def name(self) -> str:
        return "MA60+MA120组合"

    @property
    def lookback_trading_days(self) -> int:
        return 480


@register_strategy("ma60_ma120_volume")
class MA60MA120VolumeStrategy(CompositeStrategy):
    """MA60成交量 + MA120成交量 组合 — 优先 MA60."""

    SUB_STRATEGIES = ["ma60_volume", "ma120_volume"]

    @property
    def name(self) -> str:
        return "MA60+MA120成交量组合"

    @property
    def lookback_trading_days(self) -> int:
        return max(60, 120)


