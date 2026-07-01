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
    position: str       # "回调一半" | "MA60" | "MA120" | "MA240"
    price: float        # 买点价格
    distance_pct: float  # (买点价 / 当前价 - 1) × 100，正=买点高于现价
    position_size: str = "—"   # 仓位，待定
    reason: str = ""


class BaseBuyPointChecker(ABC):
    """买点检查器基类."""

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

        reason = f"回调{pullback_days}天 ≥ 13天，且跌破过{band.line_625:.2f}"

        return [BuyPoint(
            type=bp_type,
            position="回调一半",
            price=hr_latest,
            distance_pct=dist,
            reason=reason,
        )]


# ── 均线买点 ──────────────────────────────────────────────────

class MAChecker(BaseBuyPointChecker):
    """均线支撑买点.

    对 MA60/MA120/MA240 逐一检查：
    1. 均线向上（↑）
    2. 均线在现价下方（支撑）
    3. 扣抵量 且 后续均量 都 > 今日成交额 × 1.1
    """

    MA_PERIODS = [60, 120, 240]
    VOL_THRESHOLD = 1.1   # 今日成交额需超过扣抵量/后续均量的倍数

    def check(self, df, band: BandResult) -> list[BuyPoint]:
        if df.empty:
            log.debug("MAChecker: df empty, skip")
            return []

        cur = band.current_price
        today_amount = float(df["amount"].iloc[-1]) / 1e5  # 千元 → 亿

        mas = calc_ma(df, self.MA_PERIODS)
        results: list[BuyPoint] = []

        for p in self.MA_PERIODS:
            ma_key = f"MA{p}"
            ma_vals = mas[ma_key]

            # 条件1: 均线方向向上
            direction = ma_direction(ma_vals)
            if direction != "↑":
                log.info("MAChecker MA%d: dir=%s, skip (not ↑)", p, direction)
                continue

            # 条件2: 均线在当前价下方
            ma_val = None
            for v in reversed(ma_vals):
                if not np.isnan(v):
                    ma_val = float(v)
                    break
            if ma_val is None or ma_val >= cur:
                log.info("MAChecker MA%d: val=%s cur=%.2f, skip (N/A or >=cur)",
                         p, f"{ma_val:.2f}" if ma_val else "N/A", cur)
                continue

            # 条件3: 扣抵量 & 后续均量 都 > 今日×阈值
            off = get_offset_info(df, p)
            offset_amt = off.get("offset_amount_yi")
            avg_amt = off.get("avg_offset_amount_yi")

            if offset_amt is None or avg_amt is None:
                log.info("MAChecker MA%d: offset_amt=%s avg_amt=%s, skip (N/A)",
                         p, offset_amt, avg_amt)
                continue
            if today_amount <= offset_amt * self.VOL_THRESHOLD:
                log.info("MAChecker MA%d: 今日量 %.2f <= 扣抵量%.2f×%.1f=%.2f, skip",
                         p, today_amount, offset_amt, self.VOL_THRESHOLD, offset_amt * self.VOL_THRESHOLD)
                continue
            if today_amount <= avg_amt * self.VOL_THRESHOLD:
                log.info("MAChecker MA%d: 今日量 %.2f <= 后续均量%.2f×%.1f=%.2f, skip",
                         p, today_amount, avg_amt, self.VOL_THRESHOLD, avg_amt * self.VOL_THRESHOLD)
                continue
                continue

            # 通过所有条件 → 产出买点
            dist = round((ma_val / cur - 1) * 100, 1)
            off_pct = round((today_amount / offset_amt - 1) * 100, 1)
            avg_pct = round((today_amount / avg_amt - 1) * 100, 1)
            reason = f"MA{p}↑支撑，今日量>扣抵量+{off_pct}%，今日量>后续均量+{avg_pct}%"

            results.append(BuyPoint(
                type="均线支撑",
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
                        position_capital: float = 0.0) -> list[BuyPoint]:
    """收集所有买点类型，按价格从高到低排序.

    Args:
        df: K线 DataFrame
        band: 波段分析结果
        position_capital: 单个仓位资金（0=不计算仓位）
    """
    checkers: list[BaseBuyPointChecker] = [
        HalfRetraceChecker(),
        MAChecker(),
    ]
    all_points: list[BuyPoint] = []
    for c in checkers:
        all_points.extend(c.check(df, band))

    # 计算仓位
    if position_capital > 0:
        for bp in all_points:
            bp.position_size = _calc_shares(bp.price, position_capital)

    all_points.sort(key=lambda bp: bp.price, reverse=True)
    return all_points
