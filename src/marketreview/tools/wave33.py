"""
33 Formula (Wave 33) — A-share screener for stocks in strong main-lift-wave.

Pure computation module: reads from DataProvider cache, writes results to
wave33_cache. No Tushare API calls.
"""

import json
import numpy as np
from typing import Dict, List

from ..data.data_provider import DataProvider
from .technical import rows_to_df, calc_kd, calc_rsi, calc_wr


def scan_wave33(
    dates: List[str],
    dp: DataProvider,
    progress_cb=None,
) -> Dict[str, dict]:
    """
    Scan all A-shares for the 33 formula on each date in `dates`.

    Args:
        dates: Trading dates (YYYYMMDD), most-recent-first.
               Each date requires 21 trading days of K-line ending on that date.
        dp: DataProvider instance (cache must be pre-loaded).
        progress_cb: Optional callable(phase, current, total, date_str).

    Returns:
        {date: {count, profit_count, profit_pct, stock_codes}, ...}
        Only returns dates that were actually scanned (not already cached).
    """
    results = {}
    total_dates = len(dates)

    for di, trade_date in enumerate(dates):
        if dp.cache.has_wave33_date(trade_date):
            continue

        # Get qualifying stock list
        stocks = dp.get_stock_list(trade_date)
        if not stocks:
            continue

        # Get market cap for this date
        market_caps = dp.get_market_cap(trade_date)

        qualifying_codes = []
        profit_codes = []
        total_stocks = len(stocks)

        if progress_cb:
            progress_cb("wave33_init", total_stocks, total_dates, trade_date)

        for si, stock in enumerate(stocks):
            code = stock["ts_code"]

            if progress_cb and si > 0 and si % 200 == 0:
                progress_cb("wave33_scan", si, total_stocks,
                           f"{trade_date}|{di+1}|{total_dates}")

            # Condition 4: market cap > 100万元
            # Only reject when market cap is KNOWN to be too small;
            # missing data (None) is not grounds for exclusion — daily_basic
            # may have gaps on some dates (e.g. 2026-05-15).
            mv = market_caps.get(code)
            if mv is not None and mv <= 100:
                continue

            # Fetch K-line ending at trade_date.
            # Need enough history: WR(20) requires 20 periods before first
            # valid value, plus 5 check days → minimum 25, use 40 for margin.
            rows = dp.get_daily(code, end_date=trade_date, lookback_days=40)
            if len(rows) < 25:
                continue

            df = rows_to_df(rows)
            if len(df) < 21:
                continue

            # Convert to qfq
            df = DataProvider.raw_to_qfq(df)

            # Compute indicators once
            kd = calc_kd(df)
            wr10 = calc_wr(df, 10)
            wr20 = calc_wr(df, 20)
            rsi_all = calc_rsi(df)
            rsi9 = rsi_all["RSI1"]

            # Check 5 conditions on last 5 trading days (indices -5..-1)
            all_5_pass = True
            for offset in range(-5, 0):
                # Condition 1: K > 80
                kv = kd["K"][offset]
                if np.isnan(kv) or kv <= 80:
                    all_5_pass = False
                    break

                # Condition 2: WR(10) < 20 AND WR(20) < 20
                w10 = wr10[offset]
                w20 = wr20[offset]
                if np.isnan(w10) or np.isnan(w20):
                    all_5_pass = False
                    break
                if w10 >= 20 or w20 >= 20:
                    all_5_pass = False
                    break

                # Condition 3: RSI(9) > 70
                rv = rsi9[offset]
                if np.isnan(rv) or rv <= 70:
                    all_5_pass = False
                    break

            if not all_5_pass:
                continue

            qualifying_codes.append(code)

            # 20-day profit: close today vs 20 trading days ago
            # iloc[-1] = today (trade_date), iloc[-21] = ~20 trading days ago
            close_today = float(df["close"].iloc[-1])
            close_20d_ago = float(df["close"].iloc[-21])
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
