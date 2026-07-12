"""量价节点上浮2%变体：进场成本×1.02（默认版×1.04），其它（成本止损/激活条件）不变。

作为 trial 买点，与 回调一半严格 同一套三态机制：STAGE=trial，仅胜率默认扫描 +
个股页「显示试验买点」时出现。
"""
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import VolPriceNodeChecker
from marketreview.winrate.buypoint_defs import _NAME_MAP


# 复用 test_volnode 的同一组序列：节点在 idx8，成本 min(low8,low7)=100
_CLOSE = [100,  100,  100,   90,   99,    101.2,  101,  102,  104.1, 105,  106,  103,  101.5, 101,   101]
_LOW = [ 98,   98,   98,   88,   90,     95,     99,  100,  101,   103,  104,  102,  101,   100.5, 100.5]
_AMT = [1000, 1000, 1000, 1000, 1000,  1300,   1000, 1000, 1300,  1000, 1000, 1000, 1000,  1000,  1000]


def _df():
    n = len(_CLOSE)
    dates = [f"202401{i + 1:02d}" for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": _CLOSE, "high": _CLOSE, "low": _LOW, "close": _CLOSE,
        "vol": [1.0] * n, "amount": _AMT,
    })


def _band():
    b = BandResult()
    b.v_qualified = True
    b.v_idx, b.v_price = 3, 88.0
    b.p_idx, b.p_price = 10, 107.0
    b.line_75 = 88.0 + 0.75 * (107.0 - 88.0)   # 102.25
    b.l_price = 100.5                          # < line_75 → 激活
    b.current_price = 101.0
    return b


def test_stage_live_vs_trial():
    # 默认(1.04)=live；上浮2%(1.02)=trial
    assert VolPriceNodeChecker().STAGE == "live"
    assert VolPriceNodeChecker().ENTRY_PREMIUM == 1.04
    assert VolPriceNodeChecker(entry_premium=1.02).STAGE == "trial"
    assert VolPriceNodeChecker(entry_premium=1.02).ENTRY_PREMIUM == 1.02


def test_uplift_target_is_cost_times_1_02():
    pts = VolPriceNodeChecker(entry_premium=1.02).check(_df(), _band(), code="600000.SH")
    assert len(pts) == 1                        # 同默认版：idx5 被前日涨停排除，只剩 idx8
    p = pts[0]
    assert p.type == "量价节点" and p.position == "量价节点"   # position 不变 → 沿用成本止损/共振逻辑
    assert p.price == 102.0                     # 成本100 ×1.02（默认版是 104.0=×1.04）
    assert p.intraday_stop == 99.99             # 成本止损不变：成本100.0 低一分钱
    assert "×1.02" in p.reason
    assert "[上浮2%]" in p.reason


def test_default_target_unchanged():
    # 默认版仍 ×1.04，reason 无上浮前缀（回归保护）
    p = VolPriceNodeChecker().check(_df(), _band(), code="600000.SH")[0]
    assert p.price == 104.0
    assert "×1.04" in p.reason
    assert "上浮" not in p.reason


def test_registered_in_name_map():
    assert "量价节点上浮2%" in _NAME_MAP
    kind, checker = _NAME_MAP["量价节点上浮2%"]
    assert kind == "volnode"
    assert isinstance(checker, VolPriceNodeChecker)
    assert checker.ENTRY_PREMIUM == 1.02
