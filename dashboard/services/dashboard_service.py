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

    # ---- index K-line ----

    def get_index_data(self, code: str, lookback: int = 360,
                       end_date: str | None = None):
        """
        Load K-line data for an index symbol.
        Returns a DataFrame (date ASC), optionally truncated to end_date.
        """
        rows = self._dp.get_daily(code, lookback_days=lookback)
        df = rows_to_df(rows)
        if end_date and not df.empty:
            cutoff = end_date.replace("-", "")
            df = df[df["date"].str.replace("-", "") <= cutoff]
        return df

    # ---- latest trade date ----

    def get_latest_trade_date(self) -> str:
        """Return latest available trading date (YYYYMMDD), fallback to today."""
        raw = self._dp.get_latest_trade_date("000001.SH")
        return raw if raw else datetime.now().strftime("%Y%m%d")

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
        index_rows = self._dp.get_daily("000001.SH", lookback_days=360)
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
