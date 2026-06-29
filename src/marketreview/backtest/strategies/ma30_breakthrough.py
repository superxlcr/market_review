"""MA30 突破拉回战法 — 薄壳子类，所有逻辑在 MABreakthroughStrategy 基类."""
from .ma_breakthrough import MABreakthroughStrategy, register_strategy


@register_strategy("ma30_breakthrough")
class MA30BreakthroughStrategy(MABreakthroughStrategy):
    ma_period = 30
