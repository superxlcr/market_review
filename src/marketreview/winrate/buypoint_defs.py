"""把 buy_points.py 的 checker 包成可回测的 BuyPointSignal（触发价 + 收盘止损规则）。"""
from __future__ import annotations
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import (
    HalfRetraceChecker, Band50Checker, MAChecker, VolPriceNodeChecker,
    ShrinkToExpandChecker, Channel20BreakoutChecker, RandomBaselineChecker,
    TurtleSystem1Checker, TurtleSystem2Checker,
)
from marketreview.tools.technical import calc_ma
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
    "回调一半严格": ("half", HalfRetraceChecker(strict=True)),
    "回调一半严格5%": ("half", HalfRetraceChecker(strict=True, close_below_max_pct=5.0)),
    "波段50%": ("band50", Band50Checker()),
    "量价节点": ("volnode", VolPriceNodeChecker()),
    "量价节点上浮2%": ("volnode", VolPriceNodeChecker(entry_premium=1.02)),
    "量价节点严格": ("volnode", VolPriceNodeChecker(entry_premium=1.04, strict=True)),
    "量价节点严格上浮2%": ("volnode", VolPriceNodeChecker(entry_premium=1.02, strict=True)),
    "缩转放": ("shrink_expand", ShrinkToExpandChecker()),
    "缩转放收盘止损": ("shrink_expand_close", ShrinkToExpandChecker()),
    "20日突破": ("channel20", Channel20BreakoutChecker()),
    "海龟S1": ("turtle_s1", TurtleSystem1Checker()),
    "海龟S2": ("turtle_s2", TurtleSystem2Checker()),
    "随机基准": ("random", RandomBaselineChecker()),
}

# 所有 MA checker 用到的周期并集（预算一次共享，避免每个 checker 各算一遍）
_ALL_MA_PERIODS = sorted({p for _, (kind, chk) in _NAME_MAP.items()
                          if kind == "ma" for p in chk.periods})


def detect_buy_points(df_asc: pd.DataFrame, band: BandResult,
                      selected: list[str], code: str = "") -> list[BuyPointSignal]:
    out: list[BuyPointSignal] = []
    # 预算 MA 一次（全周期并集），所有 MA checker 共享，避免重复 calc_ma
    has_ma = any(_NAME_MAP.get(n, ("",))[0] == "ma" for n in selected)
    pre_mas = calc_ma(df_asc, _ALL_MA_PERIODS) if (has_ma and not df_asc.empty) else None
    for name in selected:
        entry = _NAME_MAP.get(name)
        if entry is None:
            continue
        kind, checker = entry
        # 量价节点/随机基准/缩转放需要 code（判涨跌停 / 随机种子），其余 checker 签名统一 (df, band)
        if kind == "volnode" or kind == "random" or kind in ("shrink_expand", "shrink_expand_close"):
            bps = checker.check(df_asc, band, code=code)
        elif kind == "ma":
            bps = checker.check(df_asc, band, pre_mas=pre_mas)
        else:
            bps = checker.check(df_asc, band)
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
            elif kind in ("shrink_expand", "shrink_expand_close"):
                # 缩转放：信号当天收盘价成交；止损 = 信号日 low - 0.01（逻辑止损）
                # 量能值从 checker 实例属性读取（check 后暂存）
                vr = getattr(checker, "_last_vol_ratios", {})
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="fixed", close_stop_period=0,
                    intraday_stop_price=bp.intraday_stop,
                    reason=bp.reason,
                    entry_mode="close",
                    strategy=kind,
                    vol_ratio_20=vr.get("vol_ratio_20", 0.0),
                    vol_ratio_5=vr.get("vol_ratio_5", 0.0),
                    vol_shrink=vr.get("vol_shrink", 0.0),
                ))
            elif kind == "channel20":
                # 20日突破：收盘 > 20日高点进场，收盘 < 20日低点离场，无止损止盈
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="entry", close_stop_period=0,
                    reason=bp.reason,
                    entry_mode="close",
                    strategy="channel20",
                ))
            elif kind in ("turtle_s1", "turtle_s2"):
                # 海龟S1：突破20日高进场，跌破10日低离场
                # 海龟S2：突破55日高进场，跌破20日低离场
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="entry", close_stop_period=0,
                    reason=bp.reason,
                    entry_mode="close",
                    strategy=kind,  # "turtle_s1" or "turtle_s2"
                ))
            else:
                # 回调一半 / 波段50% / 随机基准：收盘止损 = 跌破买入价；吃全局空间/ATR止损
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="entry", close_stop_period=0,
                    reason=bp.reason,
                ))
    return out
