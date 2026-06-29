"""MA20 突破拉回战法 — 薄壳子类，所有逻辑在 MABreakthroughStrategy 基类."""
from .ma_breakthrough import MABreakthroughStrategy, register_strategy


@register_strategy("ma20_breakthrough")
class MA20BreakthroughStrategy(MABreakthroughStrategy):
    ma_period = 20
