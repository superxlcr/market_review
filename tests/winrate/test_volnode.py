"""量价节点买点：识别 / 前日涨跌停排除 / 已跌破成本作废 / line_75激活，
以及引擎按"节点成本"绝对价盘中止损。"""
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import VolPriceNodeChecker
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import BuyPointSignal, simulate_trade


# idx:      0     1     2     3(V)  4(涨停) 5(排除)  6     7     8(节点) 9    10(P) 11    12     13     14(今)
_CLOSE = [100,  100,  100,   90,   99,    101.2,  101,  102,  104.1, 105,  106,  103,  101.5, 101,   101]
_LOW = [ 98,   98,   98,   88,   90,     95,     99,  100,  101,   103,  104,  102,  101,   100.5, 100.5]
_AMT = [1000, 1000, 1000, 1000, 1000,  1300,   1000, 1000, 1300,  1000, 1000, 1000, 1000,  1000,  1000]


def _df(close, low, amt):
    n = len(close)
    dates = [f"202401{i + 1:02d}" for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": close, "high": close, "low": low, "close": close,
        "vol": [1.0] * n, "amount": amt,
    })


def _band(l_price=100.5):
    # V@idx3(low=88), P@idx10(high=107) → line_75 = 88 + 0.75×(107−88) = 102.25
    b = BandResult()
    b.v_qualified = True
    b.v_idx, b.v_price = 3, 88.0
    b.p_idx, b.p_price = 10, 107.0
    b.line_75 = 88.0 + 0.75 * (107.0 - 88.0)   # 102.25
    b.l_price = l_price                        # 回调最低 low（< line_75 → 激活）
    b.current_price = 101.0                    # close[14]
    return b


def test_volnode_detects_single_valid_node():
    df = _df(_CLOSE, _LOW, _AMT)
    pts = VolPriceNodeChecker().check(df, _band(), code="600000.SH")
    assert len(pts) == 1                        # idx5 被前日涨停排除，只剩 idx8
    p = pts[0]
    assert p.type == "量价节点" and p.position == "量价节点"
    assert p.price == 104.0                     # 成本 min(low8,low7)=100 ×1.04
    assert p.intraday_stop == 99.99             # 跌破成本 = 成本100.0 低一分钱
    assert "量价节点" in p.reason and "成本100.0" in p.reason


def test_volnode_prev_limit_up_excluded():
    # 把 idx4 从涨停(99)改成普通上涨(95) → idx5 不再被排除 → 2 个节点
    close = list(_CLOSE)
    close[4] = 95.0
    df = _df(close, _LOW, _AMT)
    pts = VolPriceNodeChecker().check(df, _band(), code="600000.SH")
    assert len(pts) == 2                        # idx5(成本90→93.6) + idx8(100→104)
    targets = sorted(round(p.price, 2) for p in pts)
    assert targets == [93.6, 104.0]


def test_volnode_not_armed_above_line75():
    df = _df(_CLOSE, _LOW, _AMT)
    # 回调最低 103 > line_75(102.25) → 未跌破 75%线 → 不激活
    pts = VolPriceNodeChecker().check(df, _band(l_price=103.0), code="600000.SH")
    assert pts == []


def test_volnode_broken_cost_invalidated():
    # 后续 low 跌破节点成本 100（idx13 low=99）→ idx8 节点作废；idx5 仍被涨停排除 → 空
    low = list(_LOW)
    low[13] = 99.0
    df = _df(_CLOSE, low, _AMT)
    pts = VolPriceNodeChecker().check(df, _band(l_price=99.0), code="600000.SH")
    assert pts == []


def test_engine_honors_absolute_intraday_stop():
    # close_stop_kind="fixed" + intraday_stop_price=100：盘中触 100 即止损，
    # 而非全局 5%(=买入价104×0.95=98.8)。100>98.8，只有绝对止损能在此触发。
    def k(date, o, h, l, c):
        return {"date": date, "open": o, "high": h, "low": l, "close": c}
    klines = [
        k("20240101", 104, 104, 104, 104),   # 信号日
        k("20240102", 104, 105, 103, 104),   # 进场：low<=104<=high → entry=104
        k("20240103", 102, 102, 100, 101),   # 盘中 low=100 = 绝对止损价 → 出场
    ]
    sig = BuyPointSignal(buy_point="量价节点", target_price=104.0,
                         close_stop_kind="fixed", intraday_stop_price=100.0,
                         reason="量价节点@20240101 成本100.0(两日最低)×1.04")
    cfg = WinrateConfig(space_stop_pct=5.0)
    tr = simulate_trade(sig, 0, klines, cfg, "600000.SH", "x", atr_at_signal=0.0)
    assert tr is not None
    assert tr.exit_reason == "盘中止损"
    assert tr.exit_price == 100.0
    assert round(tr.pnl_pct, 2) == round((100 - 104) / 104 * 100, 2)   # ≈ -3.85
    assert tr.reason == "量价节点@20240101 成本100.0(两日最低)×1.04"   # 买入理由透出到成交记录


# ── 严格版：50% 线过滤 ──

def test_volnode_strict_filters_node_below_line50():
    """strict 下 target < line_50 的节点被过滤。
    节点 target=104（成本100×1.04）；设 line_50=105 → 104<105 → 作废。"""
    df = _df(_CLOSE, _LOW, _AMT)
    b = _band()
    b.line_50 = 105.0   # 高于 target 104
    pts = VolPriceNodeChecker(entry_premium=1.04, strict=True).check(df, b, code="600000.SH")
    assert pts == []


def test_volnode_strict_keeps_node_above_line50():
    """strict 下 target >= line_50 的节点保留。
    target=104；设 line_50=97.5（真实 50% 线）→ 104>=97.5 → 保留。"""
    df = _df(_CLOSE, _LOW, _AMT)
    b = _band()
    b.line_50 = 88.0 + 0.5 * (107.0 - 88.0)   # 97.5
    pts = VolPriceNodeChecker(entry_premium=1.04, strict=True).check(df, b, code="600000.SH")
    assert len(pts) == 1
    assert pts[0].price == 104.0


def test_volnode_strict_stage_is_trial():
    """strict 实例 STAGE=trial（不论 entry_premium）。"""
    assert VolPriceNodeChecker(entry_premium=1.04, strict=True).STAGE == "trial"
    assert VolPriceNodeChecker(entry_premium=1.02, strict=True).STAGE == "trial"


def test_volnode_non_strict_ignores_line50():
    """非 strict 行为不变：line_50 不影响（即使 target<line_50 也保留）。"""
    df = _df(_CLOSE, _LOW, _AMT)
    b = _band()
    b.line_50 = 105.0   # 高于 target 104，但非 strict 不过滤
    pts = VolPriceNodeChecker(entry_premium=1.04, strict=False).check(df, b, code="600000.SH")
    assert len(pts) == 1
