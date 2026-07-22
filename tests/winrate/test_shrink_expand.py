"""缩转放买点：放量上涨阳线识别 / 量能维度计算 / 两版止损 strategy 标志。"""
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import ShrinkToExpandChecker
from marketreview.winrate.buypoint_defs import detect_buy_points
from marketreview.winrate.config import WinrateConfig


def _df(rows):
    """rows: list of (close, open, low, amount)。日期递增。"""
    n = len(rows)
    dates = [f"202401{i + 1:02d}" for i in range(n)]
    close = [r[0] for r in rows]
    open_ = [r[1] for r in rows]
    low = [r[2] for r in rows]
    amt = [r[3] for r in rows]
    return pd.DataFrame({
        "date": dates, "open": open_, "high": close, "low": low, "close": close,
        "vol": [1.0] * n, "amount": amt,
    })


def _band():
    return BandResult()   # 缩转放不依赖波段


def _rows(today_close, today_open, today_low, today_amt, prev_amt=1000.0):
    """构造 21 天数据：前 20 天平稳(amount=prev_amt, close 微涨)，今天为参数值。"""
    rows = []
    base_close = 100.0
    for i in range(20):
        rows.append((base_close + i * 0.01, base_close + i * 0.01, base_close - 1, prev_amt))
    rows.append((today_close, today_open, today_low, today_amt))
    return rows


def _squeeze_rows(today_close, today_open, today_low, today_amt):
    """前期缩量形态：前15天量1500(高位)，后5天缩到500(缩量平衡态)，今天放量1500。
    MA5(不含今日)=500 < MA20(不含今日)=1250 → vol_shrink=0.4 <1。"""
    rows = []
    base_close = 100.0
    for i in range(15):
        rows.append((base_close + i * 0.01, base_close + i * 0.01, base_close - 1, 1500.0))
    for i in range(5):
        rows.append((base_close + 0.15, base_close + 0.15, base_close - 1, 500.0))
    rows.append((today_close, today_open, today_low, today_amt))
    return rows


def test_shrink_expand_detects_volume_up_yangxian():
    # 今日：收盘105>昨100（上涨）、收盘105>开盘102（阳线）、量1500>20日均(含今日~1025)（放量）
    rows = _rows(today_close=105, today_open=102, today_low=101, today_amt=1500)
    df = _df(rows)
    pts = ShrinkToExpandChecker().check(df, _band(), code="930734.CSI")
    assert len(pts) == 1
    p = pts[0]
    assert p.type == "缩转放" and p.position == "缩转放"
    assert p.price == 105.0                      # 收盘价进场
    assert p.intraday_stop == 100.99             # low(101)-0.01


def test_shrink_expand_rejects_low_volume():
    # 缩量上涨：今日量800 < 20日均(~1000) → 不触发
    rows = _rows(today_close=105, today_open=102, today_low=101, today_amt=800)
    df = _df(rows)
    pts = ShrinkToExpandChecker().check(df, _band(), code="930734.CSI")
    assert pts == []


def test_shrink_expand_rejects_yinxian():
    # 阴线：收盘<开盘（高开低走），即使收盘>昨收也不触发
    rows = _rows(today_close=101, today_open=103, today_low=100, today_amt=1500)
    df = _df(rows)
    pts = ShrinkToExpandChecker().check(df, _band(), code="930734.CSI")
    assert pts == []


def test_shrink_expand_rejects_down():
    # 下跌：收盘<昨收 → 不触发
    rows = _rows(today_close=99, today_open=99, today_low=98, today_amt=1500)
    df = _df(rows)
    pts = ShrinkToExpandChecker().check(df, _band(), code="930734.CSI")
    assert pts == []


def test_shrink_expand_vol_ratios_recorded():
    # 平稳形态：vol_shrink=1.0（无缩量），vol_ratio_20=1500/1025≈1.463
    rows = _rows(today_close=105, today_open=102, today_low=101, today_amt=1500)
    df = _df(rows)
    chk = ShrinkToExpandChecker()
    chk.check(df, _band(), code="930734.CSI")
    vr = chk._last_vol_ratios
    assert abs(vr["vol_ratio_20"] - 1.463) < 0.01
    assert abs(vr["vol_shrink"] - 1.0) < 0.01
    assert vr["vol_ratio_5"] > 0


def test_shrink_expand_vol_shrink_detects_prior_squeeze():
    # 前期缩量形态：vol_shrink=0.4 <1（信号前处于缩量平衡态）
    rows = _squeeze_rows(today_close=105, today_open=102, today_low=101, today_amt=1500)
    df = _df(rows)
    chk = ShrinkToExpandChecker()
    pts = chk.check(df, _band(), code="930734.CSI")
    assert len(pts) == 1                         # 今日1500 > MA20(含今日) 仍触发
    assert chk._last_vol_ratios["vol_shrink"] < 1.0   # 前期缩量
    assert abs(chk._last_vol_ratios["vol_shrink"] - 0.4) < 0.01


def test_shrink_expand_two_versions_strategy():
    # detect_buy_points 给两版设正确的 strategy
    rows = _rows(today_close=105, today_open=102, today_low=101, today_amt=1500)
    df = _df(rows)
    sigs = detect_buy_points(df, _band(), ["缩转放", "缩转放收盘止损"], code="930734.CSI")
    assert len(sigs) == 2
    strat = {s.buy_point: s.strategy for s in sigs}
    assert strat["缩转放"] == "shrink_expand"
    assert strat["缩转放收盘止损"] == "shrink_expand_close"
    # 两版都收盘价进场、量能值已传入
    for s in sigs:
        assert s.entry_mode == "close"
        assert abs(s.vol_ratio_20 - 1.463) < 0.01
        assert s.intraday_stop_price == 100.99


def test_shrink_expand_rejects_short_history():
    # 数据不足 21 天 → 不触发（MA20 需 20 日）
    rows = [(100, 100, 99, 1500)] * 15
    df = _df(rows)
    pts = ShrinkToExpandChecker().check(df, _band(), code="930734.CSI")
    assert pts == []
