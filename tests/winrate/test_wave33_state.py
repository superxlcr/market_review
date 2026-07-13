"""_wave33_state 测试：按 signal_date 查 21 天 count 序列算趋势状态。"""
from marketreview.data.cache_manager import CacheManager
from marketreview.winrate import scan_engine as SE


def _wave33_row(date, count):
    return {"trade_date": date, "count": count, "profit_count": 0,
            "profit_pct": 0.0, "stock_codes": "[]"}


def test_wave33_state_no_cache_returns_empty():
    """无 cache → 空状态（防御性，门禁已保证就绪）。"""
    res = SE._wave33_state(None, "20240105")
    assert res == {"direction": "", "streak": 0, "label": ""}


def test_wave33_state_insufficient_series_returns_empty(tmp_path):
    """序列不足 2 天 → 空状态。"""
    cm = CacheManager(str(tmp_path / "t.db"))
    cm.upsert_wave33("20240105", 10, 5, 50.0, "[]")   # 仅 1 天
    res = SE._wave33_state(cm, "20240105")
    assert res["direction"] == ""
    assert res["streak"] == 0


def test_wave33_state_confirmed_up(tmp_path):
    """连续 6 天 count 递增 → streak=5 → 确认上升。
    注：compute_trend 的 streak = 相邻递增步数，6 个点 = 5 步 = streak 5。"""
    cm = CacheManager(str(tmp_path / "t.db"))
    for i, d in enumerate(["20240101", "20240102", "20240103", "20240104", "20240105", "20240106"]):
        cm.upsert_wave33(d, 10 + i, 5, 50.0, "[]")
    res = SE._wave33_state(cm, "20240106")
    assert res["direction"] == "up"
    assert res["streak"] >= 5
    assert "确认上升" in res["label"]


def test_wave33_state_flat_when_equal(tmp_path):
    """count 全相等 → flat/盘整。"""
    cm = CacheManager(str(tmp_path / "t.db"))
    for d in ["20240101", "20240102", "20240103"]:
        cm.upsert_wave33(d, 10, 5, 50.0, "[]")
    res = SE._wave33_state(cm, "20240103")
    assert res["direction"] == "flat"
    assert "盘整" in res["label"]
