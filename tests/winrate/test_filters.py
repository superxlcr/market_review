import pandas as pd
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate import filters as F


def _rising_df(n=260, base=10.0, step=0.05):
    # 单调上升 → 短/长均线都多头且向上
    closes = [base + i * step for i in range(n)]
    return pd.DataFrame({"close": closes})


def _falling_df(n=260, base=30.0, step=0.05):
    closes = [base - i * step for i in range(n)]
    return pd.DataFrame({"close": closes})


def test_ma_group_state_bull():
    df = _rising_df()
    assert F.ma_group_state(df, [5, 10, 20]) == "多头"
    assert F.ma_group_state(df, [60, 120, 240]) == "多头"


def test_ma_group_state_bear():
    df = _falling_df()
    assert F.ma_group_state(df, [5, 10, 20]) == "空头"


def test_ma_group_state_insufficient():
    df = _rising_df(n=30)
    assert F.ma_group_state(df, [60, 120, 240]) == "其他"


def test_passes_ma_arrange_dont_care_always_true():
    df = _falling_df()
    assert F.passes_ma_arrange(df, "无关", [60, 120, 240]) is True


def test_passes_ma_arrange_match():
    df = _rising_df()
    assert F.passes_ma_arrange(df, "多头", [60, 120, 240]) is True
    assert F.passes_ma_arrange(df, "空头", [60, 120, 240]) is False


def test_passes_market_cap_bounds():
    cfg = WinrateConfig(mv_min_yi=100, mv_max_yi=300)
    assert F.passes_market_cap(50, cfg) is False
    assert F.passes_market_cap(150, cfg) is True
    assert F.passes_market_cap(400, cfg) is False


def test_passes_market_cap_no_bounds():
    cfg = WinrateConfig(mv_min_yi=0, mv_max_yi=0)
    assert F.passes_market_cap(5, cfg) is True
    assert F.passes_market_cap(9999, cfg) is True


def test_passes_industry():
    assert F.passes_industry("电子", "半导体", []) is True          # 空=不限
    assert F.passes_industry("电子", "半导体", ["电子"]) is True
    assert F.passes_industry("电子", "半导体", ["半导体"]) is True   # L2 命中
    assert F.passes_industry("汽车", "整车", ["电子"]) is False


def test_passes_list_age():
    assert F.passes_list_age("20230101", "20240101", 250) is True   # ~365天
    assert F.passes_list_age("20231201", "20240101", 250) is False  # ~31天
    assert F.passes_list_age("", "20240101", 250) is False          # 缺失=不通过
