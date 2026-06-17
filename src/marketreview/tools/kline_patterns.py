"""
K-line pattern recognition — two-pass architecture (§5).

Pass 1: Classify each individual candle (entity strength + shape).
Pass 2: Match multi-candle patterns against the classified sequence.

All pattern detectors return None (no match) or a result dict.
The main entry point `detect_patterns()` runs all detectors and
returns a list of matched patterns for the latest trading day(s).

Object types:
  - "index"       — 指数,  use fixed % thresholds
  - "sector"      — 行业指数, same thresholds as index for now
  - "stock"       — 个股,  use ATR-normalised thresholds (WIP)
"""

from __future__ import annotations
from typing import Any
import pandas as pd
import numpy as np
from marketreview.log_util import get_logger

log = get_logger(__name__)


# ──────────────────────────────────────────────────────
#  Pass 1 — Single Candle Classification
# ──────────────────────────────────────────────────────

# Entity strength thresholds for indices / sectors
INDEX_LONG_PCT = 1.5   # |chg%| > 1.5  → 长阳/长阴
INDEX_MID_PCT = 0.8    # 0.8 ≤ |chg%| ≤ 1.5 → 中阳/中阴
# |chg%| < 0.8 → 小阳/小阴

# 长影线: 影线长度 ≥ 实体 × 2
LONG_SHADOW_BODY_RATIO = 2.0


def _entity_strength(
    o: float, c: float, prev_c: float,
    obj_type: str = "index", atr: float | None = None,
) -> dict[str, Any]:
    """Classify entity strength of a single candle.

    Returns dict with keys: is_bullish, entity_label, chg_pct
    """
    body = c - o
    is_bullish = body > 0
    chg_pct = round((c / prev_c - 1) * 100, 2)

    if obj_type in ("index", "sector"):
        abs_chg = abs(chg_pct)
        if abs_chg > INDEX_LONG_PCT:
            label = "长阳" if is_bullish else "长阴"
        elif abs_chg >= INDEX_MID_PCT:
            label = "中阳" if is_bullish else "中阴"
        else:
            label = "小阳" if is_bullish else "小阴"
    else:
        # stock — ATR-normalised (placeholder until ATR is wired)
        if atr and atr > 0:
            entity_atr = abs(body) / atr
            if entity_atr >= 0.5:
                label = "长阳" if is_bullish else "长阴"
            elif entity_atr >= 0.25:
                label = "中阳" if is_bullish else "中阴"
            else:
                label = "小阳" if is_bullish else "小阴"
        else:
            label = "阳线" if is_bullish else "阴线"

    return {"is_bullish": is_bullish, "entity_label": label, "chg_pct": chg_pct}


def _candle_shape(o: float, h: float, l: float, c: float) -> dict[str, Any]:
    """Analyze the shape of a single candle — body, shadows, etc.

    Returns dict with keys:
      body, total_range, upper_wick, lower_wick,
      body_pct, upper_pct, lower_pct,
      has_long_upper, has_long_lower, is_doji
    """
    body = abs(c - o)
    total = h - l
    if total == 0:
        return {
            "body": 0.0, "total_range": 0.0,
            "upper_wick": 0.0, "lower_wick": 0.0,
            "body_pct": 0.0, "upper_pct": 0.0, "lower_pct": 0.0,
            "has_long_upper": False, "has_long_lower": False,
            "is_doji": True,
        }

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_pct = round(body / total * 100, 1)
    upper_pct = round(upper_wick / total * 100, 1)
    lower_pct = round(lower_wick / total * 100, 1)

    # 长影线判定：影线 ≥ 实体 × 2
    has_long_upper = upper_wick >= body * LONG_SHADOW_BODY_RATIO
    has_long_lower = lower_wick >= body * LONG_SHADOW_BODY_RATIO

    return {
        "body": round(body, 4),
        "total_range": round(total, 4),
        "upper_wick": round(upper_wick, 4),
        "lower_wick": round(lower_wick, 4),
        "body_pct": body_pct,
        "upper_pct": upper_pct,
        "lower_pct": lower_pct,
        "has_long_upper": has_long_upper,
        "has_long_lower": has_long_lower,
        "is_doji": body_pct < 5.0,
    }


def classify_candle(
    row,
    prev_close: float | None = None,
    obj_type: str = "index",
    atr: float | None = None,
) -> dict[str, Any]:
    """Single-candle classification — combines entity strength + shape.

    Args:
        row: A dict/Series with keys open, high, low, close.
        prev_close: Previous day's close (for chg% calculation).
        obj_type: "index", "sector", or "stock".
        atr: ATR(14) value (only used when obj_type="stock").

    Returns a dict with all classification fields.
    """
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    pc = prev_close if prev_close is not None else c

    entity = _entity_strength(o, c, pc, obj_type, atr)
    shape = _candle_shape(o, h, l, c)

    return {**entity, **shape}


# ──────────────────────────────────────────────────────
#  Pass 2 — Pattern Detectors
# ──────────────────────────────────────────────────────
#
#  Each detector:
#    - Takes a DataFrame (date ASC, rows = individual candles) + obj_type
#    - Returns None if no match, or a dict:
#        { "name": str, "direction": str, "note": str }
#    - Assumes df has at least 2 rows; otherwise returns None.
# ──────────────────────────────────────────────────────


def detect_bullish_engulfing_shadow(
    df: pd.DataFrame, obj_type: str = "index",
) -> dict[str, Any] | None:
    """检测多头吞影线（仙人指路）。

    条件:
      1. 昨：有长上影线
      2. 今：收阳线
      3. 今：收盘价 ≥ 昨最高价（阳线实体覆盖了昨长上影线区域）
      4. 短期趋势非多头（均线多头时在高档，偏中性，不触发）
    """
    if len(df) < 2:
        return None

    # ④ 均线多头时（高档）偏中性，不触发
    if _short_term_trend(df) == "多头":
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    prev_shape = _candle_shape(
        float(prev["open"]), float(prev["high"]),
        float(prev["low"]), float(prev["close"]),
    )

    # ① 昨上影线显著（上影线 ≥ 实体）—— 确保上影线是昨K线的显著特征
    #    不同于纺锤线的 has_long_upper（上影 ≥ 实体×2），吞影线只需要上影≥实体即可
    if prev_shape["upper_wick"] < prev_shape["body"]:
        return None

    curr_o = float(curr["open"])
    curr_c = float(curr["close"])

    # ② 今收阳线
    if curr_c <= curr_o:
        return None

    # ③ 今开 ≤ 昨高 — 排除大幅跳空高开（今开比昨高还高）
    prev_h = float(prev["high"])
    if curr_o > prev_h:
        return None

    # ④ 今收盘 ≥ 昨最高（阳线实体覆盖长上影线区域）
    if curr_c < prev_h:
        return None

    return {
        "name": "多头吞影线",
        "direction": "短线偏多",
        "note": (
            "也称仙人指路，如果明日K线下跌，则形态意义打折扣；"
            "下跌或回调中出现，偏多解读；"
            "后续放量增强有效性，缩量偏多力度存疑"
        ),
    }


def detect_bearish_engulfing_shadow(
    df: pd.DataFrame, obj_type: str = "index",
) -> dict[str, Any] | None:
    """检测空头吞影线。

    条件:
      1. 昨：有下影线
      2. 今：收阴线
      3. 今开 ≥ 昨低（排除大幅跳空低开）
      4. 今收 ≤ 昨最低价（阴线实体覆盖了昨下影线区域）
    """
    if len(df) < 2:
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    prev_shape = _candle_shape(
        float(prev["open"]), float(prev["high"]),
        float(prev["low"]), float(prev["close"]),
    )

    # ① 昨有下影线
    if prev_shape["lower_wick"] <= 0:
        return None

    curr_o = float(curr["open"])
    curr_c = float(curr["close"])

    # ② 今收阴线
    if curr_c >= curr_o:
        return None

    # ③ 今开 ≥ 昨低 — 排除大幅跳空低开（今开比昨低还低）
    prev_l = float(prev["low"])
    if curr_o < prev_l:
        return None

    # ④ 今收 ≤ 昨最低价（阴线实体覆盖了昨下影线区域）
    if curr_c > prev_l:
        return None

    return {
        "name": "空头吞影线",
        "direction": "短线偏空",
        "note": (
            "下影线本是洗盘/落底信号（如单针探底），被阴线吃掉则可能是诱多骗线"
        ),
    }


def _neck_common(
    df: pd.DataFrame,
) -> tuple[float, float, float, float] | None:
    """Return (prev_o, prev_c, curr_o, curr_c) if basic neck conditions met.

    共通条件:
      1. 今：收阳线、开低（今开 < 昨实体下沿）
    """
    if len(df) < 2:
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    prev_o = float(prev["open"])
    prev_c = float(prev["close"])

    curr_o = float(curr["open"])
    curr_c = float(curr["close"])

    entity_low = min(prev_o, prev_c)

    # 今收阳线 且 开低（今开 < 昨实体下沿）
    if curr_c <= curr_o:
        return None
    if curr_o >= entity_low:
        return None

    return (prev_o, prev_c, curr_o, curr_c)


def detect_neck_above(
    df: pd.DataFrame, obj_type: str = "index",
) -> dict[str, Any] | None:
    """检测颈上线（迫切线）。

    条件:
      1. 今：收阳线、开低（今开 < 昨收）
      2. 今收盘 ≤ 昨实体下沿 → 未进入昨K线实体范围
    """
    common = _neck_common(df)
    if common is None:
        return None

    prev_o, prev_c, _curr_o, curr_c = common

    # 昨实体下沿 = min(昨开, 昨收)
    entity_low = min(prev_o, prev_c)

    # 今收盘 ≤ 实体下沿 → 没进入实体范围
    if curr_c > entity_low:
        return None

    return {
        "name": "颈上线",
        "direction": "偏空",
        "note": (
            "也称迫切线，<b>提防反弹再下杀</b>；"
            "后续持续补量上涨，大于各级均量扣抵量，才可化解"
        ),
    }


def detect_neck_inside(
    df: pd.DataFrame, obj_type: str = "index",
) -> dict[str, Any] | None:
    """检测颈内线（入首线）。

    条件:
      1. 今：收阳线、开低（今开 < 昨收）
      2. 昨实体下沿 < 今收盘 ≤ (昨开 + 昨收) / 2 → 进入实体但未越过一半
    """
    common = _neck_common(df)
    if common is None:
        return None

    prev_o, prev_c, _curr_o, curr_c = common

    # 昨实体下沿
    entity_low = min(prev_o, prev_c)

    # 进入昨实体但未越过实体一半
    if curr_c <= entity_low:
        return None  # 没进入 → 交给 detect_neck_above
    entity_mid = (prev_o + prev_c) / 2
    if curr_c > entity_mid:
        return None  # 越过一半 → 也不是颈内线

    return {
        "name": "颈内线",
        "direction": "偏空",
        "note": (
            "也称入首线，<b>提防反弹再下杀</b>；"
            "后续持续补量上涨，大于各级均量扣抵量，才可化解"
        ),
    }


# ──────────────────────────────────────────────────────
#  Main Entry Point
# ──────────────────────────────────────────────────────



# Helpers shared across detectors


def _short_term_trend(df: pd.DataFrame) -> str:
    """Determine short-term trend from MA5/MA10/MA20.

    Returns "多头" (MA5 > MA10 > MA20), "空头" (MA5 < MA10 < MA20),
    or "盘整" (everything else).
    """
    from .technical import calc_ma

    mas = calc_ma(df, [5, 10, 20])
    vals = {}
    for period in [5, 10, 20]:
        key = f"MA{period}"
        arr = mas[key]
        # Get latest non-NaN
        vals[key] = next(
            (float(v) for v in reversed(arr) if not np.isnan(v)), None
        )

    m5, m10, m20 = vals.get("MA5"), vals.get("MA10"), vals.get("MA20")
    if m5 is None or m10 is None or m20 is None:
        return "盘整"
    if m5 > m10 > m20:
        return "多头"
    if m5 < m10 < m20:
        return "空头"
    return "盘整"


# ──────────────────────────────────────────────────────
#  More pattern detectors
# ──────────────────────────────────────────────────────


def detect_spinning_top(
    df: pd.DataFrame, obj_type: str = "index",
) -> dict[str, Any] | None:
    """检测纺锤线（上影线型）。

    条件:
      1. 今：长上影线（上影线 ≥ 实体 × 2）
      2. 今：实体很小（body_pct < 30%）
      3. + 短期多头 + 今日收涨 → 高档纺锤线 → 偏空
      4. + 短期空头 + 今日收跌 → 低档纺锤线 → 偏多
      盘整或日涨跌与趋势方向不符时不触发。
    """
    if len(df) < 20:
        return None

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(curr["close"])
    prev_close = float(prev["close"])
    shape = _candle_shape(
        float(curr["open"]), float(curr["high"]),
        float(curr["low"]), float(curr["close"]),
    )

    # ① 长上影线
    if not shape["has_long_upper"]:
        return None

    # ② 实体很小
    if shape["body_pct"] >= 30:
        return None

    # ③ 确定高档/低档：趋势方向 + 日涨跌须一致
    trend = _short_term_trend(df)
    if trend == "多头" and close > prev_close:
        return {
            "name": "高档纺锤线",
            "direction": "偏空",
            "note": "在上涨之后出现，已经出现空方的进攻苗头和多方不是那么再有强烈持续上攻的念头",
        }
    elif trend == "空头" and close < prev_close:
        return {
            "name": "低档纺锤线",
            "direction": "偏多",
            "note": "在下跌之后才出现，多方在这K线当中有试探和抵抗的表现",
        }
    else:
        return None


def detect_patterns(
    df: pd.DataFrame, obj_type: str = "index",
) -> list[dict[str, Any]]:
    """Run all registered pattern detectors against the latest candles.

    Args:
        df: K-line DataFrame, date ASC (as produced by rows_to_df()).
        obj_type: "index", "sector", or "stock".

    Returns:
        List of matched patterns (may be empty).  Each element:
          { name, direction, note }
    """
    if df.empty or len(df) < 2:
        return []

    results = []
    for detector in _PATTERN_DETECTORS:
        try:
            match = detector(df, obj_type)
            if match is not None:
                results.append(match)
        except Exception:
            # Skip detectors that fail on insufficient data / bad inputs
            continue

    # Log detected patterns with trigger candle dates
    if results:
        last_date = str(df["date"].iloc[-1])[:10] if "date" in df.columns else "?"
        prev_date = str(df["date"].iloc[-2])[:10] if len(df) >= 2 and "date" in df.columns else "?"
        names = [p["name"] for p in results]
        log.info("detect_patterns: type=%s prev=%s curr=%s → %s",
                 obj_type, prev_date, last_date, names)
    return results


# Registry of all pattern detectors (append new ones here).
_PATTERN_DETECTORS = [
    detect_bullish_engulfing_shadow,
    detect_bearish_engulfing_shadow,
    detect_neck_above,
    detect_neck_inside,
    detect_spinning_top,
]
