"""单笔交易模拟器 — 条件单进场 + 逐日出场，无仓位无资金。纯函数。"""
from __future__ import annotations
from dataclasses import dataclass

from .config import WinrateConfig, cap_bucket  # noqa: F401  (cap_bucket 由 scan 用)


def board_limit_pct(code: str) -> float:
    """次日涨跌停幅度。"""
    c = code.split(".")[0]
    if c.startswith(("300", "301", "688")):
        return 0.20
    if c.startswith(("8", "4")):  # 北交所
        return 0.30
    return 0.10


@dataclass
class BuyPointSignal:
    buy_point: str
    target_price: float
    close_stop_kind: str = "entry"   # "entry" | "ma" | "fixed"
    close_stop_period: int = 0       # ma 时用（60/120/240）
    intraday_stop_price: float = 0.0  # >0 时：绝对盘中止损价（量价节点=节点成本），覆盖全局空间/ATR止损
    reason: str = ""


@dataclass
class TradeResult:
    buy_point: str
    code: str
    name: str
    signal_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    mfp_pct: float
    hold_days: int
    pnl_pct: float
    success: bool
    reason: str = ""                 # 买入理由（哪个买点/节点/均线），由 checker 生成
    # 上下文标签（由 scan_engine 回填）
    short_ma_state: str = ""
    long_ma_state: str = ""
    market_cap_yi: float = 0.0
    cap_bucket: str = ""
    industry_l1: str = ""
    industry_l2: str = ""
    # 3浪3 市场趋势状态（按 signal_date 查 21 天 count 序列算，市场层标签）
    wave33_direction: str = ""   # "up" | "down" | "flat"
    wave33_streak: int = 0       # 连续天数
    wave33_label: str = ""       # "确认上升，连续上升 5 天" 等
    wave33_sma3: float = 0.0     # SMA(3) 平滑后的 count
    wave33_sma3_dir: str = ""    # SMA3 方向 "up"|"down"|"flat" (t vs t-1)
    # KD80 市场广度趋势（简化版 3浪3，K>80 连续3天 → 日度量 → SMA3）
    kd80_count: int = 0          # signal_date 当天 KD80 raw count
    kd80_sma3: float = 0.0       # KD80 SMA(3) 平滑值
    kd80_sma3_dir: str = ""      # SMA3 方向 "up"|"down"|"flat" (t vs t-1)


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def simulate_trade(signal: BuyPointSignal, signal_idx: int,
                   klines_asc: list[dict], cfg: WinrateConfig,
                   code: str, name: str, atr_at_signal: float) -> TradeResult | None:
    target = signal.target_price
    if target <= 0:
        return None
    sig_row = klines_asc[signal_idx]
    sig_close = _f(sig_row.get("close"))
    if sig_close <= 0:
        return None

    # ⑤ 挂单前涨跌停可达性：目标价必须落在次日涨跌停幅度内
    limit = board_limit_pct(code)
    if target < sig_close * (1 - limit) or target > sig_close * (1 + limit):
        return None

    entry_idx = signal_idx + 1
    if entry_idx >= len(klines_asc):
        return None

    # ② / ③ 成交
    er = klines_asc[entry_idx]
    o, h, l = _f(er.get("open")), _f(er.get("high")), _f(er.get("low"))
    cap_price = target * cfg.open_chase_cap_pct / 100.0
    if o > target and o <= cap_price:
        entry_price = o
    elif l <= target <= h:
        entry_price = target
    else:
        return None  # 未成交/跳空过上限

    entry_date = str(er.get("date"))
    # 空间止损价
    if signal.intraday_stop_price > 0:
        stop_price = signal.intraday_stop_price           # 量价节点：绝对止损价=节点成本
    elif cfg.use_atr_stop and atr_at_signal > 0:
        stop_price = entry_price - cfg.atr_multiplier * atr_at_signal
    else:
        stop_price = entry_price * (1 - cfg.space_stop_pct / 100.0)
    big_price = entry_price * (1 + cfg.big_win_pct / 100.0)
    small_price = entry_price * (1 + cfg.small_win_floor_pct / 100.0)

    # MFP 从建仓当日起（含 entry day high），但出场从 entry_idx+1 起（T+1）
    mfp = max(0.0, (h - entry_price) / entry_price * 100.0)
    armed = mfp >= cfg.win_threshold_pct

    def _mk(exit_idx, exit_price, reason):
        exit_row = klines_asc[exit_idx]
        mfp_final = max(mfp, (_f(exit_row.get("high")) - entry_price) / entry_price * 100.0)
        return TradeResult(
            buy_point=signal.buy_point, code=code, name=name,
            signal_date=str(sig_row.get("date")),
            entry_date=entry_date, entry_price=round(entry_price, 3),
            exit_date=str(exit_row.get("date")), exit_price=round(exit_price, 3),
            exit_reason=reason,
            mfp_pct=round(mfp_final, 2),
            hold_days=exit_idx - entry_idx,
            pnl_pct=round((exit_price - entry_price) / entry_price * 100.0, 2),
            success=mfp_final >= cfg.win_threshold_pct,
            reason=signal.reason,
        )

    for i in range(entry_idx + 1, len(klines_asc)):
        row = klines_asc[i]
        oo, hh, ll, cc = _f(row.get("open")), _f(row.get("high")), _f(row.get("low")), _f(row.get("close"))

        # 开盘（先止损）
        if oo <= stop_price:
            return _mk(i, oo, "盘中止损")
        if oo >= big_price:
            return _mk(i, oo, "大胜利")
        if armed and oo <= small_price:
            return _mk(i, oo, "小胜利")

        # 盘中：先更新 MFP，再判（先止损）
        cur = (hh - entry_price) / entry_price * 100.0
        if cur > mfp:
            mfp = cur
        if mfp >= cfg.win_threshold_pct:
            armed = True
        if ll <= stop_price:
            return _mk(i, stop_price, "盘中止损")
        if hh >= big_price:
            return _mk(i, big_price, "大胜利")
        if armed and ll <= small_price:
            return _mk(i, small_price, "小胜利")

        # 收盘
        hold_days = i - entry_idx
        if hold_days >= cfg.time_stop_days:
            return _mk(i, cc, "时间止损")
        if signal.close_stop_kind == "ma":
            cs = _f(row.get(f"ma{signal.close_stop_period}"))
        elif signal.close_stop_kind == "fixed":
            cs = signal.intraday_stop_price   # 量价节点：收盘也看节点成本
        else:
            cs = entry_price
        if cs > 0 and cc < cs:
            return _mk(i, cc, "收盘止损")

    # 数据到底仍未触发任何出场 → 右删失（观察期被截断），不计样本
    return None
