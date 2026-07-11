"""把 buy_points.py 的 checker 包成可回测的 BuyPointSignal（触发价 + 收盘止损规则）。"""
from __future__ import annotations
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import (
    HalfRetraceChecker, Band50Checker, MAChecker,
)
from .trade_sim import BuyPointSignal

# 页面标签 → checker
_NAME_MAP = {
    "扣抵量均线支撑": ("ma", MAChecker(vol_mode="today", type_name="扣抵量均线支撑")),
    "5日均量均线支撑": ("ma", MAChecker(vol_mode="avg5", type_name="5日均量均线支撑")),
    "回调一半": ("half", HalfRetraceChecker()),
    "波段50%": ("band50", Band50Checker()),
}


def detect_buy_points(df_asc: pd.DataFrame, band: BandResult,
                      selected: list[str]) -> list[BuyPointSignal]:
    out: list[BuyPointSignal] = []
    for name in selected:
        entry = _NAME_MAP.get(name)
        if entry is None:
            continue
        kind, checker = entry
        for bp in checker.check(df_asc, band):
            if kind == "ma":
                # 均线支撑：收盘止损 = 跌破 MA（该周期）；触发价 = MA 值
                try:
                    period = int(bp.position.replace("MA", ""))
                except ValueError:
                    period = 0
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="ma", close_stop_period=period,
                    reason=bp.reason,
                ))
            else:
                # 回调一半 / 波段50%：收盘止损 = 跌破买入价
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="entry", close_stop_period=0,
                    reason=bp.reason,
                ))
    return out
