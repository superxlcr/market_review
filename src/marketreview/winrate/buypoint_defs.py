"""把 buy_points.py 的 checker 包成可回测的 BuyPointSignal（触发价 + 收盘止损规则）。"""
from __future__ import annotations
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import (
    HalfRetraceChecker, Band50Checker, MAChecker, VolPriceNodeChecker,
    RandomBaselineChecker,
)
from .trade_sim import BuyPointSignal

# 页面标签 → checker
_NAME_MAP = {
    # 组合变体（[60,120,240]）—— 用于对比"量确认"维度：今日量 vs 5日均量 vs 无量
    "扣抵量均线支撑": ("ma", MAChecker(vol_mode="today", periods=[60, 120, 240], type_name="扣抵量均线支撑")),
    "5日均量均线支撑": ("ma", MAChecker(vol_mode="avg5", periods=[60, 120, 240], type_name="5日均量均线支撑")),
    "无量均线支撑": ("ma", MAChecker(vol_mode="none", periods=[60, 120, 240], type_name="无量均线支撑")),
    # 单周期变体（今日量）—— 用于对比"均线周期"维度
    "MA20支撑": ("ma", MAChecker(vol_mode="today", periods=[20], type_name="MA20支撑")),
    "MA55支撑": ("ma", MAChecker(vol_mode="today", periods=[55], type_name="MA55支撑")),
    "MA60支撑": ("ma", MAChecker(vol_mode="today", periods=[60], type_name="MA60支撑")),
    "MA120支撑": ("ma", MAChecker(vol_mode="today", periods=[120], type_name="MA120支撑")),
    "MA144支撑": ("ma", MAChecker(vol_mode="today", periods=[144], type_name="MA144支撑")),
    "MA240支撑": ("ma", MAChecker(vol_mode="today", periods=[240], type_name="MA240支撑")),
    "回调一半": ("half", HalfRetraceChecker()),
    "波段50%": ("band50", Band50Checker()),
    "量价节点": ("volnode", VolPriceNodeChecker()),
    "随机基准": ("random", RandomBaselineChecker()),
}


def detect_buy_points(df_asc: pd.DataFrame, band: BandResult,
                      selected: list[str], code: str = "") -> list[BuyPointSignal]:
    out: list[BuyPointSignal] = []
    for name in selected:
        entry = _NAME_MAP.get(name)
        if entry is None:
            continue
        kind, checker = entry
        # 量价节点/随机基准需要 code（判涨跌停 / 随机种子），其余 checker 签名统一 (df, band)
        bps = (checker.check(df_asc, band, code=code)
               if kind in ("volnode", "random") else checker.check(df_asc, band))
        for bp in bps:
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
            elif kind == "volnode":
                # 量价节点：条件单进场（成本×1.04）；盘中/收盘止损 = 节点成本（绝对价）
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="fixed", close_stop_period=0,
                    intraday_stop_price=bp.intraday_stop,
                    reason=bp.reason,
                ))
            else:
                # 回调一半 / 波段50% / 随机基准：收盘止损 = 跌破买入价；吃全局空间/ATR止损
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="entry", close_stop_period=0,
                    reason=bp.reason,
                ))
    return out
