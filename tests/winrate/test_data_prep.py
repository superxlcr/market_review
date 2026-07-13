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
