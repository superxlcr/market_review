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

    def _init_schema(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql = f.read()
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(sql)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------- write / read -------

    def upsert_daily(self, code: str, rows: list[dict]):
        """Batch upsert daily K-line rows. Each row: {date, open, high, low, close, vol, amount, adj_factor}"""
        sql = """
            INSERT OR REPLACE INTO tushare_cache
                (code, date, open, high, low, close, vol, amount, adj_factor)
            VALUES (:code, :date, :open, :high, :low, :close, :vol, :amount, :adj_factor)
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

    def code_has_data(self, code: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tushare_cache WHERE code = ? LIMIT 1", [code]
            ).fetchone()
        return row is not None
