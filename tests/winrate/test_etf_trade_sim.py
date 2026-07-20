from marketreview.winrate.trade_sim import board_limit_pct, simulate_trade, BuyPointSignal
from marketreview.winrate.config import WinrateConfig


def test_board_limit_stock():
    assert board_limit_pct("000001.SZ") == 0.10
    assert board_limit_pct("300001.SZ") == 0.20
    assert board_limit_pct("688001.SH") == 0.20


def test_board_limit_index_no_limit():
    # 指数无涨跌停 → 返回 1.0（100%），条件单可达性恒通过
    assert board_limit_pct("931152.CSI", asset_class="index") == 1.0
    assert board_limit_pct("H30199.CSI", asset_class="index") == 1.0


def test_simulate_trade_index_no_qfq_implied():
    # 指数模式：条件单可达性不拦（即使 target 距收盘很远也能成交）
    # 构造 K 线：信号日 close=100，次日 open=99/low=95/high=101，target=95
    klines = [
        {"date": "20260101", "open": 100, "high": 101, "low": 99, "close": 100},
        {"date": "20260102", "open": 99, "high": 101, "low": 95, "close": 100},
        {"date": "20260103", "open": 100, "high": 110, "low": 99, "close": 108},
        {"date": "20260104", "open": 108, "high": 112, "low": 107, "close": 111},
    ]
    sig = BuyPointSignal(buy_point="波段50%", target_price=95.0,
                         close_stop_kind="entry")
    cfg = WinrateConfig(asset_class="index", win_threshold_pct=10.0,
                        big_win_pct=20.0, small_win_floor_pct=5.0,
                        space_stop_pct=5.0, time_stop_days=13,
                        open_chase_cap_pct=102.0)
    tr = simulate_trade(sig, signal_idx=0, klines_asc=klines, cfg=cfg,
                        code="931152.CSI", name="CS创新药", atr_at_signal=0.0,
                        asset_class="index")
    # 次日 low=95 <= target=95 <= high=101 → 成交@95
    assert tr is not None
    assert tr.entry_price == 95.0
    assert tr.entry_date == "20260102"


def test_simulate_trade_stock_still_uses_board_limit():
    # 回归：stock 模式仍用涨跌停可达性（target 远超 10% 涨停 → 不成交）
    klines = [
        {"date": "20260101", "open": 100, "high": 101, "low": 99, "close": 100},
        {"date": "20260102", "open": 100, "high": 101, "low": 99, "close": 100},
    ]
    sig = BuyPointSignal(buy_point="波段50%", target_price=200.0,
                         close_stop_kind="entry")  # target 翻倍，超涨跌停
    cfg = WinrateConfig(asset_class="stock", win_threshold_pct=10.0,
                        big_win_pct=20.0, small_win_floor_pct=5.0,
                        space_stop_pct=5.0, time_stop_days=13,
                        open_chase_cap_pct=102.0)
    tr = simulate_trade(sig, signal_idx=0, klines_asc=klines, cfg=cfg,
                        code="000001.SZ", name="平安银行", atr_at_signal=0.0)
    assert tr is None  # 涨跌停可达性拦截
