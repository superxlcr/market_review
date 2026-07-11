"""买点提示 — 基类+子类架构，便于后续扩展新的买点类型.

Usage:
    from marketreview.tools.buy_points import find_all_buy_points, BuyPoint
    buy_points = find_all_buy_points(df, band)
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    else:
        # 回调一半 / 波段50%
        if atr_pct is not None and atr_pct > 0:
            pct = min(atr_pct * 2, atr_cap)
            if pct >= atr_cap:
                bp.intraday_stop_reason = f"{atr_cap:.0f}%上限"
            else:
                bp.intraday_stop_reason = f"2×ATR {atr_pct*2:.1f}%"
        else:
            pct = atr_cap
            bp.intraday_stop_reason = f"{atr_cap:.0f}%上限"
        bp.intraday_stop_pct = round(pct, 1)
        bp.intraday_stop = round(bp_price * (1 - pct / 100), 2)
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

    STAGE = "live"   # "live"=各页面可见；"trial"=试验中，仅买点胜率可见（find_all_buy_points 默认过滤）

    @abstractmethod
    def check(self, df, band: BandResult) -> list[BuyPoint]:
        """从 K线数据 + 波段结果中提取买点列表."""
        ...


# ── 回调一半买点 ─────────────────────────────────────────────

class HalfRetraceChecker(BaseBuyPointChecker):
    """回调一半位置买点.

    条件: 已跌破62.5%（trigger_625_date 非空）+ 波段幅度成立 + 回调≥13天.
    """

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if not band.trigger_625_date:
            return []
        if not band.v_qualified:
            return []
        pullback_days = band.rows_count - 1 - band.p_idx
        if pullback_days < 13:
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

        reason = f"回调{pullback_days}天 ≥ 13天，且跌破过波段 62.5% {band.line_625:.2f}"

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
    """

    STAGE = "trial"
    MA_PERIODS = [60, 120, 240]
    VOL_THRESHOLD = 1.0   # 量 > 扣抵量/后续均量即可

    def __init__(self, vol_mode: str = "today", type_name: str = "扣抵量均线支撑"):
        self.vol_mode = vol_mode        # "today" | "avg5"
        self.type_name = type_name

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if df.empty:
            log.debug("MAChecker: df empty, skip")
            return []

        cur = band.current_price
        if self.vol_mode == "avg5":
            measure = float(df["amount"].iloc[-5:].mean()) / 1e5  # 近5日均量（千元→亿）
            vol_label = "5日均量"
        else:
            measure = float(df["amount"].iloc[-1]) / 1e5          # 今日量（千元→亿）
            vol_label = "今日量"

        mas = calc_ma(df, self.MA_PERIODS)
        results: list[BuyPoint] = []

        for p in self.MA_PERIODS:
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
            bp_type = self.type_name
            reason = f"MA{p}↑支撑，{vol_label}>扣抵量+{off_pct}%，{vol_label}>后续均量+{avg_pct}%"

            results.append(BuyPoint(
                type=bp_type,
                position=f"MA{p}",
                price=round(ma_val, 2),
                distance_pct=dist,
                reason=reason,
            ))

        return results


# ── 汇总入口 ──────────────────────────────────────────────────

def _calc_shares(price: float, capital: float) -> str:
    """根据仓位资金计算可买股数，四舍五入到100股（A股最小交易单位）."""
    if capital <= 0 or price <= 0:
        return "—"
    shares = capital / price
    rounded = round(shares / 100) * 100
    return f"{rounded:,}股"


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
        HalfRetraceChecker(),
        Band50Checker(),
        High21Checker(),
        MAChecker(vol_mode="today", type_name="扣抵量均线支撑"),
        MAChecker(vol_mode="avg5", type_name="5日均量均线支撑"),
    ]
    # 试验中的买点默认只在「买点胜率」出现，不污染个股追踪/波段分析
    checkers = [c for c in checkers if show_trial or getattr(c, "STAGE", "live") != "trial"]
    all_points: list[BuyPoint] = []
    for c in checkers:
        all_points.extend(c.check(df, band))

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

    all_points.sort(key=lambda bp: bp.price, reverse=True)
    return all_points
