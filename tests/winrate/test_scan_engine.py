from marketreview.winrate.config import WinrateConfig
from marketreview.winrate import scan_engine as SE


def _row(date, o, h, l, c, amount=1.0):
    # 不复权价（raw_to_qfq 需 adj_factor），这里给 adj_factor=1 避免复权改动
    return {"date": date, "open": o, "high": h, "low": l, "close": c,
            "vol": 1.0, "amount": amount, "adj_factor": 1.0, "asset_type": "stock"}


def test_prepare_klines_adds_ma_keys():
    rows_desc = [_row(f"2024{m:02d}{d:02d}", 10, 10, 10, 10)
                 for m in range(1, 4) for d in range(1, 29)][::-1]  # DESC
    ks = SE.prepare_klines(rows_desc)
    assert ks[0]["date"] <= ks[-1]["date"]          # ASC
    assert "ma5" in ks[-1] and "ma20" in ks[-1]


def test_scan_stock_no_signal_when_flat_series():
    # 全平的序列不会触发任何买点 → 空结果，且不报错
    cfg = WinrateConfig(min_list_days=0, long_ma_states=[],
                        short_ma_states=[])
    rows_desc = [_row(f"202401{d:02d}", 10, 10, 10, 10) for d in range(1, 29)][::-1]
    trades = SE.scan_stock("600000.SH", "测试", rows_desc, cfg,
                           "电子", "半导体", "", "20200101",
                           mv_series={r["date"]: 150.0 for r in rows_desc})
    assert isinstance(trades, list)
