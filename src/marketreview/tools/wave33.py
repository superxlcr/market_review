"""
33 Formula (Wave 33) — A-share screener for stocks in strong main-lift-wave.

Pure computation module: reads from DataProvider cache, writes results to
wave33_cache. No Tushare API calls.

Optimisation: when scanning multiple dates, each stock's K-line is fetched
ONCE for the full window, indicators are computed ONCE, and per-date checks
are pure in-memory slices (no DB queries, no re-computation).
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np

from ..data.data_provider import DataProvider
from .technical import rows_to_df, calc_kd_standard, calc_rsi, calc_wr


def scan_wave33(
    dates: List[str],
    dp: DataProvider,
    progress_cb=None,
) -> Dict[str, dict]:
    """
    Scan all A-shares for the 33 formula on each date in `dates`.

    Args:
        dates: Trading dates (YYYYMMDD), most-recent-first.
        dp: DataProvider instance (cache must be pre-loaded).
        progress_cb: Optional callable(phase, current, total, date_str).

    Returns:
        {date: {count, profit_count, profit_pct, stock_codes}, ...}
        Only returns dates that were actually scanned (not already cached).
    """
    # ── Determine which dates actually need scanning ──
    dates_to_scan = [d for d in dates if not dp.cache.has_wave33_date(d)]
    if not dates_to_scan:
        return {}

    latest_date = dates_to_scan[0]   # most recent
    earliest_date = dates_to_scan[-1]  # furthest back

    # Full window: earliest scan date - 180cal → latest scan date.
    # 180 calendar days ≈ 120 trading days — enough for WR(20) + SMA(9)
    # convergence (SMA seed weight decays below 0.01% after ~60 iterations).
    # Was 60cal (~40td), which caused RSI to deviate by 10+ points when the
    # earliest scan date was close to the latest (few missing days).
    latest_dt = datetime.strptime(latest_date, "%Y%m%d")
    earliest_dt = datetime.strptime(earliest_date, "%Y%m%d")
    full_start_dt = earliest_dt - timedelta(days=180)
    full_lookback = (latest_dt - full_start_dt).days

    results: Dict[str, dict] = {}
    total_dates = len(dates_to_scan)

    # ── Stock list + market caps (by date) ──
    stocks = dp.get_stock_list(latest_date)
    if not stocks:
        return {}

    market_caps_by_date: Dict[str, Dict[str, float]] = {}
    for d in dates_to_scan:
        market_caps_by_date[d] = dp.get_market_cap(d)

    total_stocks = len(stocks)

    if progress_cb:
        progress_cb("wave33_init", total_stocks, total_dates, latest_date)

    # ═══════════════════════════════════════════════════════════════════
    # Phase 1 — Load K-line + compute indicators ONCE per stock
    # ═══════════════════════════════════════════════════════════════════
    #
    # stock_cache[code] = (df, k_arr, wr10_arr, wr20_arr, rsi9_arr)
    #   df          — pd.DataFrame, date ASC, qfq prices
    #   k_arr       — np.array of K values (same length as df)
    #   wr10_arr    — np.array of WR(10)
    #   wr20_arr    — np.array of WR(20)
    #   rsi9_arr    — np.array of RSI(9)

    stock_cache: dict = {}

    for si, stock in enumerate(stocks):
        code = stock["ts_code"]

        if progress_cb and si > 0 and si % 50 == 0:
            progress_cb("wave33_load", si, total_stocks, str(total_dates))

        # Fetch full-window K-line once
        rows = dp.get_daily(code, end_date=latest_date,
                            lookback_days=full_lookback)
        if len(rows) < 25:
            continue

        df = rows_to_df(rows)
        if len(df) < 21:
            continue

        df = DataProvider.raw_to_qfq(df)

        # Compute all indicators once on the full series
        kd = calc_kd_standard(df)
        wr10 = calc_wr(df, 10)
        wr20 = calc_wr(df, 20)
        rsi9 = calc_rsi(df)["RSI1"]

        stock_cache[code] = (
            df,
            np.array(kd["K"]),
            np.array(wr10),
            np.array(wr20),
            np.array(rsi9),
        )

    loaded = len(stock_cache)
    if progress_cb:
        progress_cb("wave33_scan", loaded, total_stocks, str(total_dates))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2 — Per-date check (pure in-memory slices)
    # ═══════════════════════════════════════════════════════════════════

    for di, trade_date in enumerate(dates_to_scan):
        market_caps = market_caps_by_date[trade_date]
        qualifying_codes: list[str] = []
        profit_codes: list[str] = []

        for code, (df, k_arr, w10, w20, r9) in stock_cache.items():
            # Market cap filter
            mv = market_caps.get(code)
            if mv is not None and mv <= 100:
                continue

            # Find the row index for this trade_date — the last row with
            # date <= trade_date.  df is sorted date ASC.
            date_mask = df["date"] <= trade_date
            n_rows = date_mask.sum()
            if n_rows < 21:
                continue
            end_idx = n_rows - 1  # last valid row index for this date

            # Check 5 conditions on last 5 trading days (indices -5..-1
            # relative to end_idx)
            all_5_pass = True
            for offset in range(-5, 0):
                i = end_idx + offset + 1  # offset → absolute index
                if np.isnan(k_arr[i]) or k_arr[i] <= 80:
                    all_5_pass = False
                    break
                if np.isnan(w10[i]) or np.isnan(w20[i]):
                    all_5_pass = False
                    break
                if w10[i] >= 20 or w20[i] >= 20:
                    all_5_pass = False
                    break
                if np.isnan(r9[i]) or r9[i] <= 70:
                    all_5_pass = False
                    break

            if not all_5_pass:
                continue

            qualifying_codes.append(code)

            # 20-day profit: close today vs 20 trading days ago
            close_today = float(df["close"].iloc[end_idx])
            close_20d_ago = float(df["close"].iloc[end_idx - 20])
            if close_today > close_20d_ago:
                profit_codes.append(code)

        count = len(qualifying_codes)
        profit_count = len(profit_codes)
        profit_pct = round(profit_count / count * 100, 1) if count > 0 else 0.0

        dp.cache.upsert_wave33(
            trade_date=trade_date,
            count=count,
            profit_count=profit_count,
            profit_pct=profit_pct,
            stock_codes=json.dumps({
                "all": qualifying_codes,
                "profit": profit_codes,
            }, ensure_ascii=False),
        )

        results[trade_date] = {
            "count": count,
            "profit_count": profit_count,
            "profit_pct": profit_pct,
            "stock_codes": qualifying_codes,
        }

        if progress_cb:
            progress_cb("wave33_date", di + 1, total_dates, trade_date)

    return results


def compute_trend_series(counts: List[int]) -> List[str]:
    """
    Compute per-bar trend direction with hysteresis — the direction only flips
    after 3 *consecutive* moves in the opposite direction. A flat (equal) day
    resets the opposite-streak counter.

    This matches the intuition behind ``compute_trend()`` labels:
      - streak 0‑2 → "维持<方向>，盘整中" (direction unchanged)
      - streak ≥3  → "暂时/确认<方向>" (direction confirmed)

    Returns list of "up"|"down" (same length as input, no "flat" — equal days
    inherit the current direction).
    """
    n = len(counts)
    if n == 0:
        return []
    dirs: List[str] = []
    current_dir = "up"
    opposite_streak = 0
    for i in range(n):
        if i == 0:
            dirs.append(current_dir)
            continue
        if counts[i] > counts[i - 1]:
            if current_dir == "up":
                opposite_streak = 0
            else:
                opposite_streak += 1
                if opposite_streak >= 3:
                    current_dir = "up"
                    opposite_streak = 0
        elif counts[i] < counts[i - 1]:
            if current_dir == "down":
                opposite_streak = 0
            else:
                opposite_streak += 1
                if opposite_streak >= 3:
                    current_dir = "down"
                    opposite_streak = 0
        else:  # equal → reset streak, maintain direction
            opposite_streak = 0
        dirs.append(current_dir)
    return dirs


def compute_trend(counts: List[int]) -> dict:
    """
    Compute trend state from wave33 count series (most-recent-first).

    Returns:
        {direction: "up"|"down"|"flat", streak: int, label: str}
    """
    if len(counts) < 2:
        return {"direction": "flat", "streak": 0, "label": "维持，盘整中"}

    direction = "flat"
    streak = 0

    for i in range(len(counts) - 1):
        curr = counts[i]
        prev = counts[i + 1]
        if curr > prev:
            new_dir = "up"
        elif curr < prev:
            new_dir = "down"
        else:
            new_dir = "flat"

        if i == 0:
            direction = new_dir
            streak = 1 if new_dir != "flat" else 0
        else:
            if new_dir == direction:
                streak += 1
            else:
                break

    if direction == "flat":
        return {"direction": "flat", "streak": 0, "label": "维持，盘整中"}

    if direction == "up":
        if streak >= 5:
            label = f"确认上升，连续上升 {streak} 天"
        elif streak >= 3:
            label = f"暂时上升，连续上升 {streak} 天"
        else:
            label = "维持上升，盘整中"
    else:
        if streak >= 5:
            label = f"确认下降，连续下降 {streak} 天"
        elif streak >= 3:
            label = f"暂时下降，连续下降 {streak} 天"
        else:
            label = "维持下降，盘整中"

    return {"direction": direction, "streak": streak, "label": label}
