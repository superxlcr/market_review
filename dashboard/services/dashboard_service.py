"""
DashboardService — single facade for all dashboard data access.

Creates ONE DataProvider instance and reuses it for all calls.
This ensures:
  - DataProvider-as-single-entry-point rule is respected
  - No Tushare API calls outside DataProvider
  - No DataProvider construction scattered across app.py
"""

import os
from datetime import datetime, timedelta

from marketreview.data.data_provider import DataProvider
from marketreview.tools.technical import rows_to_df


class DashboardService:
    """Unified data service for the Streamlit dashboard."""

    def __init__(self, tushare_token: str | None = None):
        token = tushare_token or os.environ.get("TUSHARE_TOKEN", "")
        self._dp = DataProvider(tushare_token=token)

    @property
    def is_configured(self) -> bool:
        return bool(os.environ.get("TUSHARE_TOKEN", ""))

    # ---- bulk data loading ----

    def ensure_data_loaded(self, trade_date: str, progress_cb=None) -> dict:
        """
        Ensure cache has raw K-line + adj_factor for all stocks.
        Called once when the user selects a date in the console.

        Args:
            trade_date: target date (YYYYMMDD)
            progress_cb: optional callable(phase, current, total)
        Returns:
            {"status": "ok"|"error", "fetched_dates": int, "elapsed": float}
        """
        return self._dp.ensure_data_loaded(trade_date, progress_cb=progress_cb)

    @staticmethod
    def raw_to_qfq(df):
        """Convert raw (不复权) DataFrame to qfq (前复权) for display."""
        return DataProvider.raw_to_qfq(df)

    # ---- cache coverage check ----

    def check_cache_coverage(self, trade_date: str) -> bool:
        """Return True if cache already covers this date (no loading needed)."""
        return self._dp.check_cache_coverage(trade_date)

    # ---- trading day validation ----

    def is_trading_day(self, trade_date: str) -> bool:
        """Check if a given date (YYYYMMDD) is a trading day (via trade_cal API)."""
        return self._dp.is_trading_day(trade_date)

    # ---- index K-line ----

    def get_index_data(self, code: str, lookback: int = 360,
                       end_date: str | None = None):
        """
        Load K-line data for an index/stock symbol.
        Returns a DataFrame (date ASC) with prices converted to qfq (前复权).
        """
        rows = self._dp.get_daily(code, end_date=end_date, lookback_days=lookback)
        df = rows_to_df(rows)
        # Convert raw → qfq for display (no-op for indices, essential for stocks)
        if not df.empty:
            df = DataProvider.raw_to_qfq(df)
        return df

    # ---- latest trade date ----

    def get_latest_trade_date(self) -> str:
        """
        Walk back from today to find the nearest trading day with data.

        Tries up to 15 calendar days back. Each candidate is checked via
        get_market_breadth() — if Tushare returns data, it's a trading day.
        This is authoritative regardless of what's in cache.
        """
        today = datetime.now()
        for i in range(15):
            candidate = (today - timedelta(days=i)).strftime("%Y%m%d")
            if self._dp.get_market_breadth(candidate) is not None:
                return candidate
        return today.strftime("%Y%m%d")

    # ---- market overview ----

    def get_market_overview(self, trade_date: str) -> dict | None:
        """
        Fetch complete market overview for a given trade_date.
        Returns dict with keys: today, yesterday, trend, error (if any).
        """
        if not self.is_configured:
            return None

        # Today
        today = self._dp.get_market_breadth(trade_date)
        if today is None:
            return {"error": f"无法获取 {trade_date} 市场数据"}

        # Yesterday — walk back calendar days
        dt = datetime.strptime(trade_date, "%Y%m%d")
        yesterday = None
        for i in range(1, 10):
            prev_date = (dt - timedelta(days=i)).strftime("%Y%m%d")
            result = self._dp.get_market_breadth(prev_date)
            if result is not None:
                yesterday = result
                break

        # 10-day trend — find last 10 trading days up to trade_date
        index_rows = self._dp.get_daily("000001.SH", end_date=trade_date, lookback_days=360)
        all_trading_dates = sorted(set(
            r["date"].replace("-", "") for r in index_rows
        ), reverse=True)
        trading_dates = [td for td in all_trading_dates if td <= trade_date]

        trend = []
        for td in trading_dates:
            if len(trend) >= 10:
                break
            day_data = self._dp.get_market_breadth(td)
            if day_data is not None:
                trend.append({
                    "date": td,
                    "total_yi": day_data["total_yi"],
                    "up": day_data["up"],
                    "down": day_data["down"],
                })
        trend.reverse()  # chronological

        # 5/10-day average turnover
        amounts = [d["total_yi"] for d in trend]
        avg_5d = round(sum(amounts[-5:]) / min(5, len(amounts[-5:])), 0) if len(amounts) >= 5 else 0
        avg_10d = round(sum(amounts[-10:]) / min(10, len(amounts[-10:])), 0) if len(amounts) >= 10 else 0

        return {
            "today": today,
            "yesterday": yesterday,
            "trend": trend,
            "avg_5d": avg_5d,
            "avg_10d": avg_10d,
        }

    # ---- index contribution ----

    def get_index_contribution(
        self, index_code: str, trade_date: str | None = None
    ) -> dict | None:
        """
        Fetch index weight contribution analysis.

        Delegates to build_index_contribution() in contribution.py.
        Returns {index, gainers, losers} or None.
        """
        try:
            # Lazy import to avoid circular dependency at module level
            from marketreview.tools.contribution import build_index_contribution
            return build_index_contribution(index_code, trade_date, self._dp)
        except Exception as e:
            print(f"[DashboardService] get_index_contribution failed: {e}")
            return None

    # ---- industry frequency (cross-date aggregation) ----

    def get_recent_trading_dates(self, end_date: str, count: int = 5) -> list[str]:
        """
        Return the last `count` trading dates up to and including `end_date`.

        Uses cached index daily data to determine which dates are trading days.
        Returns dates in YYYYMMDD format, most-recent-first.
        """
        index_rows = self._dp.get_daily("000001.SH", end_date=end_date, lookback_days=360)
        all_dates = sorted(set(
            r["date"].replace("-", "") for r in index_rows
        ), reverse=True)
        return [d for d in all_dates if d <= end_date.replace("-", "")][:count]

    # ---- K-line pattern detection ----

    def get_kline_patterns(self, df) -> list[dict]:
        """
        Run all K-line pattern detectors and return matched patterns.
        The caller provides the DataFrame (already loaded via get_index_data).
        Returns a list of dicts: [{name, direction, note}, ...]
        """
        try:
            from marketreview.tools.kline_patterns import detect_patterns
            return detect_patterns(df, obj_type="index")
        except Exception as e:
            print(f"[DashboardService] get_kline_patterns failed: {e}")
            return []

    def get_industry_frequency(
        self, index_code: str, trade_date: str
    ) -> dict | None:
        """
        Count industry appearances in top-10 gainers/losers over the last 5
        trading days.  Only returns industries that appear ≥ 3 days.
        """
        try:
            from marketreview.tools.contribution import build_industry_frequency
            dates = self.get_recent_trading_dates(trade_date, count=5)
            if len(dates) < 3:
                return None
            return build_industry_frequency(index_code, dates, self._dp, top_n=10, min_days=3)
        except Exception as e:
            print(f"[DashboardService] get_industry_frequency failed: {e}")
            return None

    # ---- wave33 ----

    def ensure_wave33_computed(self, trade_date: str, progress_cb=None) -> dict:
        """
        Ensure wave33_cache has results for the last 20 trading days.
        Scans any missing days (most-recent-first) using pre-loaded cache.
        Called from console page after ensure_data_loaded().

        Returns {"scanned": int, "cached": int, "elapsed": float}.
        """
        import time as _time
        from marketreview.tools.wave33 import scan_wave33

        t0 = _time.time()

        # Determine last 40 trading days (15 chart + 21 rolling window + margin)
        index_rows = self._dp.get_daily(
            "000001.SH", end_date=trade_date, lookback_days=90
        )
        all_dates = sorted(set(
            r["date"].replace("-", "") for r in index_rows
        ), reverse=True)
        td_clean = trade_date.replace("-", "")
        target_dates = [d for d in all_dates if d <= td_clean][:40]

        missing = []
        already_cached = 0
        for d in target_dates:
            if self._dp.cache.has_wave33_date(d):
                already_cached += 1
            else:
                missing.append(d)

        scanned = 0
        if missing:
            scan_wave33(missing, self._dp, progress_cb=progress_cb)
            scanned = len(missing)

        elapsed = _time.time() - t0
        return {
            "scanned": scanned,
            "cached": already_cached,
            "elapsed": round(elapsed, 1),
        }

    def get_wave33_data(self, chart_days: int = 15,
                       rolling_days: int = 21) -> dict:
        """
        Read wave33 results from cache and compute rolling cumulative counts.
        Each bar = unique stocks passing in the [date - rolling_days td, date] window.
        Chart shows `chart_days` bars; rolling window is `rolling_days` trading days.
        Returns {dates, counts, profit_counts, profit_pcts, trend}.
        Always READ-ONLY — never triggers computation.
        """
        import json
        from marketreview.tools.wave33 import compute_trend

        # Need: chart_days for display + rolling_days for the earliest bar's window
        fetch_days = chart_days + rolling_days
        rows = self._dp.cache.get_wave33_range(limit=fetch_days)
        rows = list(reversed(rows))  # chronological (oldest first)

        if not rows:
            return {
                "dates": [], "counts": [], "profit_counts": [],
                "profit_pcts": [], "trend": {
                    "direction": "flat", "streak": 0, "label": "维持，盘整中"
                },
            }

        # Build date-indexed lookup: {trade_date: {"all": set, "profit": set}}
        day_data = {}
        for r in rows:
            try:
                data = json.loads(r["stock_codes"]) if r["stock_codes"] else {}
            except (json.JSONDecodeError, TypeError):
                codes_list = json.loads(r["stock_codes"]) if r["stock_codes"] else []
                data = {"all": codes_list, "profit": []}
            day_data[r["trade_date"]] = {
                "all": set(data.get("all", [])),
                "profit": set(data.get("profit", [])),
            }

        all_dates = sorted(day_data.keys())  # chronological

        dates = []
        counts = []
        profit_counts = []
        profit_pcts = []

        # For each target date, compute rolling cumulative over last `rolling_days` days
        for i, target_date in enumerate(all_dates):
            # Find the start of the rolling window (rolling_days trading days before target)
            window_start_idx = max(0, i - rolling_days + 1)
            window_dates = all_dates[window_start_idx:i + 1]

            cum_all = set()
            cum_profit = set()
            for wd in window_dates:
                cum_all |= day_data[wd]["all"]
                cum_profit |= day_data[wd]["profit"]

            dates.append(target_date)
            counts.append(len(cum_all))
            profit_counts.append(len(cum_profit))
            profit_pcts.append(round(len(cum_profit) / len(cum_all) * 100, 1)
                             if cum_all else 0.0)

        # Only return the last `chart_days` entries for the chart
        dates = dates[-chart_days:]
        counts = counts[-chart_days:]
        profit_counts = profit_counts[-chart_days:]
        profit_pcts = profit_pcts[-chart_days:]

        rev_counts = list(reversed(counts))
        trend = compute_trend(rev_counts) if rev_counts else {
            "direction": "flat", "streak": 0, "label": "维持，盘整中"
        }

        return {
            "dates": dates,
            "counts": counts,
            "profit_counts": profit_counts,
            "profit_pcts": profit_pcts,
            "trend": trend,
        }
