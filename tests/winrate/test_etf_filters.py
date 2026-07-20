import pandas as pd
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate import filters as F


def _rising_df(n=260, base=10.0, step=0.05):
    closes = [base + i * step for i in range(n)]
    return pd.DataFrame({"close": closes})


def test_index_skips_market_cap():
    # index 模式：即使设了市值下限，也不过滤（mv_yi=0 也能过）
    df = _rising_df()
    cfg = WinrateConfig(asset_class="index", mv_min_yi=9999, mv_max_yi=0,
                        long_ma_states=[], short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="电子", l2="半导体",
                        list_date="20100101", on_date="20260101") is True


def test_index_skips_industry_whitelist():
    # index 模式：行业白名单不生效
    df = _rising_df()
    cfg = WinrateConfig(asset_class="index",
                        industry_whitelist=["不存在行业"],
                        long_ma_states=[], short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="电子", l2="半导体",
                        list_date="20100101", on_date="20260101") is True


def test_index_keeps_ma_arrange_filter():
    # index 模式：均线排列过滤仍生效
    df = _rising_df()
    cfg_bull = WinrateConfig(asset_class="index", long_ma_states=["多头"],
                             short_ma_states=[], min_list_days=0)
    cfg_bear = WinrateConfig(asset_class="index", long_ma_states=["空头"],
                             short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg_bull, mv_yi=0.0, l1="", l2="",
                        list_date="20100101", on_date="20260101") is True
    assert F.passes_all(df, cfg_bear, mv_yi=0.0, l1="", l2="",
                        list_date="20100101", on_date="20260101") is False


def test_index_keeps_list_age_filter():
    # index 模式：发布天数过滤仍生效
    df = _rising_df()
    cfg = WinrateConfig(asset_class="index", min_list_days=250,
                        long_ma_states=[], short_ma_states=[])
    # 上市 100 天 < 250 → 不通过
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="", l2="",
                        list_date="20250901", on_date="20260101") is False
    # 上市 400 天 ≥ 250 → 通过
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="", l2="",
                        list_date="20241101", on_date="20260101") is True


def test_stock_path_unchanged():
    # 回归：stock 模式行为不变（市值过滤仍生效）
    df = _rising_df()
    cfg = WinrateConfig(asset_class="stock", mv_min_yi=9999,
                        long_ma_states=[], short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg, mv_yi=10.0, l1="", l2="",
                        list_date="20100101", on_date="20260101") is False
