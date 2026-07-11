from marketreview.data.cache_manager import CacheManager


def test_get_daily_basic_for_code(tmp_path):
    db = tmp_path / "t.db"
    cache = CacheManager(str(db))
    cache.upsert_daily_basic_bulk([
        {"ts_code": "600000.SH", "trade_date": "20240102", "total_mv": 2_000_000.0, "circ_mv": 1_800_000.0},
        {"ts_code": "600000.SH", "trade_date": "20240101", "total_mv": 1_000_000.0, "circ_mv": 900_000.0},
        {"ts_code": "000001.SZ", "trade_date": "20240101", "total_mv": 5_000_000.0, "circ_mv": 4_000_000.0},
    ])
    rows = cache.get_daily_basic_for_code("600000.SH")
    assert [r["trade_date"] for r in rows] == ["20240101", "20240102"]  # 升序
    assert rows[0]["total_mv"] == 1_000_000.0
