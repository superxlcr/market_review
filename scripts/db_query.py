"""
db_query.py — Query the project SQLite database (data/marketreview.db).

Usage:
    .venv/Scripts/python scripts/db_query.py "SELECT * FROM tushare_cache WHERE code='002709.SZ' ORDER BY date DESC LIMIT 5"
    .venv/Scripts/python scripts/db_query.py --tables                   # list all tables
    .venv/Scripts/python scripts/db_query.py --schema tushare_cache     # show table schema
    .venv/Scripts/python scripts/db_query.py --code 002709.SZ --days 5  # recent K-line for a stock
    .venv/Scripts/python scripts/db_query.py --code 002709.SZ --buy     # check buy_points.log
    echo "SELECT COUNT(*) FROM tushare_cache" | .venv/Scripts/python scripts/db_query.py  # read SQL from stdin

Output: formatted table (default) or JSON (--json).
"""

import sqlite3
import os
import sys
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "marketreview.db")


def get_connection():
    """Return a read-only connection + list of table names."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables():
    conn = get_connection()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()
    return [r["name"] for r in rows]


def table_schema(table_name: str):
    conn = get_connection()
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    conn.close()
    return rows


def run_query(sql: str):
    conn = get_connection()
    rows = conn.execute(sql).fetchall()
    conn.close()
    return rows


def format_table(rows) -> str:
    """Format rows as aligned text table."""
    if not rows:
        return "(empty)"
    keys = rows[0].keys()
    # Calculate column widths
    widths = {k: len(k) for k in keys}
    for r in rows:
        for k in keys:
            val = str(r[k]) if r[k] is not None else "NULL"
            widths[k] = max(widths[k], min(len(val), 60))
    # Header
    header = " | ".join(f"{k:<{widths[k]}}" for k in keys)
    sep = "-+-".join("-" * widths[k] for k in keys)
    lines = [header, sep]
    # Data rows
    for r in rows:
        line = " | ".join(
            f"{str(r[k]) if r[k] is not None else 'NULL':<{widths[k]}}"[:
            widths[k] + 5] for k in keys
        )
        lines.append(line)
    return "\n".join(lines)


def recent_kline(code: str, days: int = 5):
    """Quick lookup: recent K-line for a stock/index."""
    rows = run_query(
        f"SELECT code, date, open, high, low, close, vol, amount "
        f"FROM tushare_cache WHERE code='{code}' "
        f"ORDER BY date DESC LIMIT {days}"
    )
    # Reverse to ASC order for display
    rows_list = list(rows)
    rows_list.reverse()
    # Build fake Row objects for format_table
    class FakeRow:
        def __init__(self, d):
            self._d = d
        def keys(self):
            return self._d.keys()
        def __getitem__(self, k):
            return self._d[k]
    return [FakeRow(dict(r)) for r in rows_list]


def check_buy_points_log(code: str):
    """Tail the buy_points.log for a specific stock."""
    log_path = os.path.join(PROJECT_ROOT, "logs", "buy_points.log")
    if not os.path.exists(log_path):
        return f"(no log file at {log_path})"
    lines = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if code in line:
                lines.append(line.rstrip())
    if not lines:
        return f"(no lines for {code})"
    return "\n".join(lines[-20:])  # last 20 lines


def main():
    parser = argparse.ArgumentParser(description="Query marketreview.db")
    parser.add_argument("sql", nargs="?", help="SQL query string")
    parser.add_argument("--tables", action="store_true", help="List all tables")
    parser.add_argument("--schema", metavar="TABLE", help="Show table schema")
    parser.add_argument("--code", metavar="CODE", help="Quick stock/index lookup")
    parser.add_argument("--days", type=int, default=5, help="Days for --code lookup")
    parser.add_argument("--buy", action="store_true", help="Check buy_points.log for --code")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # ── Special modes ──
    if args.tables:
        tables = list_tables()
        print(f"Tables in {DB_PATH}:")
        for t in tables:
            print(f"  {t}")
        return

    if args.schema:
        rows = table_schema(args.schema)
        print(f"Schema for {args.schema}:")
        for r in rows:
            print(f"  {r['name']:<20} {r['type']:<15} "
                  f"{'NOT NULL' if r['notnull'] else '':<10} "
                  f"{'PK' if r['pk'] else ''}")
        return

    if args.code:
        if args.buy:
            print(check_buy_points_log(args.code))
            return
        rows = recent_kline(args.code, args.days)
        print(format_table(rows))
        return

    # ── SQL query mode ──
    sql = args.sql
    if not sql:
        # Read from stdin
        if sys.stdin.isatty():
            print("Usage: db_query.py 'SELECT ...'  or  echo 'SELECT ...' | db_query.py")
            print("       db_query.py --tables")
            print("       db_query.py --schema TABLE")
            print("       db_query.py --code 002709.SZ [--days N] [--buy]")
            sys.exit(1)
        sql = sys.stdin.read().strip()

    if not sql:
        print("(no query)")
        return

    rows = run_query(sql)

    if args.json:
        import json
        result = [dict(r) for r in rows]
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_table(rows))
        print(f"\n({len(rows)} rows)")


if __name__ == "__main__":
    main()
