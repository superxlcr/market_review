"""MA60 突破拉回 + 成交量限制 战法."""
from .ma55_volume import MA55VolumeStrategy, register_strategy


@register_strategy("ma60_volume")
class MA60VolumeStrategy(MA55VolumeStrategy):
    """MA60 突破拉回 + 成交量限制.

    与 MA55 成交量限制策略逻辑完全一致，仅均线周期改为 60.
    量能门槛：
      - 昨额 vs 5日均量 ≥ -10%
      - 昨额 vs 10日均量 ≥ -5%
    """

    ma_period = 60

    @property
    def name(self) -> str:
        return "MA60成交量限制战法"
