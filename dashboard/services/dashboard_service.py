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
from marketreview.tools.technical import rows_to_df, build_technical_summary
from marketreview.backtest.config import load_pools, load_strategies, PoolConfig, StrategyConfig
from marketreview.backtest.engine import BacktestEngine, get_limit_pct
from marketreview.backtest.strategy_base import (
    DayContext, BuySignal, create_strategy, safe_float,
)
from marketreview.backtest.reporter import Report
from marketreview.tools.technical import calc_ma
from marketreview.log_util import get_logger

log = get_logger(__name__)


class DashboardService:
    """Unified data service for the Streamlit dashboard."""

    def __init__(self, tushare_token: str | None = None):
        token = tushare_token or os.environ.get("TUSHARE_TOKEN", "")
        self._dp = DataProvider(tushare_token=token)
        self._llm_client = None  # lazy init
        log.info("[AI v%s] DashboardService started", self._AI_VERSION)

    @property
    def is_configured(self) -> bool:
        return bool(os.environ.get("TUSHARE_TOKEN", ""))

    # ---- bulk data loading ----

    def ensure_data_loaded(self, trade_date: str, progress_cb=None) -> dict:
        """
        Ensure cache has raw K-line + adj_factor for all stocks.
        Also ensures watchlist industry daily data.

        Args:
            trade_date: target date (YYYYMMDD)
            progress_cb: optional callable(phase, current, total)
        Returns:
            {"status": "ok"|"error", "fetched_dates": int, "elapsed": float}
        """
        # Resolve watchlist industry codes for extra fetch
        extra_codes: list[str] = []
        try:
            wl = self.get_watchlist_industries()["matched"]
            extra_codes = [w["code"] for w in wl if w.get("code")]
        except Exception as e:
            log.warning("ensure_data_loaded: failed to read watchlist: %s", e)

        return self._dp.ensure_data_loaded(trade_date, progress_cb=progress_cb,
                                           extra_industry_codes=extra_codes)

    @staticmethod
    def raw_to_qfq(df):
        """Convert raw (不复权) DataFrame to qfq (前复权) for display."""
        return DataProvider.raw_to_qfq(df)

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
        import time as _time
        _t0 = _time.perf_counter()
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

        result = {
            "today": today,
            "yesterday": yesterday,
            "trend": trend,
            "avg_5d": avg_5d,
            "avg_10d": avg_10d,
        }
        log.info("get_market_overview(%s) elapsed=%.2fs", trade_date,
                 _time.perf_counter() - _t0)
        return result

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
            log.warning("get_index_contribution failed: %s", e)
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

    def get_kline_patterns(self, df, obj_type: str = "index") -> list[dict]:
        """
        Run all K-line pattern detectors and return matched patterns.
        The caller provides the DataFrame (already loaded via get_index_data).

        Args:
            df: OHLCV DataFrame (date ASC).
            obj_type: "index", "industry", or "stock".
        Returns a list of dicts: [{name, direction, note}, ...]
        """
        try:
            from marketreview.tools.kline_patterns import detect_patterns
            return detect_patterns(df, obj_type=obj_type)
        except Exception as e:
            log.warning("get_kline_patterns failed: %s", e)
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
            log.warning("get_industry_frequency failed: %s", e)
            return None

    # ---- industry / sector analysis ----


    def get_industry_split_config(self) -> dict:
        """Return SPLIT_L1 / SPLIT_L2 configuration for UI display."""
        from marketreview.tools.industry import get_split_summary
        return get_split_summary()

    def get_industry_list(self) -> list[dict]:
        """
        Return the display industry list (after SPLIT_L1 / SPLIT_L2 filtering).

        Returns list of dicts with keys: code, name, level.
        """
        codes = self._dp._get_display_industry_codes()
        classify_map = self._dp.cache.get_industry_classify_map()
        result = []
        for code in codes:
            info = classify_map.get(code, {})
            result.append({
                "code": code,
                "name": info.get("industry_name", code),
                "level": info.get("level", ""),
            })
        return result

    def get_watchlist_industries(self) -> dict:
        """
        Read config/watchlist_industries.txt, match names against
        industry_classify table.

        Returns dict:
          - matched: list of {code, name, level}
          - unmatched: list of names that couldn't be resolved
        """
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config", "watchlist_industries.txt",
        )
        result: dict = {"matched": [], "unmatched": []}
        if not os.path.exists(config_path):
            log.info("get_watchlist_industries: config file not found at %s", config_path)
            return result

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        names = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            names.append(stripped)

        if not names:
            return result

        # Match against industry_classify
        self._dp._ensure_industry_classify()  # lazy-init if needed
        classify_map = self._dp.cache.get_industry_classify_map()

        # Build name → info lookup
        name_to_info: dict[str, dict] = {}
        for code, info in classify_map.items():
            name_to_info[info.get("industry_name", "")] = {**info, "code": code}

        for name in names:
            if name in name_to_info:
                info = name_to_info[name]
                result["matched"].append({
                    "code": info["code"],
                    "name": name,
                    "level": info.get("level", ""),
                })
            else:
                result["unmatched"].append(name)
                log.warning("get_watchlist_industries: name '%s' not found in classification", name)

        log.info("get_watchlist_industries: %d matched, %d unmatched",
                 len(result["matched"]), len(result["unmatched"]))
        return result

    def get_watchlist_stocks(self) -> dict:
        """
        Read config/watchlist_stocks.txt, match names against
        stock_basic_cache table.

        Returns dict:
          - matched: list of {ts_code, name, industry}
          - unmatched: list of names that couldn't be resolved
        """
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config", "watchlist_stocks.txt",
        )
        result: dict = {"matched": [], "unmatched": []}
        if not os.path.exists(config_path):
            log.info("get_watchlist_stocks: config file not found at %s", config_path)
            return result

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        names = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            names.append(stripped)

        if not names:
            return result

        # Match against stock_basic_cache
        all_stocks = self._dp.cache.get_stock_basic()
        name_to_stock: dict[str, dict] = {s["name"]: s for s in all_stocks}

        matched_codes = []
        for name in names:
            stock = name_to_stock.get(name)
            if stock:
                matched_codes.append(stock["ts_code"])
                result["matched"].append({
                    "ts_code": stock["ts_code"],
                    "name": name,
                    "industry": "",  # filled below
                })
            else:
                result["unmatched"].append(name)
                log.warning("get_watchlist_stocks: name '%s' not found in stock_basic", name)

        # Batch-fetch industry for matched stocks
        if matched_codes:
            from marketreview.tools.industry import resolve_industry_label
            industries = self._dp.cache.get_stock_industries(matched_codes)
            for item in result["matched"]:
                ind = industries.get(item["ts_code"], {})
                item["industry"] = resolve_industry_label(
                    l1_name=ind.get("l1_name", ""),
                    l2_name=ind.get("l2_name", ""),
                    l3_name=ind.get("l3_name", ""),
                ) or ind.get("l1_name", "未知")

        log.info("get_watchlist_stocks: %d matched, %d unmatched",
                 len(result["matched"]), len(result["unmatched"]))
        return result

    def get_industry_daily(self, industry_code: str,
                           end_date: str = None,
                           lookback: int = 240):
        """
        Load K-line data for an industry sector.

        Returns a DataFrame (date ASC) with columns: date, open, high, low,
        close, vol, amount, pct_change.  Compatible with render_ohlcv_section().
        """
        df = self._dp.get_industry_daily(
            industry_code, end_date=end_date, lookback=lookback,
        )
        if not df.empty and "trade_date" in df.columns:
            df = df.rename(columns={"trade_date": "date"})
        return df

    def get_industry_ranking(self, trade_date: str, lookback: int = 1) -> list[dict]:
        """
        Return all display industries ranked by pct_change on trade_date.

        Each entry: {code, name, level, pct_change, close, amount,
                      pct_5d (if lookback>=6), pct_20d (if lookback>=21)}.
        Sorted descending (top gainers first).

        Args:
            trade_date: target date (YYYYMMDD or YYYY-MM-DD)
            lookback: rows to fetch per industry. Default 1 (today only).
                      Set >=6 to compute pct_5d, >=21 to compute pct_20d.
        """
        td = trade_date.replace("-", "")
        codes = self._dp._get_display_industry_codes()
        classify_map = self._dp.cache.get_industry_classify_map()

        _compute_multiday = lookback >= 6
        _fetch_lookback = max(lookback, 21) if _compute_multiday else lookback

        rankings = []
        for code in codes:
            df = self._dp.get_industry_daily(code, end_date=td, lookback=_fetch_lookback)
            if df.empty:
                continue
            row = df.iloc[-1]
            row_td = str(row.get("trade_date", ""))
            if row_td != td:
                continue
            info = classify_map.get(code, {})
            entry = {
                "code": code,
                "name": info.get("industry_name", code),
                "level": info.get("level", ""),
                "pct_change": float(row.get("pct_change", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "amount": float(row.get("amount", 0) or 0),
            }

            # Multi-day returns from close prices
            if _compute_multiday and len(df) >= 6:
                _close_today = float(df.iloc[-1].get("close", 0) or 0)
                _close_5d = float(df.iloc[-6].get("close", 0) or 0)
                if _close_5d and _close_5d != 0:
                    entry["pct_5d"] = round((_close_today - _close_5d) / _close_5d * 100, 2)
                else:
                    entry["pct_5d"] = None
            else:
                entry["pct_5d"] = None

            if _compute_multiday and len(df) >= 21:
                _close_today = float(df.iloc[-1].get("close", 0) or 0)
                _close_20d = float(df.iloc[-21].get("close", 0) or 0)
                if _close_20d and _close_20d != 0:
                    entry["pct_20d"] = round((_close_today - _close_20d) / _close_20d * 100, 2)
                else:
                    entry["pct_20d"] = None
            else:
                entry["pct_20d"] = None

            rankings.append(entry)

        rankings.sort(key=lambda x: x["pct_change"], reverse=True)
        log.info("get_industry_ranking(%s): %d industries", trade_date, len(rankings))
        return rankings

    def get_prev_trading_date(self, trade_date: str, max_walkback: int = 10) -> str | None:
        """
        Walk back calendar days from trade_date to find the previous trading day.

        Uses index daily data (000001.SH) as the trading calendar reference.
        Returns the previous trading date as YYYYMMDD, or None if not found.
        """
        td = trade_date.replace("-", "")
        dt = datetime.strptime(td, "%Y%m%d")
        for i in range(1, max_walkback + 1):
            prev_date = (dt - timedelta(days=i)).strftime("%Y%m%d")
            rows = self._dp.get_daily("000001.SH", end_date=prev_date, lookback_days=1)
            if rows:
                row_td = str(rows[-1].get("date", "")).replace("-", "")
                if row_td == prev_date:
                    return prev_date
        return None

    def get_industry_analysis_set(self, trade_date: str) -> list[dict]:
        """
        Select industries for detailed analysis on the sector page.

        Candidate sources (union, then dedup by code):
          1. TOP 5 by pct_change   → 🥇 涨幅第N
          2. BOTTOM 5 by pct_change → 📉 跌幅第N
          3. Frequent leaders/laggards over last 5 days → 🔁 近5日频繁领涨/领跌

        Returns list of dicts with keys: code, name, level, pct_change, close,
        amount, reasons (list of label strings).
        """
        ranking = self.get_industry_ranking(trade_date)
        if not ranking:
            return []

        # Collect frequent industries from both index contributions
        freq_labels: dict[str, str] = {}  # industry_name → reason label
        for idx_code in ["000001.SH", "399006.SZ"]:
            freq = self.get_industry_frequency(idx_code, trade_date)
            if freq:
                for g in freq.get("gainers", []):
                    freq_labels[g["industry"]] = "🔁 近5日频繁领涨"
                for l in freq.get("losers", []):
                    if l["industry"] not in freq_labels:
                        freq_labels[l["industry"]] = "🔁 近5日频繁领跌"

        seen: set[str] = set()
        result: list[dict] = []

        # 1. TOP 5
        for i, r in enumerate(ranking[:5]):
            reasons = [f"🥇 涨幅第{i + 1}"]
            if r["name"] in freq_labels:
                reasons.append(freq_labels[r["name"]])
            result.append({**r, "reasons": reasons})
            seen.add(r["code"])

        # 2. BOTTOM 5
        bottom = ranking[-5:] if len(ranking) >= 5 else []
        for i, r in enumerate(reversed(bottom)):
            if r["code"] in seen:
                continue
            reasons = [f"📉 跌幅第{i + 1}"]
            if r["name"] in freq_labels:
                reasons.append(freq_labels[r["name"]])
            result.append({**r, "reasons": reasons})
            seen.add(r["code"])

        # 3. Frequent industries not yet included
        for r in ranking:
            if r["name"] in freq_labels and r["code"] not in seen:
                reasons = [freq_labels[r["name"]]]
                result.append({**r, "reasons": reasons})
                seen.add(r["code"])

        log.info("get_industry_analysis_set(%s): %d candidates", trade_date, len(result))
        return result

    def get_industry_constituents(
        self, industry_name: str, level: str, trade_date: str
    ) -> dict:
        """
        Get constituent stock analysis for an industry on a given date.

        Returns two ranked lists:
          - top_cap: top 10 by total market cap (desc)
          - top_movers: top 10 by absolute daily pct_change (desc)

        Each entry: {ts_code, name, total_mv, circ_mv, pct_change, mv_pct}.
        """
        td = trade_date.replace("-", "")

        # 1. Find constituent stocks by industry name + level
        stocks = self._dp.cache.get_stocks_by_industry_level(
            industry_name, level
        )
        if not stocks:
            log.info(
                "get_industry_constituents(%s, L=%s): no stocks found",
                industry_name, level,
            )
            return {"top_cap": [], "top_movers": []}

        codes = [s["ts_code"] for s in stocks]
        name_map = {s["ts_code"]: s["name"] for s in stocks}
        log.info(
            "get_industry_constituents(%s, L=%s): %d stocks",
            industry_name, level, len(codes),
        )

        # 2. Daily performance (close, pre_close, change_pct) from tushare_cache
        batch = self._dp.get_daily_batch(codes, td)

        # 3. Market cap from daily_basic_cache
        all_basic = self._dp.cache.get_daily_basic(td)
        mv_map: dict[str, dict] = {r["ts_code"]: r for r in all_basic}

        # 4. Combine
        total_mv_sum: float = 0.0
        combined: list[dict] = []
        for code in codes:
            perf = batch.get(code, {})
            mv = mv_map.get(code, {})
            total_mv = float(mv.get("total_mv") or 0)
            combined.append({
                "ts_code": code,
                "name": name_map.get(code, code),
                "total_mv": total_mv,
                "circ_mv": float(mv.get("circ_mv") or 0),
                "pct_change": float(perf.get("change_pct") or 0),
            })
            total_mv_sum += total_mv

        # Compute market cap share for each stock
        for s in combined:
            s["mv_pct"] = round(
                s["total_mv"] / total_mv_sum * 100, 2
            ) if total_mv_sum > 0 else 0.0

        # 5. Two views: top by market cap, top by absolute move
        top_cap = sorted(
            [c for c in combined if c["total_mv"] > 0],
            key=lambda x: x["total_mv"], reverse=True,
        )[:10]
        top_movers = sorted(
            combined,
            key=lambda x: abs(x["pct_change"]), reverse=True,
        )[:10]

        return {"top_cap": top_cap, "top_movers": top_movers}

    # ---- wave33 ----

    def ensure_wave33_computed(self, trade_date: str, progress_cb=None) -> dict:
        """
        Ensure wave33_cache covers the chart+window need for `trade_date`.

        Two-window design:
          - USE window:  40 trading days (15 chart + 21 rolling + 4 buffer)
          - CACHE window: 80 trading days (~4 months, 2x the USE window)

        Only the USE window is checked for cache completeness. When any date in
        the USE window is missing, the full CACHE window is scanned (over-fetch),
        so switching to nearby dates hits cache and feels instant.

        Returns {"scanned": int, "cached": int, "elapsed": float}.
        """
        import time as _time
        from marketreview.tools.wave33 import scan_wave33

        USE_DAYS = 40       # needed for chart display
        CACHE_DAYS = 80     # over-fetch when scanning

        t0 = _time.time()

        # Trading date list (most-recent-first), covering CACHE_DAYS
        index_rows = self._dp.get_daily(
            "000001.SH", end_date=trade_date, lookback_days=180
        )
        all_dates = sorted(set(
            r["date"].replace("-", "") for r in index_rows
        ), reverse=True)
        td_clean = trade_date.replace("-", "")
        use_dates = [d for d in all_dates if d <= td_clean][:USE_DAYS]

        # ── Fast path: all USE dates already cached ──
        missing_use = [d for d in use_dates
                       if not self._dp.cache.has_wave33_date(d)]
        if not missing_use:
            log.info("ensure_wave33: FAST PATH — all %d USE dates cached "
                     "(end=%s, range=%s..%s)",
                     len(use_dates), td_clean, use_dates[-1], use_dates[0])
            self._precompute_cumulative_profit(use_dates, progress_cb=progress_cb)
            return {
                "scanned": 0,
                "cached": len(use_dates),
                "elapsed": round(_time.time() - t0, 1),
            }

        # ── Slow path: scan the full CACHE window ──
        cache_dates = [d for d in all_dates if d <= td_clean][:CACHE_DAYS]
        missing_cache = [d for d in cache_dates
                         if not self._dp.cache.has_wave33_date(d)]
        already_cached = len(cache_dates) - len(missing_cache)
        log.info("ensure_wave33: SLOW PATH — %d/%d USE missing, "
                 "scanning %d/%d CACHE dates (end=%s)",
                 len(missing_use), len(use_dates),
                 len(missing_cache), len(cache_dates), td_clean)

        if missing_cache:
            scan_wave33(missing_cache, self._dp, progress_cb=progress_cb)

        self._precompute_cumulative_profit(cache_dates, progress_cb=progress_cb)

        elapsed = _time.time() - t0
        return {
            "scanned": len(missing_cache),
            "cached": already_cached,
            "elapsed": round(elapsed, 1),
        }

    def _precompute_cumulative_profit(self, target_dates: list[str],
                                      progress_cb=None) -> None:
        """
        Pre-compute cumulative 20-day profit for each target_date over a
        21-trading-day rolling window, and store the count in each wave33_cache
        row's stock_codes JSON blob (key ``cum_profit``).

        This moves the expensive per-stock profit re-check from the read path
        (get_wave33_data) to the write path (console), where a progress bar
        provides feedback.
        """
        import json
        from marketreview.tools.technical import rows_to_df

        rolling_days = 21
        rows = []
        for d in target_dates:
            row = self._dp.cache.get_wave33_row(d)
            if row:
                rows.append(row)
        rows.sort(key=lambda r: r["trade_date"])  # chronological

        if len(rows) < 2:
            return

        # Skip if all rows already have pre-computed cum_profit
        all_cached = True
        for r in rows:
            try:
                data = json.loads(r["stock_codes"]) if r["stock_codes"] else {}
            except (json.JSONDecodeError, TypeError):
                all_cached = False
                break
            if "cum_profit" not in data:
                all_cached = False
                break
        if all_cached:
            return

        # Build day_data: {date: {"all": set, "profit": set}}
        day_data: dict[str, dict] = {}
        for r in rows:
            try:
                data = json.loads(r["stock_codes"]) if r["stock_codes"] else {}
            except (json.JSONDecodeError, TypeError):
                data = {}
            day_data[r["trade_date"]] = {
                "all": set(data.get("all", [])),
                "profit": set(data.get("profit", [])),
            }

        all_dates = sorted(day_data.keys())

        # Collect (code, target_date) pairs and per-date cumulative union
        date_cum_all: dict[str, set] = {}
        for i, target_date in enumerate(all_dates):
            window_start_idx = max(0, i - rolling_days + 1)
            window_dates = all_dates[window_start_idx:i + 1]
            cum_all: set = set()
            for wd in window_dates:
                cum_all |= day_data[wd]["all"]
            date_cum_all[target_date] = cum_all

        # Unique stocks across ALL cumulative unions
        all_codes = sorted(set().union(*date_cum_all.values()))
        if not all_codes:
            return

        # Pre-fetch stock data — ONE query per unique stock
        latest_date = all_dates[-1]
        stock_df_cache: dict[str, object] = {}  # code -> pd.DataFrame (date ASC, qfq)
        total_codes = len(all_codes)

        for idx, code in enumerate(all_codes):
            if progress_cb and idx % 100 == 0:
                progress_cb("wave33_cumprofit", idx, total_codes,
                            str(len(all_dates)))

            rows_daily = self._dp.get_daily(code, end_date=latest_date,
                                            lookback_days=90)
            if len(rows_daily) < 22:
                continue
            df = rows_to_df(rows_daily)
            if len(df) < 21:
                continue
            df = DataProvider.raw_to_qfq(df)
            stock_df_cache[code] = df

        if progress_cb:
            progress_cb("wave33_cumprofit", total_codes, total_codes,
                        str(len(all_dates)))

        # Update each wave33 row with cumulative profit count
        for target_date in all_dates:
            cum_all = date_cum_all.get(target_date, set())
            cum_profit = 0
            for code in cum_all:
                df = stock_df_cache.get(code)
                if df is None:
                    continue
                date_mask = df["date"] <= target_date
                n_rows = date_mask.sum()
                if n_rows < 21:
                    continue
                end_idx = n_rows - 1
                if float(df["close"].iloc[end_idx]) > float(df["close"].iloc[end_idx - 20]):
                    cum_profit += 1

            row = self._dp.cache.get_wave33_row(target_date)
            if not row:
                continue
            try:
                sc_data = json.loads(row["stock_codes"]) if row["stock_codes"] else {}
            except (json.JSONDecodeError, TypeError):
                sc_data = {}
            sc_data["cum_profit"] = cum_profit
            self._dp.cache.update_wave33_stock_codes(
                target_date, json.dumps(sc_data, ensure_ascii=False),
            )

    def get_wave33_data(self, chart_days: int = 15,
                       rolling_days: int = 21,
                       end_date: str | None = None) -> dict:
        """
        Read wave33 results from cache and compute rolling cumulative counts.
        Each bar = unique stocks passing in the [date - rolling_days td, date] window.
        Chart shows `chart_days` bars; rolling window is `rolling_days` trading days.
        Returns {dates, counts, profit_counts, profit_pcts, trend}.
        Always READ-ONLY — never triggers computation.

        Args:
            end_date: Optional YYYYMMDD — filter to trade_date <= end_date.
                      Defaults to today (cache layer also defaults to today).
        """
        from datetime import datetime
        import json
        from marketreview.tools.wave33 import compute_trend, compute_trend_series

        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        # Need: chart_days for display + rolling_days for the earliest bar's window
        fetch_days = chart_days + rolling_days
        log.info("get_wave33_data: end_date=%s chart_days=%s rolling_days=%s "
                 "fetch_days=%s", end_date, chart_days, rolling_days, fetch_days)
        rows = self._dp.cache.get_wave33_range(limit=fetch_days, end_date=end_date)
        rows = list(reversed(rows))  # chronological (oldest first)

        if not rows:
            return {
                "dates": [], "counts": [], "profit_counts": [],
                "profit_pcts": [], "trend": {
                    "direction": "flat", "streak": 0, "label": "维持，盘整中"
                },
                "trend_series": [], "last_window_start": "", "last_window_end": "",
                "latest_day_count": 0, "latest_day_new": 0,
            }

        # Build date-indexed lookup: {trade_date: {"all": set, "profit": set, "cum_profit": int|None}}
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
                "cum_profit": data.get("cum_profit"),  # pre-computed, or None for old data
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
            for wd in window_dates:
                cum_all |= day_data[wd]["all"]

            # Read pre-computed cumulative profit when available (from
            # _precompute_cumulative_profit), otherwise fall back to per-stock
            # re-check on the TARGET date.
            cached_cum = day_data[target_date].get("cum_profit")
            if cached_cum is not None:
                cum_profit = cached_cum
            else:
                cum_profit = 0
                for code in cum_all:
                    if self._dp.check_profit_on_date(code, target_date):
                        cum_profit += 1

            dates.append(target_date)
            counts.append(len(cum_all))
            profit_counts.append(cum_profit)
            profit_pcts.append(round(cum_profit / len(cum_all) * 100, 1)
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

        # Window boundary for the last (most recent) bar — used in sidebar label
        last_window_end = all_dates[-1] if all_dates else ""
        last_window_start_idx = max(0, len(all_dates) - rolling_days)
        last_window_start = all_dates[last_window_start_idx] if all_dates else ""

        # ── Latest single-day stats (not cumulative) ──
        latest_date = all_dates[-1]
        latest_day_all = day_data[latest_date]["all"]
        latest_day_count = len(latest_day_all)

        # New: stocks selected today that were NOT in the previous 20-day
        # cumulative (i.e. first appearance in the rolling window).
        prev_start = max(0, len(all_dates) - 1 - rolling_days + 1)
        prev_cum = set()
        for wd in all_dates[prev_start:len(all_dates) - 1]:
            prev_cum |= day_data[wd]["all"]
        latest_day_new = len(latest_day_all - prev_cum)

        return {
            "dates": dates,
            "counts": counts,
            "profit_counts": profit_counts,
            "profit_pcts": profit_pcts,
            "trend": trend,
            "trend_series": compute_trend_series(counts),
            "last_window_start": last_window_start,
            "last_window_end": last_window_end,
            "latest_day_count": latest_day_count,
            "latest_day_new": latest_day_new,
        }

    # ---- AI summary ----

    # Shared system prompt path (relative to this file)
    _SYSTEM_PROMPT_PATH = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "src", "marketreview", "llm", "system.md",
    )

    @classmethod
    def _load_system_prompt(cls) -> str:
        """Load the shared analysis framework (system prompt)."""
        with open(cls._SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()

    @staticmethod
    def _load_prompt(name: str) -> str:
        """Load a per-guide user-prompt template from llm/prompts/<name>.md."""
        import os as _os
        prompt_dir = _os.path.join(
            _os.path.dirname(__file__),
            "..", "..", "src", "marketreview", "llm", "prompts",
        )
        filepath = _os.path.join(prompt_dir, f"{name}.md")
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _get_llm(self):
        """Lazy-init the LLM client."""
        if self._llm_client is None:
            from marketreview.llm import create_llm_client
            self._llm_client = create_llm_client()
        return self._llm_client

    def get_ai_summary(self, trade_date: str,
                        summary_type: str = "market_overview") -> dict:
        """
        Read cached AI summaries for a given trade_date and type.
        Returns dict keyed by guide_key, each value is {content, model, created_at}.
        Returns empty dict if nothing cached.
        """
        rows = self._dp.cache.get_ai_summary(trade_date, summary_type)
        result = {}
        for r in rows:
            if r.get("content") == "AI 摘要暂时不可用":
                continue  # stale placeholder from a prior failed run — skip so caller retries
            result[r["guide_key"]] = r
        return result

    @staticmethod
    def _build_index_ai_data(code: str, name: str, rows: list[dict],
                              tech_summary: dict,
                              contrib: dict | None = None,
                              freq: dict | None = None) -> dict:
        """Build structured AI-ready data dict for an index guide.

        contrib / freq are optional pre-fetched contribution & industry-frequency
        data from get_index_contribution / get_industry_frequency.
        """
        if not rows:
            return {"error": "无数据"}

        # get_daily returns date DESC; sort to ASC so [-1]/[-2] indexing is correct
        rows = sorted(rows, key=lambda r: r["date"])

        latest = rows[-1]
        close = float(latest["close"])
        open_val = float(latest["open"])
        high = float(latest["high"])
        low = float(latest["low"])

        # --- 涨跌幅 ---
        if len(rows) >= 2:
            prev_close = float(rows[-2]["close"])
            chg_pct = (close / prev_close - 1) * 100
        else:
            chg_pct = 0.0

        # === K线价格 ===
        kp = tech_summary.get("kline_pattern", {})
        price_data: dict = {
            "今日": {
                "开盘": round(open_val, 2),
                "最高": round(high, 2),
                "最低": round(low, 2),
                "收盘": round(close, 2),
                "涨跌幅": f"{chg_pct:+.2f}%",
                "K线类型": kp.get("type", ""),
                "实体占比": f"{kp.get('body_pct', 0)}%",
                "上影线占比": f"{kp.get('upper_wick_pct', 0)}%",
                "下影线占比": f"{kp.get('lower_wick_pct', 0)}%",
            },
        }

        # 近5日K线
        recent_5 = rows[-min(5, len(rows)):]
        price_data["近5日K线"] = []
        for i, r in enumerate(recent_5):
            entry: dict = {
                "日期": f"{r['date'][4:6]}-{r['date'][6:8]}",
                "开": round(float(r["open"]), 2),
                "高": round(float(r["high"]), 2),
                "低": round(float(r["low"]), 2),
                "收": round(float(r["close"]), 2),
            }
            # chg from previous candle
            if i > 0:
                prev_r = recent_5[i - 1]
                entry["涨跌幅"] = f"{(float(r['close']) / float(prev_r['close']) - 1) * 100:+.2f}%"
            elif len(rows) > len(recent_5):
                prev_r = rows[-len(recent_5) - 1]
                entry["涨跌幅"] = f"{(float(r['close']) / float(prev_r['close']) - 1) * 100:+.2f}%"
            price_data["近5日K线"].append(entry)

        # === 均线 ===
        mas = tech_summary.get("mas", {})
        ma_dirs = tech_summary.get("ma_directions", {})
        ma_arrangement = tech_summary.get("ma_arrangement", "")

        ma_list: list[dict] = []
        for period in [5, 10, 20, 60, 120, 240]:
            key = f"MA{period}"
            val = mas.get(key)
            if val is None:
                continue
            direction = ma_dirs.get(key, "→")
            if direction == "↑":
                role = "支撑"
            elif direction == "↓":
                role = "压力"
            else:
                role = "无(走平)"
            ma_list.append({
                "均线": key,
                "值": val,
                "方向": direction,
                "作用": role,
            })

        ma_data = {"排列": ma_arrangement, "各均线": ma_list}

        # === 成交量 ===
        vol = tech_summary.get("volume", {})

        # 近10日成交额
        recent_10 = rows[-min(10, len(rows)):]
        turnover_10d: list[dict] = []
        for r in recent_10:
            amount_yi = round(float(r["amount"]) / 1e5, 2)
            turnover_10d.append({
                "日期": f"{r['date'][4:6]}-{r['date'][6:8]}",
                "成交额": f"{amount_yi:,.0f}亿",
            })

        # 扣抵量（含扣抵日日期）
        deduct_data: dict = {}
        for period, label in [(5, "MA5"), (10, "MA10")]:
            idx = len(rows) - 1 - period
            if idx >= 0:
                deduct_date = rows[idx]["date"]
                deduct_amt = vol.get(f"ma{period}_deduct_yi")
                vs_pct = vol.get(f"vs_ma{period}_deduct_pct")
                deduct_data[label] = {
                    "扣抵日": f"{deduct_date[4:6]}-{deduct_date[6:8]}",
                    "扣抵量": f"{deduct_amt:,.0f}亿" if deduct_amt is not None else "N/A",
                    "今日vs扣抵量": f"{vs_pct:+.1f}%" if vs_pct is not None else "N/A",
                }

        volume_data: dict = {
            "今日成交额": f"{vol.get('latest_amount_yi', 0):,.0f}亿",
            "5日均量": f"{vol.get('ma5_yi', 0):,.0f}亿",
            "10日均量": f"{vol.get('ma10_yi', 0):,.0f}亿",
            "今日vs5日均量": f"{vol.get('vs_ma5_pct', 0):+.1f}%",
            "今日vs10日均量": f"{vol.get('vs_ma10_pct', 0):+.1f}%",
            "量能趋势": vol.get("trend_5d", ""),
            "均量状态": f"{vol.get('cross_state', '')}{'(' + str(vol.get('cross_days', 0)) + '天)' if vol.get('cross_days', 0) else ''}",
            "扣抵量": deduct_data,
            "近10日成交额": turnover_10d,
        }

        # === 技术指标 ===
        kd_k = tech_summary.get("kd_k", 0) or 0
        kd_d = tech_summary.get("kd_d", 0) or 0
        if kd_k > 80 and kd_d > 80:
            kd_zone = "超买区"
        elif kd_k < 20 and kd_d < 20:
            kd_zone = "超卖区"
        else:
            kd_zone = "常态区"
        rsi_val = tech_summary.get("rsi")
        rsi_zone = "超买区" if (rsi_val and rsi_val > 70) else ("超卖区" if (rsi_val and rsi_val < 30) else "常态区")

        kd_div = tech_summary.get("kd_divergence") or {}
        rsi_div = tech_summary.get("rsi_divergence") or {}

        # --- KD 背离详情 ---
        if kd_div.get("type"):
            parts = []
            if kd_div.get("kd_divergence"):
                parts.append("KD")
            elif kd_div.get("k_divergence"):
                parts.append("K")
            elif kd_div.get("d_divergence"):
                parts.append("D")
            kd_div_detail: dict = {
                "类型": kd_div["type"],
                "背离线": "/".join(parts),
                "背离起始日": kd_div.get("divergence_date", "")[:10] if kd_div.get("divergence_date") else "",
                "持续天数": kd_div.get("days", 0) or 0,
            }
        else:
            kd_div_detail = "无"

        # --- RSI 背离详情 ---
        if rsi_div.get("type"):
            rsi_div_detail: dict = {
                "类型": rsi_div["type"],
                "背离起始日": rsi_div.get("divergence_date", "")[:10] if rsi_div.get("divergence_date") else "",
                "持续天数": rsi_div.get("days", 0) or 0,
            }
        else:
            rsi_div_detail = "无"

        indicator_data: dict = {
            "KD": {
                "K": tech_summary.get("kd_k"),
                "D": tech_summary.get("kd_d"),
                "区间": kd_zone,
                "背离": kd_div_detail,
            },
            "RSI": {
                "值": rsi_val,
                "区间": rsi_zone,
                "背离": rsi_div_detail,
            },
            "BIAS10": {
                "值": f"{tech_summary.get('bias10', 0):+.2f}%",
                "状态": tech_summary.get("bias10_status") or "—",
            },
            "BIAS20": {
                "值": f"{tech_summary.get('bias20', 0):+.2f}%",
                "状态": tech_summary.get("bias20_status") or "—",
            },
        }

        # === 多K线形态（dashboard 同款量化分析） ===
        try:
            from marketreview.tools.technical import rows_to_df
            from marketreview.tools.kline_patterns import detect_patterns
            _df = rows_to_df(rows)
            pattern_results = detect_patterns(_df, obj_type="index")
        except Exception:
            pattern_results = []

        # === 权重贡献（dashboard 同款） ===
        contrib_data: dict = {}
        if contrib:
            idx = contrib.get("index", {})
            contrib_data["指数涨跌"] = {
                "收盘": idx.get("close"),
                "涨跌点": idx.get("chg_pts"),
                "涨跌幅": f"{idx.get('chg_pct', 0):+.2f}%",
            }
            # 领涨 Top10 — keep only key fields for AI
            if contrib.get("gainers"):
                contrib_data["领涨Top10"] = [
                    {
                        "代码": g["code"],
                        "名称": g["name"],
                        "行业": g["industry"],
                        "权重": f"{g['weight']:.1f}%",
                        "涨幅": f"{g['chg_pct']:+.2f}%",
                        "贡献点": f"{g['contrib']:+.2f}",
                    }
                    for g in contrib["gainers"]
                ]
            # 领跌 Top10
            if contrib.get("losers"):
                contrib_data["领跌Top10"] = [
                    {
                        "代码": l["code"],
                        "名称": l["name"],
                        "行业": l["industry"],
                        "权重": f"{l['weight']:.1f}%",
                        "跌幅": f"{l['chg_pct']:+.2f}%",
                        "贡献点": f"{l['contrib']:+.2f}",
                    }
                    for l in contrib["losers"]
                ]
            # 近5日频繁领涨/领跌行业
            if freq:
                if freq.get("gainers"):
                    contrib_data["近5日频繁领涨行业"] = [
                        {"行业": f["industry"], "出现天数": f["days"]}
                        for f in freq["gainers"]
                    ]
                if freq.get("losers"):
                    contrib_data["近5日频繁领跌行业"] = [
                        {"行业": f["industry"], "出现天数": f["days"]}
                        for f in freq["losers"]
                    ]

        return {
            "指数": name,
            "K线价格": price_data,
            "均线": ma_data,
            "成交量": volume_data,
            "技术指标": indicator_data,
            "K线形态": pattern_results,
            "权重贡献": contrib_data,
        }

    # ═══════════════════════════════════════════════════════════════
    #  Sector AI guide helpers
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _build_sector_ai_data(name: str, rows: list[dict],
                               tech_summary: dict,
                               constituents: dict,
                               reason: str) -> dict:
        """Build structured AI-ready data dict for a single industry guide.

        Same structure as _build_index_ai_data, but replaces 权重贡献 with
        大市值权重股 + 今日异动股 from the constituent analysis.
        """
        if not rows:
            return {"error": "无数据"}

        rows = sorted(rows, key=lambda r: r["date"])
        latest = rows[-1]
        close = float(latest["close"])
        open_val = float(latest["open"])
        high = float(latest["high"])
        low = float(latest["low"])

        # --- 涨跌幅 ---
        if len(rows) >= 2:
            prev_close = float(rows[-2]["close"])
            chg_pct = (close / prev_close - 1) * 100
        else:
            chg_pct = 0.0

        # === K线价格 ===
        kp = tech_summary.get("kline_pattern", {})
        price_data: dict = {
            "今日": {
                "开盘": round(open_val, 2),
                "最高": round(high, 2),
                "最低": round(low, 2),
                "收盘": round(close, 2),
                "涨跌幅": f"{chg_pct:+.2f}%",
                "K线类型": kp.get("type", ""),
                "实体占比": f"{kp.get('body_pct', 0)}%",
                "上影线占比": f"{kp.get('upper_wick_pct', 0)}%",
                "下影线占比": f"{kp.get('lower_wick_pct', 0)}%",
            },
        }

        recent_5 = rows[-min(5, len(rows)):]
        price_data["近5日K线"] = []
        for i, r in enumerate(recent_5):
            entry: dict = {
                "日期": f"{r['date'][4:6]}-{r['date'][6:8]}",
                "开": round(float(r["open"]), 2),
                "高": round(float(r["high"]), 2),
                "低": round(float(r["low"]), 2),
                "收": round(float(r["close"]), 2),
            }
            if i > 0:
                prev_r = recent_5[i - 1]
                entry["涨跌幅"] = f"{(float(r['close']) / float(prev_r['close']) - 1) * 100:+.2f}%"
            elif len(rows) > len(recent_5):
                prev_r = rows[-len(recent_5) - 1]
                entry["涨跌幅"] = f"{(float(r['close']) / float(prev_r['close']) - 1) * 100:+.2f}%"
            price_data["近5日K线"].append(entry)

        # === 均线 ===
        mas = tech_summary.get("mas", {})
        ma_dirs = tech_summary.get("ma_directions", {})
        ma_arrangement = tech_summary.get("ma_arrangement", "")

        ma_list: list[dict] = []
        for period in [5, 10, 20, 60, 120, 240]:
            key = f"MA{period}"
            val = mas.get(key)
            if val is None:
                continue
            direction = ma_dirs.get(key, "→")
            role = "支撑" if direction == "↑" else ("压力" if direction == "↓" else "无(走平)")
            ma_list.append({"均线": key, "值": val, "方向": direction, "作用": role})

        ma_data = {"排列": ma_arrangement, "各均线": ma_list}

        # === 成交量 ===
        vol = tech_summary.get("volume", {})
        recent_10 = rows[-min(10, len(rows)):]
        turnover_10d: list[dict] = []
        for r in recent_10:
            amount_yi = round(float(r["amount"]) / 1e5, 2)
            turnover_10d.append({
                "日期": f"{r['date'][4:6]}-{r['date'][6:8]}",
                "成交额": f"{amount_yi:,.0f}亿",
            })

        deduct_data: dict = {}
        for period, label in [(5, "MA5"), (10, "MA10")]:
            idx = len(rows) - 1 - period
            if idx >= 0:
                deduct_date = rows[idx]["date"]
                deduct_amt = vol.get(f"ma{period}_deduct_yi")
                vs_pct = vol.get(f"vs_ma{period}_deduct_pct")
                deduct_data[label] = {
                    "扣抵日": f"{deduct_date[4:6]}-{deduct_date[6:8]}",
                    "扣抵量": f"{deduct_amt:,.0f}亿" if deduct_amt is not None else "N/A",
                    "今日vs扣抵量": f"{vs_pct:+.1f}%" if vs_pct is not None else "N/A",
                }

        volume_data: dict = {
            "今日成交额": f"{vol.get('latest_amount_yi', 0):,.0f}亿",
            "5日均量": f"{vol.get('ma5_yi', 0):,.0f}亿",
            "10日均量": f"{vol.get('ma10_yi', 0):,.0f}亿",
            "今日vs5日均量": f"{vol.get('vs_ma5_pct', 0):+.1f}%",
            "今日vs10日均量": f"{vol.get('vs_ma10_pct', 0):+.1f}%",
            "量能趋势": vol.get("trend_5d", ""),
            "均量状态": f"{vol.get('cross_state', '')}{'(' + str(vol.get('cross_days', 0)) + '天)' if vol.get('cross_days', 0) else ''}",
            "扣抵量": deduct_data,
            "近10日成交额": turnover_10d,
        }

        # === 技术指标 ===
        kd_k = tech_summary.get("kd_k", 0) or 0
        kd_d = tech_summary.get("kd_d", 0) or 0
        if kd_k > 80 and kd_d > 80:
            kd_zone = "超买区"
        elif kd_k < 20 and kd_d < 20:
            kd_zone = "超卖区"
        else:
            kd_zone = "常态区"
        rsi_val = tech_summary.get("rsi")
        rsi_zone = "超买区" if (rsi_val and rsi_val > 70) else ("超卖区" if (rsi_val and rsi_val < 30) else "常态区")

        kd_div = tech_summary.get("kd_divergence") or {}
        rsi_div = tech_summary.get("rsi_divergence") or {}

        if kd_div.get("type"):
            parts = []
            if kd_div.get("kd_divergence"):
                parts.append("KD")
            elif kd_div.get("k_divergence"):
                parts.append("K")
            elif kd_div.get("d_divergence"):
                parts.append("D")
            kd_div_detail: dict = {
                "类型": kd_div["type"],
                "背离线": "/".join(parts),
                "背离起始日": kd_div.get("divergence_date", "")[:10] if kd_div.get("divergence_date") else "",
                "持续天数": kd_div.get("days", 0) or 0,
            }
        else:
            kd_div_detail = "无"

        if rsi_div.get("type"):
            rsi_div_detail: dict = {
                "类型": rsi_div["type"],
                "背离起始日": rsi_div.get("divergence_date", "")[:10] if rsi_div.get("divergence_date") else "",
                "持续天数": rsi_div.get("days", 0) or 0,
            }
        else:
            rsi_div_detail = "无"

        indicator_data: dict = {
            "KD": {"K": tech_summary.get("kd_k"), "D": tech_summary.get("kd_d"),
                   "区间": kd_zone, "背离": kd_div_detail},
            "RSI": {"值": rsi_val, "区间": rsi_zone, "背离": rsi_div_detail},
            "BIAS10": {"值": f"{tech_summary.get('bias10', 0):+.2f}%",
                       "状态": tech_summary.get("bias10_status") or "—"},
            "BIAS20": {"值": f"{tech_summary.get('bias20', 0):+.2f}%",
                       "状态": tech_summary.get("bias20_status") or "—"},
        }

        # === K线形态 ===
        try:
            from marketreview.tools.technical import rows_to_df
            from marketreview.tools.kline_patterns import detect_patterns
            _df = rows_to_df(rows)
            pattern_results = detect_patterns(_df, obj_type="index")
        except Exception:
            pattern_results = []

        # === 成分股数据（替代权重贡献） ===
        constituent_data: dict = {}
        if constituents:
            # 大市值权重股
            if constituents.get("top_cap"):
                constituent_data["大市值权重股"] = [
                    {
                        "代码": s["ts_code"],
                        "名称": s["name"],
                        "总市值": f"{s['total_mv'] / 1e4:,.0f}亿",
                        "市值占比": f"{s.get('mv_pct', 0):.1f}%",
                        "涨跌幅": f"{s['pct_change']:+.2f}%",
                    }
                    for s in constituents["top_cap"]
                ]
            # 今日异动股
            if constituents.get("top_movers"):
                constituent_data["今日异动股"] = [
                    {
                        "代码": s["ts_code"],
                        "名称": s["name"],
                        "涨跌幅": f"{s['pct_change']:+.2f}%",
                        "总市值": f"{s['total_mv'] / 1e4:,.0f}亿",
                        "市值占比": f"{s.get('mv_pct', 0):.1f}%",
                    }
                    for s in constituents["top_movers"]
                ]

        return {
            "行业": name,
            "入选理由": reason,
            "K线价格": price_data,
            "均线": ma_data,
            "成交量": volume_data,
            "技术指标": indicator_data,
            "K线形态": pattern_results,
            "成分股": constituent_data,
        }

    def generate_ai_sector_analysis(self, trade_date: str, progress_cb=None
                                     ) -> dict:
        """
        Generate AI guides + summary for sector_analysis, store in DB.

        Same 3-step pipeline as generate_ai_summary():
          1. Build shared market_data
          2. Concurrent per-industry guides (analysis set only, ~10-15)
          3. Sector summary (synthesises all industry guides)

        Uses batch_chat() for concurrent LLM calls.
        Returns dict with keys: 'sector/<code>' guides + 'sector_summary'.
        """
        import json as _json, time as _time

        _t_total_start = _time.perf_counter()
        log.info("[AI v%s] generate_ai_sector_analysis(%s)",
                 self._AI_VERSION, trade_date)

        llm = self._get_llm()
        model = llm.model_name
        result = {}
        FAIL_PLACEHOLDER = "AI 摘要暂时不可用"
        sys_prompt = self._load_system_prompt()

        # ── 1. Market data (shared) ──
        if progress_cb:
            progress_cb("sector_start", "正在准备行业数据...")
        _t1 = _time.perf_counter()
        overview = self.get_market_overview(trade_date)
        log.info("stage=sector_market_data elapsed=%.1fs",
                 _time.perf_counter() - _t1)
        if overview is None or "error" in overview:
            return {"error": "无法获取市场概览数据"}

        today = overview["today"]
        yesterday = overview["yesterday"]
        trend = overview["trend"]

        # Build market_data JSON (same structure as market_overview)
        t_total = today["up"] + today["flat"] + today["down"]
        breadth_structure = {
            "今日": {
                "上涨": today["up"],
                "平盘": today["flat"],
                "下跌": today["down"],
                "上涨占比": f"{today['up'] / t_total * 100:.1f}%",
                "涨停": today["up_limit"],
                "跌停": today["down_limit"],
            },
        }
        if yesterday:
            y_total = yesterday["up"] + yesterday["flat"] + yesterday["down"]
            breadth_structure["昨日"] = {
                "上涨": yesterday["up"],
                "平盘": yesterday["flat"],
                "下跌": yesterday["down"],
                "上涨占比": f"{yesterday['up'] / y_total * 100:.1f}%",
                "涨停": yesterday["up_limit"],
                "跌停": yesterday["down_limit"],
            }

        turnover_data = {"今日": f"{today['total_yi']:,.0f}亿"}
        if yesterday:
            turnover_data["昨日"] = f"{yesterday['total_yi']:,.0f}亿"
        amounts = [d["total_yi"] for d in trend]
        if len(amounts) >= 5:
            turnover_data["5日均量"] = f"{sum(amounts[-5:]) / 5:,.0f}亿"
        if len(amounts) >= 10:
            turnover_data["10日均量"] = f"{sum(amounts[-10:]) / 10:,.0f}亿"
        turnover_data["近10日每日"] = []
        for d in trend:
            up_n = d.get("up", 0)
            down_n = d.get("down", 0)
            side = "涨多" if up_n >= down_n else "跌多"
            turnover_data["近10日每日"].append({
                "日期": f"{d['date'][4:6]}-{d['date'][6:8]}",
                "成交额": f"{d['total_yi']:,.0f}亿",
                "涨跌": side,
            })

        w33 = self.get_wave33_data(chart_days=15, rolling_days=21,
                                    end_date=trade_date)
        wave33_list = []
        if w33["dates"]:
            for i, d in enumerate(w33["dates"]):
                dc = d.replace("-", "")
                wave33_list.append({
                    "日期": f"{dc[4:6]}-{dc[6:8]}",
                    "数量": w33["counts"][i],
                    "20日盈利占比": f"{w33['profit_pcts'][i]}%",
                })

        market_data = {
            "涨跌结构": breadth_structure,
            "成交额": turnover_data,
            "3浪3选股_近15日": wave33_list,
        }
        market_data_json = _json.dumps(market_data, ensure_ascii=False)

        # ── 2. Prepare industry tasks ──
        candidates = self.get_industry_analysis_set(trade_date)

        # Merge watchlist industries (dedup by code)
        watchlist = self.get_watchlist_industries()["matched"]
        seen_codes: set[str] = {c["code"] for c in candidates}
        if watchlist:
            for w in watchlist:
                if w["code"] not in seen_codes:
                    # Fetch pct_change for the watchlist industry
                    df_1d = self._dp.get_industry_daily(
                        w["code"], end_date=trade_date, lookback=1
                    )
                    pct = 0.0
                    if not df_1d.empty:
                        row = df_1d.iloc[-1]
                        if str(row.get("trade_date", "")) == trade_date:
                            pct = float(row.get("pct_change", 0) or 0)

                    candidates.append({
                        "code": w["code"],
                        "name": w["name"],
                        "level": w["level"],
                        "pct_change": pct,
                        "reasons": ["⭐ 自选"],
                    })
                    seen_codes.add(w["code"])

        if not candidates:
            return {"error": "无行业分析候选"}

        log.info("stage=sector_data_prep candidates=%d (with watchlist)", len(candidates))

        sector_tasks: list[dict] = []
        for c in candidates:
            code = c["code"]
            name = c["name"]
            level = c["level"]
            reason = "、".join(c.get("reasons", []))

            # Get industry OHLCV
            ind_rows_raw = self._dp.cache.get_industry_daily(
                code, end_date=trade_date, lookback=360
            )
            if not ind_rows_raw:
                log.warning("generate_ai_sector_analysis: no data for %s (%s)", code, name)
                continue

            # Convert to row format compatible with build_technical_summary
            from marketreview.tools.technical import build_technical_summary
            rows = [{
                "date": r["trade_date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "vol": float(r.get("vol", 0)),
                "amount": float(r.get("amount", 0)),
            } for r in ind_rows_raw]

            tech_summary = build_technical_summary(code, name, rows)
            constituents = self.get_industry_constituents(name, level, trade_date)

            ind_data = self._build_sector_ai_data(
                name, rows, tech_summary, constituents, reason,
            )
            ind_data_json = _json.dumps(ind_data, ensure_ascii=False)

            user_tmpl = self._load_prompt("guide_sector_item")
            user_msg = user_tmpl.format(
                market_data=market_data_json,
                data=ind_data_json,
            )

            sector_tasks.append({
                "label": f"sector/{code}",
                "user_message": user_msg,
                # Store metadata for DB save later
                "_code": code,
                "_name": name,
            })

        log.info("stage=sector_data_prep elapsed=%.1fs tasks=%d",
                 _time.perf_counter() - _t1, len(sector_tasks))

        if not sector_tasks:
            return {"error": "无行业数据可用"}

        # ── 3. Concurrent per-industry guides ──
        from marketreview.llm.concurrent import batch_chat

        def _sector_progress(phase: str, current: int, total: int, label: str):
            if progress_cb is None:
                return
            if phase == "start":
                progress_cb("sector_start", f"正在生成行业导语（共 {total} 个）...")
            elif phase == "progress":
                # label is e.g. "sector/801081.SI" — extract readable name
                short = label.replace("sector/", "")
                progress_cb("sector_progress", f"✅ {short} 导语完成（{current}/{total}）")
            elif phase == "done":
                progress_cb("sector_done", f"行业导语全部完成（{total}/{total}）")

        if progress_cb:
            progress_cb("sector_start", f"正在生成行业导语（共 {len(sector_tasks)} 个）...")

        sector_results = batch_chat(
            llm, sys_prompt, sector_tasks,
            max_workers=4,
            progress_cb=_sector_progress,
            fail_placeholder=FAIL_PLACEHOLDER,
        )

        # Save per-industry guides to DB
        for t in sector_tasks:
            label = t["label"]
            content = sector_results.get(label, FAIL_PLACEHOLDER)
            if content != FAIL_PLACEHOLDER:
                self._dp.cache.save_ai_summary(
                    trade_date, "sector_analysis", label,
                    content, model,
                )
            result[label] = {"content": content, "model": model}

        # ── 4. Sector summary ──
        _t4 = _time.perf_counter()
        if progress_cb:
            progress_cb("sector_summary_start", "正在生成行业总览...")

        # Build ranking text — today's top 5 gainers + losers with 5d/20d
        ranking = self.get_industry_ranking(trade_date, lookback=21)
        top5 = ranking[:5] if ranking else []
        bot5 = ranking[-5:] if ranking and len(ranking) > 5 else []
        # dedup in case total < 10
        top_codes = {r["code"] for r in top5}
        bot5 = [r for r in bot5 if r["code"] not in top_codes]

        def _fmt_pct(val) -> str:
            if val is None:
                return "N/A"
            return f"{val:+.2f}%"

        ranking_lines = []
        ranking_lines.append("【今日涨幅前5】")
        for i, r in enumerate(top5):
            ranking_lines.append(
                f"  {i + 1}. {r['name']} ({r['level']})  "
                f"今日 {_fmt_pct(r['pct_change'])}  "
                f"5日 {_fmt_pct(r.get('pct_5d'))}  "
                f"20日 {_fmt_pct(r.get('pct_20d'))}  "
                f"成交额 {r['amount'] / 1e5:,.0f}亿"
            )
        if bot5:
            ranking_lines.append("【今日跌幅前5】")
            for i, r in enumerate(bot5):
                ranking_lines.append(
                    f"  {i + 1}. {r['name']} ({r['level']})  "
                    f"今日 {_fmt_pct(r['pct_change'])}  "
                    f"5日 {_fmt_pct(r.get('pct_5d'))}  "
                    f"20日 {_fmt_pct(r.get('pct_20d'))}  "
                    f"成交额 {r['amount'] / 1e5:,.0f}亿"
                )

        # Yesterday's ranking
        prev_td = self.get_prev_trading_date(trade_date)
        if prev_td:
            yest_ranking = self.get_industry_ranking(prev_td)
            if yest_ranking:
                yest_top5 = yest_ranking[:5]
                yest_bot5 = yest_ranking[-5:][::-1] if len(yest_ranking) >= 5 else []
                yest_top_codes = {r["code"] for r in yest_top5}
                yest_bot5 = [r for r in yest_bot5 if r["code"] not in yest_top_codes]
                yest_date_display = f"{prev_td[:4]}-{prev_td[4:6]}-{prev_td[6:8]}"
                ranking_lines.append(f"【昨日({yest_date_display})涨幅前5】")
                for i, r in enumerate(yest_top5):
                    ranking_lines.append(
                        f"  {i + 1}. {r['name']} ({r['level']})  "
                        f"涨跌幅 {_fmt_pct(r['pct_change'])}  "
                        f"成交额 {r['amount'] / 1e5:,.0f}亿"
                    )
                if yest_bot5:
                    ranking_lines.append(f"【昨日({yest_date_display})跌幅前5】")
                    for i, r in enumerate(yest_bot5):
                        ranking_lines.append(
                            f"  {i + 1}. {r['name']} ({r['level']})  "
                            f"涨跌幅 {_fmt_pct(r['pct_change'])}  "
                            f"成交额 {r['amount'] / 1e5:,.0f}亿"
                        )

        ranking_text = "\n".join(ranking_lines) if ranking_lines else "无排名数据"

        # Build sector guides text
        guide_texts = []
        for t in sector_tasks:
            guide_key = t["label"]
            guide_content = sector_results.get(guide_key, "")
            if guide_content and guide_content != FAIL_PLACEHOLDER:
                guide_texts.append(f"### {t['_name']}\n{guide_content}")
        guides_blob = "\n\n".join(guide_texts) if guide_texts else "无行业导语"

        try:
            user_tmpl = self._load_prompt("guide_sector_summary")
            summary = llm.chat(sys_prompt, user_tmpl.format(
                market_data=market_data_json,
                ranking=ranking_text,
                sector_guides=guides_blob,
            ))
        except Exception as e:
            import traceback as _tb3
            log.warning("sector_summary LLM call failed: %s\n%s", e, _tb3.format_exc())
            summary = FAIL_PLACEHOLDER

        log.info("stage=sector_summary elapsed=%.1fs",
                 _time.perf_counter() - _t4)

        if summary != FAIL_PLACEHOLDER:
            self._dp.cache.save_ai_summary(
                trade_date, "sector_analysis", "sector_summary",
                summary, model,
            )
        result["sector_summary"] = {"content": summary, "model": model}

        log.info("generate_ai_sector_analysis DONE total=%.1fs model=%s keys=%d",
                 _time.perf_counter() - _t_total_start, model, len(result))
        return result

    # ── AI 功能版本号 ─────────────────────────────────────────────
    # X.Y.Z (语义化，仅用于验证代码是否热更成功)
    #   X — 大板块上线时 +1，Y/Z 归零  （例：市场全景→1，个股追踪→2）
    #   Y — 大板块内新增子版块时 +1，Z 归零 （例：加了市场概览导语、加了指数导语）
    #   Z — 每次本地改完代码、想验证重启是否生效时 +1
    # 打印位置：__init__() + generate_ai_summary() → log.info
    # ──────────────────────────────────────────────────────────────
    _AI_VERSION = "4.4.1"

    def generate_ai_summary(self, trade_date: str, progress_cb=None) -> dict:
        """
        Generate AI guides + summary for market_overview, store in DB, return result.
        Same dict shape as get_ai_summary().

        If all LLM calls fail, returns dict with a single 'error' key.
        Individual guide failures are replaced with a placeholder string.

        progress_cb(phase, label): called at each stage for UI status updates.
            phase: "market_data" | "index_start" | "index_progress" | "index_done" | "summary_start" | "summary_done"
            label: human-readable description of current stage
        """
        import json as _json, sys as _sys, time as _time

        _t_total_start = _time.perf_counter()
        log.info("[AI v%s] generate_ai_summary(%s)", self._AI_VERSION, trade_date)

        llm = self._get_llm()
        model = llm.model_name
        result = {}
        FAIL_PLACEHOLDER = "AI 摘要暂时不可用"
        sys_prompt = self._load_system_prompt()

        # --- 1. Market overview data ---
        if progress_cb:
            progress_cb("market_data", "正在准备市场数据...")
        _t1 = _time.perf_counter()
        overview = self.get_market_overview(trade_date)
        log.info("stage=market_data elapsed=%.1fs", _time.perf_counter() - _t1)
        if overview is None or "error" in overview:
            return {"error": "无法获取市场概览数据"}

        # --- 2. Build market data (shared by index guides + summary) ---
        today = overview["today"]
        yesterday = overview["yesterday"]
        trend = overview["trend"]

        # -- 涨跌结构 --
        t_total = today["up"] + today["flat"] + today["down"]
        breadth_structure = {
            "今日": {
                "上涨": today["up"],
                "平盘": today["flat"],
                "下跌": today["down"],
                "上涨占比": f"{today['up'] / t_total * 100:.1f}%",
                "涨停": today["up_limit"],
                "跌停": today["down_limit"],
            },
        }
        if yesterday:
            y_total = yesterday["up"] + yesterday["flat"] + yesterday["down"]
            breadth_structure["昨日"] = {
                "上涨": yesterday["up"],
                "平盘": yesterday["flat"],
                "下跌": yesterday["down"],
                "上涨占比": f"{yesterday['up'] / y_total * 100:.1f}%",
                "涨停": yesterday["up_limit"],
                "跌停": yesterday["down_limit"],
            }

        # -- 成交额 --
        turnover_data = {
            "今日": f"{today['total_yi']:,.0f}亿",
        }
        if yesterday:
            turnover_data["昨日"] = f"{yesterday['total_yi']:,.0f}亿"

        amounts = [d["total_yi"] for d in trend]
        if len(amounts) >= 5:
            turnover_data["5日均量"] = f"{sum(amounts[-5:]) / 5:,.0f}亿"
        if len(amounts) >= 10:
            turnover_data["10日均量"] = f"{sum(amounts[-10:]) / 10:,.0f}亿"

        turnover_data["近10日每日"] = []
        for d in trend:
            up_n = d.get("up", 0)
            down_n = d.get("down", 0)
            side = "涨多" if up_n >= down_n else "跌多"
            turnover_data["近10日每日"].append({
                "日期": f"{d['date'][4:6]}-{d['date'][6:8]}",
                "成交额": f"{d['total_yi']:,.0f}亿",
                "涨跌": side,
            })

        # -- 3浪3选股 --
        w33 = self.get_wave33_data(chart_days=15, rolling_days=21,
                                    end_date=trade_date)
        wave33_list = []
        if w33["dates"]:
            for i, d in enumerate(w33["dates"]):
                dc = d.replace("-", "")
                wave33_list.append({
                    "日期": f"{dc[4:6]}-{dc[6:8]}",
                    "数量": w33["counts"][i],
                    "20日盈利占比": f"{w33['profit_pcts'][i]}%",
                })

        breadth_data = {
            "涨跌结构": breadth_structure,
            "成交额": turnover_data,
            "3浪3选股_近15日": wave33_list,
        }

        market_data_json = _json.dumps(breadth_data, ensure_ascii=False)

        # --- 3. Prepare index data (fast, local cache reads) ---
        _t2 = _time.perf_counter()
        sh_rows = self._dp.get_daily("000001.SH", end_date=trade_date, lookback_days=360)
        sh_summary = build_technical_summary("000001.SH", "上证指数", sh_rows)
        sh_contrib = self.get_index_contribution("000001.SH", trade_date)
        sh_freq = self.get_industry_frequency("000001.SH", trade_date)
        sh_data_json = _json.dumps(
            self._build_index_ai_data("000001.SH", "上证指数", sh_rows, sh_summary,
                                      contrib=sh_contrib, freq=sh_freq),
            ensure_ascii=False)
        sh_user_tmpl = self._load_prompt("guide_sh_index")
        sh_user_msg = sh_user_tmpl.format(market_data=market_data_json, data=sh_data_json)

        cz_rows = self._dp.get_daily("399006.SZ", end_date=trade_date, lookback_days=360)
        cz_summary = build_technical_summary("399006.SZ", "创业板指", cz_rows)
        cz_contrib = self.get_index_contribution("399006.SZ", trade_date)
        cz_freq = self.get_industry_frequency("399006.SZ", trade_date)
        cz_data_json = _json.dumps(
            self._build_index_ai_data("399006.SZ", "创业板指", cz_rows, cz_summary,
                                      contrib=cz_contrib, freq=cz_freq),
            ensure_ascii=False)
        cz_user_tmpl = self._load_prompt("guide_cz_index")
        cz_user_msg = cz_user_tmpl.format(market_data=market_data_json, data=cz_data_json)

        # --- 4. Guide: SH + CZ index (concurrent LLM calls) ---
        from marketreview.llm.concurrent import batch_chat

        log.info("stage=index_data_prep elapsed=%.1fs", _time.perf_counter() - _t2)

        INDEX_TASKS = [
            {"label": "guide/sh_index", "user_message": sh_user_msg},
            {"label": "guide/cz_index", "user_message": cz_user_msg},
        ]

        def _index_progress(phase: str, current: int, total: int, label: str):
            if progress_cb is None:
                return
            label_map = {"guide/sh_index": "上证指数", "guide/cz_index": "创业板指"}
            if phase == "start":
                progress_cb("index_start", f"正在生成指数总结（共 {total} 个）...")
            elif phase == "progress":
                name = label_map.get(label, label)
                progress_cb("index_progress", f"✅ {name} 总结完成（{current}/{total}）")
            elif phase == "done":
                progress_cb("index_done", f"指数总结全部完成（{total}/{total}）")

        if progress_cb:
            progress_cb("index_start", f"正在生成指数总结（共 2 个）...")
        index_results = batch_chat(
            llm, sys_prompt, INDEX_TASKS,
            max_workers=2,
            progress_cb=_index_progress,
            fail_placeholder=FAIL_PLACEHOLDER,
        )

        guide_sh = index_results["guide/sh_index"]
        guide_cz = index_results["guide/cz_index"]

        if guide_sh != FAIL_PLACEHOLDER:
            self._dp.cache.save_ai_summary(
                trade_date, "market_overview", "guide/sh_index",
                guide_sh, model,
            )
        result["guide/sh_index"] = {"content": guide_sh, "model": model}

        if guide_cz != FAIL_PLACEHOLDER:
            self._dp.cache.save_ai_summary(
                trade_date, "market_overview", "guide/cz_index",
                guide_cz, model,
            )
        result["guide/cz_index"] = {"content": guide_cz, "model": model}

        # --- 5. Summary (market panorama overview, placed at top of page) ---
        _t4 = _time.perf_counter()
        if progress_cb:
            progress_cb("summary_start", "正在生成市场全景总览...")
        try:
            user_tmpl = self._load_prompt("summary")
            summary = llm.chat(sys_prompt, user_tmpl.format(
                market_data=market_data_json,
                guide_sh=guide_sh,
                guide_cz=guide_cz,
            ))
        except Exception as e:
            import traceback as _tb3
            log.warning("summary LLM call failed: %s\n%s", e, _tb3.format_exc())
            summary = FAIL_PLACEHOLDER

        log.info("stage=summary elapsed=%.1fs", _time.perf_counter() - _t4)

        if summary != FAIL_PLACEHOLDER:
            self._dp.cache.save_ai_summary(
                trade_date, "market_overview", "summary",
                summary, model,
            )
        result["summary"] = {"content": summary, "model": model}

        log.info("generate_ai_summary DONE total=%.1fs model=%s keys=%s",
                 _time.perf_counter() - _t_total_start, model,
                 sorted(result.keys()))
        return result

    # ──────────────────────────────────────────────────────────────
    #  战法回测 (Backtest Engine)
    # ──────────────────────────────────────────────────────────────

    def load_backtest_pools(self) -> list[PoolConfig]:
        """Parse config/backtest_pools.txt."""
        return load_pools(self._dp)

    def load_backtest_strategies(self) -> list[StrategyConfig]:
        """Parse config/backtest_strategies.txt."""
        return load_strategies()

    def run_backtest(self, pool: PoolConfig,
                     strategy_cfg: StrategyConfig,
                     seed: int | None = None) -> Report:
        """Create engine, run backtest, return report."""
        engine = BacktestEngine(self._dp, pool, strategy_cfg)
        return engine.run(seed=seed)

    def check_stock_signal(
        self, ts_code: str, name: str,
        trade_date: str, strategy_class: str,
    ) -> dict:
        """Check if a strategy would set a conditional order for a stock.

        Args:
            ts_code: Stock code e.g. "002709.SZ".
            name: Display name e.g. "天赐材料".
            trade_date: YYYYMMDD trade date.
            strategy_class: Registry key e.g. "ma60_breakthrough".

        Returns:
            {
                "has_signal": bool,
                "price_reachable": bool,
                "message": str,
                "error": str | None,
            }
        """
        # ── Ensure strategy registration ──
        import marketreview.backtest.strategies  # noqa: F811 — triggers @register_strategy

        strategy = create_strategy(strategy_class)
        if strategy is None:
            return {
                "has_signal": False, "price_reachable": False,
                "message": f"⚠️ 战法「{strategy_class}」不存在",
                "error": "strategy_not_found",
            }

        # ── Get strategy config for open_chase_cap_pct & volume thresholds ──
        strategies_cfg = self.load_backtest_strategies()
        open_chase_cap_pct = 102.0  # default
        vol_5d_threshold = -10.0
        vol_10d_threshold = -5.0
        position_pct = 20.0
        space_stop_pct = 5.0
        total_capital = 2_500_000
        for sc in strategies_cfg:
            if sc.class_name == strategy_class:
                open_chase_cap_pct = sc.open_chase_cap_pct
                vol_5d_threshold = sc.volume_5d_threshold_pct
                vol_10d_threshold = sc.volume_10d_threshold_pct
                position_pct = sc.position_pct
                space_stop_pct = sc.space_stop_pct
                total_capital = sc.total_capital
                break

        # 注入量能阈值
        if hasattr(strategy, 'VOLUME_5D_THRESHOLD_PCT'):
            strategy.VOLUME_5D_THRESHOLD_PCT = vol_5d_threshold
            strategy.VOLUME_10D_THRESHOLD_PCT = vol_10d_threshold

        # ── Load K-line data ──
        df = self.get_index_data(ts_code, lookback=500, end_date=trade_date)
        if df.empty or len(df) < 2:
            return {
                "has_signal": False, "price_reachable": False,
                "message": f"⚠️ {name}：无足够K线数据",
                "error": "no_data",
            }

        # ── Compute all MAs (matching engine's precompute) ──
        try:
            ma_result = calc_ma(df, [20, 60, 120, 240])
        except Exception:
            return {
                "has_signal": False, "price_reachable": False,
                "message": f"⚠️ {name}：MA计算失败",
                "error": "ma_error",
            }

        # ── Build klines_asc (list[dict] date ASC, with MA columns) ──
        df_dates = df["date"].tolist()
        klines_asc = []
        for i in range(len(df)):
            row = {
                "date": str(df_dates[i]).replace("-", "")[:8],
                "open": safe_float(df["open"].iloc[i]),
                "high": safe_float(df["high"].iloc[i]),
                "low": safe_float(df["low"].iloc[i]),
                "close": safe_float(df["close"].iloc[i]),
                "vol": safe_float(df["vol"].iloc[i]) if "vol" in df.columns else 0.0,
                "amount": safe_float(df["amount"].iloc[i]) if "amount" in df.columns else 0.0,
            }
            for p in [20, 60, 120, 240]:
                ma_key = f"MA{p}"
                vals = ma_result.get(ma_key, [])
                row[ma_key.lower()] = safe_float(vals[i]) if i < len(vals) else 0.0
            klines_asc.append(row)

        # ── Find trade_date index ──
        idx = None
        for i, r in enumerate(klines_asc):
            if r["date"] == trade_date:
                idx = i
                break
        if idx is None:
            return {
                "has_signal": False, "price_reachable": False,
                "message": f"⚠️ {name}：{trade_date} 不在K线数据中",
                "error": "date_not_found",
            }

        today = klines_asc[idx]
        yesterday = klines_asc[idx - 1] if idx >= 1 else {}

        # ── Build DayContext ──
        def _yma(key: str) -> float:
            return safe_float(yesterday.get(key, 0.0))

        ctx = DayContext(
            date=trade_date,
            symbol=ts_code,
            symbol_name=name,
            open=today["open"],
            high=today["high"],
            low=today["low"],
            close=today["close"],
            volume=today["vol"],
            amount=today["amount"],
            ma20=today.get("ma20", 0.0),
            ma20_yesterday=_yma("ma20"),
            ma55=today.get("ma55", 0.0),
            ma55_yesterday=_yma("ma55"),
            ma60=today.get("ma60", 0.0),
            ma60_yesterday=_yma("ma60"),
            ma120=today.get("ma120", 0.0),
            ma120_yesterday=_yma("ma120"),
            ma144=today.get("ma144", 0.0),
            ma144_yesterday=_yma("ma144"),
            ma240=today.get("ma240", 0.0),
            ma240_yesterday=_yma("ma240"),
            kline_history=klines_asc[:idx + 1],
            in_pool_window=True,
            position=None,
        )

        # ── Call check_buy ──
        try:
            buy_sig = strategy.check_buy(ctx)
        except Exception as e:
            return {
                "has_signal": False, "price_reachable": False,
                "message": f"⚠️ {name}：信号检查异常 — {e}",
                "error": "check_buy_error",
            }

        if buy_sig is not None:
            target = buy_sig.price
            open_cap = round(target * open_chase_cap_pct / 100.0, 2)
            today_close = today["close"]
            limit = get_limit_pct(ts_code)
            lower = today_close * (1 - limit)
            upper = today_close * (1 + limit)

            if lower > target or target > upper:
                return {
                    "has_signal": True,
                    "price_reachable": False,
                    "message": (
                        f"⚠️ **{strategy.name}**：目标价 {target:.2f} "
                        f"超出{limit*100:.0f}%涨跌停限制"
                        f"（涨停价 {upper:.2f} / 跌停价 {lower:.2f}），"
                        f"无法设置条件单 — {buy_sig.reason}"
                    ),
                    "error": None,
                }
            else:
                # ── 计算目标仓位 & 止损价 ──
                trade_capital = total_capital * position_pct / 100.0
                raw_shares = trade_capital / target
                shares = max(100, round(raw_shares / 100) * 100)
                stop_price = round(target * (1 - space_stop_pct / 100.0), 2)

                _r = '<span style="color:#e53935;font-weight:bold;">'
                _e = '</span>'
                return {
                    "has_signal": True,
                    "price_reachable": True,
                    "message": (
                        f"✅ **{strategy.name}**：目标价 "
                        f"{_r}{target:.2f}{_e} "
                        f"处设条件单，开盘追价上限 "
                        f"{_r}{open_cap:.2f}{_e}"
                        f" — {buy_sig.reason}\n\n"
                        f"目标仓位 "
                        f"{_r}{shares:,}{_e} 股，"
                        f"{space_stop_pct:.0f}%止损价："
                        f"{_r}{stop_price:.2f}{_e}"
                    ),
                    "error": None,
                }
        else:
            diag = strategy.diagnose_buy(ctx)
            if diag is None:
                diag = "当前状态不符合买入条件"
            return {
                "has_signal": False,
                "price_reachable": False,
                "message": f"📋 **{strategy.name}**：无信号 — {diag}",
                "error": None,
            }
