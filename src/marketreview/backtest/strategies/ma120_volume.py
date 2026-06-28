"""MA120 突破拉回 + 成交量限制 战法."""
from .ma60_volume import VolumeStrategy, register_strategy


@register_strategy("ma120_volume")
class MA120VolumeStrategy(VolumeStrategy):
    """MA120 突破拉回 + 成交量限制."""

    ma_period = 120

    @property
    def name(self) -> str:
        return "MA120成交量限制战法"
