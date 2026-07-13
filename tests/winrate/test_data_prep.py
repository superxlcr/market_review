"""数据准备相关测试：cache 覆盖率查询 + provider check_kline_coverage。"""
import pytest

from marketreview.data.cache_manager import CacheManager


def _row(code, date):
    return {"date": date, "open": 10, "high": 10, "low": 10, "close": 10,
            "vol": 1.0, "amount": 1.0, "adj_factor": 1.0, "asset_type": "stock"}


def test_count_daily_by_date_range(tmp_path):
    cm = CacheManager(str(tmp_path / "t.db"))
    # 两个日期，各塞不同数量的票（upsert_daily(code, rows)）
    cm.upsert_daily("600000.SH", [_row("600000.SH", "20240101"),
                                  _row("600000.SH", "20240102")])
    cm.upsert_daily("600001.SH", [_row("600001.SH", "20240101")])
    cm.upsert_daily("600002.SH", [_row("600002.SH", "20240101")])

    out = cm.count_daily_by_date_range("20240101", "20240102")
    assert out["20240101"] == 3      # 三只票
    assert out["20240102"] == 1      # 一只票
    assert "20240103" not in out     # 无数据日期不出现


def test_count_daily_by_date_range_empty(tmp_path):
    cm = CacheManager(str(tmp_path / "t.db"))
    out = cm.count_daily_by_date_range("20240101", "20240131")
    assert out == {}


from marketreview.data.data_provider import DataProvider


def _make_dp_with_basic(tmp_path, n_basic=10):
    """构造一个不触网的 DataProvider：直接往 stock_basic_cache 塞 N 只票。
    DataProvider.__init__ 会连 tushare，这里用 __new__ 绕过，只挂 cache。"""
    dp = DataProvider.__new__(DataProvider)
    dp.cache = CacheManager(str(tmp_path / "t.db"))
    rows = [{"ts_code": f"60000{i}.SH", "name": f"票{i}", "list_date": "20200101",
             "is_st": 0} for i in range(n_basic)]
    if rows:
        dp.cache.upsert_stock_basic(rows)
    return dp


def test_check_kline_coverage_all_ready(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=10)
    # 20240101 这天 10 只票全有 → 覆盖率 100%
    for i in range(10):
        dp.cache.upsert_daily(f"60000{i}.SH", [_row(f"60000{i}.SH", "20240101")])
    res = dp.check_kline_coverage("20240101", "20240101")
    assert res["ready"] is True
    assert res["total_dates"] == 1
    assert res["covered_dates"] == 1
    assert res["missing_dates"] == []
    assert res["min_ratio"] >= 0.9


def test_check_kline_coverage_missing_date(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=10)
    # 20240101 全有，20240102 完全没数据
    for i in range(10):
        dp.cache.upsert_daily(f"60000{i}.SH", [_row(f"60000{i}.SH", "20240101")])
    res = dp.check_kline_coverage("20240101", "20240102")
    assert res["ready"] is True            # 有数据的那天全覆盖 → ready
    assert res["total_dates"] == 1         # 只有 20240101 有数据
    # 注：完全没数据的日期不出现在 count dict，故不计入 total_dates；
    # 调用方按"期望范围 vs total_dates"判断是否漏拉，coverage 只判有数据日的覆盖率。


def test_check_kline_coverage_partial_date(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=10)
    # 20240101 只塞 3 只（30% < 90%）→ 缺口
    for i in range(3):
        dp.cache.upsert_daily(f"60000{i}.SH", [_row(f"60000{i}.SH", "20240101")])
    res = dp.check_kline_coverage("20240101", "20240101")
    assert res["ready"] is False
    assert res["missing_dates"] == ["20240101"]
    assert res["min_ratio"] < 0.9


def test_check_kline_coverage_no_basic(tmp_path):
    dp = _make_dp_with_basic(tmp_path, n_basic=0)   # stock_basic 空
    res = dp.check_kline_coverage("20240101", "20240101")
    assert res["ready"] is False
    assert res["error"] is not None
