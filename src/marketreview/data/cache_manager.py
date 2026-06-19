import sqlite3
import os
from datetime import datetime, timedelta

from marketreview.log_util import get_logger

log = get_logger(__name__)

DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
DB_PATH = os.path.join(DB_DIR, "marketreview.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


class CacheManager:
    """SQLite-based cache for daily K-line data."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    # Expected columns per table.  If the actual schema doesn't match, the
    # database is dropped and recreated — no migrations, no ALTER TABLE.
    _EXPECTED_COLUMNS = {
        "tushare_cache": {
            "code", "date", "open", "high", "low", "close",
            "vol", "amount", "adj_factor", "asset_type",
        },
        "index_weight_cache": {
            "index_code", "con_code", "weight_date", "weight",
        },
        "stock_industry_cache": {
            "ts_code", "name",
            "l1_code", "l1_name", "l2_code", "l2_name",
            "l3_code", "l3_name",
        },
        "stock_basic_cache": {
            "ts_code", "name", "list_date", "is_st",
        },
        "daily_basic_cache": {
            "ts_code", "trade_date", "total_mv", "circ_mv",
        },
        "wave33_cache": {
            "trade_date", "count", "profit_count", "profit_pct",
            "stock_codes", "updated_at",
        },
        "index_contribution_cache": {
            "index_code", "trade_date", "top_n",
            "weight_type", "data", "created_at",
        },
        "stk_limit_cache": {
            "ts_code", "trade_date", "up_limit", "down_limit",
        },
        "ai_summary": {
            "trade_date", "summary_type", "guide_key",
            "content", "model", "created_at",
        },
        "industry_member_cache": {
            "industry_code", "con_code",
        },
        "industry_daily": {
            "industry_code", "trade_date",
            "open", "high", "low", "close",
            "amount", "vol",
            "up_count", "down_count", "flat_count", "stock_count",
        },
    }

    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            # Check each table individually — only drop mismatched ones
            any_change = False
            for table, expected in self._EXPECTED_COLUMNS.items():
                if not self._table_exists(conn, table):
                    any_change = True  # new table, will be created
                elif not self._table_schema_ok(conn, table, expected):
                    log.warning("Schema mismatch for %s — dropping and recreating", table)
                    conn.executescript(f"DROP TABLE IF EXISTS {table}")
                    any_change = True
            # Always run schema.sql — all statements use IF NOT EXISTS
            # (idempotent; ensures new indexes are created on existing DBs)
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            conn.commit()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]
        ).fetchone()
        return row is not None

    @staticmethod
    def _table_schema_ok(conn: sqlite3.Connection, table: str,
                         expected: set) -> bool:
        """Return True if table exists with the exact expected columns."""
        try:
            info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        except Exception:
            return False
        actual = {row[1] for row in info}  # row[1] = column name
        return actual == expected

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------- write / read -------

    def upsert_daily(self, code: str, rows: list[dict]):
        """Batch upsert daily K-line rows. Each row: {date, open, high, low, close, vol, amount, adj_factor, pre_close}"""
        sql = """
            INSERT OR REPLACE INTO tushare_cache
                (code, date, open, high, low, close, vol, amount, adj_factor, asset_type)
            VALUES (:code, :date, :open, :high, :low, :close, :vol, :amount, :adj_factor, :asset_type)
        """
        with self._get_conn() as conn:
            for r in rows:
                conn.execute(sql, {"code": code, **r})
            conn.commit()

    def get_daily(self, code: str, start: str = None, end: str = None, limit: int = None) -> list[dict]:
        """Return daily rows ordered by date DESC. If limit given, return most recent N rows."""
        sql = "SELECT * FROM tushare_cache WHERE code = ?"
        params = [code]
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = [dict(r) for r in rows]
        log.debug("get_daily: code=%s end=%s limit=%s → %d rows",
                  code, end, limit, len(result))
        return result

    def get_daily_snapshot(
        self, codes: list[str], date_str: str,
    ) -> list[dict]:
        """Return daily rows for multiple codes on a single date.
        Efficient batch alternative to N × get_daily() for one date.
        Returns rows with keys matching tushare_cache columns.
        """
        if not codes:
            return []
        placeholders = ",".join(["?"] * len(codes))
        sql = (
            f"SELECT * FROM tushare_cache "
            f"WHERE code IN ({placeholders}) AND date = ?"
        )
        with self._get_conn() as conn:
            rows = conn.execute(sql, codes + [date_str]).fetchall()
        return [dict(r) for r in rows]

    def get_latest_date(self, code: str) -> str | None:
        """Return the most recent cached date for a code, or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(date) as d FROM tushare_cache WHERE code = ?", [code]
            ).fetchone()
        return row["d"] if row and row["d"] else None

    def get_earliest_date(self, code: str) -> str | None:
        """Return the earliest cached date for a code, or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MIN(date) as d FROM tushare_cache WHERE code = ?", [code]
            ).fetchone()
        return row["d"] if row and row["d"] else None

    def code_has_data(self, code: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tushare_cache WHERE code = ? LIMIT 1", [code]
            ).fetchone()
        return row is not None

    def count_daily_date(self, date_str: str) -> int:
        """Return number of stocks with daily data for a given date."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT code) FROM tushare_cache WHERE date = ?",
                [date_str],
            ).fetchone()
        return row[0] if row else 0

    def get_daily_dates_in_range(self, start: str, end: str) -> list[str]:
        """Return distinct trade dates in tushare_cache for a range."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT date FROM tushare_cache "
                "WHERE date >= ? AND date <= ? ORDER BY date",
                [start, end],
            ).fetchall()
        return [r[0] for r in rows]

    def get_previous_trade_date(self, date_str: str) -> str | None:
        """Return the most recent trade date in cache strictly before date_str."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(date) FROM tushare_cache WHERE date < ?",
                [date_str],
            ).fetchone()
        return row[0] if row and row[0] else None

    def get_date_snapshot(self, date_str: str) -> list[dict]:
        """Return all stock rows for a given date (code, close, amount).
        Only returns rows where asset_type='stock' (excludes indices)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT code, close, amount FROM tushare_cache "
                "WHERE date = ? AND asset_type = 'stock'",
                [date_str],
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stock_basic_count(self) -> int:
        """Return number of stocks in stock_basic_cache."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM stock_basic_cache"
            ).fetchone()
        return row[0] if row else 0

    # ------- index_weight_cache -------

    def upsert_index_weights(self, index_code: str, weight_date: str,
                              rows: list[dict]):
        """
        Batch upsert index weight rows.
        Each row: {con_code, weight}
        weight_date is the official publication date (from API trade_date field).
        """
        sql = """
            INSERT OR REPLACE INTO index_weight_cache
                (index_code, con_code, weight_date, weight)
            VALUES (?, ?, ?, ?)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, [
                (index_code, r["con_code"], weight_date, r["weight"])
                for r in rows
            ])
            conn.commit()

    def get_latest_weight_date(self, index_code: str,
                                trade_date: str) -> str | None:
        """
        Return the latest weight_date <= trade_date for an index.
        Returns None if no cache exists.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT MAX(weight_date) as d FROM index_weight_cache
                   WHERE index_code = ? AND weight_date <= ?""",
                [index_code, trade_date],
            ).fetchone()
        return row["d"] if row and row["d"] else None

    def get_index_weights(self, index_code: str,
                           weight_date: str) -> list[dict]:
        """
        Return all constituent weights for a given index_code + weight_date.
        Returns list of {con_code, weight}.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT con_code, weight FROM index_weight_cache
                   WHERE index_code = ? AND weight_date = ?
                   ORDER BY weight DESC""",
                [index_code, weight_date],
            ).fetchall()
        return [dict(r) for r in rows]

    # ------- stock_industry_cache -------

    def get_stock_industries(self, codes: list[str]) -> dict[str, dict]:
        """
        Return industry info for given ts_codes.
        Returns {ts_code: {name, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name}}.
        Only returns rows that exist in cache — caller must handle misses.
        """
        if not codes:
            return {}
        placeholders = ",".join(["?" for _ in codes])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT ts_code, name, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name
                    FROM stock_industry_cache
                    WHERE ts_code IN ({placeholders})""",
                codes,
            ).fetchall()
        return {r["ts_code"]: dict(r) for r in rows}

    def upsert_stock_industries(self, rows: list[dict]):
        """
        Batch upsert industry rows.
        Each row: {ts_code, name, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name}.
        """
        sql = """
            INSERT OR REPLACE INTO stock_industry_cache
                (ts_code, name, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name)
            VALUES (:ts_code, :name, :l1_code, :l1_name, :l2_code, :l2_name, :l3_code, :l3_name)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()

    # ------- batch daily upsert -------

    def upsert_daily_bulk(self, rows: list[dict]):
        """
        Bulk upsert daily K-line rows from a full-market fetch.
        Each row: {code, date, open, high, low, close, vol, amount, adj_factor, pre_close}.
        Uses executemany for efficiency with large datasets (~5000+ rows).
        """
        sql = """
            INSERT OR REPLACE INTO tushare_cache
                (code, date, open, high, low, close, vol, amount, adj_factor, asset_type)
            VALUES (:code, :date, :open, :high, :low, :close, :vol, :amount, :adj_factor, :asset_type)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()

    # ------- stock_basic_cache -------

    def upsert_stock_basic(self, rows: list[dict]):
        """
        Batch upsert stock basic info.
        Each row: {ts_code, name, list_date, is_st}.
        is_st: 1 = ST/*ST, 0 = normal.
        """
        sql = """
            INSERT OR REPLACE INTO stock_basic_cache
                (ts_code, name, list_date, is_st)
            VALUES (:ts_code, :name, :list_date, :is_st)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()

    def get_stock_basic(self) -> list[dict]:
        """Return all cached stock basic rows."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT ts_code, name, list_date, is_st FROM stock_basic_cache"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stock_basic_count(self) -> int:
        """Return count of cached stocks."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM stock_basic_cache"
            ).fetchone()
        return row["cnt"] if row else 0

    # ------- industry_member_cache -------

    def get_industry_members(self, industry_code: str) -> list[str]:
        """Return list of con_code for an industry. Empty list if not cached."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT con_code FROM industry_member_cache WHERE industry_code = ?",
                [industry_code],
            ).fetchall()
        return [r["con_code"] for r in rows]

    def upsert_industry_members(self, industry_code: str, con_codes: list[str]):
        """Replace all constituent stocks for an industry (DELETE + INSERT batch)."""
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM industry_member_cache WHERE industry_code = ?",
                [industry_code],
            )
            conn.executemany(
                "INSERT OR REPLACE INTO industry_member_cache "
                "(industry_code, con_code) VALUES (?, ?)",
                [(industry_code, c) for c in con_codes],
            )
            conn.commit()

    def has_industry_members(self, industry_code: str) -> bool:
        """Return True if this industry has cached members."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM industry_member_cache "
                "WHERE industry_code = ? LIMIT 1",
                [industry_code],
            ).fetchone()
        return row is not None

    # ------- industry_daily -------

    def get_industry_daily(
        self, industry_code: str,
        end_date: str | None = None,
        lookback: int = 360,
    ) -> list[dict]:
        """Return daily rows for one industry, date DESC, limited to lookback."""
        end_date = (end_date or "").replace("-", "")
        sql = "SELECT * FROM industry_daily WHERE industry_code = ?"
        params: list = [industry_code]
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        sql += " ORDER BY trade_date DESC"
        if lookback:
            sql += " LIMIT ?"
            params.append(lookback)
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def upsert_industry_daily(self, rows: list[dict]):
        """Bulk upsert industry_daily rows."""
        sql = """
            INSERT OR REPLACE INTO industry_daily
                (industry_code, trade_date, open, high, low, close,
                 amount, vol, up_count, down_count, flat_count, stock_count)
            VALUES (:industry_code, :trade_date, :open, :high, :low, :close,
                    :amount, :vol, :up_count, :down_count, :flat_count,
                    :stock_count)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()

    def has_industry_daily(self, industry_code: str, trade_date: str) -> bool:
        """Return True if this industry has daily data for this date."""
        trade_date = trade_date.replace("-", "")
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM industry_daily "
                "WHERE industry_code = ? AND trade_date = ? LIMIT 1",
                [industry_code, trade_date],
            ).fetchone()
        return row is not None

    def get_industry_daily_dates_in_range(
        self, industry_code: str, start: str, end: str,
    ) -> list[str]:
        """Return distinct trade dates in industry_daily for a range."""
        start = start.replace("-", "")
        end = end.replace("-", "")
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT trade_date FROM industry_daily "
                "WHERE industry_code = ? AND trade_date >= ? "
                "AND trade_date <= ? ORDER BY trade_date",
                [industry_code, start, end],
            ).fetchall()
        return [r[0] for r in rows]

    def count_industry_daily_date(self, trade_date: str) -> int:
        """Return number of industries with daily data for a given date."""
        trade_date = trade_date.replace("-", "")
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT industry_code) FROM industry_daily "
                "WHERE trade_date = ?",
                [trade_date],
            ).fetchone()
        return row[0] if row else 0

    # ------- daily_basic_cache -------

    def upsert_daily_basic_bulk(self, rows: list[dict]):
        """
        Bulk upsert daily basic rows (market cap).
        Each row: {ts_code, trade_date, total_mv, circ_mv}.
        """
        sql = """
            INSERT OR REPLACE INTO daily_basic_cache
                (ts_code, trade_date, total_mv, circ_mv)
            VALUES (:ts_code, :trade_date, :total_mv, :circ_mv)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()

    def get_daily_basic(self, trade_date: str) -> list[dict]:
        """
        Return all daily_basic rows for a given trade_date.
        Returns [{ts_code, total_mv, circ_mv}, ...].
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT ts_code, total_mv, circ_mv
                   FROM daily_basic_cache
                   WHERE trade_date = ?""",
                [trade_date],
            ).fetchall()
        return [dict(r) for r in rows]

    def daily_basic_has_range(self, start_date: str, end_date: str) -> bool:
        """
        Return True if daily_basic_cache has COMPLETE data in [start_date, end_date].

        Checks both existence AND count consistency: if any date in the range has
        < 90% of the max count for the range, the chunk is treated as incomplete
        so it will be re-fetched.  This auto-heals gaps caused by tushare
        pagination limits (offset >= 105000 fails for daily_basic).

        Also checks the boundary — dates with zero rows don't appear in GROUP BY
        above, so an explicit check guards against silent gaps at the edges.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT COUNT(*) FROM daily_basic_cache
                   WHERE trade_date >= ? AND trade_date <= ?
                   GROUP BY trade_date""",
                [start_date, end_date],
            ).fetchall()
        if not rows:
            return False
        counts = [r[0] for r in rows]
        max_cnt = max(counts)
        # All existing dates must be ≥ 90% of max
        if not all(c >= max_cnt * 0.9 for c in counts):
            return False
        # Boundary check: end_date must have rows (dates without rows are
        # invisible in GROUP BY).  This may cause a redundant fetch when
        # end_date falls on a weekend, but that is far cheaper than silently
        # skipping missing data on an actual trading day.
        if self.count_daily_basic_date(end_date) == 0:
            return False
        return True

    def count_daily_basic_date(self, date_str: str) -> int:
        """Return number of stocks with daily_basic data for a given date."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM daily_basic_cache WHERE trade_date = ?",
                [date_str],
            ).fetchone()
        return row[0] if row else 0

    def get_daily_basic_dates_in_range(self, start: str, end: str) -> list[str]:
        """Return distinct trade dates in daily_basic_cache for a range."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT trade_date FROM daily_basic_cache "
                "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
                [start, end],
            ).fetchall()
        return [r[0] for r in rows]

    # ------- wave33_cache -------

    def upsert_wave33(self, trade_date: str, count: int,
                       profit_count: int, profit_pct: float,
                       stock_codes: str):
        """Insert or replace one wave33 daily result."""
        sql = """
            INSERT OR REPLACE INTO wave33_cache
                (trade_date, count, profit_count, profit_pct, stock_codes, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """
        with self._get_conn() as conn:
            conn.execute(sql, [trade_date, count, profit_count,
                               profit_pct, stock_codes])
            conn.commit()
        log.info("upsert_wave33: date=%s count=%s profit=%s", trade_date, count, profit_count)

    def get_wave33_range(self, limit: int = 15, end_date: str | None = None) -> list[dict]:
        """
        Return last N rows from wave33_cache (trade_date DESC), filtered to
        trade_date <= end_date.  When end_date is None, defaults to today.
        Returns [{trade_date, count, profit_count, profit_pct, stock_codes}, ...].
        """
        from datetime import datetime
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trade_date, count, profit_count, profit_pct, stock_codes
                   FROM wave33_cache
                   WHERE trade_date <= ?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                [end_date, limit],
            ).fetchall()
        result = [dict(r) for r in rows]
        log.info("get_wave33_range: end_date=%s limit=%s → %d rows",
                 end_date, limit, len(result))
        return result

    def has_wave33_date(self, trade_date: str) -> bool:
        """Return True if wave33_cache has this date."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM wave33_cache WHERE trade_date = ?",
                [trade_date],
            ).fetchone()
        return row is not None

    def get_wave33_row(self, trade_date: str) -> dict | None:
        """Read a single wave33_cache row by trade_date. Returns dict or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT trade_date, count, profit_count, profit_pct, stock_codes
                   FROM wave33_cache WHERE trade_date = ?""",
                [trade_date],
            ).fetchone()
        return dict(row) if row else None

    def update_wave33_stock_codes(self, trade_date: str, stock_codes: str):
        """Update only the stock_codes JSON blob for an existing wave33 row."""
        sql = """UPDATE wave33_cache SET stock_codes = ?,
                    updated_at = datetime('now') WHERE trade_date = ?"""
        with self._get_conn() as conn:
            conn.execute(sql, [stock_codes, trade_date])
            conn.commit()

    # ------- index_contribution_cache -------

    def get_index_contribution_cache(self, index_code: str, trade_date: str,
                                      top_n: int = 10) -> dict | None:
        """Return cached contribution JSON, or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT data FROM index_contribution_cache "
                "WHERE index_code = ? AND trade_date = ? AND top_n = ?",
                (index_code, trade_date, top_n),
            ).fetchone()
        if row:
            import json as _json
            return _json.loads(row["data"])
        return None

    def upsert_index_contribution_cache(self, index_code: str,
                                         trade_date: str, top_n: int,
                                         weight_type: str, data: dict):
        """Insert or replace a cached contribution result."""
        import json as _json
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO index_contribution_cache "
                "(index_code, trade_date, top_n, weight_type, data, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (index_code, trade_date, top_n, weight_type,
                 _json.dumps(data, ensure_ascii=False)),
            )
            conn.commit()

    # ------- stk_limit_cache -------

    def upsert_stk_limits(self, trade_date: str, rows: list[dict]):
        """Insert or replace stk_limit rows for a single trade_date."""
        sql = """INSERT OR REPLACE INTO stk_limit_cache
                 (ts_code, trade_date, up_limit, down_limit)
                 VALUES (:ts_code, :trade_date, :up_limit, :down_limit)"""
        with self._get_conn() as conn:
            conn.executemany(sql, [
                {
                    "ts_code": r["ts_code"],
                    "trade_date": trade_date,
                    "up_limit": float(r["up_limit"]),
                    "down_limit": float(r["down_limit"]),
                }
                for r in rows
            ])
            conn.commit()

    def has_stk_limits(self, trade_date: str) -> bool:
        """Return True if stk_limit_cache has this date."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM stk_limit_cache WHERE trade_date = ? LIMIT 1",
                [trade_date],
            ).fetchone()
        return row is not None

    def get_stk_limits(self, trade_date: str) -> dict[str, tuple[float, float]]:
        """Return {ts_code: (up_limit, down_limit)} for a trade_date."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT ts_code, up_limit, down_limit FROM stk_limit_cache "
                "WHERE trade_date = ?",
                [trade_date],
            ).fetchall()
        return {r["ts_code"]: (r["up_limit"], r["down_limit"]) for r in rows}

    # ------- ai_summary -------

    def get_ai_summary(self, trade_date: str, summary_type: str) -> list[dict]:
        """Get all AI summary rows for a given date and type.
        Returns list of dicts with keys: guide_key, content, model, created_at.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT guide_key, content, model, created_at "
                "FROM ai_summary WHERE trade_date = ? AND summary_type = ?",
                (trade_date, summary_type),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_ai_summary(self, trade_date: str, summary_type: str,
                        guide_key: str, content: str, model: str = ""):
        """Insert or replace one AI summary row."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ai_summary "
                "(trade_date, summary_type, guide_key, content, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (trade_date, summary_type, guide_key, content, model),
            )
            conn.commit()
