from pathlib import Path
from marketreview.winrate.config import (
    WinrateConfig, default_winrate_config, parse_winrate_config, cap_bucket,
)


def test_defaults():
    c = default_winrate_config()
    assert c.win_threshold_pct == 10.0
    assert c.big_win_pct == 20.0
    assert c.small_win_floor_pct == 5.0
    assert c.space_stop_pct == 5.0
    assert c.use_atr_stop is False
    assert c.atr_multiplier == 2.0
    assert c.time_stop_days == 20
    assert c.open_chase_cap_pct == 102.0
    assert c.long_ma_arrange == "多头"
    assert c.short_ma_arrange == "无关"
    assert c.buy_points == ["均线支撑", "回调一半", "波段50%"]


def test_cap_bucket():
    assert cap_bucket(50) == "微盘"
    assert cap_bucket(100) == "小盘"
    assert cap_bucket(299) == "小盘"
    assert cap_bucket(300) == "中盘"
    assert cap_bucket(599) == "中盘"
    assert cap_bucket(600) == "大盘"
    assert cap_bucket(1200) == "大盘"


def test_parse_overrides(tmp_path):
    p = tmp_path / "winrate_config.txt"
    p.write_text(
        "判赢阈值%=8\n"
        "启用ATR止损=是\n"
        "ATR倍数=3\n"
        "时间止损天数=15\n"
        "长期均线排列=空头\n"
        "市值下限亿=100\n"
        "行业白名单=电子|计算机\n"
        "上市最短天数=300\n",
        encoding="utf-8",
    )
    c = parse_winrate_config(p)
    assert c.win_threshold_pct == 8.0
    assert c.use_atr_stop is True
    assert c.atr_multiplier == 3.0
    assert c.time_stop_days == 15
    assert c.long_ma_arrange == "空头"
    assert c.mv_min_yi == 100.0
    assert c.industry_whitelist == ["电子", "计算机"]
    assert c.min_list_days == 300


def test_parse_missing_file_returns_defaults(tmp_path):
    c = parse_winrate_config(tmp_path / "nope.txt")
    assert c == default_winrate_config()
