from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import TradeResult
from marketreview.winrate import reporter as R


def _tr(bp, code, reason, pnl, mfp, success, hold=3):
    return TradeResult(
        buy_point=bp, code=code, name="x", signal_date="20240101",
        entry_date="20240102", entry_price=10.0, exit_date="20240105",
        exit_price=10 * (1 + pnl / 100), exit_reason=reason, mfp_pct=mfp,
        hold_days=hold, pnl_pct=pnl, success=success,
    )


def test_aggregate_counts_and_rates():
    trades = [
        _tr("扣抵量均线支撑", "A.SH", "大胜利", 20, 22, True),
        _tr("扣抵量均线支撑", "B.SH", "小胜利", 5, 12, True),
        _tr("扣抵量均线支撑", "C.SH", "盘中止损", -5, 3, False),
        _tr("扣抵量均线支撑", "D.SH", "收盘止损", -2, 4, False),
        _tr("回调一半", "E.SH", "大胜利", 20, 25, True),
    ]
    stats = R.aggregate(trades)
    ma = stats["扣抵量均线支撑"]
    assert ma.n == 4
    assert ma.big_win_n == 1
    assert ma.small_win_n == 1
    assert ma.stop_n == 1          # 盘中止损
    assert ma.loss_n == 1          # 收盘止损且 pnl<0
    assert round(ma.win_rate, 3) == 0.5     # (1+1)/4
    assert round(ma.expectancy_pct, 2) == round((20 + 5 - 5 - 2) / 4, 2)
    assert stats["回调一半"].n == 1


def test_export_rows_sorted_by_code(tmp_path):
    trades = [
        _tr("扣抵量均线支撑", "B.SH", "大胜利", 20, 22, True),
        _tr("扣抵量均线支撑", "A.SH", "小胜利", 5, 12, True),
        _tr("回调一半", "Z.SH", "大胜利", 20, 22, True),  # 应被过滤掉
    ]
    rows = R.export_rows(trades, "扣抵量均线支撑")
    assert [r["code"] for r in rows] == ["A.SH", "B.SH"]


def test_export_csv_writes_config_header(tmp_path):
    cfg = WinrateConfig()
    trades = [_tr("扣抵量均线支撑", "A.SH", "大胜利", 20, 22, True)]
    out = tmp_path / "x.csv"
    R.export_csv(trades, cfg, "扣抵量均线支撑", out)
    text = out.read_text(encoding="utf-8-sig")
    assert "判赢阈值" in text or "win_threshold_pct" in text
    assert "A.SH" in text


def test_export_fields_include_wave33():
    """CSV 导出字段含 wave33 三列。"""
    assert "wave33_direction" in R._EXPORT_FIELDS
    assert "wave33_streak" in R._EXPORT_FIELDS
    assert "wave33_label" in R._EXPORT_FIELDS
