"""
debug_stock.py — Quick debug: band analysis + buy points for a single stock.

Usage:
    .venv/Scripts/python scripts/debug_stock.py 002709.SZ
    .venv/Scripts/python scripts/debug_stock.py 002709.SZ --date 20260702
    .venv/Scripts/python scripts/debug_stock.py 002709.SZ --lookback 500
"""

import os
import sys
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT_ROOT, "src")
sys.path.insert(0, SRC)

from dotenv import load_dotenv
load_dotenv()

from marketreview.data.data_provider import DataProvider
from marketreview.data.cache_manager import CacheManager
from marketreview.tools.band_analysis import analyze_band, format_band_report
from marketreview.tools.buy_points import find_all_buy_points, load_buy_point_config


def main():
    parser = argparse.ArgumentParser(description="Debug stock band analysis + buy points")
    parser.add_argument("code", help="Stock code, e.g. 002709.SZ")
    parser.add_argument("--date", "-d", default=None, help="Trade date YYYYMMDD (default: latest)")
    parser.add_argument("--lookback", "-n", type=int, default=500, help="Fetch days (default: 500)")
    parser.add_argument("--peak-lookback", "-p", type=int, default=300, help="Peak lookback (default: 300)")
    args = parser.parse_args()

    code = args.code
    trade_date = args.date

    # ── Load data ──
    print(f"=== Debug: {code} ===\n")
    cache = CacheManager(os.path.join(PROJECT_ROOT, "data", "marketreview.db"))

    # Get latest date if not specified
    if not trade_date:
        row = cache.db.execute(
            "SELECT date FROM tushare_cache WHERE code=? ORDER BY date DESC LIMIT 1",
            (code,)
        ).fetchone()
        if row:
            trade_date = row["date"]
            print(f"Auto date: {trade_date}")
        else:
            print(f"No data for {code}")
            sys.exit(1)

    # Fetch data
    rows = cache.get_daily(code, limit=args.lookback)
    # Filter up to trade_date and reverse to ASC
    rows_filtered = [r for r in rows if r["date"] <= trade_date]
    rows_asc = list(reversed(rows_filtered))

    if not rows_asc:
        print(f"No data for {code} up to {trade_date}")
        sys.exit(1)

    print(f"K-line: {len(rows_asc)} rows ({rows_asc[0]['date']} ~ {rows_asc[-1]['date']})")

    # ── Band analysis ──
    band = analyze_band(rows_asc, peak_lookback=args.peak_lookback)
    print("\n" + format_band_report(band))

    # ── Close peaks ──
    if band.close_peaks:
        print(f"\n--- 收盘波峰 (P→今日) ---")
        today_idx = len(rows_asc) - 1
        for p in band.close_peaks:
            days_ago = today_idx - p.idx
            print(f"  {p.price:.2f} @ {p.date} (距今{days_ago}天, idx={p.idx})")

    # ── Buy points ──
    print(f"\n--- 买点提示 ---")
    config = load_buy_point_config()
    position_capital = config.get("单个仓位资金", 0.0)
    import pandas as pd
    import numpy as np
    from marketreview.tools.technical import calc_atr

    df_dict = {k: [] for k in rows_asc[0].keys()}
    for r in rows_asc:
        for k, v in r.items():
            df_dict[k].append(v)
    df = pd.DataFrame(df_dict)

    atr_vals = calc_atr(df, period=14)
    atr = next((v for v in reversed(atr_vals) if not np.isnan(v)), None)

    buy_points = find_all_buy_points(df, band, ts_code=code, atr=atr,
                                      position_capital=position_capital)

    if buy_points:
        for bp in buy_points:
            dist_sign = "+" if bp.distance_pct >= 0 else ""
            cap_info = f" (仓位×{bp.capital_multiplier})" if bp.capital_multiplier != 1.0 else ""
            print(f"  [{bp.type}] {bp.position} @ {bp.price:.2f} "
                  f"距离={dist_sign}{bp.distance_pct}%{cap_info}")
            print(f"    止损: 盘中{bp.intraday_stop:.2f}(-{bp.intraday_stop_pct}%) "
                  f"| 收盘{bp.close_stop:.2f}")
            print(f"    原因: {bp.reason}")
            if bp.position_size != "—":
                print(f"    仓位: {bp.position_size}")
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
