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
        self, code: str, end_date: str = None, lookback_days: int = 120
    ) -> list[dict]:
        """
        Return recent daily K-line rows (date DESC) for `code`, ending at `end_date`.

        Args:
            code: Stock/index code like '000001.SH'.
            end_date: Latest date to include (YYYYMMDD or YYYY-MM-DD).
                      Defaults to today.
            lookback_days: Approximate number of trading days to return.

        Checks cache first: if the cached data already covers `end_date` with
        enough history, returns directly.  Otherwise fetches the missing range
        from Tushare, upserts into cache, and returns.
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        end_date = end_date.replace("-", "")
        end_dt = datetime.strptime(end_date, "%Y%m%d")

        # ---- check whether cache covers the requested end_date ----
        latest_cached = self.cache.get_latest_date(code)

        if latest_cached:
            latest_clean = latest_cached.replace("-", "")
            if latest_clean >= end_date:
                # Cache has data up to (or beyond) our end_date.
                # Verify there are enough rows.
                cached = self.cache.get_daily(code, end=end_date, limit=lookback_days)
                if len(cached) >= lookback_days:
                    return cached
                # latest date is covered but not enough rows → need more history

        # ---- fetch missing range from Tushare ----
        desired_start = (end_dt - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")

        if latest_cached:
            latest_clean = latest_cached.replace("-", "")
            if latest_clean < end_date:
                # Missing recent data: fetch from day after latest cached
                api_start = (datetime.strptime(latest_clean, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                api_end = end_date
            else:
                # Have recent data but need more history → widen the window
                api_start = desired_start
                api_end = end_date
        else:
            # No cache at all → fetch full window
            api_start = desired_start
            api_end = end_date

        fetched = self._fetch_from_api(code, api_start, api_end)
        if fetched:
            self.cache.upsert_daily(code, fetched)

        return self.cache.get_daily(code, end=end_date, limit=lookback_days)

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

    def get_index_weights(self, index_code: str,
                           trade_date: str) -> list[dict] | None:
        """
        Return all constituent weights for the given index as of trade_date.

        Uses the latest official weight publication whose weight_date
        is <= trade_date.  Index weights are published monthly (month-end)
        and take effect the following month.  The method checks cache first;
        if the cached weight_date is from before the prior month-end, it
        re-fetches from tushare to pick up any new publication.

        Returns list of {con_code, weight} sorted by weight DESC, or None.
        """
        trade_date = trade_date.replace("-", "")
        td = datetime.strptime(trade_date, "%Y%m%d")

        # Expected weight date: published at the end of the month *before*
        # the month containing trade_date.
        # e.g. trade_date="20260608" → prior_month_end = "20260531"
        #      the cached weight_date should be >= "202605"
        prior_month = (td.replace(day=1) - timedelta(days=1))
        expected_ym = prior_month.strftime("%Y%m")  # "202605"

        # Check cache
        cached_wd = self.cache.get_latest_weight_date(index_code, trade_date)

        if cached_wd and cached_wd[:6] >= expected_ym:
            # Cache is current enough
            return self.cache.get_index_weights(index_code, cached_wd)

        # Fetch from Tushare
        import time
        try:
            df = self._api.index_weight(
                index_code=self._normalize_code(index_code),
                trade_date=trade_date,
            )
        except Exception as e:
            print(f"[DataProvider] index_weight failed for {index_code} @ {trade_date}: {e}")
            return None

        if df is None or df.empty:
            return None

        # Normalize: the API returns 'trade_date' — rename to weight_date for storage
        weight_date = str(df["trade_date"].iloc[0])

        # If cache already has this exact weight_date, no need to re-insert
        if cached_wd == weight_date:
            return self.cache.get_index_weights(index_code, weight_date)

        rows = []
        for _, r in df.iterrows():
            rows.append({
                "con_code": r["con_code"],
                "weight": float(r["weight"]),
            })

        self.cache.upsert_index_weights(index_code, weight_date, rows)
        return self.cache.get_index_weights(index_code, weight_date)

    def get_daily_batch(self, codes: list[str],
                         end_date: str) -> dict[str, dict]:
        """
        Return close/pre_close/change_pct for a batch of stocks on a single day.

        Checks tushare_cache first for each code.  Missing codes are fetched
        from tushare via a single api.daily() call (one round-trip for all
        stocks on that day).  Fetched data is upserted into the shared cache
        so future calls benefit.

        Returns {ts_code: {close, pre_close, change_pct}} for all codes that
        have data.  Stocks with no data on end_date are omitted.
        """
        end_date = end_date.replace("-", "")
        result = {}

        # ---- check cache for each code ----
        missing = []
        for code in codes:
            rows = self.cache.get_daily(code, start=end_date, end=end_date, limit=1)
            if rows:
                r = rows[0]
                close = float(r["close"])
                pre = float(r.get("pre_close", close))
                chg = round((close / pre - 1) * 100, 2) if pre else 0.0
                result[code] = {"close": close, "pre_close": pre, "change_pct": chg}
            else:
                missing.append(code)

        if not missing:
            return result

        # ---- fetch missing from Tushare (one call for all stocks on end_date) ----
        try:
            df = self._api.daily(
                trade_date=end_date,
                fields="ts_code,close,pre_close,open,high,low,vol,amount",
            )
            if df is not None and not df.empty:
                # Normalize: ts_code -> code, trade_date -> date
                df = df.rename(columns={"ts_code": "code", "trade_date": "date"})
                df["date"] = df["date"].astype(str)
                if "adj_factor" not in df.columns:
                    df["adj_factor"] = 1.0
                cols = ["code", "date", "open", "high", "low", "close",
                        "vol", "amount", "adj_factor"]
                df = df[[c for c in cols if c in df.columns]]
                self.cache.upsert_daily_bulk(df.to_dict(orient="records"))
        except Exception as e:
            print(f"[DataProvider] get_daily_batch fetch failed for {end_date}: {e}")
            return result

        # ---- re-check cache for previously-missing codes ----
        for code in missing:
            rows = self.cache.get_daily(code, start=end_date, end=end_date, limit=1)
            if rows:
                r = rows[0]
                close = float(r["close"])
                pre = float(r.get("pre_close", close))
                chg = round((close / pre - 1) * 100, 2) if pre else 0.0
                result[code] = {"close": close, "pre_close": pre, "change_pct": chg}

        return result

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
