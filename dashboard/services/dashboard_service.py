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

    # ---- trading day validation ----

    def is_trading_day(self, trade_date: str) -> bool:
        """Check if a given date (YYYYMMDD) is a trading day (via trade_cal API)."""
        return self._dp.is_trading_day(trade_date)

    # ---- index K-line ----

    def get_index_data(self, code: str, lookback: int = 360,
                       end_date: str | None = None):
        """
        Load K-line data for an index symbol.
        Returns a DataFrame (date ASC).  `end_date` is passed through to
        DataProvider.get_daily() so the cache check is date-aware.
        """
        rows = self._dp.get_daily(code, end_date=end_date, lookback_days=lookback)
        df = rows_to_df(rows)
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
