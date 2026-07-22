"""买点胜率回测配置解析。key=value 文本，# 注释，沿用项目风格。"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from pathlib import Path

# 买点状态（单一真相源，胜率侧）：
#   live=启用（个股页+胜率）  trial=实验中（仅胜率）  disabled=停用（不出现）
# 实盘侧（tools/buy_points.py 的 find_all_buy_points）另有一份 checker.STAGE，需与此保持一致。
BUY_POINT_STAGE = {
    "回调一半": "trial",            # 普通版（非严格），与严格版一起 trial 对比
    "回调一半严格": "live",           # 严格条件，5%过滤不成立（被砍信号胜率更高31%→保留）
    "回调一半严格5%": "trial",        # 分析结论：5%过滤砍掉的反而是高弹性反弹（胜率31.3% vs 25.5%）
    "波段50%": "live",
    "量价节点": "trial",             # → 被严格2%版替代（盈亏比1.36 vs 2.35）
    "量价节点上浮2%": "trial",
    "量价节点严格": "trial",          # → 被2%版替代（盈亏比1.40 vs 2.35）
    "量价节点严格上浮2%": "live",      # 盈亏比2.35，紧止损+严格过滤，最优量价变体
    "缩转放": "trial",                  # ETF 量能驱动：放量上涨阳线收盘进场，盘中止损版
    "缩转放收盘止损": "trial",          # ETF 量能驱动：纯收盘止损版（盘中不动，收盘<信号日low才走）
    "20日突破": "trial",               # ETF 通道突破战法，收盘>20日高点买入、<20日低点卖出
    "海龟S1": "trial",                  # 海龟系统S1，突破20日高买入、跌破10日低卖出
    "海龟S2": "trial",                  # 海龟系统S2，突破55日高买入、跌破20日低卖出
    "随机基准": "trial",
    # ── MA 家族全部禁用（胜率仅比随机高 0.6~3.5pp，无实用价值）──
    "MA240支撑": "disabled",
    "扣抵量均线支撑": "disabled",
    "5日均量均线支撑": "disabled",
    "无量均线支撑": "disabled",
    "MA20支撑": "disabled",
    "MA55支撑": "disabled",
    "MA60支撑": "disabled",
    "MA120支撑": "disabled",
    "MA144支撑": "disabled",
}

# ETF/行业指数 版可测买点（绕过 BUY_POINT_STAGE 的 disabled 门槛）。
# MA 家族在 ETF 实测无效（6个不如随机/2个打平/1个略好且吃beta），ETF 版也已关闭。
# 共 6 个：量价节点 + 缩转放两版 + 20日突破 + 海龟S1/S2 + 随机基准。
ETF_BUY_POINTS = [
    "量价节点", "缩转放", "缩转放收盘止损", "20日突破", "海龟S1", "海龟S2", "随机基准",
]

# 展示/扫描顺序（含全部；disabled 会被 ALL_BUY_POINTS 过滤掉，改状态即可重新启用）
_BUY_POINT_ORDER = [
    "回调一半", "回调一半严格", "回调一半严格5%", "波段50%",
    "量价节点", "量价节点上浮2%", "量价节点严格", "量价节点严格上浮2%",
    "缩转放", "缩转放收盘止损", "20日突破", "海龟S1", "海龟S2",
    "MA240支撑", "随机基准",
    "扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑",
    "MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑",
]

# 胜率页可选项 / 默认扫描集 = 非 disabled
ALL_BUY_POINTS = [n for n in _BUY_POINT_ORDER if BUY_POINT_STAGE.get(n, "live") != "disabled"]


@dataclass
class WinrateConfig:
    buy_points: list[str] = field(default_factory=lambda: list(ALL_BUY_POINTS))
    # 判赢与止盈
    win_threshold_pct: float = 10.0
    big_win_pct: float = 20.0
    small_win_floor_pct: float = 5.0
    # 通用止损
    space_stop_pct: float = 5.0
    use_atr_stop: bool = False
    atr_multiplier: float = 2.0
    time_stop_days: int = 20
    # 进场
    open_chase_cap_pct: float = 102.0
    # 扫描范围
    start_date: str = "20230921"
    end_date: str = "now"
    # 过滤器
    short_ma_states: list[str] = field(default_factory=list)          # 空=不限；多头/空头/盘整 可多选
    long_ma_states: list[str] = field(default_factory=lambda: ["多头"])
    mv_min_yi: float = 0.0           # 0 = 不限下限
    mv_max_yi: float = 0.0           # 0 = 不限上限
    industry_whitelist: list[str] = field(default_factory=list)
    min_list_days: int = 250
    # 运行
    max_workers: int = 1
    # 调试：填 ts_code 只跑单只（绕过 is_st），留空=全市场
    debug_code: str = ""
    # 标的类型 / ETF 模式专用
    asset_class: str = "stock"       # "stock" | "index"
    index_pool: list[str] = field(default_factory=list)  # ETF 模式选中的指数 ts_code
    entry_mode: str = "limit"        # "limit"=条件单等回踩 | "close"=收盘价进场（预留，第一版不实现）


def default_winrate_config(asset_class: str = "stock") -> WinrateConfig:
    cfg = WinrateConfig()
    if asset_class == "index":
        cfg = replace(cfg, asset_class="index", buy_points=list(ETF_BUY_POINTS))
    return cfg


def cap_bucket(mv_yi: float) -> str:
    if mv_yi < 100:
        return "微盘"
    if mv_yi < 300:
        return "小盘"
    if mv_yi < 600:
        return "中盘"
    return "大盘"


_KEY_MAP = {
    "判赢阈值%": ("win_threshold_pct", float),
    "大胜利止盈%": ("big_win_pct", float),
    "小胜利回落止盈%": ("small_win_floor_pct", float),
    "空间止损幅度%": ("space_stop_pct", float),
    "启用ATR止损": ("use_atr_stop", "bool"),
    "ATR倍数": ("atr_multiplier", float),
    "时间止损天数": ("time_stop_days", int),
    "开盘追高上限%": ("open_chase_cap_pct", float),
    "开始日期": ("start_date", str),
    "结束日期": ("end_date", str),
    "短期均线排列": ("short_ma_states", "list"),
    "长期均线排列": ("long_ma_states", "list"),
    "市值下限亿": ("mv_min_yi", float),
    "市值上限亿": ("mv_max_yi", float),
    "行业白名单": ("industry_whitelist", "list"),
    "上市最短天数": ("min_list_days", int),
    "并发数": ("max_workers", int),
    "调试标的": ("debug_code", str),
}


def _coerce(kind, val: str):
    if kind == "bool":
        return val.strip() in ("是", "true", "True", "1", "yes")
    if kind == "list":
        return [x.strip() for x in val.split("|") if x.strip()]
    if kind is float:
        return float(val) if val.strip() != "" else 0.0
    if kind is int:
        return int(float(val)) if val.strip() != "" else 0
    return val.strip()


def parse_winrate_config(path: str | Path, asset_class: str = "stock") -> WinrateConfig:
    path = Path(path)
    cfg = default_winrate_config(asset_class)
    if not path.exists():
        return cfg
    updates = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            entry = _KEY_MAP.get(k.strip())
            if not entry:
                continue
            field_name, kind = entry
            updates[field_name] = _coerce(kind, v)
    return replace(cfg, **updates)
