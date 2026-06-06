import tushare as ts
from datetime import datetime, timedelta
from .cache_manager import CacheManager


class DataProvider:
    """
    Abstract data interface for agents.
    Agents call get_daily() — they don't know or care whether data comes
    from tushare/akshare/wind.  Swap the backend by changing _fetch_from_api().
    """

    def __init__(self, tushare_token: str, cache: CacheManager | None = None):
        ts.set_token(tushare_token)
        self._api = ts.pro_api()
        self.cache = cache or CacheManager()

    # ------- public API (called by agent tools) -------

    def get_daily(
        self, code: str, lookback_days: int = 120
    ) -> list[dict]:
        """
        Return recent daily K-line rows (date DESC) for `code`.
        Tries cache first; fetches missing range from tushare and writes cache.
        """
        cached = self.cache.get_daily(code, limit=lookback_days)

        if len(cached) >= lookback_days:
            return cached[:lookback_days]

        # Determine fetch range
        end_date = datetime.now().strftime("%Y%m%d")
        if cached:
            oldest = cached[-1]["date"].replace("-", "")
            start_date = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        else:
            start_date = (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")

        fetched = self._fetch_from_api(code, start_date, end_date)
        if fetched:
            self.cache.upsert_daily(code, fetched)

        return self.cache.get_daily(code, limit=lookback_days)

    def get_latest_trade_date(self, code: str) -> str | None:
        """Return latest available trading date for a code."""
        latest = self.cache.get_latest_date(code)
        if latest:
            return latest
        # fallback: fetch recent and return max date
        rows = self.get_daily(code, lookback_days=5)
        return rows[0]["date"] if rows else None

    # ------- internal -------

    def _fetch_from_api(self, code: str, start: str, end: str) -> list[dict]:
        """
        Pull daily data from Tushare.  Normalizes field names to cache schema.
        Override this method to swap data sources.
        """
        # Normalize code format: tushare wants 000001.SH / 399006.SZ
        ts_code = self._normalize_code(code)
        try:
            df = self._api.daily(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields="trade_date,open,high,low,close,vol,amount",
            )
            if df is None or df.empty:
                return []
            df = df.sort_values("trade_date", ascending=False)
            # Add adj_factor placeholder (will be populated by adj task later)
            df["adj_factor"] = 1.0
            df.rename(columns={"trade_date": "date", "vol": "vol", "amount": "amount"}, inplace=True)
            return df.to_dict(orient="records")
        except Exception as e:
            print(f"[DataProvider] fetch failed for {code}: {e}")
            return []

    @staticmethod
    def _normalize_code(code: str) -> str:
        """Ensure code format like 000001.SH / 399006.SZ for tushare."""
        code = code.strip().upper()
        if "." not in code:
            if code.startswith(("60", "68")):
                code = f"{code}.SH"
            else:
                code = f"{code}.SZ"
        return code
