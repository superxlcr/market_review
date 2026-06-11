import sqlite3
import os
from datetime import datetime, timedelta

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
    }

    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            if self._schema_ok(conn):
                return
            # Schema mismatch — drop everything and recreate
            conn.executescript("DROP TABLE IF EXISTS tushare_cache")
            conn.executescript("DROP TABLE IF EXISTS index_weight_cache")
            conn.executescript("DROP TABLE IF EXISTS stock_industry_cache")
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
