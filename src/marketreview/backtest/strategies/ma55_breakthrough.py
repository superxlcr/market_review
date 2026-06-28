"""MA55 突破拉回战法 — 薄壳子类，所有逻辑在 MABreakthroughStrategy 基类."""
from .ma_breakthrough import MABreakthroughStrategy, register_strategy


@register_strategy("ma55_breakthrough")
class MA55BreakthroughStrategy(MABreakthroughStrategy):
    ma_period = 55
