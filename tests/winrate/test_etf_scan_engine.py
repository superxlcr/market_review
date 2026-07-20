from marketreview.winrate.scan_engine import prepare_klines
from marketreview.winrate.config import WinrateConfig


def test_prepare_klines_index_no_qfq():
    """index 模式：adj_factor 不是 1.0 时也不做 qfq（直接用 raw close）。
    构造 raw close=100 但 adj_factor=0.5 → 若错误 qfq 会变 50，index 应保持 100。"""
    rows_desc = [
        {"date": "2026010%d" % i, "open": 100, "high": 101, "low": 99,
         "close": 100, "vol": 1000, "amount": 100000, "adj_factor": 0.5}
        for i in range(1, 70)
    ]
    klines = prepare_klines(rows_desc, asset_class="index")
    assert len(klines) > 0
    # index 不 qfq → close 保持 raw 100，不是 qfq 后的 50
    assert klines[-1]["close"] == 100


def test_prepare_klines_stock_does_qfq():
    """stock 模式：会调 raw_to_qfq（相对最新 adj_factor 复权）。
    构造：最新行 adj_factor=1.0、早期行 adj_factor=0.5 → qfq 后早期 close 翻倍=200。
    index 模式同数据则保持 raw=100。"""
    rows_desc = [
        {"date": "2026010%d" % i, "open": 100, "high": 101, "low": 99,
         "close": 100, "vol": 1000, "amount": 100000, "adj_factor": 0.5}
        for i in range(1, 69)
    ] + [
        {"date": "20260309", "open": 100, "high": 101, "low": 99,
         "close": 100, "vol": 1000, "amount": 100000, "adj_factor": 1.0}  # 最新行=复权基准
    ]
    klines_stock = prepare_klines(rows_desc, asset_class="stock")
    klines_index = prepare_klines(rows_desc, asset_class="index")
    # 早期行 adj_factor=0.5, latest=1.0 → qfq=100*0.5/1.0=50
    assert klines_stock[0]["close"] == 50.0
    # index 不 qfq → 早期行保持 raw 100
    assert klines_index[0]["close"] == 100


def test_scan_stock_index_path_runs():
    """index 模式 scan_stock 端到端不报错（用合成 K 线，无真实买点触发也 OK）。"""
    from marketreview.winrate.scan_engine import scan_stock
    rows_desc = [
        {"date": "2026010%d" % i, "open": 100, "high": 101, "low": 99,
         "close": 100, "vol": 1000, "amount": 100000, "adj_factor": 1.0}
        for i in range(1, 320)
    ]
    cfg = WinrateConfig(asset_class="index", buy_points=["波段50%"],
                        long_ma_states=[], short_ma_states=[], min_list_days=0,
                        start_date="20260101", end_date="now",
                        time_stop_days=13)
    # 不应抛异常（可能返回空 list）
    results = scan_stock("931152.CSI", "CS创新药", rows_desc, cfg,
                         industry_l1="", industry_l2="", industry_l3="",
                         list_date="20190422", mv_series={},
                         asset_class="index")
    assert isinstance(results, list)


def test_run_scan_index_uses_index_pool(tmp_path):
    """run_scan 在 index 模式从 cfg.index_pool 取标的，不查 stock_basic/industry/concept。"""
    from marketreview.winrate import scan_engine
    from marketreview.winrate.scan_engine import run_scan

    cfg = WinrateConfig(asset_class="index", index_pool=["931152.CSI"],
                        buy_points=["波段50%"], long_ma_states=[],
                        short_ma_states=[], min_list_days=0,
                        start_date="20260101", end_date="now",
                        time_stop_days=13, max_workers=1)

    # mock DataProvider：cache.get_daily 返回空（scan_stock 会因 n<60 返回 []）
    dp = scan_engine.DataProvider.__new__(scan_engine.DataProvider)
    dp.cache = type("C", (), {
        "get_daily": lambda self, code, limit=2000: [],
        "has_concepts": lambda self: False,
        "get_stock_basic": lambda self: [],
        "get_stock_industries": lambda self, codes: {},
    })()

    results = run_scan(dp, cfg)
    assert results == []  # 空 K 线 → 无交易
    # 关键：走 index_pool 路径不抛异常（不依赖 stock_basic/industry/concept）
