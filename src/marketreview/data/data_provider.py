"""
DataProvider — unified data layer (v2: raw + adj_factor → qfq).
All daily K-line data is stored as 不复权 (raw) prices with per-date
adj_factor.  Display conversion (raw → qfq) happens at read time.

API surface:
  - ensure_data_loaded(trade_date)  – bulk backfill + daily increment
  - get_daily(code, end_date, n)    – cached K-line (raw, with adj_factor)
  - get_daily_batch(codes, date)    – batch snapshot for contribution
  - raw_to_qfq(df)                  – convert to display prices
"""

import time as _time
import threading
import tushare as ts
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from .cache_manager import CacheManager
from marketreview.log_util import get_logger

log = get_logger(__name__)


# ── constants ──

_PAGE_SIZE = 5000          # Tushare API page limit
_CHUNK_DAYS = 20           # calendar days per date-range chunk (~14 trading days)
                            # Kept small so per-chunk records stay under tushare's
                            # pagination limit (offset >= ~100k fails for most endpoints).
_FETCH_DAYS = 1000         # calendar days to FETCH (~670 trading days)
_CHECK_DAYS = 500          # calendar days to REQUIRE in cache (tighter, leaves headroom)
MAX_PAGES_PER_CHUNK = 30   # safety cap per chunk: ~150k records max
_MAX_FETCH_WORKERS = 4     # concurrent chunk fetchers (tested: 2x+ speedup, no rate-limit)
_DB_FETCH_DAYS = 180       # calendar days for daily_basic fetch (wave33 window: 80td ≈ 110cal)
_BASIC_CHUNK_DAYS = 10    # smaller chunks for daily_basic: its pagination limit is ~100k offset

# Indices tracked by the dashboard (api.daily doesn't return index data,
# so we fetch them via api.index_daily separately).
_TRACKED_INDICES = [
    "000001.SH",   # 上证指数
    "399006.SZ",   # 创业板指
    "000016.SH",   # 上证50
    "000300.SH",   # 沪深300
    "399001.SZ",   # 深证成指
    "399005.SZ",   # 中小板指
]

# Proxy stock used for cache-coverage checks (must be a STOCK that
# api.daily actually returns; 000001.SZ = 平安银行).
_PROXY_CODE = "000001.SZ"

# Industry (sector) data loading — sw_daily paid API.
# Per-industry calls: ~659 rows per industry for 1000 calendar days,
# well within a single API page.  63 display industries × 4 workers.
_INDUSTRY_FETCH_DAYS = 1000     # calendar days to fetch from sw_daily
_INDUSTRY_CHECK_DAYS = 40       # USE window: calendar days to check (≈27td)
_INDUSTRY_MAX_WORKERS = 4       # concurrent industry fetchers
_STOCK_IND_MAX_WORKERS = 1    # single worker to stay under 500/min rate limit (with 0.15s sleep)


class DataProvider:
    """Single entry point for all market data."""

    def __init__(self, tushare_token: str, cache: CacheManager | None = None):
        ts.set_token(tushare_token)
        self._api = ts.pro_api()
        self.cache = cache or CacheManager()

    # ═══════════════════════════════════════════════════════════════
    #  Bulk Data Loading (called from dashboard console)
    # ═══════════════════════════════════════════════════════════════

    def ensure_data_loaded(
        self, end_date: str, progress_cb=None,
        extra_industry_codes: list[str] | None = None,
    ) -> dict:
        """
        Ensure tushare_cache has raw K-line + adj_factor for all stocks.

        Fetches _FETCH_DAYS of history for new/missing ranges, but only
        requires _CHECK_DAYS of coverage to consider cache complete.
        This gives generous MA240 data while avoiding re-fetches when
        switching dates.

        Returns {"status": "ok"|"error", "elapsed": float, "chunks": int}
        """
        end_date = end_date.replace("-", "")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        fetch_start_dt = end_dt - timedelta(days=_FETCH_DAYS)
        fetch_start = fetch_start_dt.strftime("%Y%m%d")
        check_start_dt = end_dt - timedelta(days=_CHECK_DAYS)
        check_start = check_start_dt.strftime("%Y%m%d")
        db_start_dt = end_dt - timedelta(days=_DB_FETCH_DAYS)
        db_start = db_start_dt.strftime("%Y%m%d")

        # ── Determine what date ranges are missing ──
        missing_ranges: list[tuple[str, str]] = []

        proxy_latest = self.cache.get_latest_date(_PROXY_CODE)
        proxy_earliest = self.cache.get_earliest_date(_PROXY_CODE)
        log.info("ensure_data_loaded: end=%s fetch_start=%s check_start=%s "
                 "proxy_latest=%s proxy_earliest=%s",
                 end_date, fetch_start, check_start,
                 proxy_latest, proxy_earliest)

        if proxy_latest:
            proxy_latest_clean = proxy_latest.replace("-", "")
            # Gap at tail (cache behind target date)?
            if proxy_latest_clean < end_date:
                missing_ranges.append((_next_day(proxy_latest_clean), end_date))
        else:
            # No cache at all — full backfill
            missing_ranges.append((fetch_start, end_date))

        if proxy_earliest and proxy_latest:
            proxy_earliest_clean = proxy_earliest.replace("-", "")
            # Gap at head? Use check_start (360d) not fetch_start (500d)
            # so we don't re-fetch just because we're a few days short of 500.
            if proxy_earliest_clean > check_start:
                missing_ranges.append(
                    (fetch_start, _yesterday(proxy_earliest_clean))
                )

        # ── If nothing missing, just verify indices + stock_basic + daily_basic + industry ──
        if not missing_ranges:
            log.info("ensure_data_loaded: cache up to date, verifying indices+industry+coverage")
            idx_missing = self._ensure_indices_loaded(
                fetch_start, end_date, progress_cb
            )
            self._fetch_stock_basic_once()
            db_pages = self._ensure_daily_basic_loaded(
                db_start, end_date, progress_cb
            )
            # Validate coverage even when cache appears up-to-date
            self._validate_coverage(fetch_start, end_date)
            # Industry daily may not be loaded yet on this date
            ind_classify_count, ind_daily_count = self._ensure_industry_daily(
                end_date, progress_cb,
                extra_codes=extra_industry_codes,
            )
            # Stock-to-industry classification (lazy → eager on first run)
            stock_ind_count = self._ensure_stock_industries(progress_cb)
            return {
                "status": "ok", "elapsed": 0.0,
                "chunks": 0, "note": "cache up to date",
                "index_chunks": idx_missing,
                "db_pages": db_pages,
                "ind_classify": ind_classify_count,
                "ind_daily": ind_daily_count,
                "stock_ind": stock_ind_count,
            }

        # ── Fetch each missing range (concurrent across chunks) ──
        t0 = _time.time()

        # Compute total chunks upfront for progress bar
        all_chunks = []
        for fetch_start, fetch_end in missing_ranges:
            all_chunks.extend(_date_chunks(fetch_start, fetch_end, _CHUNK_DAYS))
        total_chunks = len(all_chunks)
        if progress_cb:
            progress_cb("init", 0, total_chunks)

        raw_pages_total = 0
        adj_pages_total = 0
        completed = 0
        t_chunks_start = _time.time()

        if all_chunks:
            with ThreadPoolExecutor(max_workers=_MAX_FETCH_WORKERS) as executor:
                future_map = {
                    executor.submit(self._fetch_chunk, cs, ce): (cs, ce)
                    for cs, ce in all_chunks
                }
                log.info("ensure_data_loaded: dispatching %d chunks across %d workers",
                         len(all_chunks), _MAX_FETCH_WORKERS)
                for future in as_completed(future_map):
                    cs, ce = future_map[future]
                    try:
                        rp, ap = future.result()
                    except Exception as e:
                        log.warning("_fetch_chunk(%s~%s) failed: %s", cs, ce, e)
                        rp, ap = 0, 0
                    raw_pages_total += rp
                    adj_pages_total += ap
                    completed += 1
                    if progress_cb:
                        progress_cb("chunk", completed, total_chunks,
                                    f"{cs}~{ce}")
            t_chunks = _time.time() - t_chunks_start
            log.info("ensure_data_loaded: %d chunks done in %.1fs wall-clock "
                     "(%.0f pages raw + %.0f pages adj, %d workers)",
                     completed, t_chunks, raw_pages_total, adj_pages_total,
                     _MAX_FETCH_WORKERS)

        # ── Load index data ──
        idx_chunks = self._ensure_indices_loaded(fetch_start, end_date, progress_cb)

        # ── Ensure stock_basic list is cached (once, first-run only) ──
        self._fetch_stock_basic_once()

        # ── Load daily_basic (market cap) ──
        db_pages = self._ensure_daily_basic_loaded(
            db_start, end_date, progress_cb
        )

        # ── Validate coverage (catches silent data gaps like missing 0506-0507) ──
        self._validate_coverage(fetch_start, end_date, progress_cb)

        # ── Load industry (sector) daily data ──
        ind_classify_count, ind_daily_count = self._ensure_industry_daily(
            end_date, progress_cb,
            extra_codes=extra_industry_codes,
        )

        # ── Stock-to-industry classification (eager populate on first run) ──
        stock_ind_count = self._ensure_stock_industries(progress_cb)

        if progress_cb:
            progress_cb("done", 0, 0)

        elapsed = _time.time() - t0
        return {
            "status": "ok",
            "elapsed": round(elapsed, 1),
            "chunks": total_chunks,
            "raw_pages": raw_pages_total,
            "adj_pages": adj_pages_total,
            "index_chunks": idx_chunks,
            "db_pages": db_pages,
            "ind_classify": ind_classify_count,
            "ind_daily": ind_daily_count,
            "stock_ind": stock_ind_count,
        }

    _COVERAGE_WARN_THRESHOLD = 0.90    # warn if < 90% stocks covered on a date
    _COVERAGE_MAX_RETRY = 2            # max re-fetch attempts per gapped date

    def _validate_coverage(self, start: str, end: str, progress_cb=None):
        """
        Check that all dates in [start, end] have adequate stock coverage.

        Tushare's daily API can silently return fewer stocks than expected
        (rate limits, server issues, data not yet published).  A single
        missing date breaks path-dependent indicators (SMA, EMA) and
        produces wrong screening results that are very hard to diagnose.

        Logs a warning for each date below threshold.  If gaps are found,
        attempts one re-fetch of the gapped dates.
        """
        date_strs = self.cache.get_daily_dates_in_range(start, end)
        if not date_strs:
            return

        total_stocks = self.cache.get_stock_basic_count()
        if total_stocks == 0:
            return  # no stock_basic yet, skip validation

        gaps = []
        for d in date_strs:
            cnt = self.cache.count_daily_date(d)
            ratio = cnt / total_stocks if total_stocks > 0 else 1.0
            if ratio < self._COVERAGE_WARN_THRESHOLD:
                gaps.append((d, cnt, total_stocks))

        if gaps:
            # Log all gaps
            gap_lines = "\n".join(
                f"  {d}: {cnt}/{total} stocks ({cnt / total * 100:.1f}%)"
                for d, cnt, total in gaps
            )
            log.warning("COVERAGE GAP DETECTED (%d dates):\n%s", len(gaps), gap_lines)

            if progress_cb:
                progress_cb("validate", 0, 0, f"发现 {len(gaps)} 天数据不完整，补拉中...")

            # Attempt one re-fetch for gapped dates
            for attempt in range(1, self._COVERAGE_MAX_RETRY + 1):
                still_gapped = []
                for d, cnt, total in gaps:
                    new_cnt = self.cache.count_daily_date(d)
                    if new_cnt / total < self._COVERAGE_WARN_THRESHOLD:
                        still_gapped.append(d)

                if not still_gapped:
                    log.info("Coverage restored after re-fetch")
                    return

                log.warning(
                    "Re-fetching %d gapped dates (attempt %d/%d)...",
                    len(still_gapped), attempt, self._COVERAGE_MAX_RETRY,
                )
                # Split into _CHUNK_DAYS ranges so each API call stays
                # within tushare's pagination limit (offset < ~100k).
                for cs, ce in _date_chunks(
                    still_gapped[0], still_gapped[-1], _CHUNK_DAYS,
                ):
                    self._fetch_chunk(cs, ce)

            # Final check — raise if still gapped
            final_gaps = []
            for d, cnt, total in gaps:
                new_cnt = self.cache.count_daily_date(d)
                if new_cnt / total < self._COVERAGE_WARN_THRESHOLD:
                    final_gaps.append((d, new_cnt, total))

            if final_gaps:
                gap_lines = "\n".join(
                    f"  {d}: {cnt}/{total} stocks ({cnt / total * 100:.1f}%)"
                    for d, cnt, total in final_gaps
                )
                log.error(
                    "PERSISTENT COVERAGE GAP after %d re-fetch attempts:\n%s\n"
                    "These dates may not be trading days, or tushare may not "
                    "have published the data yet.",
                    self._COVERAGE_MAX_RETRY, gap_lines,
                )

    def _fetch_chunk(self, chunk_start: str, chunk_end: str
                     ) -> tuple[int, int]:
        """
        Fetch raw K-line + adj_factor for a single 20-day chunk.

        API calls are thread-safe (each gets its own HTTP request).
        DB writes use WAL mode (set at DB init) — SQLite serializes
        concurrent writers internally via its WAL lock, no Python lock
        needed.

        Returns (raw_pages, adj_pages).
        """
        tid = threading.current_thread().name
        fields = "ts_code,trade_date,open,high,low,close,vol,amount"
        raw_pages = 0
        adj_pages = 0
        t_api = 0.0
        t_db = 0.0
        t_chunk_start = _time.time()

        # ── raw K-line ──
        offset = 0
        while raw_pages < MAX_PAGES_PER_CHUNK:
            t0 = _time.time()
            try:
                df = self._api.daily(
                    start_date=chunk_start, end_date=chunk_end,
                    fields=fields,
                    offset=offset, limit=_PAGE_SIZE,
                )
            except Exception as e:
                log.warning("daily(%s~%s) offset=%d: %s", chunk_start, chunk_end, offset, e)
                break
            t_api += _time.time() - t0

            if df is None or df.empty:
                break

            raw_pages += 1
            rows = _normalize_raw_batch(df)
            t_db0 = _time.time()
            if rows:
                self.cache.upsert_daily_bulk(rows)
            t_db += _time.time() - t_db0

            if len(df) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        # ── adj_factor ──
        offset = 0
        while adj_pages < MAX_PAGES_PER_CHUNK:
            t0 = _time.time()
            try:
                df = self._api.adj_factor(
                    start_date=chunk_start, end_date=chunk_end,
                    offset=offset, limit=_PAGE_SIZE,
                )
            except Exception as e:
                log.warning("adj_factor(%s~%s) offset=%d: %s", chunk_start, chunk_end, offset, e)
                break
            t_api += _time.time() - t0

            if df is None or df.empty:
                break

            adj_pages += 1
            t_db0 = _time.time()
            _upsert_adj_factors(self.cache, df)
            t_db += _time.time() - t_db0

            if len(df) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        t_total = _time.time() - t_chunk_start
        log.info("[%s] chunk %s~%s: pages=%d+%d api=%.1fs db=%.1fs total=%.1fs "
                 "(lock_wait=%.1fs)",
                 tid, chunk_start, chunk_end, raw_pages, adj_pages,
                 t_api, t_db, t_total, max(0, t_total - t_api - t_db))
        return raw_pages, adj_pages

    def _ensure_indices_loaded(
        self, start_date: str, end_date: str, progress_cb=None
    ) -> int:
        """
        Ensure tracked indices have daily data in cache.

        api.daily() only returns stocks, not indices.  We fetch index
        OHLCV via api.index_daily() for each tracked index and upsert
        into the same cache.  Indices have adj_factor=1.0 (no 复权).

        Returns number of index-days fetched.
        """
        pages = 0
        total_indices = len(_TRACKED_INDICES)
        for ii, idx_code in enumerate(_TRACKED_INDICES):
            # Check coverage first
            latest_cached = self.cache.get_latest_date(idx_code)
            if latest_cached and latest_cached.replace("-", "") >= end_date:
                earliest_cached = self.cache.get_earliest_date(idx_code)
                if earliest_cached and earliest_cached.replace("-", "") <= start_date:
                    continue  # this index is fully cached
                # partial — just skip incremental, reload full range

            try:
                df = self._api.index_daily(
                    ts_code=idx_code,
                    start_date=start_date,
                    end_date=end_date,
                    limit=_PAGE_SIZE,
                )
            except Exception as e:
                log.warning("index_daily(%s) failed: %s", idx_code, e)
                continue

            if df is None or df.empty:
                continue

            pages += 1
            rows = _normalize_index_batch(df)
            if rows:
                self.cache.upsert_daily_bulk(rows)

            if progress_cb:
                progress_cb("index", ii + 1, total_indices)

        return pages

    # ═══════════════════════════════════════════════════════════════
    #  Single-code K-line (cache-first, no per-stock API)
    # ═══════════════════════════════════════════════════════════════

    def get_daily(
        self, code: str, end_date: str = None, lookback_days: int = 120
    ) -> list[dict]:
        """
        Return recent daily K-line rows (date DESC) from cache.

        Data is expected to be pre-loaded via ensure_data_loaded().
        If the cache doesn't cover the requested range, returns what's
        available (caller should handle short data gracefully).
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        end_date = end_date.replace("-", "")
        end_dt = datetime.strptime(end_date, "%Y%m%d")

        # Check cache coverage
        latest_cached = self.cache.get_latest_date(code)
        if not latest_cached:
            return []  # no data at all — call ensure_data_loaded first

        latest_clean = latest_cached.replace("-", "")

        # If cache is behind, return what we have (don't do per-stock API)
        effective_end = min(end_date, latest_clean)
        log.debug("get_daily: code=%s requested_end=%s latest_cached=%s effective_end=%s",
                  code, end_date, latest_clean, effective_end)
        cached = self.cache.get_daily(
            code, end=effective_end, limit=lookback_days
        )

        # Verify the first row is close to the effective end date
        if cached:
            first_date = cached[0]["date"].replace("-", "")
            first_dt = datetime.strptime(first_date, "%Y%m%d")
            effective_dt = datetime.strptime(effective_end, "%Y%m%d")
            if (effective_dt - first_dt).days <= 7:
                return cached

        return cached  # return what we have even if stale

    def get_latest_trade_date(self, code: str) -> str | None:
        """Return latest available trading date for a code from cache."""
        return self.cache.get_latest_date(code)

    def check_profit_on_date(self, code: str, trade_date: str) -> bool:
        """
        Check if a stock closed higher than 20 trading days ago on a given date.

        Reads from cache only — data must be pre-loaded.
        Returns True if close_today > close_20d_ago (qfq prices).
        """
        import pandas as pd

        rows = self.cache.get_daily(code, end=trade_date, limit=60)
        if len(rows) < 22:
            return False

        # Build a minimal df sorted date ASC, convert to qfq, check profit
        df = pd.DataFrame(rows)
        if df.empty:
            return False
        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        for col in ["close", "adj_factor"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if len(df) < 21:
            return False

        latest_adj = df["adj_factor"].max()
        if latest_adj <= 0:
            return False

        close_today = float(df["close"].iloc[-1]) * float(df["adj_factor"].iloc[-1]) / latest_adj
        close_20d = float(df["close"].iloc[-21]) * float(df["adj_factor"].iloc[-21]) / latest_adj
        return close_today > close_20d

    # ═══════════════════════════════════════════════════════════════
    #  Batch snapshot (cache-only)
    # ═══════════════════════════════════════════════════════════════

    def get_daily_batch(self, codes: list[str],
                         end_date: str) -> dict[str, dict]:
        """
        Return {ts_code: {close, pre_close, change_pct}} for a batch of
        stocks on a single day.

        Reads from cache only — data must be pre-loaded.
        pre_close is computed as: prev_close × adj_factor[prev] / adj_factor[today].
        This correctly handles ex-rights dates where adj_factor jumps.
        """
        end_date = end_date.replace("-", "")
        result = {}

        for code in codes:
            rows = self.cache.get_daily(code, end=end_date, limit=2)
            if len(rows) >= 2 and rows[0]["date"] == end_date:
                r = rows[0]
                prev = rows[1]
                close = float(r["close"])
                prev_close = float(prev["close"])
                adj_today = float(r.get("adj_factor", 1.0))
                adj_prev = float(prev.get("adj_factor", 1.0))
                pre = round(prev_close * adj_prev / adj_today, 4) if adj_today > 0 else prev_close
                chg = round((close / pre - 1) * 100, 2) if pre else 0.0
                result[code] = {
                    "close": close,
                    "pre_close": pre,
                    "change_pct": chg,
                }

        return result

    # ═══════════════════════════════════════════════════════════════
    #  Market breadth (cache-first — respects the cache-before-API rule)
    # ═══════════════════════════════════════════════════════════════

    # Minimum number of stocks that must be in cache for a date
    # before we trust the cache over the API (≥ 4000 for a normal trading day).
    _BREADTH_CACHE_MIN_STOCKS = 4000

    def _get_stk_limits(self, trade_date: str) -> dict[str, tuple[float, float]]:
        """Return {ts_code: (up_limit, down_limit)} for a date, caching on first access."""
        if self.cache.has_stk_limits(trade_date):
            result = self.cache.get_stk_limits(trade_date)
            log.info("_get_stk_limits(%s): cache hit, %d stocks", trade_date, len(result))
            return result
        try:
            limits = self._api.stk_limit(trade_date=trade_date)
            if limits is not None and not limits.empty:
                rows = limits.to_dict(orient="records")
                self.cache.upsert_stk_limits(trade_date, rows)
                result = {r["ts_code"]: (r["up_limit"], r["down_limit"]) for r in rows}
                log.info("_get_stk_limits(%s): API ok, cached %d stocks", trade_date, len(result))
                return result
            else:
                log.warning("_get_stk_limits(%s): API returned empty", trade_date)
        except Exception as e:
            log.warning("_get_stk_limits(%s): API failed: %s", trade_date, e)
        return {}

    def get_market_breadth(self, trade_date: str) -> dict | None:
        """
        Fetch single-day market breadth (up/down counts, turnover by exchange).

        Cache-first: reads from local tushare_cache if the date has ≥ 4000 stocks;
        falls back to live API only when cache is incomplete.
        """
        try:
            cnt = self.cache.count_daily_date(trade_date)
            if cnt >= self._BREADTH_CACHE_MIN_STOCKS:
                return self._breadth_from_cache(trade_date)
            # Fallback to live API
            log.info("get_market_breadth(%s): cache has %d stocks (< %d), falling back to API",
                     trade_date, cnt, self._BREADTH_CACHE_MIN_STOCKS)
            return self._breadth_from_api(trade_date)
        except Exception as e:
            log.warning("get_market_breadth failed for %s: %s", trade_date, e)
            return None

    def _breadth_from_cache(self, trade_date: str) -> dict | None:
        """Compute market breadth from local tushare_cache."""
        today_rows = self.cache.get_date_snapshot(trade_date)
        if not today_rows:
            return None

        prev_date = self.cache.get_previous_trade_date(trade_date)
        prev_rows = self.cache.get_date_snapshot(prev_date) if prev_date else []
        prev_map = {r["code"]: r["close"] for r in prev_rows} if prev_rows else {}

        up = down = flat = 0
        total_amount = 0.0
        sh_amount = sz_amount = bj_amount = 0.0

        for r in today_rows:
            code = r["code"]
            close = float(r["close"]) if r["close"] else 0.0
            amount = float(r["amount"]) if r["amount"] else 0.0
            total_amount += amount

            if code.endswith(".SH"):
                sh_amount += amount
            elif code.endswith(".SZ"):
                sz_amount += amount
            elif code.endswith(".BJ"):
                bj_amount += amount

            prev_close = prev_map.get(code)
            if prev_close is None or prev_close == 0:
                flat += 1
            elif close > prev_close:
                up += 1
            elif close < prev_close:
                down += 1
            else:
                flat += 1

        # up_limit / down_limit from stk_limit (cache-first)
        up_limit = down_limit = 0
        limit_map = self._get_stk_limits(trade_date)
        if limit_map:
            for r in today_rows:
                code = r["code"]
                if code in limit_map:
                    close = float(r["close"]) if r["close"] else 0.0
                    ul, dl = limit_map[code]
                    if close == ul:
                        up_limit += 1
                    elif close == dl:
                        down_limit += 1

        return {
            "trade_date": trade_date,
            "up": up, "down": down, "flat": flat,
            "up_limit": up_limit, "down_limit": down_limit,
            "total_yi": round(total_amount / 1e5, 0),
            "sh_yi": round(sh_amount / 1e5, 0),
            "sz_yi": round(sz_amount / 1e5, 0),
            "bj_yi": round(bj_amount / 1e5, 0),
        }

    def _breadth_from_api(self, trade_date: str) -> dict | None:
        """Live API fallback when cache doesn't have enough data for the date."""
        daily = self._api.daily(
            trade_date=trade_date,
            fields="ts_code,close,pre_close,amount",
        )
        if daily is None or daily.empty:
            return None

        up = int(len(daily[daily["close"] > daily["pre_close"]]))
        down = int(len(daily[daily["close"] < daily["pre_close"]]))
        flat = int(len(daily[daily["close"] == daily["pre_close"]]))

        sh = daily[daily["ts_code"].str.endswith(".SH")]
        sz = daily[daily["ts_code"].str.endswith(".SZ")]
        bj = daily[daily["ts_code"].str.endswith(".BJ")]

        total_yi = round(float(daily["amount"].sum()) / 1e5, 0)
        sh_yi = round(float(sh["amount"].sum()) / 1e5, 0) if len(sh) > 0 else 0
        sz_yi = round(float(sz["amount"].sum()) / 1e5, 0) if len(sz) > 0 else 0
        bj_yi = round(float(bj["amount"].sum()) / 1e5, 0) if len(bj) > 0 else 0

        # stk_limit — cache-first, fall back to live API
        limit_map = self._get_stk_limits(trade_date)
        up_limit = down_limit = 0
        if limit_map:
            for _, row in daily.iterrows():
                code = row["ts_code"]
                if code in limit_map:
                    ul, dl = limit_map[code]
                    if row["close"] == ul:
                        up_limit += 1
                    elif row["close"] == dl:
                        down_limit += 1

        return {
            "trade_date": trade_date,
            "up": up, "down": down, "flat": flat,
            "up_limit": up_limit, "down_limit": down_limit,
            "total_yi": total_yi,
            "sh_yi": sh_yi, "sz_yi": sz_yi, "bj_yi": bj_yi,
        }

    # ═══════════════════════════════════════════════════════════════
    #  Index weights
    # ═══════════════════════════════════════════════════════════════

    def get_index_weights(self, index_code: str,
                           trade_date: str) -> list[dict] | None:
        """Return constituent weights for an index as of trade_date."""
        trade_date = trade_date.replace("-", "")
        td = datetime.strptime(trade_date, "%Y%m%d")

        prior_month = (td.replace(day=1) - timedelta(days=1))
        expected_ym = prior_month.strftime("%Y%m")

        cached_wd = self.cache.get_latest_weight_date(index_code, trade_date)
        if cached_wd and cached_wd[:6] >= expected_ym:
            return self.cache.get_index_weights(index_code, cached_wd)

        query_dt = prior_month
        df = None
        for offset in range(7):
            qd = (query_dt - timedelta(days=offset)).strftime("%Y%m%d")
            try:
                df = self._api.index_weight(
                    index_code=self._normalize_code(index_code),
                    trade_date=qd,
                )
            except Exception as e:
                log.warning("index_weight failed for %s @ %s: %s", index_code, qd, e)
                return None
            if df is not None and not df.empty:
                break

        if df is None or df.empty:
            return None

        weight_date = str(df["trade_date"].iloc[0])
        if cached_wd == weight_date:
            return self.cache.get_index_weights(index_code, weight_date)

        rows = [
            {"con_code": r["con_code"], "weight": float(r["weight"])}
            for _, r in df.iterrows()
        ]
        self.cache.upsert_index_weights(index_code, weight_date, rows)
        return self.cache.get_index_weights(index_code, weight_date)

    # ═══════════════════════════════════════════════════════════════
    #  Stock industries
    # ═══════════════════════════════════════════════════════════════

    def get_stock_industries(self, codes: list[str]) -> dict[str, dict]:
        """Return Shenwan 3-level industry classification for given codes."""
        if not codes:
            return {}

        cached = self.cache.get_stock_industries(codes)
        missing = [c for c in codes if c not in cached]
        if not missing:
            return cached

        new_rows = []
        for code in missing:
            try:
                df = self._api.index_member_all(ts_code=code, is_new="Y")
                if df is not None and not df.empty:
                    r = df.iloc[0]
                    row = {
                        "ts_code": r["ts_code"],
                        "name": r.get("name", ""),
                        "l1_code": r.get("l1_code", ""),
                        "l1_name": r.get("l1_name", ""),
                        "l2_code": r.get("l2_code", ""),
                        "l2_name": r.get("l2_name", ""),
                        "l3_code": r.get("l3_code", ""),
                        "l3_name": r.get("l3_name", ""),
                    }
                    new_rows.append(row)
                    cached[code] = row
            except Exception as e:
                log.warning("index_member_all failed for %s: %s", code, e)

        if new_rows:
            self.cache.upsert_stock_industries(new_rows)
        return cached

    # ═══════════════════════════════════════════════════════════════
    #  Stock basic (fetched once, cached permanently)
    # ═══════════════════════════════════════════════════════════════

    def _fetch_stock_basic_once(self) -> list[dict]:
        """
        Fetch full A-share stock list from Tushare stock_basic API.
        Caches permanently in stock_basic_cache. Called once on first run.
        Returns the list of dicts.
        """
        existing = self.cache.get_stock_basic()
        if existing:
            return existing

        rows = []
        try:
            df = self._api.stock_basic(
                exchange="", list_status="L",
                fields="ts_code,name,list_date",
            )
            if df is not None and not df.empty:
                for _, r in df.iterrows():
                    code = str(r["ts_code"])
                    if not (code.endswith(".SH") or code.endswith(".SZ")):
                        continue
                    name = str(r.get("name", ""))
                    rows.append({
                        "ts_code": code,
                        "name": name,
                        "list_date": str(r.get("list_date", "")),
                        "is_st": 1 if ("ST" in name.upper() or
                                       "*ST" in name.upper()) else 0,
                    })
        except Exception as e:
            log.warning("stock_basic API failed: %s", e)
            return []

        if rows:
            self.cache.upsert_stock_basic(rows)
        return rows

    def get_stock_list(self, trade_date: str) -> list[dict]:
        """
        Return list of qualifying A-shares for wave33 scanning.
        Filters: non-ST, listed >= ~420 calendar days (~300 trading days).
        Returns [{ts_code, name, list_date}, ...].
        """
        rows = self._fetch_stock_basic_once()
        if not rows:
            return []

        trade_date = trade_date.replace("-", "")
        trade_dt = datetime.strptime(trade_date, "%Y%m%d")

        qualifying = []
        for s in rows:
            if s.get("is_st"):
                continue
            list_date_str = s.get("list_date", "")
            if not list_date_str:
                continue
            try:
                list_dt = datetime.strptime(list_date_str, "%Y%m%d")
            except Exception:
                continue
            if (trade_dt - list_dt).days < 420:
                continue
            qualifying.append(s)

        return qualifying

    # ═══════════════════════════════════════════════════════════════
    #  Daily basic (market cap) — cached with K-line
    # ═══════════════════════════════════════════════════════════════

    def _ensure_daily_basic_loaded(
        self, start_date: str, end_date: str, progress_cb=None,
    ) -> int:
        """
        Fetch daily_basic (market cap) for the date range.
        Called internally by ensure_data_loaded().
        Skips ranges already in cache. Paginates to get all trading days.
        Returns number of API pages fetched.
        """
        pages = 0
        chunks = _date_chunks(start_date, end_date, _BASIC_CHUNK_DAYS)
        total_chunks = len(chunks)
        for ci, (chunk_start, chunk_end) in enumerate(chunks, 1):
            # Skip if already cached
            if self.cache.daily_basic_has_range(chunk_start, chunk_end):
                log.debug("daily_basic(%s~%s): cached, skip", chunk_start, chunk_end)
                continue

            if progress_cb:
                progress_cb("basic", ci, total_chunks,
                            f"{chunk_start[:4]}-{chunk_start[4:6]}-{chunk_start[6:8]}"
                            f"~{chunk_end[:4]}-{chunk_end[4:6]}-{chunk_end[6:8]}")

            log.info("daily_basic(%s~%s): fetching...", chunk_start, chunk_end)
            offset = 0
            chunk_pages = 0
            while pages < MAX_PAGES_PER_CHUNK * len(chunks):
                try:
                    df = self._api.daily_basic(
                        start_date=chunk_start, end_date=chunk_end,
                        fields="ts_code,trade_date,total_mv,circ_mv",
                        offset=offset, limit=_PAGE_SIZE,
                    )
                except Exception as e:
                    log.warning("daily_basic(%s~%s) offset=%d: %s", chunk_start, chunk_end, offset, e)
                    break

                if df is None or df.empty:
                    break

                pages += 1
                chunk_pages += 1
                df = df.copy()
                df["trade_date"] = df["trade_date"].astype(str)
                df["total_mv"] = df["total_mv"].astype(float)
                df["circ_mv"] = df["circ_mv"].astype(float)

                rows = []
                for _, r in df.iterrows():
                    rows.append({
                        "ts_code": r["ts_code"],
                        "trade_date": r["trade_date"],
                        "total_mv": float(r["total_mv"]),
                        "circ_mv": float(r["circ_mv"]),
                    })

                if rows:
                    self.cache.upsert_daily_basic_bulk(rows)

                if len(df) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE

            if chunk_pages > 0:
                log.info("daily_basic(%s~%s): fetched %d pages",
                         chunk_start, chunk_end, chunk_pages)

        return pages

    def get_market_cap(self, trade_date: str) -> dict[str, float]:
        """
        Return {ts_code: total_mv} for all stocks on a given trade_date.
        Reads from cache only — data must be pre-loaded.
        """
        trade_date = trade_date.replace("-", "")
        rows = self.cache.get_daily_basic(trade_date)
        return {r["ts_code"]: float(r["total_mv"])
                for r in rows if r.get("total_mv")}

    def get_circ_mv(self, trade_date: str) -> dict[str, float]:
        """
        Return {ts_code: circ_mv} (流通市值) for all stocks on a given trade_date.
        Used for dynamic index weight calculation — circ_mv reflects actual
        tradable shares, which is closer to what index providers use.
        """
        trade_date = trade_date.replace("-", "")
        rows = self.cache.get_daily_basic(trade_date)
        return {r["ts_code"]: float(r["circ_mv"])
                for r in rows if r.get("circ_mv")}

    # ═══════════════════════════════════════════════════════════════
    #  Industry (sector) daily — sw_daily paid API
    # ═══════════════════════════════════════════════════════════════

    def _ensure_industry_classify(self) -> int:
        """
        Lazy-init: fetch L1/L2/L3 industry classifications from
        index_classify API, cache to industry_classify table.

        Called once on first use.  Returns total row count cached.
        """
        if self.cache.has_industry_classify():
            log.info("_ensure_industry_classify: already cached, skip")
            return 0

        rows = []
        for level in ("L1", "L2", "L3"):
            try:
                df = self._api.index_classify(level=level, src="SW2021")
            except Exception as e:
                log.warning("index_classify(level=%s) failed: %s", level, e)
                continue

            if df is None or df.empty:
                log.warning("index_classify(level=%s): empty response", level)
                continue

            for _, r in df.iterrows():
                rows.append({
                    "index_code": str(r["index_code"]),
                    "industry_name": str(r.get("industry_name", "")),
                    "level": level,
                    "industry_code": str(r.get("industry_code", "")),
                    "parent_code": str(r.get("parent_code", "0")),
                    "src": str(r.get("src", "SW2021")),
                })

        if rows:
            self.cache.upsert_industry_classify(rows)

        log.info("_ensure_industry_classify: loaded %d industries (L1+L2+L3)",
                 len(rows))
        return len(rows)

    def _get_display_industry_codes(self) -> list[str]:
        """
        Compute the display industry index_codes using SPLIT_L1/SPLIT_L2
        recursive split rules.  Returns ~63 industry codes.
        """
        from marketreview.tools.industry import SPLIT_L1, SPLIT_L2

        cl_map = self.cache.get_industry_classify_map()
        if not cl_map:
            return []

        # Group by level
        l1_list = [r for r in cl_map.values() if r["level"] == "L1"]
        # Build parent→children maps for L2/L3 (keyed by parent_code)
        l2_by_parent: dict[str, list[dict]] = {}
        l3_by_parent: dict[str, list[dict]] = {}
        for r in cl_map.values():
            if r["level"] == "L2":
                l2_by_parent.setdefault(r["parent_code"], []).append(r)
            elif r["level"] == "L3":
                l3_by_parent.setdefault(r["parent_code"], []).append(r)

        codes = []
        for l1 in l1_list:
            name = l1["industry_name"]
            if name in SPLIT_L1:
                # Replace L1 with all its L2 children
                for l2 in l2_by_parent.get(l1["industry_code"], []):
                    l2_name = l2["industry_name"]
                    if l2_name in SPLIT_L2:
                        # Replace L2 with all its L3 children
                        for l3 in l3_by_parent.get(l2["industry_code"], []):
                            codes.append(l3["index_code"])
                    else:
                        codes.append(l2["index_code"])
            else:
                codes.append(l1["index_code"])

        log.info("_get_display_industry_codes: %d display industries "
                 "(from %d L1)", len(codes), len(l1_list))
        return codes

    def _ensure_industry_daily(self, end_date: str, progress_cb=None,
                               extra_codes: list[str] | None = None
                               ) -> tuple[int, int]:
        """
        Ensure industry_daily table has data for all display industries
        AND any extra_codes (e.g., watchlist industries not in display set).

        Steps:
          1. Lazy-init industry_classify (once)
          2. Compute display industry codes + merge extra_codes
          3. Concurrently fetch sw_daily for each industry that has gaps

        Returns (classify_rows, daily_industries_fetched).
        """
        t0 = _time.time()

        # ── Step 1: lazy-init classifications ──
        if progress_cb:
            progress_cb("ind_classify", 0, 0)
        classify_count = self._ensure_industry_classify()
        if progress_cb:
            progress_cb("ind_classify", classify_count, classify_count)

        # ── Step 2: compute display codes + merge extra ──
        codes = list(self._get_display_industry_codes())
        if extra_codes:
            existing = set(codes)
            for ec in extra_codes:
                if ec not in existing:
                    codes.append(ec)
                    existing.add(ec)
            log.info("_ensure_industry_daily: merged %d extra codes, total %d",
                     len(extra_codes), len(codes))
        if not codes:
            log.warning("_ensure_industry_daily: no display codes — skip")
            return classify_count, 0

        # Determine fetch range
        end_date = end_date.replace("-", "")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        fetch_start = (end_dt - timedelta(days=_INDUSTRY_FETCH_DAYS)
                       ).strftime("%Y%m%d")

        # ── Step 3: find industries that need data ──
        to_fetch: list[str] = []
        already_ok = 0
        for code in codes:
            latest = self.cache.get_latest_industry_date(code)
            if latest and latest >= end_date:
                earliest = self.cache.get_earliest_industry_date(code)
                if earliest and earliest <= fetch_start:
                    already_ok += 1
                    continue
            to_fetch.append(code)

        log.info("_ensure_industry_daily: end=%s fetch_start=%s "
                 "%d/%d industries need fetch",
                 end_date, fetch_start, len(to_fetch), len(codes))

        if not to_fetch:
            elapsed = _time.time() - t0
            log.info("_ensure_industry_daily: all %d industries up to date (%.1fs)",
                     already_ok, elapsed)
            return classify_count, 0

        # ── Step 4: concurrent fetch ──
        total = len(to_fetch)
        completed = 0
        failed = 0
        t_chunks_start = _time.time()

        def _fetch_one(code: str) -> tuple[str, int, str]:
            tid = threading.current_thread().name
            t1 = _time.time()
            rows = 0
            try:
                df = self._api.sw_daily(
                    ts_code=code,
                    start_date=fetch_start,
                    end_date=end_date,
                    limit=_PAGE_SIZE,
                )
                if df is not None and not df.empty:
                    df = df.copy()
                    df["trade_date"] = df["trade_date"].astype(str)
                    batch = []
                    for _, r in df.iterrows():
                        batch.append({
                            "industry_code": str(r["ts_code"]),
                            "trade_date": str(r["trade_date"]),
                            "open": float(r.get("open", 0) or 0),
                            "high": float(r.get("high", 0) or 0),
                            "low": float(r.get("low", 0) or 0),
                            "close": float(r.get("close", 0) or 0),
                            "vol": float(r.get("vol", 0) or 0),
                            "amount": float(r.get("amount", 0) or 0),
                            "pct_change": float(r.get("pct_change", 0) or 0),
                        })
                    if batch:
                        self.cache.upsert_industry_daily_bulk(batch)
                        rows = len(batch)
            except Exception as e:
                log.warning("[%s] sw_daily(%s) failed: %s", tid, code, e)
                return code, -1, str(e)

            elapsed = _time.time() - t1
            return code, rows, f"{elapsed:.1f}s"

        if progress_cb:
            progress_cb("ind_daily", 0, total)

        with ThreadPoolExecutor(max_workers=_INDUSTRY_MAX_WORKERS) as executor:
            future_map = {
                executor.submit(_fetch_one, code): code
                for code in to_fetch
            }
            log.info("_ensure_industry_daily: dispatching %d industries "
                     "across %d workers", total, _INDUSTRY_MAX_WORKERS)

            for future in as_completed(future_map):
                code = future_map[future]
                try:
                    code_out, nrows, info = future.result()
                except Exception as e:
                    log.warning("_ensure_industry_daily future(%s) error: %s", code, e)
                    failed += 1
                else:
                    if nrows < 0:
                        failed += 1
                    else:
                        completed += 1
                    if nrows > 0:
                        log.info("sw_daily(%s): %d rows in %s",
                                 code, nrows, info)

                if progress_cb:
                    progress_cb("ind_daily", completed + failed, total,
                                f"{completed}/{total} 行业已拉取")

        t_chunks = _time.time() - t_chunks_start
        elapsed = _time.time() - t0

        log.info("_ensure_industry_daily: %d/%d industries fetched (%d failed) "
                 "in %.1fs wall-clock (total %.1fs)",
                 completed, total, failed, t_chunks, elapsed)

        return classify_count, completed

    def _ensure_stock_industries(self, progress_cb=None) -> int:
        """
        Ensure stock_industry_cache has SW industry classification
        (L1/L2/L3) for every stock in stock_basic_cache.

        First run populates ~5000 stocks (one index_member_all call each);
        subsequent runs only fill in newly listed stocks.

        Returns number of new stock classifications cached.
        """
        t0 = _time.time()

        # ── 1. All stock codes from stock_basic_cache ──
        all_stocks = self.cache.get_stock_basic()
        all_codes = [s["ts_code"] for s in all_stocks]
        if not all_codes:
            log.info("_ensure_stock_industries: no stocks in stock_basic_cache, skip")
            return 0

        # ── 2. Find which are not yet classified ──
        cached = self.cache.get_stock_industries(all_codes)
        missing = [c for c in all_codes if c not in cached]

        total = len(all_codes)
        already = total - len(missing)

        if not missing:
            elapsed = _time.time() - t0
            log.info("_ensure_stock_industries: all %d stocks already "
                     "classified (%.1fs)", total, elapsed)
            return 0

        log.info("_ensure_stock_industries: %d/%d stocks need "
                 "classification (%d already cached)",
                 len(missing), total, already)

        # ── 3. Concurrent fetch ──
        completed = 0
        failed = 0
        new_rows: list[dict] = []

        if progress_cb:
            progress_cb("stock_industry", already, total)

        def _fetch_one(code: str) -> dict | None:
            _time.sleep(0.15)  # throttle: max ~400 calls/min, safely under 500/min limit
            try:
                df = self._api.index_member_all(ts_code=code, is_new="Y")
                if df is not None and not df.empty:
                    r = df.iloc[0]
                    return {
                        "ts_code": str(r["ts_code"]),
                        "name": str(r.get("name", "")),
                        "l1_code": str(r.get("l1_code", "")),
                        "l1_name": str(r.get("l1_name", "")),
                        "l2_code": str(r.get("l2_code", "")),
                        "l2_name": str(r.get("l2_name", "")),
                        "l3_code": str(r.get("l3_code", "")),
                        "l3_name": str(r.get("l3_name", "")),
                    }
            except Exception as e:
                log.warning("index_member_all(%s) failed: %s", code, e)
            return None

        with ThreadPoolExecutor(max_workers=_STOCK_IND_MAX_WORKERS) as executor:
            future_map = {
                executor.submit(_fetch_one, code): code
                for code in missing
            }
            log.info("_ensure_stock_industries: dispatching %d stocks "
                     "across %d workers", len(missing),
                     _STOCK_IND_MAX_WORKERS)

            for future in as_completed(future_map):
                code = future_map[future]
                try:
                    row = future.result()
                except Exception as e:
                    log.warning("_ensure_stock_industries future(%s) "
                                "error: %s", code, e)
                    failed += 1
                    row = None

                if row:
                    new_rows.append(row)
                    completed += 1
                else:
                    failed += 1

                if progress_cb:
                    progress_cb("stock_industry", already + completed + failed,
                                total)

        # ── 4. Batch upsert ──
        if new_rows:
            self.cache.upsert_stock_industries(new_rows)

        elapsed = _time.time() - t0
        log.info("_ensure_stock_industries: cached %d new stocks "
                 "(failed=%d, total=%d) in %.1fs",
                 len(new_rows), failed, total, elapsed)
        return len(new_rows)

    def get_industry_daily(self, industry_code: str,
                           end_date: str = None,
                           lookback: int = 240) -> "pd.DataFrame":
        """
        Return industry daily K-line as a DataFrame (date ASC, close/high/low/open/vol/amount).

        Data must be pre-loaded via ensure_data_loaded().
        """
        import pandas as pd
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        end_date = end_date.replace("-", "")

        rows = self.cache.get_industry_daily(
            industry_code, end_date=end_date, lookback=lookback
        )
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        # Ensure numeric
        for col in ["open", "high", "low", "close", "vol", "amount", "pct_change"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.sort_values("trade_date", ascending=True).reset_index(drop=True)

    # ═══════════════════════════════════════════════════════════════
    #  Utility
    # ═══════════════════════════════════════════════════════════════

    def is_trading_day(self, trade_date: str) -> bool:
        """Check if a date is a trading day via Tushare trade_cal API."""
        trade_date = trade_date.replace("-", "")
        try:
            df = self._api.trade_cal(
                exchange="SSE",
                start_date=trade_date,
                end_date=trade_date,
            )
            if df is not None and not df.empty:
                return int(df.iloc[0]["is_open"]) == 1
        except Exception:
            pass
        try:
            dt = datetime.strptime(trade_date, "%Y%m%d")
            return dt.weekday() < 5
        except Exception:
            return False

    @staticmethod
    def raw_to_qfq(df: "pd.DataFrame") -> "pd.DataFrame":
        """
        Convert raw (不复权) OHLCV to qfq (前复权) for display.

        Formula: qfq_price = raw_price × adj_factor(T) / adj_factor(latest)

        Expects columns: open, high, low, close, adj_factor.
        Adds a '_qfq' suffix is NOT used; prices are converted in-place.
        Returns the same DataFrame (mutated).
        """
        if df.empty or "adj_factor" not in df.columns:
            return df

        latest_adj = df["adj_factor"].max()
        if latest_adj <= 0:
            return df

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col].astype(float) * df["adj_factor"] / latest_adj

        return df

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


# ═══════════════════════════════════════════════════════════════
#  Module-private helpers
# ═══════════════════════════════════════════════════════════════

def _normalize_raw_batch(df) -> list[dict]:
    """Convert api.daily() DataFrame to cache-compatible rows."""
    df = df.copy()
    df = df.rename(columns={"ts_code": "code", "trade_date": "date"})
    df["date"] = df["date"].astype(str)
    df["adj_factor"] = 1.0  # placeholder, real values from _upsert_adj_factors
    df["asset_type"] = "stock"
    keep = ["code", "date", "open", "high", "low", "close",
            "vol", "amount", "adj_factor", "asset_type"]
    return df[[c for c in keep if c in df.columns]].to_dict(orient="records")


def _normalize_index_batch(df) -> list[dict]:
    """Convert api.index_daily() DataFrame to cache-compatible rows.

    api.index_daily() returns: ts_code, trade_date, close, open, high,
    low, pre_close, change, pct_chg, vol, amount.
    Indices have adj_factor=1.0 (no 复权).
    """
    df = df.copy()
    df = df.rename(columns={"ts_code": "code", "trade_date": "date"})
    df["date"] = df["date"].astype(str)
    df["adj_factor"] = 1.0
    df["asset_type"] = "index"
    keep = ["code", "date", "open", "high", "low", "close",
            "vol", "amount", "adj_factor", "asset_type"]
    return df[[c for c in keep if c in df.columns]].to_dict(orient="records")


def _upsert_adj_factors(cache: CacheManager, df) -> None:
    """
    Merge adj_factor values from api.adj_factor() into existing cache rows.

    api.adj_factor() returns: ts_code, trade_date, adj_factor.
    We UPDATE existing rows in tushare_cache rather than INSERT,
    because the raw data is already there from api.daily().
    """
    df = df.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    df["adj_factor"] = df["adj_factor"].astype(float)

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "code": r["ts_code"],
            "date": r["trade_date"],
            "adj_factor": float(r["adj_factor"]),
        })

    # Use cache's connection (sets busy_timeout=30s, WAL-ready) so
    # concurrent writers (daily chunks + industry fetch) don't collide.
    with cache._get_conn() as conn:
        conn.executemany(
            """UPDATE tushare_cache
               SET adj_factor = :adj_factor
               WHERE code = :code AND date = :date""",
            rows,
        )
        conn.commit()


def _yesterday(date_str: str) -> str:
    """Return the day before date_str (YYYYMMDD)."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return (dt - timedelta(days=1)).strftime("%Y%m%d")


def _next_day(date_str: str) -> str:
    """Return the day after date_str (YYYYMMDD)."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return (dt + timedelta(days=1)).strftime("%Y%m%d")


def _date_chunks(start: str, end: str, chunk_days: int) -> list[tuple[str, str]]:
    """
    Split [start, end] into overlapping-free chunks of `chunk_days` calendar days.
    Returns list of (chunk_start, chunk_end) YYYYMMDD strings.
    """
    chunks = []
    cur = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    while cur <= end_dt:
        chunk_end = min(cur + timedelta(days=chunk_days), end_dt)
        chunks.append((cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cur = chunk_end + timedelta(days=1)
    return chunks
