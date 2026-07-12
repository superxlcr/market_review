"""回调一半严格版门槛（回调谷底跌破50%线即不触发）+ 主力买点止损分支
（量价节点自带成本止损不覆盖 / 回调一半·波段50% 固定5%空间止损）。"""
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import HalfRetraceChecker, _calc_stop_losses, BuyPoint


def _band(l_price: float) -> BandResult:
    b = BandResult()
    b.trigger_625_date = "20240101"
    b.v_qualified = True
    b.p_idx = 0
    b.rows_count = 20                 # pullback = 20-1-0 = 19 >= 13
    b.half_retrace_series = [{"price": 9.3}]
    b.current_price = 9.5
    b.line_625 = 9.8
    b.line_50 = 9.0
    b.l_price = l_price
    return b


_DF = pd.DataFrame({"amount": [1.0] * 20})


def test_strict_fires_when_low_holds_above_50():
    # 回调谷底 9.2 ≥ 50%线 9.0 → 趋势未改变 → 触发
    pts = HalfRetraceChecker(strict=True).check(_DF, _band(l_price=9.2))
    assert len(pts) == 1
    assert pts[0].position == "回调一半"
    assert "[严格]" in pts[0].reason


def test_strict_blocked_when_low_breaks_50():
    # 回调谷底 8.5 < 50%线 9.0 → 趋势已改变 → 不触发（应走波段50%）
    pts = HalfRetraceChecker(strict=True).check(_DF, _band(l_price=8.5))
    assert pts == []


def test_lenient_ignores_50_line():
    # 宽松版（现版）不看谷底是否跌破50%线，照常触发
    pts = HalfRetraceChecker(strict=False).check(_DF, _band(l_price=8.5))
    assert len(pts) == 1
    assert "[严格]" not in pts[0].reason


def test_strict_stage_is_trial_lenient_is_live():
    assert HalfRetraceChecker(strict=True).STAGE == "trial"
    assert HalfRetraceChecker(strict=False).STAGE == "live"


def test_volnode_keeps_own_cost_stop():
    # 量价节点自带成本止损（成本-0.01），_calc_stop_losses 不得覆盖
    bp = BuyPoint(type="量价节点", position="量价节点", price=104.0,
                  distance_pct=0.0, intraday_stop=99.99)
    _calc_stop_losses(bp, atr_pct=2.0, trend="up", config={}, ma_val=0.0)
    assert bp.intraday_stop == 99.99
    assert bp.intraday_stop_reason == "跌破成本"


def test_anchor_uses_fixed_5pct_not_atr():
    # 回调一半：固定5%空间止损（读配置默认5），不再用 2×ATR
    bp = BuyPoint(type="突破", position="回调一半", price=100.0, distance_pct=0.0)
    _calc_stop_losses(bp, atr_pct=1.0, trend="up", config={}, ma_val=0.0)
    assert bp.intraday_stop == 95.0
    assert bp.intraday_stop_pct == 5.0
    assert "空间止损" in bp.intraday_stop_reason


def test_anchor_stop_reads_config_override():
    bp = BuyPoint(type="突破", position="波段50%", price=100.0, distance_pct=0.0)
    _calc_stop_losses(bp, atr_pct=None, trend="flat", config={"主力盘中止损%": 7.0}, ma_val=0.0)
    assert bp.intraday_stop == 93.0
    assert bp.intraday_stop_pct == 7.0
