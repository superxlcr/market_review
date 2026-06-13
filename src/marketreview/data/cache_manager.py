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
            "ts_code", "trade_date", "total_mv",
        },
        "wave33_cache": {
            "trade_date", "count", "profit_count", "profit_pct",
            "stock_codes", "updated_at",
        },
    }

    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            if self._schema_ok(conn):
                return
            # Schema mismatch — drop everything and recreate
            conn.executescript("DROP TABLE IF EXISTS tushare_cache")
            conn.executescript("DROP TABLE IF EXISTS index_weight_cache")
            conn.executescript("DROP TABLE IF EXISTS stock_industry_cache")
            conn.executescript("DROP TABLE IF EXISTS stock_basic_cache")
            conn.executescript("DROP TABLE IF EXISTS daily_basic_cache")
            conn.executescript("DROP TABLE IF EXISTS wave33_cache")
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            conn.commit()

    def _schema_ok(self, conn: sqlite3.Connection) -> bool:
        """Return True if all expected tables exist with the correct columns."""
        for table, expected in self._EXPECTED_COLUMNS.items():
            try:
                info = conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            except Exception:
                return False
            actual = {row[1] for row in info}  # row[1] = column name
            if actual != expected:
                return False
        return True

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

    # ------- daily_basic_cache -------

    def upsert_daily_basic_bulk(self, rows: list[dict]):
        """
        Bulk upsert daily basic rows (market cap).
        Each row: {ts_code, trade_date, total_mv}.
        """
        sql = """
            INSERT OR REPLACE INTO daily_basic_cache
                (ts_code, trade_date, total_mv)
            VALUES (:ts_code, :trade_date, :total_mv)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
            conn.commit()

    def get_daily_basic(self, trade_date: str) -> list[dict]:
        """
        Return all daily_basic rows for a given trade_date.
        Returns [{ts_code, total_mv}, ...].
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT ts_code, total_mv
                   FROM daily_basic_cache
                   WHERE trade_date = ?""",
                [trade_date],
            ).fetchall()
        return [dict(r) for r in rows]

    def daily_basic_has_range(self, start_date: str, end_date: str) -> bool:
        """
        Return True if daily_basic_cache has any data in [start_date, end_date].
        A single date hit implies the whole range was likely fetched.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM daily_basic_cache
                   WHERE trade_date >= ? AND trade_date <= ?
                   LIMIT 1""",
                [start_date, end_date],
            ).fetchone()
        return row is not None

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
