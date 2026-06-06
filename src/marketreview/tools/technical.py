"""
Shared technical analysis tools — used by Agent 1/2/3.

Covers:
  §4.1 — K-line pattern analysis (bull/bear power)
  §4.2 — Moving average + volume analysis
  §4.3 — Technical indicators (KDJ, RSI, BIAS)
"""

import pandas as pd
import numpy as np
from typing import Any


def rows_to_df(rows: list[dict]) -> pd.DataFrame:
    """Convert cache rows (date DESC) to DataFrame (date ASC for TA)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    for col in ["open", "high", "low", "close", "vol", "amount", "adj_factor"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def calc_ma(df: pd.DataFrame, periods: list[int] = None) -> dict[str, list[float]]:
    """Compute SMA for given periods. Returns {f'MA{p}': [...values...]}"""
    if periods is None:
        periods = [5, 10, 20, 60, 120, 240]
    result = {}
    for p in periods:
        col = f"MA{p}"
        result[col] = df["close"].rolling(p).mean().tolist()
    return result


def ma_direction(ma_values: list[float]) -> str:
    """
    Determine MA direction by comparing today's value to yesterday's.
    Simple 1-day slope: >0.06% up, <0.06% down, else flat.
    Returns '↑' (up), '↓' (down), or '→' (flat).
    """
    valid = [v for v in ma_values if not np.isnan(v)]
    if len(valid) < 2:
        return "→"
    chg_pct = (valid[-1] - valid[-2]) / valid[-2] * 100
    if chg_pct > 0.05:
        return "↑"
    elif chg_pct < -0.05:
        return "↓"
    return "→"


def ma_arrangement(df: pd.DataFrame) -> str:
    """
    Determine MA arrangement by splitting into two groups:
      - 短期: MA5 / MA10 / MA20
      - 中长期: MA60 / MA120 / MA240

    Each group is classified as 多头 / 空头 / 缠绕, then combined.
    """
    mas = calc_ma(df, [5, 10, 20, 60, 120, 240])

    def _latest(ma_key: str) -> float | None:
        for v in reversed(mas[ma_key]):
            if not np.isnan(v):
                return float(v)
        return None

    short = [v for v in (_latest(f"MA{p}") for p in [5, 10, 20]) if v is not None]
    medium_long = [v for v in (_latest(f"MA{p}") for p in [60, 120, 240]) if v is not None]

    def _judge(vals: list[float]) -> str:
        if len(vals) < 2:
            return "数据不足"
        if all(vals[i] > vals[i+1] for i in range(len(vals)-1)):
            return "多头"
        if all(vals[i] < vals[i+1] for i in range(len(vals)-1)):
            return "空头"
        return "缠绕"

    s = _judge(short)
    ml = _judge(medium_long)

    if "数据不足" in (s, ml):
        return "数据不足"

    # Combine
    if s == "多头" and ml == "多头":
        return "多头排列"
    if s == "空头" and ml == "空头":
        return "空头排列"
    if s == "多头" and ml == "缠绕":
        return "短期偏多，中长期缠绕"
    if s == "多头" and ml == "空头":
        return "短期偏多，中长期偏空"
    if s == "缠绕" and ml == "多头":
        return "短期缠绕，中长期偏多"
    if s == "缠绕" and ml == "空头":
        return "短期缠绕，中长期偏空"
    if s == "空头" and ml == "多头":
        return "短期偏空，中长期偏多"
    if s == "空头" and ml == "缠绕":
        return "短期偏空，中长期缠绕"
    # both 缠绕
    return "均线缠绕"


def volume_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """
    Enhanced volume analysis:
      - latest_vol_yi: 今日成交量（亿）
      - ma5_yi, ma10_yi: 5/10日均量（亿）
      - vs_ma5_pct, vs_ma10_pct: 今日量 vs 均量 %
      - trend_5d: 5日成交量趋势（持续上升/偏多上行/震荡/偏空下行/持续下降）
      - cross_state: 均量状态（金叉/死叉/多头/空头）
      - cross_days: 金叉/死叉持续天数
    """
    if df.empty or "amount" not in df.columns:
        return {}

    amount_series = df["amount"].astype(float)
    latest_amount = float(amount_series.iloc[-1])
    latest_amount_yi = round(latest_amount / 1e5, 2)   # 千元 → 亿

    ma5 = amount_series.rolling(5).mean()
    ma10 = amount_series.rolling(10).mean()
    ma20 = amount_series.rolling(20).mean()

    latest_ma5 = float(ma5.iloc[-1])
    latest_ma10 = float(ma10.iloc[-1])
    latest_ma20 = float(ma20.iloc[-1])

    ma5_yi = round(latest_ma5 / 1e5, 2)
    ma10_yi = round(latest_ma10 / 1e5, 2)
    ma20_yi = round(latest_ma20 / 1e5, 2)

    vs_ma5 = round((latest_amount / latest_ma5 - 1) * 100, 1) if not np.isnan(latest_ma5) else 0
    vs_ma10 = round((latest_amount / latest_ma10 - 1) * 100, 1) if not np.isnan(latest_ma10) else 0
    vs_ma20 = round((latest_amount / latest_ma20 - 1) * 100, 1) if not np.isnan(latest_ma20) else 0

    # ---- 5-day amount trend ----
    last5 = amount_series.iloc[-5:].tolist()
    if len(last5) >= 5:
        ups = sum(1 for i in range(1, 5) if last5[i] > last5[i-1])
        if ups == 4:
            trend_5d = "持续上升"
        elif ups == 3:
            trend_5d = "偏多上行"
        elif ups == 1:
            trend_5d = "偏空下行"
        elif ups == 0:
            trend_5d = "持续下降"
        else:
            trend_5d = "量能震荡"
    else:
        trend_5d = "数据不足"

    # ---- 均额交叉检测 (MA5 vs MA10) ----
    cross_state = None
    cross_days = 0

    ma5_vals = ma5.dropna().tolist()
    ma10_vals = ma10.dropna().tolist()
    if len(ma5_vals) >= 2 and len(ma10_vals) >= 2:
        n = min(len(ma5_vals), len(ma10_vals))
        a5 = ma5_vals[-n:]
        a10 = ma10_vals[-n:]

        # Walk backwards to find most recent cross
        for i in range(len(a5) - 1, 0, -1):
            prev_diff = a5[i-1] - a10[i-1]
            curr_diff = a5[i] - a10[i]
            if prev_diff <= 0 and curr_diff > 0:
                cross_state = "金叉"
                cross_days = len(a5) - 1 - i
                break
            elif prev_diff >= 0 and curr_diff < 0:
                cross_state = "死叉"
                cross_days = len(a5) - 1 - i
                break

        if cross_state is None:
            # No recent cross found — just report current alignment
            if a5[-1] > a10[-1]:
                cross_state = "多头"
            else:
                cross_state = "空头"
            cross_days = 0

    return {
        "latest_amount_yi": latest_amount_yi,
        "ma5_yi": ma5_yi,
        "ma10_yi": ma10_yi,
        "ma20_yi": ma20_yi,
        "vs_ma5_pct": vs_ma5,
        "vs_ma10_pct": vs_ma10,
        "vs_ma20_pct": vs_ma20,
        "trend_5d": trend_5d,
        "cross_state": cross_state,
        "cross_days": cross_days,
    }


def calc_kdj(df: pd.DataFrame, n: int = 9) -> dict[str, list[float]]:
    """Compute KDJ indicator. Returns {K, D, J} lists."""
    low_list = df["low"].rolling(n).min()
    high_list = df["high"].rolling(n).max()
    rsv = (df["close"] - low_list) / (high_list - low_list) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {"K": k.tolist(), "D": d.tolist(), "J": j.tolist()}


def calc_rsi(df: pd.DataFrame, period: int = 6) -> list[float]:
    """Compute RSI for given period."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.tolist()


def calc_bias(df: pd.DataFrame, periods: list[int] = None) -> dict[str, list[float]]:
    """Compute BIAS (乖离率) for given periods."""
    if periods is None:
        periods = [6, 12, 24]
    result = {}
    for p in periods:
        ma = df["close"].rolling(p).mean()
        bias = (df["close"] - ma) / ma * 100
        result[f"BIAS{p}"] = bias.tolist()
    return result


def kline_pattern(df: pd.DataFrame) -> dict[str, Any]:
    """
    Analyze latest candle's bull/bear power.
    Returns entity/body ratio, upper/lower wick ratio.
    """
    if df.empty:
        return {}
    row = df.iloc[-1]
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    body = abs(c - o)
    total = h - l
    if total == 0:
        return {"type": "doji", "body_pct": 0, "upper_wick_pct": 0, "lower_wick_pct": 0}
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_pct = round(body / total * 100, 1)
    is_bullish = c > o
    return {
        "type": "阳线" if is_bullish else "阴线",
        "body_pct": body_pct,
        "upper_wick_pct": round(upper_wick / total * 100, 1),
        "lower_wick_pct": round(lower_wick / total * 100, 1),
        "interpretation": _interpret_candle(is_bullish, body_pct, upper_wick/total, lower_wick/total),
    }


def _interpret_candle(bullish: bool, body_pct: float, upper_pct: float, lower_pct: float) -> str:
    """Simple candle interpretation."""
    parts = []
    if body_pct > 60:
        parts.append("强势" if bullish else "弱势")
    elif body_pct < 20:
        parts.append("十字星/多空均衡")
    if upper_pct > 0.5:
        parts.append("上方压力大")
    if lower_pct > 0.5:
        parts.append("下方支撑强")
    return "；".join(parts) if parts else "普通K线"


# ------- MA offset / role helpers (shared by Agent tools & dashboard) -------

def get_offset_info(df: pd.DataFrame, period: int) -> dict[str, Any]:
    """
    Returns dict with keys:
      offset_date, offset_amount_yi, vs_today_pct,
      avg_offset_amount_yi, avg_vs_today_pct, window

    扣抵日 = N trading days before today (date-ascending df).
    扣抵量 = turnover on that single day (in 亿).
    后续均量 = average turnover from 扣抵日 (inclusive) forward window days.
               Window: MA5/10→1, MA20/60/120/240→5.
    pct = (今日量 / xx量 - 1) * 100: 正=今日量更大=安全, 负=今日量不足=危险。
    """
    idx = len(df) - 1 - period
    if idx < 0:
        return {"offset_date": "N/A", "offset_amount_yi": None, "vs_today_pct": None,
                "avg_offset_amount_yi": None, "avg_vs_today_pct": None, "window": 0}

    # Window size for后续均量: MA5/10不取, 其余统一5天
    window = 1 if period <= 10 else 5

    today_amount = float(df.iloc[-1]["amount"]) / 1e5   # 千元 → 亿

    # 单日扣抵量
    offset_amount = float(df.iloc[idx]["amount"]) / 1e5
    vs_today_pct = round((today_amount / offset_amount - 1) * 100, 1)

    # 后续均量: 扣抵日 + 后续 window-1 天
    end_idx = min(idx + window, len(df))
    window_amounts = [float(df.iloc[i]["amount"]) / 1e5 for i in range(idx, end_idx)]
    avg_offset_amount = round(sum(window_amounts) / len(window_amounts), 2)
    avg_vs_today_pct = round((today_amount / avg_offset_amount - 1) * 100, 1)

    return {
        "offset_date": str(df.iloc[idx]["date"])[:10],
        "offset_amount_yi": round(offset_amount, 2),
        "vs_today_pct": vs_today_pct,
        "avg_offset_amount_yi": avg_offset_amount,
        "avg_vs_today_pct": avg_vs_today_pct,
        "window": window,
    }


def get_ma_role(price: float, ma_val: float, direction: str) -> str:
    """Determine MA role: 支撑/压制/拖拽/无, combining direction + price position."""
    if direction == "→":
        return "无"
    if direction == "↑":
        return "支撑" if price > ma_val else "向上拖拽"
    # ↓
    return "压制" if price < ma_val else "向下拖拽"


# ------- Summary builder (called by Agent tools) -------

def build_technical_summary(code: str, name: str, rows: list[dict]) -> dict[str, Any]:
    """
    Build a structured technical summary for one symbol.
    Returns dict ready for Agent consumption and dashboard rendering.
    """
    df = rows_to_df(rows)
    if df.empty:
        return {"code": code, "name": name, "error": "无数据"}

    mas = calc_ma(df)
    latest_close = float(df["close"].iloc[-1])
    latest_ma5 = float([v for v in mas["MA5"] if not np.isnan(v)][-1]) if any(not np.isnan(v) for v in mas["MA5"]) else None

    # Latest indicator values
    kdj = calc_kdj(df)
    rsi6 = calc_rsi(df, 6)
    bias = calc_bias(df)

    return {
        "code": code,
        "name": name,
        "latest_close": round(latest_close, 2),
        "ma_arrangement": ma_arrangement(df),
        "ma_directions": {
            f"MA{p}": ma_direction(mas[f"MA{p}"]) for p in [5, 10, 20, 60, 120, 240]
        },
        "mas": {f"MA{p}": round(float([v for v in mas[f"MA{p}"] if not np.isnan(v)][-1]), 2)
                for p in [5, 10, 20, 60, 120, 240] if any(not np.isnan(v) for v in mas[f"MA{p}"])},
        "volume": volume_analysis(df),
        "kline_pattern": kline_pattern(df),
        "kdj_k": round(float([v for v in kdj["K"] if not np.isnan(v)][-1]), 1),
        "kdj_d": round(float([v for v in kdj["D"] if not np.isnan(v)][-1]), 1),
        "kdj_j": round(float([v for v in kdj["J"] if not np.isnan(v)][-1]), 1),
        "rsi6": round(float([v for v in rsi6 if not np.isnan(v)][-1]), 1),
        "bias6": round(float([v for v in bias["BIAS6"] if not np.isnan(v)][-1]), 2),
    }
