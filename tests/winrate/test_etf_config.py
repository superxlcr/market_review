from pathlib import Path
from marketreview.winrate.config import (
    WinrateConfig, default_winrate_config, parse_winrate_config, ETF_BUY_POINTS,
)


def test_etf_buy_points_has_12():
    # 3 非MA + 9 MA变体
    assert len(ETF_BUY_POINTS) == 12
    for n in ["回调一半", "波段50%", "量价节点",
              "MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑", "MA240支撑",
              "扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑"]:
        assert n in ETF_BUY_POINTS


def test_default_stock_asset_class():
    c = default_winrate_config()
    assert c.asset_class == "stock"
    assert c.index_pool == []
    assert c.entry_mode == "limit"


def test_default_index_asset_class():
    c = default_winrate_config(asset_class="index")
    assert c.asset_class == "index"
    # ETF 默认买点 = ETF_BUY_POINTS
    assert c.buy_points == ETF_BUY_POINTS


def test_parse_etf_config_ignores_market_cap(tmp_path):
    p = tmp_path / "winrate_config_etf.txt"
    p.write_text(
        "判赢阈值%=8\n"
        "上市最短天数=300\n",
        encoding="utf-8",
    )
    c = parse_winrate_config(p, asset_class="index")
    assert c.asset_class == "index"
    assert c.win_threshold_pct == 8.0
    assert c.min_list_days == 300
    # ETF 模式 buy_points 默认 = ETF_BUY_POINTS
    assert c.buy_points == ETF_BUY_POINTS


def test_parse_stock_config_default_asset_class(tmp_path):
    # 不传 asset_class → stock（回归保证）
    p = tmp_path / "winrate_config.txt"
    p.write_text("判赢阈值%=7\n", encoding="utf-8")
    c = parse_winrate_config(p)
    assert c.asset_class == "stock"
    assert c.win_threshold_pct == 7.0


def test_read_real_etf_config_file():
    # 读项目里的真实 ETF 配置文件
    p = Path("config/winrate_config_etf.txt")
    c = parse_winrate_config(p, asset_class="index")
    assert c.asset_class == "index"
    assert c.win_threshold_pct == 10.0
    assert c.space_stop_pct == 5.0
    assert c.time_stop_days == 13
