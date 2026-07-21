"""单笔交易模拟器 — 条件单进场 + 逐日出场，无仓位无资金。纯函数。"""
from __future__ import annotations
from dataclasses import dataclass

from .config import WinrateConfig, cap_bucket  # noqa: F401  (cap_bucket 由 scan 用)


def board_limit_pct(code: str, asset_class: str = "stock") -> float:
    """次日涨跌停幅度。
    stock: 按板块（300/301/688→20%, 8/4北交所→30%, 其余10%）。
    index: 指数无涨跌停，返回 1.0（100%）= 条件单可达性恒通过。"""
    if asset_class == "index":
        return 1.0
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
    entry_mode: str = "limit"        # "limit"=条件单次日等回踩 | "close"=信号日收盘价成交（权重K）
    strategy: str = "default"        # "default"=止损止盈体系 | "channel20"=通道突破（收盘<20日低点离场）


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
    # 进场日均线位置（收盘价 vs MA），index 模式填充，stock 留空
    ma20_pos: str = ""
    ma20_dist: float = 0.0
    ma60_pos: str = ""
    ma60_dist: float = 0.0
    ma120_pos: str = ""
    ma120_dist: float = 0.0
    ma240_pos: str = ""
    ma240_dist: float = 0.0
    # 以下仅 stock 模式填充，index 留空
    market_cap_yi: float = 0.0
    cap_bucket: str = ""
    industry_l1: str = ""
    industry_l2: str = ""
    industry_l3: str = ""              # 申万三级行业
    concept_i: str = ""                # 同花顺 I 型行业分类
    concept_n: str = ""                # 同花顺 N 型概念标签（竖线分隔）


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def simulate_trade(signal: BuyPointSignal, signal_idx: int,
                   klines_asc: list[dict], cfg: WinrateConfig,
                   code: str, name: str, atr_at_signal: float,
                   asset_class: str = "stock") -> TradeResult | None:
    target = signal.target_price
    if target <= 0:
        return None
    sig_row = klines_asc[signal_idx]
    sig_close = _f(sig_row.get("close"))
    if sig_close <= 0:
        return None

    # ⑤ 挂单前涨跌停可达性：目标价必须落在次日涨跌停幅度内
    # 收盘模式跳过可达性检查（直接以收盘价成交，无需次日挂单）
    if signal.entry_mode != "close":
        limit = board_limit_pct(code, asset_class=asset_class)
        if target < sig_close * (1 - limit) or target > sig_close * (1 + limit):
            return None

    # ② / ③ 成交
    if signal.entry_mode == "close":
        # 权重K战法：信号当天以收盘价直接成交，不等次日
        entry_idx = signal_idx
        entry_price = sig_close
        entry_date = str(sig_row.get("date"))
    else:
        entry_idx = signal_idx + 1
        if entry_idx >= len(klines_asc):
            return None
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
    if signal.entry_mode == "close":
        entry_day_high = sig_row_high = _f(sig_row.get("high"))
    else:
        entry_day_high = h
    mfp = max(0.0, (entry_day_high - entry_price) / entry_price * 100.0)
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

        # 通道突破策略族：纯通道跟随，无止损/止盈，只等反向信号
        # 退出规则：收盘 < 过去N日最低价（不含今天），即跌破N日Donchian下轨
        if signal.strategy in ("channel20", "turtle_s1", "turtle_s2"):
            if signal.strategy == "channel20":
                sell_n = 20
                exit_label = "通道下轨跌破"
            elif signal.strategy == "turtle_s1":
                sell_n = 10
                exit_label = "海龟S1下轨跌破"
            else:  # turtle_s2
                sell_n = 20
                exit_label = "海龟S2下轨跌破"
            # 更新 MFP（通道策略也需追踪浮盈，否则 mfp_final 只算进出两天）
            cur = (hh - entry_price) / entry_price * 100.0
            if cur > mfp:
                mfp = cur
            if mfp >= cfg.win_threshold_pct:
                armed = True
            lo = max(entry_idx + 1, i - sell_n)
            if lo < i:
                low_n = min(_f(klines_asc[j].get("low") or 0) for j in range(lo, i))
                if low_n > 0 and cc < low_n:
                    return _mk(i, cc, exit_label)
            continue

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
        # 指数不设收盘止损：指数只有盘中跌破止损价/时间止损/止盈，无"跌破MA/成本"收盘止损
        if asset_class != "index":
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
