from unittest.mock import patch
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import TradeResult


def _fake_trade(bp="均线支撑"):
    return TradeResult(
        buy_point=bp, code="A.SH", name="x", signal_date="20240101",
        entry_date="20240102", entry_price=10.0, exit_date="20240105",
        exit_price=12.0, exit_reason="大胜利", mfp_pct=22.0, hold_days=3,
        pnl_pct=20.0, success=True,
    )


def test_run_winrate_scan_returns_stats_and_trades():
    from services.dashboard_service import DashboardService
    svc = DashboardService()
    cfg = WinrateConfig(buy_points=["均线支撑"])
    with patch("marketreview.winrate.scan_engine.run_scan",
               return_value=[_fake_trade(), _fake_trade()]):
        stats, trades = svc.run_winrate_scan(cfg)
    assert len(trades) == 2
    assert stats["均线支撑"].n == 2
    assert stats["均线支撑"].win_rate == 1.0
