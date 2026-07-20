"""按 标的×买点 各自持仓：同一买点建仓后、出场前不重复建仓；不同买点互不影响；
数据到底不出样本（不产出「回测结束」）。"""
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import BuyPointSignal, simulate_trade
from marketreview.winrate import scan_engine as SE


def _k(date, o, h, l, c):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "ma60": 0.0}


def test_data_end_returns_none():
    # 进场后价格平缓（不触发止盈/止损/时间止损），数据到底 → None（不产出「回测结束」）
    cfg = WinrateConfig(time_stop_days=20)
    klines = [
        _k("20240101", 10, 10, 10, 10),        # 信号日
        _k("20240102", 10, 10.1, 9.9, 10),     # 进场：low<=目标<=high → 10
        _k("20240103", 10, 10.2, 9.9, 10),     # 平缓
        _k("20240104", 10, 10.2, 9.9, 10),     # 数据到底
    ]
    sig = BuyPointSignal(buy_point="回调一半", target_price=10.0,
                         close_stop_kind="entry", close_stop_period=0)
    tr = simulate_trade(sig, 0, klines, cfg, "600000.SH", "x", atr_at_signal=0.0)
    assert tr is None


def _row(date, c):
    return {"date": date, "open": c, "high": c, "low": c, "close": c,
            "vol": 1.0, "amount": 1.0, "adj_factor": 1.0, "asset_type": "stock"}


def _rows_rising(n=80):
    # 缓涨 +0.5%/日；n>=60（scan_stock 要求）。返回 date DESC。
    closes = [round(10 * (1.005 ** i), 3) for i in range(n)]
    rows_asc = [_row(f"2024{1 + i // 28:02d}{1 + i % 28:02d}", c)
                for i, c in enumerate(closes)]
    return rows_asc[::-1]


def _mv(rows_desc):
    return {r["date"]: 150.0 for r in rows_desc}


def test_same_buypoint_no_overlap(monkeypatch):
    # 每天都产出一个「回调一半」信号；按买点持仓 → 建仓后出场前不再建仓 → 交易互不重叠。
    rows_desc = _rows_rising()
    monkeypatch.setattr(SE, "passes_all", lambda *a, **k: True)
    monkeypatch.setattr(
        SE, "detect_buy_points",
        lambda df, band, bps, code="": [BuyPointSignal(
            buy_point="回调一半", target_price=float(df["close"].iloc[-1]),
            close_stop_kind="entry", close_stop_period=0)],
    )
    cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[],
                        time_stop_days=15)
    trades = SE.scan_stock("600000.SH", "x", rows_desc, cfg, "电子", "半导体", "",
                           "20200101", mv_series=_mv(rows_desc))
    assert len(trades) >= 2
    ts = sorted(trades, key=lambda t: t.entry_date)
    for a, b in zip(ts, ts[1:]):
        assert b.signal_date >= a.exit_date, "同一买点不应在持仓期内重复建仓"


def test_different_buypoints_independent(monkeypatch):
    # 每天产出「回调一半」+「波段50%」两个信号；两买点各自持仓、互不阻塞 →
    # 两者都持续建仓，且持仓期可重叠（一个的[进场,出场]与另一个相交）。
    rows_desc = _rows_rising()
    monkeypatch.setattr(SE, "passes_all", lambda *a, **k: True)
    monkeypatch.setattr(
        SE, "detect_buy_points",
        lambda df, band, bps, code="": [
            BuyPointSignal(buy_point="回调一半", target_price=float(df["close"].iloc[-1]),
                           close_stop_kind="entry", close_stop_period=0),
            BuyPointSignal(buy_point="波段50%", target_price=float(df["close"].iloc[-1]),
                           close_stop_kind="entry", close_stop_period=0),
        ],
    )
    cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[],
                        time_stop_days=15)
    trades = SE.scan_stock("600000.SH", "x", rows_desc, cfg, "电子", "半导体", "",
                           "20200101", mv_series=_mv(rows_desc))
    assert {t.buy_point for t in trades} == {"回调一半", "波段50%"}   # 两买点都在跑
    half = [t for t in trades if t.buy_point == "回调一半"]
    band = [t for t in trades if t.buy_point == "波段50%"]
    # 跨买点应存在持仓期重叠（互不阻塞）
    overlap = any(h.entry_date <= g.exit_date and g.entry_date <= h.exit_date
                  for h in half for g in band)
    assert overlap, "不同买点应可持仓期重叠（互不影响）"
