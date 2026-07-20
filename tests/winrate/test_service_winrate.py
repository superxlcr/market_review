from unittest.mock import patch, MagicMock
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import TradeResult


def _fake_trade(bp="扣抵量均线支撑"):
    return TradeResult(
        buy_point=bp, code="A.SH", name="x", signal_date="20240101",
        entry_date="20240102", entry_price=10.0, exit_date="20240105",
        exit_price=12.0, exit_reason="大胜利", mfp_pct=22.0, hold_days=3,
        pnl_pct=20.0, success=True,
    )


def test_run_winrate_scan_returns_stats_and_trades():
    from services.dashboard_service import DashboardService
    svc = DashboardService()
    cfg = WinrateConfig(buy_points=["扣抵量均线支撑"])
    with patch("marketreview.winrate.scan_engine.run_scan",
               return_value=[_fake_trade(), _fake_trade()]):
        stats, trades = svc.run_winrate_scan(cfg)
    assert len(trades) == 2
    assert stats["扣抵量均线支撑"].n == 2
    assert stats["扣抵量均线支撑"].win_rate == 1.0


def test_service_etf_methods_exist():
    """DashboardService 有 3 个 ETF 方法。"""
    from services.dashboard_service import DashboardService
    assert hasattr(DashboardService, "prepare_winrate_data_etf")
    assert hasattr(DashboardService, "check_winrate_coverage_etf")
    assert hasattr(DashboardService, "run_winrate_scan_etf")


def test_check_winrate_coverage_etf_returns_ready_flag():
    """check_winrate_coverage_etf 调 ensure_csi_pool + 覆盖检查，返回 ready 标志。"""
    from services.dashboard_service import DashboardService
    svc = DashboardService.__new__(DashboardService)
    svc._dp = MagicMock()
    svc._dp.ensure_csi_pool.return_value = 5
    # 模拟指数已缓存覆盖 [start, end]
    svc._dp.cache.get_latest_date.return_value = "2026-07-19"
    svc._dp.cache.get_earliest_date.return_value = "2022-01-01"
    res = svc.check_winrate_coverage_etf("20230101", "now",
                                         index_pool=["931152.CSI"])
    assert "ready" in res
    assert "kline" in res


def test_run_winrate_scan_etf_uses_run_scan():
    """run_winrate_scan_etf 复用 run_scan + aggregate。"""
    from services.dashboard_service import DashboardService
    svc = DashboardService()
    cfg = WinrateConfig(asset_class="index", buy_points=["波段50%"])
    with patch("marketreview.winrate.scan_engine.run_scan",
               return_value=[_fake_trade("波段50%")]):
        stats, trades = svc.run_winrate_scan_etf(cfg)
    assert len(trades) == 1
    assert stats["波段50%"].n == 1

