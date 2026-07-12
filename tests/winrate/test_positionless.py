"""position-less 引擎行为：数据到底不出样本；持仓期不跳过（信号逐日独立）。"""
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import BuyPointSignal, simulate_trade
from marketreview.winrate import scan_engine as SE


def _k(date, o, h, l, c):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "ma60": 0.0}


def test_data_end_returns_none():
    # 进场后价格平缓（不触发止盈/止损/时间止损），数据到底 → None（不再产出「回测结束」）
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


def test_scan_is_position_less(monkeypatch):
    # 每天都产出一个信号；position-less 下逐日各建一笔（重叠不跳过），
    # 远多于旧持仓模型（会跳过持仓期，仅 ~2-3 笔）。
    n = 80  # scan_stock 要求 >= 60 根K线
    closes = [round(10 * (1.005 ** i), 3) for i in range(n)]        # 缓涨 +0.5%/日
    rows_asc = [_row(f"2024{1 + i // 28:02d}{1 + i % 28:02d}", c)
                for i, c in enumerate(closes)]
    rows_desc = rows_asc[::-1]

    monkeypatch.setattr(SE, "passes_all", lambda *a, **k: True)
    monkeypatch.setattr(
        SE, "detect_buy_points",
        lambda df, band, bps: [BuyPointSignal(
            buy_point="回调一半", target_price=float(df["close"].iloc[-1]),
            close_stop_kind="entry", close_stop_period=0)],
    )

    cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[],
                        time_stop_days=15)
    trades = SE.scan_stock("600000.SH", "x", rows_desc, cfg, "电子", "半导体",
                           "20200101", mv_series={r["date"]: 150.0 for r in rows_desc})

    assert len(trades) > 10                       # 逐日建仓 → 远多于持仓模型
    spans = [(t.entry_date, t.signal_date, t.exit_date) for t in trades]
    overlap = any(a[0] < b[1] < a[2]              # 某笔信号日落在另一笔的[进场,出场]内
                  for i, a in enumerate(spans) for b in spans[i + 1:])
    assert overlap, "position-less 应存在持仓期重叠的交易"
