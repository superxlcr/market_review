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
from ..log_util import get_logger

log = get_logger(__name__)


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

    log.info("scan_wave33: %d dates to scan (%s..%s), full_lookback=%d days",
             len(dates_to_scan), earliest_date, latest_date, full_lookback)

    results: Dict[str, dict] = {}
    total_dates = len(dates_to_scan)

    # ── Stock list + market caps (by date) ──
    stocks = dp.get_stock_list(latest_date)
    if not stocks:
        log.warning("scan_wave33: no qualifying stocks for date=%s", latest_date)
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
    log.info("scan_wave33 Phase 1 done: %d/%d stocks loaded + indicators computed",
             loaded, total_stocks)
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
    # 从实际数据判断初始方向（而不是硬编码 "up"）
    if n >= 2 and counts[1] < counts[0]:
        current_dir = "down"
    else:
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

    Incorporates hysteresis (same as ``compute_trend_series``): the effective
    direction only flips after 3 *consecutive* opposite-direction moves.
    Until then, the trend is still in the old direction and shown as "盘整中".

    Returns:
        {direction: "up"|"down"|"flat", streak: int, label: str}
    """
    if len(counts) < 2:
        return {"direction": "flat", "streak": 0, "label": "维持，盘整中"}

    # ── 1. Raw direction + streak (most-recent comparison first) ──
    raw_direction = "flat"
    raw_streak = 0

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
            raw_direction = new_dir
            raw_streak = 1 if new_dir != "flat" else 0
        else:
            if new_dir == raw_direction:
                raw_streak += 1
            else:
                break

    if raw_direction == "flat":
        return {"direction": "flat", "streak": 0, "label": "维持，盘整中"}

    # ── 2. Hysteresis direction (process chronologically) ──
    # counts is most-recent-first; reverse for chronological order.
    chronological = list(reversed(counts))
    # 从实际数据判断初始方向（而不是硬编码 "up"）
    if len(chronological) >= 2 and chronological[1] < chronological[0]:
        hysteresis_dir = "down"
    else:
        hysteresis_dir = "up"
    opposite_streak = 0
    for i in range(1, len(chronological)):
        if chronological[i] > chronological[i - 1]:
            if hysteresis_dir == "up":
                opposite_streak = 0
            else:
                opposite_streak += 1
                if opposite_streak >= 3:
                    hysteresis_dir = "up"
                    opposite_streak = 0
        elif chronological[i] < chronological[i - 1]:
            if hysteresis_dir == "down":
                opposite_streak = 0
            else:
                opposite_streak += 1
                if opposite_streak >= 3:
                    hysteresis_dir = "down"
                    opposite_streak = 0
        else:
            opposite_streak = 0

    # ── 3. Determine label ──
    if raw_direction != hysteresis_dir:
        # Trend hasn't flipped yet — opposite streak < 3
        if hysteresis_dir == "up":
            label = "上升趋势，盘整中"
        else:
            label = "下降趋势，盘整中"
        return {"direction": hysteresis_dir, "streak": raw_streak, "label": label}

    # Direction matches hysteresis — trend is established or confirmed
    if raw_direction == "up":
        if raw_streak >= 5:
            label = f"确认上升，连续上升 {raw_streak} 天"
        elif raw_streak >= 3:
            label = f"暂时上升，连续上升 {raw_streak} 天"
        elif raw_streak == 2:
            label = "连续上涨2天"
        else:
            label = "上涨第1天"
    else:
        if raw_streak >= 5:
            label = f"确认下降，连续下降 {raw_streak} 天"
        elif raw_streak >= 3:
            label = f"暂时下降，连续下降 {raw_streak} 天"
        elif raw_streak == 2:
            label = "连续下跌2天"
        else:
            label = "下跌第1天"

    return {"direction": raw_direction, "streak": raw_streak, "label": label}


# ═══════════════════════════════════════════════════════════════════
# KD80 — 简化版市场广度指标 (K>80 连续3天 → 日度量 → SMA3)
# ═══════════════════════════════════════════════════════════════════

def scan_kd80(
    dates: list[str],
    dp,
    progress_cb=None,
) -> dict[str, dict]:
    """
    Scan all A-shares for KD80 on each date in `dates`.

    Condition: KD K-value > 80 for 3 consecutive trading days.
    Counts qualifying stocks per date → stores in kd80_cache.

    Args:
        dates: Trading dates (YYYYMMDD), most-recent-first.
        dp: DataProvider instance.
        progress_cb: Optional callable(phase, current, total, date_str).

    Returns:
        {date: {count}, ...} for newly scanned dates.
    """
    dates_to_scan = [d for d in dates if not dp.cache.has_kd80_date(d)]
    if not dates_to_scan:
        return {}

    latest_date = dates_to_scan[0]
    earliest_date = dates_to_scan[-1]

    latest_dt = datetime.strptime(latest_date, "%Y%m%d")
    earliest_dt = datetime.strptime(earliest_date, "%Y%m%d")
    full_start_dt = earliest_dt - timedelta(days=90)  # KD only needs ~20 bars
    full_lookback = (latest_dt - full_start_dt).days

    log.info("scan_kd80: %d dates to scan (%s..%s), lookback=%d days",
             len(dates_to_scan), earliest_date, latest_date, full_lookback)

    results: dict[str, dict] = {}
    total_dates = len(dates_to_scan)

    stocks = dp.get_stock_list(latest_date)
    if not stocks:
        log.warning("scan_kd80: no qualifying stocks for date=%s", latest_date)
        return {}

    total_stocks = len(stocks)
    if progress_cb:
        progress_cb("kd80_init", total_stocks, total_dates, latest_date)

    # Phase 1 — Load K-line + compute KD once per stock
    stock_k_arr: dict[str, tuple] = {}  # code → (df, k_arr)

    for si, stock in enumerate(stocks):
        code = stock["ts_code"]
        if progress_cb and si > 0 and si % 50 == 0:
            progress_cb("kd80_load", si, total_stocks, str(total_dates))

        rows = dp.get_daily(code, end_date=latest_date,
                            lookback_days=full_lookback)
        if len(rows) < 25:
            continue
        df = rows_to_df(rows)
        if len(df) < 21:
            continue
        df = DataProvider.raw_to_qfq(df)
        kd = calc_kd_standard(df)
        stock_k_arr[code] = (df, np.array(kd["K"]))

    loaded = len(stock_k_arr)
    log.info("scan_kd80 Phase 1 done: %d/%d stocks loaded", loaded, total_stocks)
    if progress_cb:
        progress_cb("kd80_scan", loaded, total_stocks, str(total_dates))

    # Phase 2 — Per-date check (pure in-memory slices)
    for di, trade_date in enumerate(dates_to_scan):
        qualifying_count = 0

        for code, (df, k_arr) in stock_k_arr.items():
            date_mask = df["date"] <= trade_date
            n_rows = date_mask.sum()
            if n_rows < 3:
                continue
            end_idx = n_rows - 1

            # Check K > 80 for last 3 trading days (end_idx-2, end_idx-1, end_idx)
            k0 = k_arr[end_idx]
            k1 = k_arr[end_idx - 1]
            k2 = k_arr[end_idx - 2]
            if np.isnan(k0) or np.isnan(k1) or np.isnan(k2):
                continue
            if k0 > 80 and k1 > 80 and k2 > 80:
                qualifying_count += 1

        dp.cache.upsert_kd80(trade_date=trade_date, count=qualifying_count)
        results[trade_date] = {"count": qualifying_count}

        if progress_cb:
            progress_cb("kd80_date", di + 1, total_dates, trade_date)

    return results


def sma3_direction(counts: list[int]) -> dict:
    """
    Compute SMA(3) direction from count series (most-recent-first).

    Args:
        counts: list of daily counts, most-recent-first. Needs ≥4 entries.

    Returns:
        {sma3: float, direction: "up"|"down"|"flat", prev_sma3: float}
    """
    if len(counts) < 4:
        return {"sma3": 0.0, "direction": "flat", "prev_sma3": 0.0}

    today = (counts[0] + counts[1] + counts[2]) / 3
    yesterday = (counts[1] + counts[2] + counts[3]) / 3

    if today > yesterday:
        direction = "up"
    elif today < yesterday:
        direction = "down"
    else:
        direction = "flat"

    return {"sma3": round(today, 1), "direction": direction,
            "prev_sma3": round(yesterday, 1)}


def compute_sma3_series(counts: list[int]) -> list[float]:
    """Compute SMA(3) on a count series (most-recent-first → same order output)."""
    n = len(counts)
    result = []
    for i in range(n):
        if i + 2 < n:
            result.append(round((counts[i] + counts[i+1] + counts[i+2]) / 3, 1))
        elif i + 1 < n:
            result.append(round((counts[i] + counts[i+1]) / 2, 1))
        else:
            result.append(float(counts[i]))
    return result


def scan_ind_kd80(
    dates: list[str],
    dp,
    progress_cb=None,
) -> dict[str, dict]:
    """
    Scan all A-shares for industry-level KD80 (L1 + L2) on each date.

    Same condition as market KD80 (K>80 for 3 consecutive days), but
    grouped by industry classification instead of aggregated globally.

    Returns:
        {date: {count: int, l1: {name: count}, l2: {name: count}}, ...}
    """
    dates_to_scan = [d for d in dates if not dp.cache.has_ind_kd80_date(d)]
    if not dates_to_scan:
        return {}

    latest_date = dates_to_scan[0]
    earliest_date = dates_to_scan[-1]

    latest_dt = datetime.strptime(latest_date, "%Y%m%d")
    earliest_dt = datetime.strptime(earliest_date, "%Y%m%d")
    full_start_dt = earliest_dt - timedelta(days=90)
    full_lookback = (latest_dt - full_start_dt).days

    log.info("scan_ind_kd80: %d dates to scan, lookback=%d days",
             len(dates_to_scan), full_lookback)

    results: dict[str, dict] = {}
    total_dates = len(dates_to_scan)

    stocks = dp.get_stock_list(latest_date)
    if not stocks:
        log.warning("scan_ind_kd80: no qualifying stocks")
        return {}

    total_stocks = len(stocks)

    # Phase 1 — Load K-line + KD; batch-fetch industry classification
    all_codes = [s["ts_code"] for s in stocks]
    ind_map = dp.cache.get_stock_industries(all_codes)  # {code: {l1_name, l2_name, ...}}

    stock_info: dict[str, tuple] = {}

    for si, stock in enumerate(stocks):
        code = stock["ts_code"]
        if progress_cb and si > 0 and si % 50 == 0:
            progress_cb("ind_kd80_load", si, total_stocks, str(total_dates))

        ind = ind_map.get(code, {})
        l1 = ind.get("l1_name", "")
        l2 = ind.get("l2_name", "")
        if not l1 and not l2:
            continue  # skip unclassified stocks

        rows = dp.get_daily(code, end_date=latest_date,
                            lookback_days=full_lookback)
        if len(rows) < 25:
            continue
        df = rows_to_df(rows)
        if len(df) < 21:
            continue
        df = DataProvider.raw_to_qfq(df)
        kd = calc_kd_standard(df)
        stock_info[code] = (df, np.array(kd["K"]), l1, l2)

    loaded = len(stock_info)
    log.info("scan_ind_kd80 Phase 1 done: %d/%d stocks", loaded, total_stocks)
    if progress_cb:
        progress_cb("ind_kd80_scan", loaded, total_stocks, str(total_dates))

    # Phase 2 — Per-date aggregation by industry
    for di, trade_date in enumerate(dates_to_scan):
        l1_counts: dict[str, int] = {}
        l2_counts: dict[str, int] = {}

        for code, (df, k_arr, l1, l2) in stock_info.items():
            date_mask = df["date"] <= trade_date
            n_rows = date_mask.sum()
            if n_rows < 3:
                continue
            end_idx = n_rows - 1

            k0 = k_arr[end_idx]
            k1 = k_arr[end_idx - 1]
            k2 = k_arr[end_idx - 2]
            if np.isnan(k0) or np.isnan(k1) or np.isnan(k2):
                continue
            if k0 > 80 and k1 > 80 and k2 > 80:
                if l1:
                    l1_counts[l1] = l1_counts.get(l1, 0) + 1
                if l2:
                    l2_counts[l2] = l2_counts.get(l2, 0) + 1

        # Write to cache (always write at least a sentinel so coverage
        # check passes even on dates where zero industries had KD80).
        if not l1_counts and not l2_counts:
            dp.cache.upsert_ind_kd80(trade_date, "__sentinel__", "__sentinel__", 0)
        else:
            for l1_name, cnt in l1_counts.items():
                dp.cache.upsert_ind_kd80(trade_date, "L1", l1_name, cnt)
            for l2_name, cnt in l2_counts.items():
                dp.cache.upsert_ind_kd80(trade_date, "L2", l2_name, cnt)

        results[trade_date] = {
            "count": sum(l1_counts.values()),
            "l1": dict(l1_counts),
            "l2": dict(l2_counts),
        }

        if progress_cb:
            progress_cb("ind_kd80_date", di + 1, total_dates, trade_date)

    return results


def sma3_streak(counts: list[int]) -> dict:
    """
    Compute SMA3 direction + consecutive streak from count series.

    Args:
        counts: most-recent-first, needs ≥6 entries for reliable streak.

    Returns:
        {sma3, direction, streak}
        streak = consecutive days in current SMA3 direction (≥1).
    """
    info = sma3_direction(counts)
    direction = info["direction"]
    sma3_val = info["sma3"]

    if direction == "flat" or len(counts) < 5:
        return {"sma3": sma3_val, "direction": direction, "streak": 1 if direction != "flat" else 0}

    # Walk back to count consecutive days in same direction
    streak = 1
    for offset in range(1, len(counts) - 3):
        # Compute SMA3 direction at offset days back
        window = counts[offset:offset + 4]
        prev_info = sma3_direction(window)
        if prev_info["direction"] == direction:
            streak += 1
        else:
            break

    return {"sma3": sma3_val, "direction": direction, "streak": streak}
