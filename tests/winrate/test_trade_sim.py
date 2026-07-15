from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import (
    BuyPointSignal, simulate_trade, board_limit_pct,
)


def _k(date, o, h, l, c, **ma):
    row = {"date": date, "open": o, "high": h, "low": l, "close": c}
    row.update({k: v for k, v in ma.items()})
    return row


def _entry_sig(target=10.0):
    # 回调一半类：收盘止损=跌破买入价
    return BuyPointSignal(buy_point="回调一半", target_price=target,
                          close_stop_kind="entry", close_stop_period=0,
                          reason="test")


def test_board_limit_pct():
    assert board_limit_pct("600000.SH") == 0.10
    assert board_limit_pct("300750.SZ") == 0.20
    assert board_limit_pct("688111.SH") == 0.20
    assert board_limit_pct("830799.BJ") == 0.30


def test_not_filled_returns_none():
    # 信号日收盘10；次日最低10.5，从未触及目标10 → 未成交
    cfg = WinrateConfig()
    klines = [
        _k("20240101", 10, 10, 10, 10.0),   # signal idx=0
        _k("20240102", 10.5, 11, 10.5, 10.8),  # never touches 10
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r is None


def test_big_win_intraday():
    # 目标10成交，之后某日 high 达 12(=+20%) → 大胜利，卖在12
    cfg = WinrateConfig()
    klines = [
        _k("20240101", 10, 10, 10, 10.0),      # signal idx=0
        _k("20240102", 10, 10.2, 9.9, 10.0),   # entry@10 (low<=10<=high)
        _k("20240103", 10.5, 12.5, 10.4, 11.0),  # high 12.5 >= 12 → 大胜利 @12
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r is not None
    assert r.entry_price == 10.0
    assert r.exit_reason == "大胜利"
    assert round(r.exit_price, 2) == 12.0
    assert r.success is True
    assert round(r.pnl_pct, 1) == 20.0


def test_small_win_pullback():
    # 摸到 +10%(mfp) 后回落到 +5% → 小胜利，卖在10.5
    cfg = WinrateConfig()
    klines = [
        _k("20240101", 10, 10, 10, 10.0),        # signal
        _k("20240102", 10, 10.0, 9.95, 10.0),    # entry@10
        _k("20240103", 10.5, 11.2, 10.4, 11.0),  # high11.2 → mfp=12% armed（未到20%）
        _k("20240104", 10.8, 10.9, 10.4, 10.6),  # low10.4 <= 10.5 → 小胜利 @10.5
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "小胜利"
    assert round(r.exit_price, 2) == 10.5
    assert r.success is True


def test_space_stop_priority_over_take_profit():
    # 同日 low 破止损 且 high 达大胜利 → 先止损
    cfg = WinrateConfig(space_stop_pct=5.0)  # 止损价=10*0.95=9.5
    klines = [
        _k("20240101", 10, 10, 10, 10.0),
        _k("20240102", 10, 10.0, 9.96, 10.0),   # entry@10
        _k("20240103", 10, 12.5, 9.4, 10.0),    # low9.4<=9.5止损 且 high12.5>=12 → 先止损@9.5
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "盘中止损"
    assert round(r.exit_price, 2) == 9.5


def test_close_stop_entry_kind():
    # 无止盈无空间止损触发，但收盘跌破买入价 → 收盘止损
    cfg = WinrateConfig(space_stop_pct=20.0)  # 止损价8，不触发
    klines = [
        _k("20240101", 10, 10, 10, 10.0),
        _k("20240102", 10, 10.1, 9.9, 10.0),    # entry@10
        _k("20240103", 9.9, 10.0, 9.6, 9.7),    # close9.7<entry10 → 收盘止损@9.7
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "收盘止损"
    assert round(r.exit_price, 2) == 9.7
    assert r.success is False


def test_time_stop():
    cfg = WinrateConfig(space_stop_pct=50.0, time_stop_days=2)
    klines = [_k("20240101", 10, 10, 10, 10.0), _k("20240102", 10, 10.1, 9.9, 10.0)]  # entry idx1
    # 之后横盘，持有到第2天触发时间止损
    klines += [
        _k("20240103", 10, 10.1, 9.9, 10.0),  # hold_days=1
        _k("20240104", 10, 10.1, 9.9, 10.0),  # hold_days=2 → 时间止损@close10
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "时间止损"
    assert r.hold_days == 2


def test_atr_stop_used_when_enabled():
    # 启用ATR：止损=entry-2*atr=10-2*0.3=9.4
    cfg = WinrateConfig(use_atr_stop=True, atr_multiplier=2.0)
    klines = [
        _k("20240101", 10, 10, 10, 10.0),
        _k("20240102", 10, 10.0, 9.96, 10.0),   # entry@10
        _k("20240103", 9.9, 10.0, 9.3, 9.8),    # low9.3<=9.4 → 盘中止损@9.4
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "盘中止损"
    assert round(r.exit_price, 2) == 9.4


def test_trade_result_wave33_fields_default_empty():
    """TradeResult 新增 wave33 三字段，默认空/0。"""
    from marketreview.winrate.trade_sim import TradeResult
    tr = TradeResult(
        buy_point="回调一半", code="600000.SH", name="测试",
        signal_date="20240101", entry_date="20240102", entry_price=10.0,
        exit_date="20240105", exit_price=10.5, exit_reason="小胜利",
        mfp_pct=12.0, hold_days=3, pnl_pct=5.0, success=True,
    )
    assert tr.industry_l3 == ""
    assert tr.concept_i == ""
    assert tr.concept_n == ""
