"""扣抵量/5日均量 两个均线支撑变体 + 试验开关（find_all_buy_points 过滤 trial）。"""
import pandas as pd
from marketreview.tools.band_analysis import BandResult
from marketreview.tools import buy_points as BP
from marketreview.tools.buy_points import MAChecker, find_all_buy_points

_TRIAL_TYPES = ("扣抵量均线支撑", "5日均量均线支撑")


def _rising(n=260):
    """单调上升的价与量：MA 向上且在价下方（支撑），量逐日放大
    → 今日量 与 近5日均量 都 > 扣抵量/后续均量 → 触发均线支撑。"""
    closes = [10.0 + i * 0.1 for i in range(n)]
    amounts = [1000.0 + i * 50 for i in range(n)]   # 千元，递增
    return pd.DataFrame({
        "date": [str(20230000 + i) for i in range(n)],
        "open": closes, "high": closes, "low": closes, "close": closes,
        "vol": [1.0] * n, "amount": amounts,
    })


def _band(df):
    b = BandResult()
    b.current_price = float(df["close"].iloc[-1])
    return b


def test_ma_checker_default_is_trial_stage():
    assert MAChecker().STAGE == "trial"
    assert MAChecker().type_name == "扣抵量均线支撑"


def test_today_variant_type_and_reason():
    df = _rising()
    pts = MAChecker(vol_mode="today", type_name="扣抵量均线支撑").check(df, _band(df))
    assert pts, "上升+放量应触发均线支撑"
    assert all(p.type == "扣抵量均线支撑" for p in pts)
    assert all("今日量" in p.reason for p in pts)


def test_avg5_variant_type_and_reason():
    df = _rising()
    pts = MAChecker(vol_mode="avg5", type_name="5日均量均线支撑").check(df, _band(df))
    assert pts
    assert all(p.type == "5日均量均线支撑" for p in pts)
    assert all("5日均量" in p.reason for p in pts)


def _band_hr():
    """能触发 回调一半（宽松 live + 严格 trial）的 band：跌破62.5、v_qualified、
    回调>=13天、有回调一半价、回调谷底 9.5 ≥ 50%线 9.0（严格版也过门槛）。"""
    b = BandResult()
    b.trigger_625_date = "20240101"
    b.v_qualified = True
    b.p_idx = 0
    b.rows_count = 20
    b.half_retrace_series = [{"price": 9.9}]
    b.current_price = 10.0
    b.line_625 = 10.2
    b.line_50 = 9.0
    b.l_price = 9.5
    return b


def test_find_all_hides_trial_by_default(monkeypatch):
    df = _rising()
    monkeypatch.setattr(BP, "load_buy_point_config", lambda: {})  # 无 显示试验买点 → 默认隐藏
    pts = find_all_buy_points(df, _band_hr())
    assert all("[严格]" not in p.reason for p in pts)   # 回调一半严格（trial）默认隐藏


def test_find_all_shows_trial_when_enabled(monkeypatch):
    df = _rising()
    monkeypatch.setattr(BP, "load_buy_point_config", lambda: {"显示试验买点": 1.0})
    pts = find_all_buy_points(df, _band_hr())
    assert any("[严格]" in p.reason for p in pts)       # 开启后严格版出现


def test_ma_single_period_only_checks_that_period():
    df = _rising()
    pts = MAChecker(vol_mode="today", periods=[20], type_name="MA20支撑").check(df, _band(df))
    assert pts, "上升+放量应触发 MA20 支撑"
    assert all(p.position == "MA20" for p in pts)   # 只检查单周期
    assert all(p.type == "MA20支撑" for p in pts)


def test_ma_no_volume_variant_ignores_volume():
    df = _rising()
    pts = MAChecker(vol_mode="none", periods=[60, 120, 240],
                    type_name="无量均线支撑").check(df, _band(df))
    assert pts
    assert all(p.type == "无量均线支撑" for p in pts)
    assert all("不看量" in p.reason for p in pts)
