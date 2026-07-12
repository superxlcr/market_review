"""随机基准买点（无技能对照）：确定性种子、发信概率≈PROB、忽略波段、
市价目标、以及 detect_buy_points 按普通市价买点（entry 收盘止损）包装。"""
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import RandomBaselineChecker
from marketreview.winrate.buypoint_defs import detect_buy_points

_P = RandomBaselineChecker.PROB


def _find_date(code: str, emit: bool) -> str:
    """找一个会/不会发信的 date token（date 只当哈希输入，无需真日历）。"""
    for i in range(1, 500000):
        d = str(20240101 + i)
        if (RandomBaselineChecker._rand01(code, d) < _P) is emit:
            return d
    raise RuntimeError("未找到符合条件的 date")


def _df(date: str, close: float = 100.0) -> pd.DataFrame:
    # 末行 = 信号日；checker 只读 iloc[-1] 的 date/close
    return pd.DataFrame({
        "date": ["20200101", date],
        "open": [close, close], "high": [close, close],
        "low": [close, close], "close": [close, close],
        "vol": [1.0, 1.0], "amount": [1.0, 1.0],
    })


def test_rand01_deterministic_across_calls():
    code, d = "000001.SZ", "20240101"
    assert RandomBaselineChecker._rand01(code, d) == RandomBaselineChecker._rand01(code, d)
    # checker 层：发信日两次调用结果一致
    d_emit = _find_date(code, emit=True)
    ck = RandomBaselineChecker()
    r1 = ck.check(_df(d_emit), BandResult(), code=code)
    r2 = ck.check(_df(d_emit), BandResult(), code=code)
    assert len(r1) == 1 and len(r2) == 1
    assert (r1[0].price, r1[0].position) == (r2[0].price, r2[0].position)


def test_emit_fraction_matches_prob():
    code = "600000.SH"
    n = 20000
    hits = sum(1 for i in range(n) if RandomBaselineChecker._rand01(code, str(i)) < _P)
    frac = hits / n
    assert abs(frac - _P) < 0.006, f"发信比例 {frac:.4f} 偏离 PROB={_P}"


def test_emits_market_price_ignoring_band():
    code = "600519.SH"
    d = _find_date(code, emit=True)
    band = BandResult()          # 无效波段：随机基准应无视之照发
    band.v_qualified = False
    band.p_idx = -1
    pts = RandomBaselineChecker().check(_df(d, close=100.0), band, code=code)
    assert len(pts) == 1
    p = pts[0]
    assert p.type == "随机基准" and p.position == "随机基准"
    assert p.price == 100.0       # 市价 = 信号日收盘
    assert p.distance_pct == 0.0
    assert p.intraday_stop == 0.0  # 不设绝对止损 → 走全局空间止损
    assert "随机基准" in p.reason


def test_non_emit_day_returns_empty():
    code = "600519.SH"
    d = _find_date(code, emit=False)
    pts = RandomBaselineChecker().check(_df(d, close=100.0), BandResult(), code=code)
    assert pts == []


def test_detect_wraps_random_as_entry_stop():
    code = "600000.SH"
    d = _find_date(code, emit=True)
    sigs = detect_buy_points(_df(d, close=50.0), BandResult(), ["随机基准"], code=code)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.buy_point == "随机基准"
    assert s.close_stop_kind == "entry"      # 与普通市价买点同框（全局空间止损）
    assert s.intraday_stop_price == 0.0
    assert s.target_price == 50.0
    assert "随机基准" in s.reason
