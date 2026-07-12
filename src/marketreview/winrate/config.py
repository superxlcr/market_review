"""买点胜率回测配置解析。key=value 文本，# 注释，沿用项目风格。"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from pathlib import Path

# 买点状态（单一真相源，胜率侧）：
#   live=启用（个股页+胜率）  trial=实验中（仅胜率）  disabled=停用（不出现）
# 实盘侧（tools/buy_points.py 的 find_all_buy_points）另有一份 checker.STAGE，需与此保持一致。
BUY_POINT_STAGE = {
    "回调一半": "live",
    "波段50%": "live",
    "量价节点": "live",           # 买拉回：波段上升腿放量节点，跌破成本止损
    "MA240支撑": "live",          # MA 家族唯一幸存（长均中性 edge +5.4）
    "回调一半严格": "trial",       # 原始定义：回调谷底跌破50%线即趋势已改变，不再触发
    "量价节点上浮2%": "trial",     # 量价节点变体：进场成本×1.02（默认版×1.04），其它不变
    "随机基准": "trial",          # 无技能对照：市价随机，校准其它买点胜率
    "扣抵量均线支撑": "disabled",
    "5日均量均线支撑": "disabled",
    "无量均线支撑": "disabled",
    "MA20支撑": "disabled",
    "MA55支撑": "disabled",
    "MA60支撑": "disabled",
    "MA120支撑": "disabled",
    "MA144支撑": "disabled",
}

# 展示/扫描顺序（含全部；disabled 会被 ALL_BUY_POINTS 过滤掉，改状态即可重新启用）
_BUY_POINT_ORDER = [
    "回调一半", "回调一半严格", "波段50%", "量价节点", "量价节点上浮2%", "MA240支撑", "随机基准",
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
    max_workers: int = 10
    # 调试：填 ts_code 只跑单只（绕过 is_st），留空=全市场
    debug_code: str = ""


def default_winrate_config() -> WinrateConfig:
    return WinrateConfig()


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


def parse_winrate_config(path: str | Path) -> WinrateConfig:
    path = Path(path)
    cfg = default_winrate_config()
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
