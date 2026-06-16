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
from marketreview.log_util import get_logger

log = get_logger(__name__)


class DashboardService:
    """Unified data service for the Streamlit dashboard."""

    def __init__(self, tushare_token: str | None = None):
        token = tushare_token or os.environ.get("TUSHARE_TOKEN", "")
        self._dp = DataProvider(tushare_token=token)
        self._llm_client = None  # lazy init

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

    @staticmethod
    def _load_prompt(name: str) -> str:
        """Load a prompt template from llm/prompts/<name>.md."""
        import os as _os
        prompt_dir = _os.path.join(
            _os.path.dirname(__file__),
            "..", "..", "src", "marketreview", "llm", "prompts",
        )
        filepath = _os.path.join(prompt_dir, f"{name}.md")
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def _get_llm(self):
        """Lazy-init the LLM client."""
        if self._llm_client is None:
            from marketreview.llm import create_llm_client
            self._llm_client = create_llm_client()
        return self._llm_client

    def get_ai_summary(self, trade_date: str) -> dict:
        """
        Read cached AI summaries for a given trade_date.
        Returns dict keyed by guide_key, each value is {content, model, created_at}.
        Returns empty dict if nothing cached.
        """
        rows = self._dp.cache.get_ai_summary(trade_date, "market_overview")
        return {r["guide_key"]: r for r in rows}

    def generate_ai_summary(self, trade_date: str) -> dict:
        """
        Generate AI guides + summary for market_overview, store in DB, return result.
        Same dict shape as get_ai_summary().

        If all LLM calls fail, returns dict with a single 'error' key.
        Individual guide failures are replaced with a placeholder string.
        """
        import json as _json

        llm = self._get_llm()
        model = llm.model_name
        result = {}
        FAIL_PLACEHOLDER = "AI 摘要暂时不可用"

        # --- 1. Market overview data ---
        overview = self.get_market_overview(trade_date)
        if overview is None or "error" in overview:
            return {"error": "无法获取市场概览数据"}

        # --- 2. Guide: market breadth ---
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
        wave33_data = {
            "说明": (
                "全市场主升浪强势股筛选：连续5个交易日同时满足 "
                "KD标准K>80、WR(10)<20、WR(20)<20、RSI(9)>70、市值>100亿。"
                "每日选出的股票取21日滚动并集，代表近期走主升浪的股票池。"
            ),
            "用法": (
                "数量上升=赚钱效应扩散，下降=收缩。"
                "3天连续同方向=初步信号，5天=趋势确立。"
                "20日盈利占比=选出强势股持有20日实际盈利比例。"
            ),
            "近15日数据": [],
        }
        if w33["dates"]:
            for i, d in enumerate(w33["dates"]):
                dc = d.replace("-", "")
                wave33_data["近15日数据"].append({
                    "日期": f"{dc[4:6]}-{dc[6:8]}",
                    "数量": w33["counts"][i],
                    "20日盈利占比": f"{w33['profit_pcts'][i]}%",
                })

        breadth_data = {
            "涨跌结构": breadth_structure,
            "成交额": turnover_data,
            "3浪3选股": wave33_data,
        }

        try:
            prompt = self._load_prompt("guide_market_breadth")
            guide_breadth = llm.chat(
                "", prompt.format(data=_json.dumps(breadth_data, ensure_ascii=False)))
        except Exception as e:
            log.warning("guide_market_breadth LLM call failed: %s", e)
            guide_breadth = FAIL_PLACEHOLDER

        self._dp.cache.save_ai_summary(
            trade_date, "market_overview", "guide/market_breadth",
            guide_breadth, model,
        )
        result["guide/market_breadth"] = {"content": guide_breadth, "model": model}

        # --- 3. Guide: SH index ---
        sh_rows = self._dp.get_daily("000001.SH", end_date=trade_date, lookback_days=360)
        sh_summary = build_technical_summary("000001.SH", "上证指数", sh_rows)

        try:
            prompt = self._load_prompt("guide_sh_index")
            guide_sh = llm.chat("", prompt.format(data=_json.dumps(sh_summary, ensure_ascii=False)))
        except Exception as e:
            log.warning("guide_sh_index LLM call failed: %s", e)
            guide_sh = FAIL_PLACEHOLDER

        self._dp.cache.save_ai_summary(
            trade_date, "market_overview", "guide/sh_index",
            guide_sh, model,
        )
        result["guide/sh_index"] = {"content": guide_sh, "model": model}

        # --- 4. Guide: CZ index ---
        cz_rows = self._dp.get_daily("399006.SZ", end_date=trade_date, lookback_days=360)
        cz_summary = build_technical_summary("399006.SZ", "创业板指", cz_rows)

        try:
            prompt = self._load_prompt("guide_cz_index")
            guide_cz = llm.chat("", prompt.format(data=_json.dumps(cz_summary, ensure_ascii=False)))
        except Exception as e:
            log.warning("guide_cz_index LLM call failed: %s", e)
            guide_cz = FAIL_PLACEHOLDER

        self._dp.cache.save_ai_summary(
            trade_date, "market_overview", "guide/cz_index",
            guide_cz, model,
        )
        result["guide/cz_index"] = {"content": guide_cz, "model": model}

        # --- 5. Summary ---
        try:
            prompt = self._load_prompt("summary")
            summary = llm.chat("", prompt.format(
                guide_breadth=guide_breadth,
                guide_sh=guide_sh,
                guide_cz=guide_cz,
            ))
        except Exception as e:
            log.warning("summary LLM call failed: %s", e)
            summary = FAIL_PLACEHOLDER

        self._dp.cache.save_ai_summary(
            trade_date, "market_overview", "summary",
            summary, model,
        )
        result["summary"] = {"content": summary, "model": model}

        return result
