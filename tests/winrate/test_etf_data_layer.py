import pandas as pd
from unittest.mock import MagicMock
from marketreview.data.cache_manager import CacheManager


def test_csi_pool_table_roundtrip(tmp_path):
    cm = CacheManager(db_path=str(tmp_path / "t.db"))
    assert cm.has_csi_pool() is False
    cm.upsert_csi_pool([
        {"ts_code": "931152.CSI", "name": "CS创新药", "category": "主题指数", "list_date": "20190422"},
        {"ts_code": "H30199.CSI", "name": "电力指数", "category": "行业指数", "list_date": "20130715"},
    ])
    assert cm.has_csi_pool() is True
    rows = cm.get_csi_pool()
    assert len(rows) == 2
    codes = {r["ts_code"] for r in rows}
    assert "931152.CSI" in codes
    assert "H30199.CSI" in codes


def test_csi_pool_clear(tmp_path):
    cm = CacheManager(db_path=str(tmp_path / "t.db"))
    cm.upsert_csi_pool([{"ts_code": "931152.CSI", "name": "CS创新药",
                         "category": "主题指数", "list_date": "20190422"}])
    assert cm.has_csi_pool() is True
    cm.clear_csi_pool()
    assert cm.has_csi_pool() is False


def test_ensure_csi_pool_filters_and_caches(tmp_path):
    """ensure_csi_pool 拉 index_basic(CSI) → 6条过滤 → 缓存，幂等。"""
    from marketreview.data.data_provider import DataProvider
    cm = CacheManager(db_path=str(tmp_path / "t.db"))
    dp = DataProvider.__new__(DataProvider)   # 跳过 __init__（不连 tushare）
    dp.cache = cm
    # mock api
    dp._api = MagicMock()
    dp._api.index_basic.return_value = pd.DataFrame([
        {"ts_code": "931152.CSI", "name": "CS创新药", "category": "主题指数", "list_date": "20190422"},
        # 被过滤：债券
        {"ts_code": "000012.CSI", "name": "国债指数", "category": "债券指数", "list_date": "20021231"},
        # 被过滤：全收益
        {"ts_code": "H20539.CSI", "name": "中证白酒全收益", "category": "主题指数", "list_date": "20150508"},
        # 被过滤：币种后缀
        {"ts_code": "931152USD210.CSI", "name": "CS创新药(全)USD", "category": "主题指数", "list_date": "20190422"},
        # 被过滤：三板
        {"ts_code": "899304.CSI", "name": "三板医药", "category": "主题指数", "list_date": "20190114"},
        # 被过滤：H300 港股通
        {"ts_code": "H30329.CSI", "name": "H300休闲", "category": "主题指数", "list_date": "20140521"},
    ])
    n = dp.ensure_csi_pool()
    assert n == 1  # 只剩 CS创新药
    rows = cm.get_csi_pool()
    assert len(rows) == 1
    assert rows[0]["ts_code"] == "931152.CSI"
    # 幂等：再调不重复拉（has_csi_pool=True → 跳过）
    dp._api.index_basic.return_value = pd.DataFrame()
    n2 = dp.ensure_csi_pool()
    assert n2 == 1
