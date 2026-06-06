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
        Checks both count AND freshness — stale cache triggers a re-fetch.
        """
        cached = self.cache.get_daily(code, limit=lookback_days)
        today = datetime.now()
        if len(cached) >= lookback_days:
            latest_cached = cached[0]["date"].replace("-", "")  # handle both YYYYMMDD and YYYY-MM-DD
            latest_dt = datetime.strptime(latest_cached, "%Y%m%d")
            if (today - latest_dt).days <= 5:   # cache is recent enough
                return cached[:lookback_days]
            # Cache is stale — fall through to fetch

        # Determine fetch range
        end_date = today.strftime("%Y%m%d")
        desired_start = (today - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")
        if cached:
            oldest = cached[-1]["date"].replace("-", "")
            # If cached data doesn't go back far enough (e.g. MA240 upgrade),
            # extend the fetch window to cover the full desired range
            if desired_start < oldest:
                start_date = desired_start
            else:
                start_date = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        else:
            start_date = desired_start

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

    def get_market_breadth(self, trade_date: str) -> dict | None:
        """
        Fetch single-day market breadth data.

        Returns dict with keys:
          trade_date, up, down, flat, up_limit, down_limit,
          total_yi, sh_yi, sz_yi, bj_yi
        Or None if no data for this date.
        """
        import time
        try:
            daily = self._api.daily(
                trade_date=trade_date,
                fields="ts_code,close,pre_close,amount",
            )
            if daily is None or daily.empty:
                return None

            up = int(len(daily[daily["close"] > daily["pre_close"]]))
            down = int(len(daily[daily["close"] < daily["pre_close"]]))
            flat = int(len(daily[daily["close"] == daily["pre_close"]]))

            # Exchange breakdown
            sh = daily[daily["ts_code"].str.endswith(".SH")]
            sz = daily[daily["ts_code"].str.endswith(".SZ")]
            bj = daily[daily["ts_code"].str.endswith(".BJ")]

            total_yi = round(float(daily["amount"].sum()) / 1e5, 0)
            sh_yi = round(float(sh["amount"].sum()) / 1e5, 0) if len(sh) > 0 else 0
            sz_yi = round(float(sz["amount"].sum()) / 1e5, 0) if len(sz) > 0 else 0
            bj_yi = round(float(bj["amount"].sum()) / 1e5, 0) if len(bj) > 0 else 0

            # 涨停/跌停
            up_limit = down_limit = 0
            try:
                limits = self._api.stk_limit(trade_date=trade_date)
                if limits is not None and not limits.empty:
                    merged = daily.merge(limits, on="ts_code")
                    up_limit = int(len(merged[merged["close"] == merged["up_limit"]]))
                    down_limit = int(len(merged[merged["close"] == merged["down_limit"]]))
            except Exception:
                pass

            return {
                "trade_date": trade_date,
                "up": up, "down": down, "flat": flat,
                "up_limit": up_limit, "down_limit": down_limit,
                "total_yi": total_yi,
                "sh_yi": sh_yi, "sz_yi": sz_yi, "bj_yi": bj_yi,
            }
        except Exception as e:
            print(f"[DataProvider] get_market_breadth failed for {trade_date}: {e}")
            return None

    # ------- internal -------

    def _fetch_from_api(self, code: str, start: str, end: str) -> list[dict]:
        """
        Pull daily data from Tushare.  Normalizes field names to cache schema.
        Uses pro_bar() (works with free-tier tokens).
        Falls back to pro_api().daily() for stocks, index_daily for indices.
        """
        import time
        ts_code = self._normalize_code(code)
        asset = self._asset_type(ts_code)

        # Try pro_bar first (works with all token tiers)
        try:
            df = ts.pro_bar(
                ts_code=ts_code,
                asset=asset,
                freq="D",
                start_date=start,
                end_date=end,
                adj="qfq",
            )
            if df is not None and not df.empty:
                return self._normalize_df(df)
        except IOError as e:
            # Rate limit or permission error — log and continue
            msg = str(e)
            if "频率" in msg or "超出" in msg:
                print(f"[DataProvider] pro_bar rate-limited for {ts_code}, trying fallback...")
            else:
                print(f"[DataProvider] pro_bar failed for {ts_code}: {msg[:100]}")

        # Fallback: try pro_api endpoints
        try:
            if asset == "I":
                df = self._api.index_daily(ts_code=ts_code, start_date=start, end_date=end)
            else:
                df = self._api.daily(
                    ts_code=ts_code, start_date=start, end_date=end,
                    fields="trade_date,open,high,low,close,vol,amount",
                )
            if df is not None and not df.empty:
                return self._normalize_df(df)
        except Exception as e:
            print(f"[DataProvider] fallback API failed for {ts_code}: {e}")

        return []

    @staticmethod
    def _asset_type(ts_code: str) -> str:
        """Determine Tushare asset type: I (index) or E (stock)."""
        code_num = ts_code.split(".")[0]
        # Index patterns: 000xxx (SSE), 399xxx (SZSE), 880xxx (sector), 999xxx
        if code_num.startswith(("000", "399", "880", "999")):
            return "I"
        return "E"

    @staticmethod
    def _normalize_df(df) -> list[dict]:
        """Convert tushare DataFrame to cache-compatible list[dict]."""
        df = df.sort_values("trade_date", ascending=False)
        # Normalize: trade_date may be int or str
        df["trade_date"] = df["trade_date"].astype(str)
        # Add adj_factor placeholder if missing
        if "adj_factor" not in df.columns:
            df["adj_factor"] = 1.0
        # Keep only needed columns
        cols = ["trade_date", "open", "high", "low", "close", "vol", "amount", "adj_factor"]
        df = df[[c for c in cols if c in df.columns]]
        df.rename(columns={"trade_date": "date"}, inplace=True)
        return df.to_dict(orient="records")

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
