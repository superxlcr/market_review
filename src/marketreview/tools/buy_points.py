"""买点提示 — 基类+子类架构，便于后续扩展新的买点类型.

Usage:
    from marketreview.tools.buy_points import find_all_buy_points, BuyPoint
    buy_points = find_all_buy_points(df, band)
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import hashlib
import os
import numpy as np

from .band_analysis import BandResult
from .technical import calc_ma, ma_direction, get_offset_info
from ..log_util import get_logger

log = get_logger("buy_points")


# ── 配置读取 ──────────────────────────────────────────────────

def load_buy_point_config() -> dict[str, float]:
    """读取 config/buy_point_config.txt，返回配置字典."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "config", "buy_point_config.txt",
    )
    result: dict[str, float] = {}
    if not os.path.exists(config_path):
        return result
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, val = stripped.split("=", 1)
                try:
                    result[key.strip()] = float(val.strip())
                except ValueError:
                    pass
    return result


@dataclass
class BuyPoint:
    """单个买点."""
    type: str           # "突破" | "重新突破" | "均线支撑"
    position: str       # "回调一半" | "波段50%" | "MA60" | "MA120" | "MA240" | "21日收盘高点"
    price: float        # 买点价格
    distance_pct: float  # (买点价 / 当前价 - 1) × 100，正=买点高于现价
    position_size: str = "—"   # 仓位，待定
    reason: str = ""
    capital_multiplier: float = 1.0  # 仓位资金乘数（1.0=标准仓，0.5=半仓）
    # 止损
    intraday_stop: float = 0.0          # 盘中止损价
    intraday_stop_pct: float = 0.0      # 盘中止损跌幅%
    intraday_stop_reason: str = ""      # "ATR 2.3%" | "10%上限" | "5%固定"
    close_stop: float = 0.0             # 收盘止损价
    close_stop_pct: float = 0.0         # 收盘止损跌幅%
    close_stop_reason: str = ""         # "跌破买入价" | "跌破MA3%" | "跌破MA"


# ── 板块阈值 ──────────────────────────────────────────────────

def _get_board_threshold(ts_code: str) -> float:
    """根据 ts_code 返回 2×涨跌幅过滤阈值（%）."""
    if not ts_code:
        return 20.0
    code = ts_code.split(".")[0]
    if code.startswith("30") or code.startswith("68"):
        return 40.0
    return 20.0


# ── 止损计算 ──────────────────────────────────────────────────

def _calc_stop_losses(bp: BuyPoint, atr_pct: float | None,
                       trend: str, config: dict, ma_val: float = 0.0) -> None:
    """为单个 BuyPoint 计算盘中和收盘止损价."""
    atr_cap = config.get("ATR盘中止损上限", 10.0)
    ma_intraday_pct = config.get("均线盘中止损", 5.0)
    bp_price = bp.price

    if bp.position.startswith("MA"):
        # 均线买点：盘中固定百分比
        bp.intraday_stop_pct = ma_intraday_pct
        bp.intraday_stop = round(bp_price * (1 - ma_intraday_pct / 100), 2)
        bp.intraday_stop_reason = f"{ma_intraday_pct:.0f}%固定"
        # 收盘
        if trend == "up":
            close_stop_price = round(ma_val * 0.97, 2)
            bp.close_stop = close_stop_price
            bp.close_stop_pct = round((ma_val - close_stop_price) / ma_val * 100, 1)
            bp.close_stop_reason = "跌破MA3%（up≤3天）"
        else:
            bp.close_stop = ma_val
            bp.close_stop_pct = 0.0
            bp.close_stop_reason = "跌破MA"
    elif bp.position == "量价节点":
        # 量价节点：自带成本止损（成本-0.01，checker 已算好），不覆盖
        if bp.intraday_stop > 0 and bp_price > 0:
            bp.intraday_stop_pct = round((bp_price - bp.intraday_stop) / bp_price * 100, 1)
        bp.intraday_stop_reason = "跌破成本"
        bp.close_stop = bp.intraday_stop
        bp.close_stop_pct = bp.intraday_stop_pct
        bp.close_stop_reason = "跌破成本"
    else:
        # 回调一半 / 波段50%：固定空间止损（默认5%，读配置 主力盘中止损%；结论=紧止损尾亏更干净）
        pct = config.get("主力盘中止损%", 5.0)
        bp.intraday_stop_pct = round(pct, 1)
        bp.intraday_stop = round(bp_price * (1 - pct / 100), 2)
        bp.intraday_stop_reason = f"{pct:.0f}%空间止损"
        # 收盘：跌破买入价
        bp.close_stop = bp_price
        bp.close_stop_pct = 0.0
        bp.close_stop_reason = "跌破买入价"


# ── MA 跌破 Episode 统计 ──────────────────────────────────────

def compute_ma_probes(df, band, periods: list[int] | None = None):
    """从 P 到今日，统计前日收在MA上方、当日最低跌破MA的探底日.

    条件: 昨日收盘 > 昨日MA 且 今日最低 < 今日MA
    返回: {60: [{date, max_penetration, offset_vs_pct, avg_vs_pct, ma_dir, recovered}, ...], ...}
    """
    if periods is None:
        periods = [60, 120, 240]
    if band.p_idx < 0 or len(df) <= 1:
        return {}

    p_idx = band.p_idx
    mas = calc_ma(df, periods)
    result: dict[int, list[dict]] = {}

    for p in periods:
        ma_key = f"MA{p}"
        ma_full = mas[ma_key]
        probes: list[dict] = []

        for i in range(max(p_idx, 1), len(df)):
            low = float(df["low"].iloc[i])
            ma_val = ma_full[i]
            date = str(df["date"].iloc[i])

            if np.isnan(ma_val):
                continue
            if ma_val <= 0:
                continue

            # 前日收盘是否在 MA 上方
            prev_ma = ma_full[i - 1]
            if np.isnan(prev_ma) or prev_ma <= 0:
                continue
            prev_close = float(df["close"].iloc[i - 1])
            if prev_close <= prev_ma:
                continue

            # 今日最低跌破 MA
            if low < ma_val:
                penetration = round((ma_val - low) / ma_val * 100, 1)
                close = float(df["close"].iloc[i])
                recovered = close >= ma_val

                # 量能上下文
                ctx = _probe_context(df, i, p)
                probes.append({
                    "date": date,
                    "ma_price": round(ma_val, 2),
                    "ma_dir": ctx["ma_dir"],
                    "offset_vs_pct": ctx["offset_vs_pct"],
                    "avg_vs_pct": ctx["avg_vs_pct"],
                    "recovered": recovered,
                    "max_penetration": penetration,
                })

        result[p] = probes

    return result


def _probe_context(df, row_idx: int, period: int) -> dict:
    """为探底日计算量能对比和均线方向."""
    ctx: dict = {
        "offset_vs_pct": None,
        "avg_vs_pct": None,
        "ma_dir": "",
    }
    try:
        df_slice = df.iloc[:row_idx + 1]
        if len(df_slice) < period + 1:
            return ctx
        off = get_offset_info(df_slice, period)
        ctx["offset_vs_pct"] = off.get("vs_today_pct")
        ctx["avg_vs_pct"] = off.get("avg_vs_today_pct")
        mas = calc_ma(df_slice, [period])
        ctx["ma_dir"] = ma_direction(mas[f"MA{period}"])
    except Exception:
        pass
    return ctx


class BaseBuyPointChecker(ABC):
    """买点检查器基类."""

    STAGE = "live"   # "live"=各页面可见；"trial"=试验中，仅买点胜率可见（find_all_buy_points 默认过滤）；"disabled"=停用，哪都不出现

    @abstractmethod
    def check(self, df, band: BandResult) -> list[BuyPoint]:
        """从 K线数据 + 波段结果中提取买点列表."""
        ...


# ── 回调一半买点 ─────────────────────────────────────────────

class HalfRetraceChecker(BaseBuyPointChecker):
    """回调一半位置买点.

    条件: 已跌破62.5%（trigger_625_date 非空）+ 波段幅度成立 + 回调≥13天.

    strict=True（回调一半严格，原始定义）: 额外要求「回调谷底未跌破50%线」——
    一旦回调最低点跌破波段50%线，趋势按定义已改变，此处合理买点应是波段50%而非回调一半。
    """

    def __init__(self, strict: bool = False):
        self.strict = strict
        self.STAGE = "trial" if strict else "live"

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if not band.trigger_625_date:
            return []
        if not band.v_qualified:
            return []
        pullback_days = band.rows_count - 1 - band.p_idx
        if pullback_days < 13:
            return []

        # 严格版：回调谷底跌破50%线 → 趋势已改变 → 不触发
        if self.strict and band.line_50 > 0 and band.l_price < band.line_50:
            return []

        hr_latest = band.half_retrace_series[-1]["price"] if band.half_retrace_series else 0.0
        if hr_latest <= 0:
            return []

        cur = band.current_price
        dist = round((hr_latest / cur - 1) * 100, 1)

        if cur < hr_latest:
            bp_type = "突破"
        else:
            bp_type = "重新突破"

        prefix = "[严格] " if self.strict else ""
        reason = f"{prefix}回调{pullback_days}天 ≥ 13天，且跌破过波段 62.5% {band.line_625:.2f}"

        return [BuyPoint(
            type=bp_type,
            position="回调一半",
            price=hr_latest,
            distance_pct=dist,
            reason=reason,
        )]


# ── 波段50%买点 ─────────────────────────────────────────────

class Band50Checker(BaseBuyPointChecker):
    """波段50%位置买点.

    条件: 已跌破62.5%（trigger_625_date 非空）+ 波段幅度成立 + 回调≥13天.
    价格: band.line_50（趋势生命线，静态 = (P+V)/2）
    """

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if not band.trigger_625_date:
            return []
        if not band.v_qualified:
            return []
        pullback_days = band.rows_count - 1 - band.p_idx
        if pullback_days < 13:
            return []

        line_50 = band.line_50
        if line_50 <= 0:
            return []

        cur = band.current_price
        dist = round((line_50 / cur - 1) * 100, 1)

        if cur < line_50:
            bp_type = "突破"
        else:
            bp_type = "重新突破"

        reason = f"回调{pullback_days}天 ≥ 13天，且跌破过波段 62.5% {band.line_625:.2f}"

        return [BuyPoint(
            type=bp_type,
            position="波段50%",
            price=line_50,
            distance_pct=dist,
            reason=reason,
        )]


# ── 21日高点买点 ─────────────────────────────────────────────

class High21Checker(BaseBuyPointChecker):
    """21日收盘高点买点.

    从 P 到今日找局部收盘波峰，波峰距今 ≥ 21天 且价格在回调一半上方。
    风险较高，仓位减半（capital_multiplier=0.5）。
    """

    STAGE = "trial"   # 从个股页撤下（未纳入胜率分析，先隐藏）

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if not band.v_qualified:
            log.info("High21Checker: V not qualified, skip")
            return []
        if not band.trigger_625_date:
            log.info("High21Checker: no trigger_625_date, skip")
            return []

        # 回调一半价格
        hr_latest = band.half_retrace_series[-1]["price"] if band.half_retrace_series else 0.0
        if hr_latest <= 0:
            log.info("High21Checker: hr_latest=0, skip")
            return []

        cur = band.current_price
        today_idx = len(df) - 1
        pullback_days = band.rows_count - 1 - band.p_idx
        results: list[BuyPoint] = []

        log.info("High21Checker: %d close_peaks, cur=%.2f, hr=%.2f, pullback=%d",
                 len(band.close_peaks), cur, hr_latest, pullback_days)

        for peak in band.close_peaks:
            days_ago = today_idx - peak.idx
            log.debug("High21Checker: peak %.2f @ %s, days_ago=%d, price>hr=%s",
                      peak.price, peak.date, days_ago, peak.price > hr_latest)
            if days_ago < 21:
                log.info("High21Checker: peak %.2f days_ago=%d < 21, skip",
                         peak.price, days_ago)
                continue
            if peak.price <= hr_latest:
                log.info("High21Checker: peak %.2f <= hr %.2f, skip",
                         peak.price, hr_latest)
                continue

            dist = round((peak.price / cur - 1) * 100, 1)

            if cur < peak.price:
                bp_type = "突破"
            else:
                bp_type = "重新突破"

            reason = (
                f"回调{pullback_days}天 ≥ 21天，收盘波峰{peak.price:.2f}（{peak.date}）"
                f" ｜ ⚠️风险较高，仓位减半"
            )

            log.info("High21Checker: FOUND type=%s price=%.2f dist=%.1f%%",
                     bp_type, peak.price, dist)

            results.append(BuyPoint(
                type=bp_type,
                position="21日收盘高点",
                price=peak.price,
                distance_pct=dist,
                reason=reason,
                capital_multiplier=0.5,
            ))

        log.info("High21Checker: %d results", len(results))
        return results


# ── 均线买点 ──────────────────────────────────────────────────

class MAChecker(BaseBuyPointChecker):
    """均线支撑买点（仅支撑拉回，试验中）.

    对 MA60/MA120/MA240 逐一检查：
    1. 均线向上（↑）—— 起拖拽作用
    2. 均线在现价下方 → 均线支撑（需放量确认）。
       均线在现价上方（突破）不作为买点 —— 均线只买支撑拉回。

    放量确认的"量"由 vol_mode 决定（均只用信号日 T 及更早，无未来函数）：
      - "today"：信号日成交额 → 「扣抵量均线支撑」
      - "avg5" ：近 5 日均量   → 「5日均量均线支撑」
      - "none" ：不看量，仅"均线向上 + 均线在价下(支撑)" → 「无量均线支撑」
    periods：检查哪些均线周期；默认 [60,120,240]（组合变体）；
             单周期变体传单元素列表（如 [20]）以拆开各周期效果。
    """

    STAGE = "trial"
    MA_PERIODS = [60, 120, 240]
    VOL_THRESHOLD = 1.0   # 量 > 扣抵量/后续均量即可

    def __init__(self, vol_mode: str = "today", type_name: str = "扣抵量均线支撑",
                 periods: list[int] | None = None, stage: str = "trial"):
        self.vol_mode = vol_mode        # "today" | "avg5" | "none"
        self.type_name = type_name
        self.periods = list(periods) if periods else list(self.MA_PERIODS)
        self.STAGE = stage              # 实例级 STAGE（MA240 传 "live"，其余默认 "trial"）

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if df.empty:
            log.debug("MAChecker: df empty, skip")
            return []

        cur = band.current_price
        if cur <= 0:            # 波段被阻断(current_price=0) → 无法算距离，跳过（与 Half/Band50 一致）
            return []
        if self.vol_mode == "avg5":
            measure = float(df["amount"].iloc[-5:].mean()) / 1e5  # 近5日均量（千元→亿）
            vol_label = "5日均量"
        elif self.vol_mode == "none":
            measure = 0.0                                          # 不看量
            vol_label = "无量"
        else:
            measure = float(df["amount"].iloc[-1]) / 1e5          # 今日量（千元→亿）
            vol_label = "今日量"

        mas = calc_ma(df, self.periods)
        results: list[BuyPoint] = []

        for p in self.periods:
            ma_key = f"MA{p}"
            ma_vals = mas[ma_key]

            # 条件1: 均线方向向上（拖拽作用）
            direction = ma_direction(ma_vals)
            if direction != "↑":
                log.info("MAChecker MA%d: dir=%s, skip (not ↑)", p, direction)
                continue

            # 条件2: 均线有值
            ma_val = None
            for v in reversed(ma_vals):
                if not np.isnan(v):
                    ma_val = float(v)
                    break
            if ma_val is None:
                log.info("MAChecker MA%d: val=N/A, skip", p)
                continue

            # 判断方向：支撑（均线在价下）还是突破（均线在价上）
            is_support = ma_val < cur
            dist = round((ma_val / cur - 1) * 100, 1)

            # 均线只买支撑拉回，突破买点已移除
            if not is_support:
                log.info("MAChecker MA%d: 均线在现价上方（突破），已移除突破买点，skip", p)
                continue

            # 支撑需要放量确认：今日量 > 扣抵量 & 后续均量
            bp_type = self.type_name
            if self.vol_mode == "none":
                # 不看量：仅"均线向上 + 均线在价下(支撑)"
                reason = f"MA{p}↑支撑（不看量）"
            else:
                off = get_offset_info(df, p)
                offset_amt = off.get("offset_amount_yi")
                avg_amt = off.get("avg_offset_amount_yi")

                if offset_amt is None or avg_amt is None:
                    log.info("MAChecker MA%d: offset_amt=%s avg_amt=%s, skip (N/A)",
                             p, offset_amt, avg_amt)
                    continue
                if measure <= offset_amt * self.VOL_THRESHOLD:
                    log.info("MAChecker MA%d: %s %.2f <= 扣抵量%.2f×%.1f=%.2f, skip",
                             p, vol_label, measure, offset_amt, self.VOL_THRESHOLD, offset_amt * self.VOL_THRESHOLD)
                    continue
                if measure <= avg_amt * self.VOL_THRESHOLD:
                    log.info("MAChecker MA%d: %s %.2f <= 后续均量%.2f×%.1f=%.2f, skip",
                             p, vol_label, measure, avg_amt, self.VOL_THRESHOLD, avg_amt * self.VOL_THRESHOLD)
                    continue

                off_pct = round((measure / offset_amt - 1) * 100, 1)
                avg_pct = round((measure / avg_amt - 1) * 100, 1)
                reason = f"MA{p}↑支撑，{vol_label}>扣抵量+{off_pct}%，{vol_label}>后续均量+{avg_pct}%"

            results.append(BuyPoint(
                type=bp_type,
                position=f"MA{p}",
                price=round(ma_val, 2),
                distance_pct=dist,
                reason=reason,
            ))

        return results


# ── 量价节点买点 ──────────────────────────────────────────────

class VolPriceNodeChecker(BaseBuyPointChecker):
    """量价节点买点（买拉回，试验中）.

    量价节点(单日 k): close[k]/close[k-1] > 1.02 且 amount[k]/amount[k-1] > 1.2
      —— 放量拉升，视作大资金进场。
    成本: min(low[k], low[k-1])，两日最低价 = 大资金进入成本。
    买入: 成本 × ENTRY_PREMIUM（默认 1.04=上浮4%；trial 变体 1.02=上浮2%）；止损: 盘中跌破成本。

    用法（买拉回）:
      ① 只在波段上升腿 [V, P] 内找节点；
      ② 前一日涨跌停（成交额未正常释放）的节点作废；
      ③ 已被后续 low 跌破过成本的节点作废；
      ④ 股价从 P 回调、曾跌破 75%线(line_75) 后才激活挂单（浅回调即激活）。
    """

    STAGE = "live"
    PRICE_RATIO = 1.02
    VOL_RATIO = 1.2
    ENTRY_PREMIUM = 1.04

    def __init__(self, entry_premium: float = 1.04):
        # entry_premium=1.04 → live（默认上浮4%）；其它值 → trial（如上浮2%=1.02 对照）
        self.ENTRY_PREMIUM = entry_premium
        self.STAGE = "live" if abs(entry_premium - 1.04) < 1e-9 else "trial"

    def check(self, df, band: BandResult, code: str = "") -> list[BuyPoint]:
        if df.empty:
            return []
        # 波段有效 + 已从 P 跌破过 75%线（line_75，浅回调即激活）
        if not band.v_qualified or band.p_idx < 0 or band.v_idx < 0:
            log.debug("VolNode: 波段无效/无P/V, skip")
            return []
        if band.line_75 <= 0 or band.l_price <= 0 or band.l_price >= band.line_75:
            log.debug("VolNode: 未跌破75%%线 (l=%.2f, line75=%.2f), skip",
                      band.l_price, band.line_75)
            return []

        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        amount = df["amount"].to_numpy(dtype=float)
        dates = df["date"].tolist()
        n = len(df)
        today_idx = n - 1
        cur = band.current_price

        # 板块单日涨跌停幅度：前一日涨跌停 → 成交额未正常释放，节点作废
        limit = _get_board_threshold(code) / 2.0 / 100.0   # 主板0.10 / 双创0.20

        # 后缀最低价：suffix_min[i] = min(low[i..today])，O(n) 一次算好供"已跌破"判定
        suffix_min = [0.0] * n
        run = float("inf")
        for i in range(n - 1, -1, -1):
            if low[i] < run:
                run = low[i]
            suffix_min[i] = run

        results: list[BuyPoint] = []
        seen_cost: set[float] = set()
        lo = max(band.v_idx, 2)   # k-2 需存在（判前一日涨跌停）
        for k in range(lo, band.p_idx + 1):
            c0, c1, c2 = close[k], close[k - 1], close[k - 2]
            a0, a1 = amount[k], amount[k - 1]
            if c1 <= 0 or a1 <= 0:
                continue
            if c0 / c1 <= self.PRICE_RATIO:          # 涨幅 > 2%
                continue
            if a0 / a1 <= self.VOL_RATIO:            # 量比 > 1.2
                continue
            if c2 > 0 and abs(c1 / c2 - 1.0) >= limit - 1e-4:   # 前一日涨跌停 → 弃
                continue
            cost = min(low[k], low[k - 1])
            if cost <= 0:
                continue
            if k + 1 <= today_idx and suffix_min[k + 1] < cost:  # 成本已被跌破 → 弃
                continue
            cost_r = round(cost, 2)
            if cost_r in seen_cost:
                continue
            seen_cost.add(cost_r)
            target = round(cost * self.ENTRY_PREMIUM, 2)
            stop_price = round(cost_r - 0.01, 2)   # 跌破成本 = 成本低一分钱
            dist = round((target / cur - 1) * 100, 1) if cur > 0 else 0.0
            prem = self.ENTRY_PREMIUM
            tag = "" if abs(prem - 1.04) < 1e-9 else f"[上浮{round((prem - 1) * 100):g}%] "
            results.append(BuyPoint(
                type="量价节点",
                position="量价节点",
                price=target,
                distance_pct=dist,
                reason=f"{tag}量价节点@{dates[k]} 成本{cost_r}(两日最低)×{prem:g}",
                intraday_stop=stop_price,
            ))
        log.debug("VolNode: %d 个存活节点 (窗口[%d,%d], code=%s)",
                  len(results), band.v_idx, band.p_idx, code)
        return results


# ── 随机基准买点（无技能对照）──────────────────────────────────

class RandomBaselineChecker(BaseBuyPointChecker):
    """随机基准买点（纯对照，无技能地板）.

    完全不看波段/量价/均线：每个交易日按固定概率 PROB「凭运气」发一个市价买点，
    走和普通市价买点完全相同的离场机器（全局空间/ATR 止损 + 收盘跌破买入价）。
    用途：校准所有买点的胜率——高于它才算真有 alpha，贴着它说明入场无效。

    随机是「确定性」的：种子 = md5(code|date)，同一(标的,日期)每次跑结果一致，
    保证跨批次可复现、可对比。**不能用 Python hash()**——它每进程加盐，跨次不稳定。
    """

    STAGE = "trial"
    PROB = 0.02   # 每个合格交易日发信概率；调此值控制样本量（≈ PROB×合格日×标的数）

    def check(self, df, band: BandResult, code: str = "") -> list[BuyPoint]:
        if df.empty:
            return []
        date = str(df["date"].iloc[-1])
        if self._rand01(code, date) >= self.PROB:
            return []
        cur = float(df["close"].iloc[-1])   # 不依赖 band：直接取信号日收盘作市价目标
        if cur <= 0:
            return []
        return [BuyPoint(
            type="随机基准",
            position="随机基准",
            price=round(cur, 2),
            distance_pct=0.0,               # 市价 = 现价
            reason=f"随机基准@{date} 无技能对照（市价随机 P={self.PROB}）",
        )]

    @staticmethod
    def _rand01(code: str, date: str) -> float:
        """确定性 [0,1)：md5(code|date) 前 32bit / 2^32。跨进程稳定（不同于 hash()）。"""
        h = hashlib.md5(f"{code}|{date}".encode("utf-8")).hexdigest()
        return int(h[:8], 16) / 0x1_0000_0000


# ── 汇总入口 ──────────────────────────────────────────────────

def _calc_shares(price: float, capital: float) -> str:
    """根据仓位资金计算可买股数，四舍五入到100股（A股最小交易单位）."""
    if capital <= 0 or price <= 0:
        return "—"
    shares = capital / price
    rounded = round(shares / 100) * 100
    return f"{rounded:,}股"


def _annotate_confluence(all_points: list[BuyPoint], df) -> None:
    """给买点 reason 追加共振标记（邻近阈值 2%）。规则源自 163313/190319 双跑结论：
      · 波段50% 附近有 MA/量价 → 偏正面（支撑位人气）
      · 量价节点 附近有 MA240（年线）→ 偏正面
      · 回调一半 与 波段50% 共振 → 强正面；仅与 MA 共振 → 谨慎（可能套牢盘）
    """
    if not all_points:
        return
    periods = [20, 55, 60, 120, 144, 240]
    try:
        mas = calc_ma(df, periods)
    except Exception:
        return
    ma_latest: dict[int, float] = {}
    for p in periods:
        for v in reversed(mas[f"MA{p}"]):
            if not np.isnan(v) and v > 0:
                ma_latest[p] = float(v)
                break

    def _near(price: float, target: float, tol: float = 0.02) -> bool:
        return target > 0 and price > 0 and abs(price - target) / price <= tol

    def _nearest_ma(price: float):
        best = None
        for p, v in ma_latest.items():
            if _near(price, v):
                d = abs(price - v) / price
                if best is None or d < best[1]:
                    best = (p, d)
        return best[0] if best else None

    band50 = next((bp.price for bp in all_points if bp.position == "波段50%"), 0.0)
    volnode_prices = [bp.price for bp in all_points if bp.position == "量价节点"]

    for bp in all_points:
        if bp.position == "波段50%":
            p = _nearest_ma(bp.price)
            near_vol = any(_near(bp.price, vp) for vp in volnode_prices)
            if p or near_vol:
                tag = f"MA{p}" if p else "量价节点"
                bp.reason += f" ｜🔴共振支撑(近{tag})，偏正面"
        elif bp.position == "量价节点":
            if 240 in ma_latest and _near(bp.price, ma_latest[240]):
                bp.reason += " ｜🔴年线共振，偏正面"
        elif bp.position == "回调一半":
            if band50 and _near(bp.price, band50):
                bp.reason += " ｜🔴与波段50%共振（强）"
            else:
                p = _nearest_ma(bp.price)
                if p:
                    bp.reason += f" ｜🟠近MA{p}，或有套牢盘，谨慎"


def find_all_buy_points(df, band: BandResult,
                        ts_code: str = "",
                        atr: float | None = None,
                        trend_direction: str = "flat",
                        position_capital: float = 0.0) -> list[BuyPoint]:
    """收集所有买点类型，过滤后按价格从高到低排序.

    Args:
        df: K线 DataFrame
        band: 波段分析结果
        ts_code: 股票代码（用于板块过滤）
        atr: 最新 ATR 绝对值（None=不计算盘中止损）
        trend_direction: 3浪3趋势方向 "up" | "down" | "flat"
        position_capital: 单个仓位资金（0=不计算仓位）
    """
    config = load_buy_point_config()
    show_trial = config.get("显示试验买点", 0.0) >= 1
    checkers: list[BaseBuyPointChecker] = [
        HalfRetraceChecker(),                                               # live
        Band50Checker(),                                                    # live
        VolPriceNodeChecker(),                                             # live（量价节点，需 code）
        MAChecker(vol_mode="today", periods=[240], type_name="MA240支撑", stage="live"),  # live
        High21Checker(),                                                    # trial（默认隐藏）
        HalfRetraceChecker(strict=True),                                    # trial（原始严格版）
        VolPriceNodeChecker(entry_premium=1.02),                            # trial（上浮2%对照，需 code）
    ]
    # STAGE 过滤：disabled 永不出现；trial 仅在「显示试验买点」开时出现
    checkers = [c for c in checkers
                if getattr(c, "STAGE", "live") != "disabled"
                and (show_trial or getattr(c, "STAGE", "live") != "trial")]
    all_points: list[BuyPoint] = []
    for c in checkers:
        bps = c.check(df, band, code=ts_code) if isinstance(c, VolPriceNodeChecker) else c.check(df, band)
        all_points.extend(bps)

    # ── 涨幅过滤 ──
    threshold = _get_board_threshold(ts_code)
    filtered_out = [bp for bp in all_points if abs(bp.distance_pct) > threshold]
    if filtered_out:
        log.info("涨幅过滤: ts_code=%s threshold=%.0f%% 过滤 %d 条: %s",
                 ts_code, threshold, len(filtered_out),
                 [(bp.position, f"{bp.distance_pct:.1f}%") for bp in filtered_out])
    all_points = [bp for bp in all_points if abs(bp.distance_pct) <= threshold]

    # ── ATR% ──
    atr_pct: float | None = None
    if atr is not None and atr > 0 and band.current_price > 0:
        atr_pct = round(atr / band.current_price * 100, 1)

    # ── 计算止损 ──
    for bp in all_points:
        # 均线买点需要 MA 值
        ma_val = 0.0
        if bp.position.startswith("MA"):
            # 从 position 字段提取 period
            try:
                ma_period = int(bp.position.replace("MA", ""))
                mas = calc_ma(df, [ma_period])
                ma_vals = mas[f"MA{ma_period}"]
                for v in reversed(ma_vals):
                    if not np.isnan(v):
                        ma_val = float(v)
                        break
            except (ValueError, KeyError):
                pass
        _calc_stop_losses(bp, atr_pct, trend_direction, config, ma_val)

    # 计算仓位（应用 capital_multiplier，如 21日高点 半仓）
    if position_capital > 0:
        for bp in all_points:
            capital = position_capital * bp.capital_multiplier
            bp.position_size = _calc_shares(bp.price, capital)

    # 共振提示（追加到 reason；邻近阈值 2%）
    _annotate_confluence(all_points, df)

    all_points.sort(key=lambda bp: bp.price, reverse=True)
    return all_points
