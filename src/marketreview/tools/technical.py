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
        periods = [5, 10, 20, 60]
    result = {}
    for p in periods:
        col = f"MA{p}"
        result[col] = df["close"].rolling(p).mean().tolist()
    return result


def ma_direction(ma_values: list[float]) -> str:
    """
    Determine MA direction from last few values.
    Returns '↑' (up), '↓' (down), or '→' (flat).
    """
    valid = [v for v in ma_values[-5:] if not np.isnan(v)]
    if len(valid) < 3:
        return "→"
    # simple linear regression slope
    x = np.arange(len(valid))
    slope = np.polyfit(x, valid, 1)[0]
    if slope > 0.3:
        return "↑"
    elif slope < -0.3:
        return "↓"
    return "→"


def ma_arrangement(df: pd.DataFrame) -> str:
    """
    Determine MA arrangement: 多头排列 / 空头排列 / 缠绕.
    Uses latest MA5/10/20/60 values.
    """
    mas = calc_ma(df, [5, 10, 20, 60])
    latest = {}
    for k, v in mas.items():
        for val in reversed(v):
            if not np.isnan(val):
                latest[k] = val
                break
    if len(latest) < 3:
        return "数据不足"

    vals = [latest.get(f"MA{p}") for p in [5, 10, 20, 60] if latest.get(f"MA{p}") is not None]
    if all(vals[i] > vals[i+1] for i in range(len(vals)-1)):
        return "多头排列"
    if all(vals[i] < vals[i+1] for i in range(len(vals)-1)):
        return "空头排列"
    return "均线缠绕"


def volume_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """Analyze volume: latest vol vs 5/20-day average."""
    if df.empty or "vol" not in df.columns:
        return {}
    latest_vol = df["vol"].iloc[-1]
    ma5_vol = df["vol"].rolling(5).mean().iloc[-1]
    ma20_vol = df["vol"].rolling(20).mean().iloc[-1]
    vs_ma5 = (latest_vol / ma5_vol - 1) * 100 if not np.isnan(ma5_vol) else 0
    vs_ma20 = (latest_vol / ma20_vol - 1) * 100 if not np.isnan(ma20_vol) else 0
    return {
        "latest_vol": round(float(latest_vol), 0),
        "ma5_vol": round(float(ma5_vol), 0),
        "vs_ma5_pct": round(float(vs_ma5), 1),
        "vs_ma20_pct": round(float(vs_ma20), 1),
        "label": "放量" if vs_ma5 > 5 else ("缩量" if vs_ma5 < -5 else "量平"),
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
            f"MA{p}": ma_direction(mas[f"MA{p}"]) for p in [5, 10, 20, 60]
        },
        "mas": {f"MA{p}": round(float([v for v in mas[f"MA{p}"] if not np.isnan(v)][-1]), 2)
                for p in [5, 10, 20, 60] if any(not np.isnan(v) for v in mas[f"MA{p}"])},
        "volume": volume_analysis(df),
        "kline_pattern": kline_pattern(df),
        "kdj_k": round(float([v for v in kdj["K"] if not np.isnan(v)][-1]), 1),
        "kdj_d": round(float([v for v in kdj["D"] if not np.isnan(v)][-1]), 1),
        "kdj_j": round(float([v for v in kdj["J"] if not np.isnan(v)][-1]), 1),
        "rsi6": round(float([v for v in rsi6 if not np.isnan(v)][-1]), 1),
        "bias6": round(float([v for v in bias["BIAS6"] if not np.isnan(v)][-1]), 2),
    }
