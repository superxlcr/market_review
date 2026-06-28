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

from marketreview.log_util import get_logger

log = get_logger(__name__)


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
        log.warning("volume_analysis: empty df or missing 'amount' column")
        return {}

    amount_series = df["amount"].astype(float)
    latest_amount = float(amount_series.iloc[-1])
    latest_amount_yi = round(latest_amount / 1e5, 2)   # 千元 → 亿

    log.debug("volume_analysis: rows=%d latest_amount_yi=%.2f", len(amount_series), latest_amount_yi)

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

    # ---- Deduction volume (扣抵量) ----
    # The day that drops off the MA-N window tomorrow: N trading days before
    # today, consistent with get_offset_info() → idx = len(df) - 1 - period.
    _n = len(amount_series)
    _idx5 = _n - 1 - 5
    _idx10 = _n - 1 - 10

    deduct_5 = float(amount_series.iloc[_idx5]) if _idx5 >= 0 else None
    deduct_10 = float(amount_series.iloc[_idx10]) if _idx10 >= 0 else None

    ma5_deduct_yi = round(deduct_5 / 1e5, 2) if deduct_5 else None
    ma10_deduct_yi = round(deduct_10 / 1e5, 2) if deduct_10 else None

    vs_ma5_deduct = round((latest_amount / deduct_5 - 1) * 100, 1) if deduct_5 and deduct_5 > 0 else None
    vs_ma10_deduct = round((latest_amount / deduct_10 - 1) * 100, 1) if deduct_10 and deduct_10 > 0 else None

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

    result = {
        "latest_amount_yi": latest_amount_yi,
        "ma5_yi": ma5_yi,
        "ma10_yi": ma10_yi,
        "ma20_yi": ma20_yi,
        "vs_ma5_pct": vs_ma5,
        "vs_ma10_pct": vs_ma10,
        "vs_ma20_pct": vs_ma20,
        "ma5_deduct_yi": ma5_deduct_yi,
        "ma10_deduct_yi": ma10_deduct_yi,
        "vs_ma5_deduct_pct": vs_ma5_deduct,
        "vs_ma10_deduct_pct": vs_ma10_deduct,
        "trend_5d": trend_5d,
        "cross_state": cross_state,
        "cross_days": cross_days,
    }
    log.debug("volume_analysis result keys: %s", sorted(result.keys()))
    return result


def calc_kdj(df: pd.DataFrame, n: int = 9) -> dict[str, list[float]]:
    """Compute KDJ indicator. Returns {K, D, J} lists."""
    low_list = df["low"].rolling(n).min()
    high_list = df["high"].rolling(n).max()
    rsv = (df["close"] - low_list) / (high_list - low_list) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {"K": k.tolist(), "D": d.tolist(), "J": j.tolist()}


def calc_rsi(df: pd.DataFrame, periods: tuple[int, ...] = (9, 9, 9)) -> dict[str, list[float]]:
    """
    TDX-style RSI.  Formula (通达信):

        LC := REF(CLOSE, 1)
        UP := MAX(CLOSE - LC, 0)
        ABS := ABS(CLOSE - LC)
        RSI := SMA(UP, N, 1) / SMA(ABS, N, 1) * 100

    where SMA(X, N, 1) = (X + (N-1) * prev) / N (new-value weight = 1/N).

    Default (9,9,9) → three identical lines with period 9.
    Returns {f"RSI{n}": [...values...]}.
    """
    close = df["close"]
    lc = close.shift(1)
    diff = close - lc
    up = diff.clip(lower=0)       # MAX(CLOSE-LC, 0)
    abs_diff = diff.abs()          # ABS(CLOSE-LC)

    result = {}
    for p_idx, n in enumerate(periods, 1):
        sma_up = np.full(len(df), np.nan)
        sma_abs = np.full(len(df), np.nan)
        rsi = np.full(len(df), np.nan)

        # seed: simple average of first n valid bars
        seed_start = 1  # first diff is at index 1
        seed_end = min(seed_start + n, len(df))
        if seed_end > seed_start:
            sma_up[seed_end - 1] = up.iloc[seed_start:seed_end].mean()
            sma_abs[seed_end - 1] = abs_diff.iloc[seed_start:seed_end].mean()
            if sma_abs[seed_end - 1] != 0:
                rsi[seed_end - 1] = sma_up[seed_end - 1] / sma_abs[seed_end - 1] * 100
            else:
                rsi[seed_end - 1] = 50.0

        for j in range(seed_end, len(df)):
            sma_up[j] = (up.iloc[j] + (n - 1) * sma_up[j - 1]) / n
            sma_abs[j] = (abs_diff.iloc[j] + (n - 1) * sma_abs[j - 1]) / n
            if sma_abs[j] != 0:
                rsi[j] = sma_up[j] / sma_abs[j] * 100
            else:
                rsi[j] = rsi[j - 1]

        result[f"RSI{p_idx}"] = rsi.tolist()

    return result


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


# BIAS thresholds: (period, threshold, short_label_prefix)
_BIAS_RULES = {
    10: (10, "短线超买", "短线超卖"),
    20: (7,  "超买",    "超卖"),
}


def bias_status(bias_dict: dict, periods: list[int] = None) -> dict:
    """Return BIAS display info with 超买/超卖 labels and colors.

    Args:
        bias_dict: output of calc_bias(), e.g. {"BIAS10": [...], "BIAS20": [...]}
        periods: list of period ints to extract (default [10, 20])

    Returns:
        {f"BIAS{p}": {"value": float|None, "status": str|None, "color": str}}
        Color convention: 超买→绿(#2e7d32)=看空, 超卖→红(#c62828)=看多
    """
    if periods is None:
        periods = [10, 20]

    result = {}
    for p in periods:
        key = f"BIAS{p}"
        vals = bias_dict.get(key, [])
        val = None
        for v in reversed(vals):
            if not np.isnan(v):
                val = round(float(v), 2)
                break

        rule = _BIAS_RULES.get(p)
        if val is not None and rule is not None:
            threshold, over_label, under_label = rule
            if val > threshold:
                status, color = over_label, "#2e7d32"
            elif val < -threshold:
                status, color = under_label, "#c62828"
            else:
                status, color = None, None
        else:
            status, color = None, None

        result[key] = {"value": val, "status": status, "color": color}

    return result


def calc_atr(df: pd.DataFrame, period: int = 14) -> list[float]:
    """Compute ATR (Average True Range) using Wilder's smoothing.

    Used by stock-mode K-line pattern detection for entity strength
    and shadow significance normalisation.

    Args:
        df: OHLCV DataFrame (date ASC), must have open/high/low/close.
        period: ATR lookback (default 14).

    Returns:
        List of ATR values (same length as df), NaN for first period-1 rows.
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    atr = np.full(n, np.nan)
    if n > period:
        # Seed: simple average of the first <period> TR values
        atr[period] = float(np.mean(tr[1:period + 1]))
        # Wilder's smoothing: ATR_t = (ATR_{t-1} * (p-1) + TR_t) / p
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr.tolist()


# ═══════════════════════════════════════════════════════════════════
# TODO — 新版技术指标（待逐个实现，取代上面的旧版 KDJ/RSI/BIAS）
# ═══════════════════════════════════════════════════════════════════

def calc_kd(df: pd.DataFrame, n: int = 9) -> dict[str, list[float]]:
    """
    TDX-style KD indicator (K/D only, no J).

    Uses a high-based RSV correction for K_final — better at capturing
    breakout strength in overbought territory.  Used by the technical
    indicator display (市场全景 K-line overlay).

    Formula:
      收盘RSV = (C - LLV(L,9)) / (HHV(H,9) - LLV(L,9)) * 100
      K_close = SMA(收盘RSV, 3, 1)
      D_close = SMA(K_close, 3, 1)
      最高RSV = (H - LLV(L,9)) / (HHV(H,9) - LLV(L,9)) * 100
      K_final = (RSV_high + 2 * K_close[-1]) / 3        (blended)
      D_final = (K_final + 2 * D_close[-1]) / 3

    Returns {"K": [...], "D": [...]}.
    """
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rng = high_n - low_n

    rsv_close = (df["close"] - low_n) / rng.replace(0, np.nan) * 100
    rsv_high = (df["high"] - low_n) / rng.replace(0, np.nan) * 100

    k_close = np.full(len(df), np.nan)
    d_close = np.full(len(df), np.nan)
    k_final = np.full(len(df), np.nan)
    d_final = np.full(len(df), np.nan)

    start = n - 1
    if start < 0 or start >= len(df):
        return {"K": [np.nan] * len(df), "D": [np.nan] * len(df)}

    k_close[start] = rsv_close.iloc[start]
    d_close[start] = k_close[start]
    k_final[start] = rsv_high.iloc[start]
    d_final[start] = k_final[start]

    for i in range(start + 1, len(df)):
        # SMA(X, 3, 1): (X + 2*prev) / 3
        if not np.isnan(rsv_close.iloc[i]):
            k_close[i] = (rsv_close.iloc[i] + 2 * k_close[i - 1]) / 3
        else:
            k_close[i] = k_close[i - 1]
        d_close[i] = (k_close[i] + 2 * d_close[i - 1]) / 3

        if not np.isnan(rsv_high.iloc[i]):
            k_final[i] = (rsv_high.iloc[i] + 2 * k_close[i - 1]) / 3
        else:
            k_final[i] = k_final[i - 1]
        d_final[i] = (k_final[i] + 2 * d_close[i - 1]) / 3

    return {"K": k_final.tolist(), "D": d_final.tolist()}


def calc_kd_standard(df: pd.DataFrame, n: int = 9) -> dict[str, list[float]]:
    """
    TDX-standard KD indicator — exact K(9,3,3) for formula screening.

    This is the correct formula for matching 通达信 condition-screening
    output.  Do NOT use calc_kd() for screening — it has a high-based
    RSV correction that produces different K values from 通达信.

    Formula:
      RSV = (CLOSE - LLV(LOW,9)) / (HHV(HIGH,9) - LLV(LOW,9)) * 100
      K   = SMA(RSV, 3, 1)    # (RSV + 2*K_prev) / 3
      D   = SMA(K,   3, 1)    # (K   + 2*D_prev) / 3

    Returns {"K": [...], "D": [...]}.
    """
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rng = high_n - low_n
    rsv = (df["close"] - low_n) / rng.replace(0, np.nan) * 100

    k_arr = np.full(len(df), np.nan)
    d_arr = np.full(len(df), np.nan)

    start = n - 1
    if start < 0 or start >= len(df):
        return {"K": [np.nan] * len(df), "D": [np.nan] * len(df)}

    k_arr[start] = rsv.iloc[start]
    d_arr[start] = k_arr[start]

    for i in range(start + 1, len(df)):
        if not np.isnan(rsv.iloc[i]):
            k_arr[i] = (rsv.iloc[i] + 2 * k_arr[i - 1]) / 3
        else:
            k_arr[i] = k_arr[i - 1]
        d_arr[i] = (k_arr[i] + 2 * d_arr[i - 1]) / 3

    return {"K": k_arr.tolist(), "D": d_arr.tolist()}

# TODO 2: calc_rsi(df, period=6) → list[float]
#   - 基于收盘价（确认：现有实现已用 close）
#   - 比 KD 更敏感，用于超买超卖 + 背离
#   - 用法：
#       RSI > 70 超买, RSI < 30 超卖
#       价格新高 RSI 未新高 → 顶背离
#       价格新低 RSI 未新低 → 底背离

def calc_wr(df: pd.DataFrame, period: int = 10) -> list[float]:
    """
    Williams %R (威廉指数).

    Formula (通达信):
        WR = (HHV(HIGH, N) - CLOSE) / (HHV(HIGH, N) - LLV(LOW, N)) * 100

    Value range 0-100. >80 = oversold, <20 = overbought (inverted vs KDJ/RSI).

    Returns a list of floats, same length as df (NaN for first N-1 rows).
    """
    high_n = df["high"].rolling(period).max()
    low_n = df["low"].rolling(period).min()
    rng = high_n - low_n
    wr = (high_n - df["close"]) / rng.replace(0, float("nan")) * 100
    return wr.tolist()

# TODO 4: calc_bias_v2(df, periods=[6,12,24]) → dict[str, list[float]]
#   - 乖离率，现有实现基本正确，待确认参数和用法细节
#   - 用途：短期偏离太多会回调，主要看指数和行业板块
#   - 用法：BIAS 负值大 → 超跌反弹；正值大 → 过热回调

# ============================================================
# KD Divergence Detection
# ============================================================

def _ma_trend_at(mas: dict, idx: int) -> str:
    """Check MA5/MA10/MA20 trend at a given DataFrame index.
    Returns '多头', '空头', or '缠绕'."""
    ma5 = mas["MA5"][idx]
    ma10 = mas["MA10"][idx]
    ma20 = mas["MA20"][idx]
    if any(np.isnan(v) for v in [ma5, ma10, ma20]):
        return "缠绕"
    if ma5 > ma10 > ma20:
        return "多头"
    elif ma5 < ma10 < ma20:
        return "空头"
    return "缠绕"


def _determine_divergence_direction(
    mas: dict, latest_idx: int, lookback: int = 20,
    k_val: float | None = None, d_val: float | None = None,
    rsi_val: float | None = None,
    at_new_high: bool = False,
    at_new_low: bool = False,
) -> str | None:
    """
    Determine whether to look for top or bottom divergence.

    Checks today's MA trend first (MA5/MA10/MA20).
    If today is 缠绕, walks back up to `lookback` days to find the last
    clear trend.  Returns 'top', 'bottom', or None.

    Staleness guards — even when a clear trend direction is found, the
    signal is suppressed if the market has already reversed:

    - 空头 → bottom:  at_new_high (price already making new highs),
      KD overbought (K>80, D>80), or RSI overbought (>70)
      → downtrend has already reversed; signal is stale.
    - 多头 → top:     at_new_low (price already making new lows),
      KD oversold (K<20, D<20), or RSI oversold (<30)
      → uptrend has already broken; signal is stale.
    """

    def _is_stale_bottom() -> bool:
        """Bearish trend is stale — market has already reversed upward."""
        if at_new_high:
            return True
        if k_val is not None and d_val is not None and k_val > 80 and d_val > 80:
            return True
        if rsi_val is not None and rsi_val > 70:
            return True
        return False

    def _is_stale_top() -> bool:
        """Bullish trend is stale — market has already broken downward."""
        if at_new_low:
            return True
        if k_val is not None and d_val is not None and k_val < 20 and d_val < 20:
            return True
        if rsi_val is not None and rsi_val < 30:
            return True
        return False

    trend = _ma_trend_at(mas, latest_idx)
    if trend == "多头":
        stale = _is_stale_top()
        log.debug("_det_dir: today=多头 stale_top(new_low=%s KD<%s,%s> RSI=%s)=%s",
                  at_new_low, k_val, d_val, rsi_val, stale)
        return None if stale else "top"
    elif trend == "空头":
        stale = _is_stale_bottom()
        log.debug("_det_dir: today=空头 stale_bottom(new_high=%s KD<%s,%s> RSI=%s)=%s",
                  at_new_high, k_val, d_val, rsi_val, stale)
        return None if stale else "bottom"

    for i in range(latest_idx - 1, max(latest_idx - lookback, -1), -1):
        trend = _ma_trend_at(mas, i)
        if trend == "多头":
            stale = _is_stale_top()
            log.debug("_det_dir: walkback idx=%d 多头 stale_top(new_low=%s KD<%s,%s> RSI=%s)=%s",
                      i, at_new_low, k_val, d_val, rsi_val, stale)
            return None if stale else "top"
        elif trend == "空头":
            stale = _is_stale_bottom()
            log.debug("_det_dir: walkback idx=%d 空头 stale_bottom(new_high=%s KD<%s,%s> RSI=%s)=%s",
                      i, at_new_high, k_val, d_val, rsi_val, stale)
            return None if stale else "bottom"

    log.debug("_det_dir: no clear trend found, returning None")
    return None


def _find_kd_cycle_start(
    k: list[float], d: list[float],
    latest_idx: int, direction: str, max_lookback: int = 240,
) -> int:
    """Find the cycle-start index using KD extreme thresholds.

    - direction='top'  → most recent day with K<20 AND D<20
    - direction='bottom' → most recent day with K>80 AND D>80

    Falls back to latest_idx - max_lookback if no extreme found,
    clamped to >= 0.
    """
    for i in range(latest_idx, max(latest_idx - max_lookback, -1), -1):
        kv, dv = k[i], d[i]
        if np.isnan(kv) or np.isnan(dv):
            continue
        if direction == "top" and kv < 20 and dv < 20:
            return i
        if direction == "bottom" and kv > 80 and dv > 80:
            return i

    return max(latest_idx - max_lookback, 0)


def _detect_top_divergence(
    df: pd.DataFrame, k: list[float], d: list[float],
    latest_idx: int, max_lookback: int = 240,
) -> dict:
    """Look for bearish (top) divergence within the current cycle."""
    cycle_start = _find_kd_cycle_start(k, d, latest_idx, "top", max_lookback)

    # Find highest HIGH in [cycle_start, latest_idx]
    peak_idx = cycle_start
    peak_high = float(df.iloc[cycle_start]["high"])
    for i in range(cycle_start + 1, latest_idx + 1):
        hi = float(df.iloc[i]["high"])
        if not np.isnan(hi) and hi > peak_high:
            peak_high = hi
            peak_idx = i

    peak_k = k[peak_idx]
    peak_d = d[peak_idx]

    # Walk back from peak to find lower price + higher KD
    for i in range(peak_idx - 1, cycle_start - 1, -1):
        hi = float(df.iloc[i]["high"])
        ki, di = k[i], d[i]
        if np.isnan(hi) or np.isnan(ki) or np.isnan(di):
            continue
        if hi >= peak_high:
            continue

        k_div = ki > peak_k
        d_div = di > peak_d

        if k_div or d_div:
            return {
                "type": "顶背离",
                "k_divergence": k_div,
                "d_divergence": d_div,
                "kd_divergence": k_div and d_div,
                "reference_date": str(df.iloc[peak_idx]["date"])[:10],
                "reference_price": round(peak_high, 2),
                "reference_k": round(float(peak_k), 1),
                "reference_d": round(float(peak_d), 1),
                "divergence_date": str(df.iloc[i]["date"])[:10],
                "divergence_price": round(hi, 2),
                "divergence_k": round(float(ki), 1),
                "divergence_d": round(float(di), 1),
                "days": latest_idx - peak_idx,
            }

    return {
        "type": None, "k_divergence": False, "d_divergence": False,
        "kd_divergence": False, "direction": "top",
        "reference_date": str(df.iloc[peak_idx]["date"])[:10],
        "reference_price": round(peak_high, 2),
        "reference_k": round(float(peak_k), 1),
        "reference_d": round(float(peak_d), 1),
        "divergence_date": None, "divergence_price": None,
        "divergence_k": None, "divergence_d": None, "days": latest_idx - peak_idx,
    }


def _detect_bottom_divergence(
    df: pd.DataFrame, k: list[float], d: list[float],
    latest_idx: int, max_lookback: int = 240,
) -> dict:
    """Look for bullish (bottom) divergence within the current cycle."""
    cycle_start = _find_kd_cycle_start(k, d, latest_idx, "bottom", max_lookback)

    # Find lowest LOW in [cycle_start, latest_idx]
    valley_idx = cycle_start
    valley_low = float(df.iloc[cycle_start]["low"])
    for i in range(cycle_start + 1, latest_idx + 1):
        lo = float(df.iloc[i]["low"])
        if not np.isnan(lo) and lo < valley_low:
            valley_low = lo
            valley_idx = i

    valley_k = k[valley_idx]
    valley_d = d[valley_idx]

    # Walk back from valley to find higher price + lower KD
    for i in range(valley_idx - 1, cycle_start - 1, -1):
        lo = float(df.iloc[i]["low"])
        ki, di = k[i], d[i]
        if np.isnan(lo) or np.isnan(ki) or np.isnan(di):
            continue
        if lo <= valley_low:
            continue

        k_div = ki < valley_k
        d_div = di < valley_d

        if k_div or d_div:
            return {
                "type": "底背离",
                "k_divergence": k_div,
                "d_divergence": d_div,
                "kd_divergence": k_div and d_div,
                "reference_date": str(df.iloc[valley_idx]["date"])[:10],
                "reference_price": round(valley_low, 2),
                "reference_k": round(float(valley_k), 1),
                "reference_d": round(float(valley_d), 1),
                "divergence_date": str(df.iloc[i]["date"])[:10],
                "divergence_price": round(lo, 2),
                "divergence_k": round(float(ki), 1),
                "divergence_d": round(float(di), 1),
                "days": latest_idx - valley_idx,
            }

    return {
        "type": None, "k_divergence": False, "d_divergence": False,
        "kd_divergence": False, "direction": "bottom",
        "reference_date": str(df.iloc[valley_idx]["date"])[:10],
        "reference_price": round(valley_low, 2),
        "reference_k": round(float(valley_k), 1),
        "reference_d": round(float(valley_d), 1),
        "divergence_date": None, "divergence_price": None,
        "divergence_k": None, "divergence_d": None, "days": latest_idx - valley_idx,
    }


def detect_kd_divergence(
    df: pd.DataFrame,
    k: list[float],
    d: list[float],
    max_lookback: int = 240,
    trend_lookback: int = 20,
) -> dict[str, Any]:
    """
    Detect KD divergence for the latest trading day.

    Steps:
      1. Determine direction via MA5/MA10/MA20 trend.
         - 多头 → look for top divergence
         - 空头 → look for bottom divergence
         - 缠绕 → walk back up to trend_lookback days.
      2. Find cycle boundary (last K<20&D<20 for top, last K>80&D>80 for bottom).
      3. Within cycle, locate the price extreme (highest high / lowest low).
      4. Walk back from extreme day to find earlier day with less extreme price
         but more extreme KD → divergence.

    Returns dict:
      type: "顶背离" | "底背离" | None
      k_divergence, d_divergence, kd_divergence: bool
      reference_date, reference_price, reference_k, reference_d
      divergence_date, divergence_price, divergence_k, divergence_d
      days: int | None
    """
    n = len(df)
    if n < 20:
        return {
            "type": None, "k_divergence": False, "d_divergence": False,
            "kd_divergence": False, "direction": None,
            "reference_date": None, "reference_price": None,
            "reference_k": None, "reference_d": None,
            "divergence_date": None, "divergence_price": None,
            "divergence_k": None, "divergence_d": None, "days": None,
        }

    mas = calc_ma(df, [5, 10, 20])
    latest_idx = n - 1

    close_series = df["close"]
    at_new_high = bool(close_series.iloc[-1] >= close_series.iloc[-20:].max())
    at_new_low = bool(close_series.iloc[-1] <= close_series.iloc[-20:].min())

    direction = _determine_divergence_direction(
        mas, latest_idx, trend_lookback,
        k[-1] if k else None, d[-1] if d else None, rsi_val=None,
        at_new_high=at_new_high, at_new_low=at_new_low)

    if direction is None:
        return {
            "type": None, "k_divergence": False, "d_divergence": False,
            "kd_divergence": False, "direction": None,
            "reference_date": None, "reference_price": None,
            "reference_k": None, "reference_d": None,
            "divergence_date": None, "divergence_price": None,
            "divergence_k": None, "divergence_d": None, "days": None,
        }

    if direction == "top":
        return _detect_top_divergence(df, k, d, latest_idx, max_lookback)
    else:
        return _detect_bottom_divergence(df, k, d, latest_idx, max_lookback)


# ============================================================
# RSI Divergence Detection  (cycle boundary = 50, price = close)
# ============================================================

def _rsi_detect_top_divergence(
    df: pd.DataFrame, rsi: list[float],
    k: list[float], d: list[float],
    latest_idx: int, max_lookback: int = 240,
) -> dict:
    """RSI bearish (top) divergence — close-based.

    - Interval:   reuses KD's cycle_start (K<20 & D<20).
    - Extreme:    highest CLOSE within [cycle_start, latest_idx].
    - Walk-back:  from peak back, stop at RSI < 50 boundary.
    """
    cycle_start = _find_kd_cycle_start(k, d, latest_idx, "top", max_lookback)

    # Find highest CLOSE in [cycle_start, latest_idx]
    peak_idx = cycle_start
    peak_close = float(df.iloc[cycle_start]["close"])
    for i in range(cycle_start + 1, latest_idx + 1):
        cl = float(df.iloc[i]["close"])
        if not np.isnan(cl) and cl > peak_close:
            peak_close = cl
            peak_idx = i

    peak_rsi = rsi[peak_idx]

    # Walk back from peak, stop at RSI < 50 boundary
    rsi_50_idx = cycle_start
    for i in range(peak_idx - 1, cycle_start - 1, -1):
        rv = rsi[i]
        if not np.isnan(rv) and rv < 50:
            rsi_50_idx = i
            break

    for i in range(peak_idx - 1, rsi_50_idx - 1, -1):
        cl = float(df.iloc[i]["close"])
        ri = rsi[i]
        if np.isnan(cl) or np.isnan(ri):
            continue
        if cl >= peak_close:
            continue

        if ri > peak_rsi:
            return {
                "type": "顶背离",
                "rsi_divergence": True,
                "reference_date": str(df.iloc[peak_idx]["date"])[:10],
                "reference_price": round(peak_close, 2),
                "reference_rsi": round(float(peak_rsi), 1),
                "divergence_date": str(df.iloc[i]["date"])[:10],
                "divergence_price": round(cl, 2),
                "divergence_rsi": round(float(ri), 1),
                "days": latest_idx - peak_idx,
            }

    return {
        "type": None, "rsi_divergence": False, "direction": "top",
        "reference_date": str(df.iloc[peak_idx]["date"])[:10],
        "reference_price": round(peak_close, 2),
        "reference_rsi": round(float(peak_rsi), 1),
        "divergence_date": None, "divergence_price": None,
        "divergence_rsi": None, "days": latest_idx - peak_idx,
    }


def _rsi_detect_bottom_divergence(
    df: pd.DataFrame, rsi: list[float],
    k: list[float], d: list[float],
    latest_idx: int, max_lookback: int = 240,
) -> dict:
    """RSI bullish (bottom) divergence — close-based.

    - Interval:   reuses KD's cycle_start (K>80 & D>80).
    - Extreme:    lowest CLOSE within [cycle_start, latest_idx].
    - Walk-back:  from valley back, stop at RSI > 50 boundary.
    """
    cycle_start = _find_kd_cycle_start(k, d, latest_idx, "bottom", max_lookback)

    # Find lowest CLOSE in [cycle_start, latest_idx]
    valley_idx = cycle_start
    valley_close = float(df.iloc[cycle_start]["close"])
    for i in range(cycle_start + 1, latest_idx + 1):
        cl = float(df.iloc[i]["close"])
        if not np.isnan(cl) and cl < valley_close:
            valley_close = cl
            valley_idx = i

    valley_rsi = rsi[valley_idx]

    # Walk back from valley, stop at RSI > 50 boundary
    rsi_50_idx = cycle_start
    for i in range(valley_idx - 1, cycle_start - 1, -1):
        rv = rsi[i]
        if not np.isnan(rv) and rv > 50:
            rsi_50_idx = i
            break

    for i in range(valley_idx - 1, rsi_50_idx - 1, -1):
        cl = float(df.iloc[i]["close"])
        ri = rsi[i]
        if np.isnan(cl) or np.isnan(ri):
            continue
        if cl <= valley_close:
            continue

        if ri < valley_rsi:
            return {
                "type": "底背离",
                "rsi_divergence": True,
                "reference_date": str(df.iloc[valley_idx]["date"])[:10],
                "reference_price": round(valley_close, 2),
                "reference_rsi": round(float(valley_rsi), 1),
                "divergence_date": str(df.iloc[i]["date"])[:10],
                "divergence_price": round(cl, 2),
                "divergence_rsi": round(float(ri), 1),
                "days": latest_idx - valley_idx,
            }

    return {
        "type": None, "rsi_divergence": False, "direction": "bottom",
        "reference_date": str(df.iloc[valley_idx]["date"])[:10],
        "reference_price": round(valley_close, 2),
        "reference_rsi": round(float(valley_rsi), 1),
        "divergence_date": None, "divergence_price": None,
        "divergence_rsi": None, "days": latest_idx - valley_idx,
    }


def detect_rsi_divergence(
    df: pd.DataFrame,
    rsi: list[float],
    k: list[float],
    d: list[float],
    max_lookback: int = 240,
    trend_lookback: int = 20,
) -> dict[str, Any]:
    """
    Detect RSI divergence for the latest trading day.

    Reuses KD's cycle interval (K<20/K>80) for extreme finding,
    then compares **close** prices with RSI 50 as walk-back boundary.

    Returns same dict structure as detect_kd_divergence(), with
    ``rsi_divergence`` instead of k_divergence/d_divergence/kd_divergence.
    """
    n = len(df)
    if n < 20:
        return {
            "type": None, "rsi_divergence": False, "direction": None,
            "reference_date": None, "reference_price": None,
            "reference_rsi": None,
            "divergence_date": None, "divergence_price": None,
            "divergence_rsi": None, "days": None,
        }

    mas = calc_ma(df, [5, 10, 20])
    latest_idx = n - 1

    close_series = df["close"]
    at_new_high = bool(close_series.iloc[-1] >= close_series.iloc[-20:].max())
    at_new_low = bool(close_series.iloc[-1] <= close_series.iloc[-20:].min())

    direction = _determine_divergence_direction(
        mas, latest_idx, trend_lookback,
        k[-1] if k else None, d[-1] if d else None,
        rsi[-1] if rsi else None,
        at_new_high=at_new_high, at_new_low=at_new_low)

    if direction is None:
        return {
            "type": None, "rsi_divergence": False, "direction": None,
            "reference_date": None, "reference_price": None,
            "reference_rsi": None,
            "divergence_date": None, "divergence_price": None,
            "divergence_rsi": None, "days": None,
        }

    if direction == "top":
        return _rsi_detect_top_divergence(df, rsi, k, d, latest_idx, max_lookback)
    else:
        return _rsi_detect_bottom_divergence(df, rsi, k, d, latest_idx, max_lookback)


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
    }


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
    kd = calc_kd(df)
    rsi = calc_rsi(df)
    bias = calc_bias(df, [10, 20])

    k_latest = round(float([v for v in kd["K"] if not np.isnan(v)][-1]), 1)
    d_latest = round(float([v for v in kd["D"] if not np.isnan(v)][-1]), 1)
    kd_divergence = detect_kd_divergence(df, kd["K"], kd["D"])
    rsi1 = [v for v in rsi["RSI1"] if not np.isnan(v)]
    rsi_latest = round(float(rsi1[-1]), 1) if rsi1 else None
    rsi_divergence = detect_rsi_divergence(df, rsi["RSI1"], kd["K"], kd["D"])

    # BIAS status (matching dashboard display)
    bstatus = bias_status(bias, [10, 20])

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
        "kd_k": k_latest,
        "kd_d": d_latest,
        "kd_divergence": kd_divergence,
        "rsi": rsi_latest,
        "rsi_divergence": rsi_divergence,
        "bias10": round(float([v for v in bias["BIAS10"] if not np.isnan(v)][-1]), 2),
        "bias20": round(float([v for v in bias["BIAS20"] if not np.isnan(v)][-1]), 2),
        "bias10_status": bstatus.get("BIAS10", {}).get("status"),
        "bias20_status": bstatus.get("BIAS20", {}).get("status"),
    }
