import pandas as pd
from marketreview.winrate.buypoint_defs import detect_buy_points
from marketreview.winrate.trade_sim import BuyPointSignal
from marketreview.tools.band_analysis import BandResult


def test_band50_maps_to_entry_stop():
    # 构造一个满足 Band50Checker 的 band：跌破62.5、v_qualified、回调>=13天
    band = BandResult()
    band.trigger_625_date = "20240101"
    band.v_qualified = True
    band.line_50 = 9.0
    band.line_625 = 9.5
    band.current_price = 8.5
    band.p_idx = 0
    band.rows_count = 20   # pullback = 20-1-0 = 19 >= 13
    df = pd.DataFrame({"amount": [1.0] * 20})
    sigs = detect_buy_points(df, band, ["波段50%"])
    assert len(sigs) == 1
    s = sigs[0]
    assert s.buy_point == "波段50%"
    assert s.target_price == 9.0
    assert s.close_stop_kind == "entry"


def test_selected_filters_out_unwanted():
    band = BandResult()
    band.trigger_625_date = "20240101"
    band.v_qualified = True
    band.line_50 = 9.0
    band.current_price = 8.5
    band.p_idx = 0
    band.rows_count = 20
    df = pd.DataFrame({"amount": [1.0] * 20})
    sigs = detect_buy_points(df, band, ["回调一半"])  # 只要回调一半
    assert all(s.buy_point == "回调一半" for s in sigs)
