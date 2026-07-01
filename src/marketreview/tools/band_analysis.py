"""波段分析工具 — 找 P/V 波峰波谷，画趋势线.

核心概念:
  P = 波峰（回顾期内最高 high）
  V = 前波谷（P 之前所有 K 线的最低 low）
  波段50%线 = (P+V)/2 — 趋势健康线，跌破则趋势可能逆转
  波段62.5%线 = V + 0.625*(P-V)
  波段75%线 = V + 0.75*(P-V)

V 资格校验: V/P < 3/7（≈0.4286），等价于 50%×1.1 < 62.5%，确保波段深度够大。
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class BandResult:
    """波段分析结果."""
    # P — 波峰
    p_price: float = 0.0
    p_date: str = ""
    p_idx: int = -1

    # V — 前波谷
    v_price: float = 0.0
    v_date: str = ""
    v_idx: int = -1

    # 资格
    v_qualified: bool = False   # V/P < 3/7 ?
    vp_ratio: float = 0.0

    # 三条趋势线
    line_75: float = 0.0
    line_625: float = 0.0
    line_50: float = 0.0

    # 当前价格信息
    current_price: float = 0.0
    current_date: str = ""
    current_vs_50: float = 0.0   # (current - line_50) / line_50

    # L — 回调最低（P之后最低low，供半分位参考，但本模块主要看趋势线）
    l_price: float = 0.0
    l_date: str = ""

    # 阻断原因
    block_reason: str = ""
    peak_lookback: int = 300

    # 原始数据行数
    rows_count: int = 0


def _safe_float(v) -> float:
    """Convert to float, return 0.0 on failure."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def analyze_band(
    rows_asc: list[dict],
    peak_lookback: int = 300,
    pullback_min_days: int = 13,
) -> BandResult:
    """分析一个标的的波段结构.

    Args:
        rows_asc: K线数据，date ASC（已前复权），每行含 open/high/low/close/date
        peak_lookback: 波峰回溯窗口（交易日），默认 300（~14个月）
        pullback_min_days: P 必须距今 ≥ N 个交易日

    Returns:
        BandResult with P, V, trend lines, and qualification status.
    """
    result = BandResult(peak_lookback=peak_lookback)
    result.rows_count = len(rows_asc)

    if len(rows_asc) < pullback_min_days + 2:
        result.block_reason = f"K线不足（需≥{pullback_min_days + 2}日，当前{len(rows_asc)}日）"
        return result

    today_idx = len(rows_asc) - 1

    # ── 1. 找波段新高 P ──
    lookback_start = max(0, today_idx - peak_lookback)
    peak_high = 0.0
    peak_idx = -1

    for i in range(lookback_start, today_idx + 1):
        h = _safe_float(rows_asc[i].get("high"))
        if h > peak_high:
            peak_high = h
            peak_idx = i

    if peak_idx < 0 or peak_high <= 0:
        result.block_reason = f"近{peak_lookback}日内未找到有效波峰"
        return result

    # P 必须距今 ≥ pullback_min_days
    if today_idx - peak_idx < pullback_min_days:
        result.block_reason = (
            f"P={peak_high:.2f}（{rows_asc[peak_idx].get('date', '?')}）"
            f"距今仅{today_idx - peak_idx}日，需≥{pullback_min_days}日"
        )
        return result

    result.p_price = peak_high
    result.p_date = str(rows_asc[peak_idx].get("date", ""))
    result.p_idx = peak_idx

    # ── 2. 找前波谷 V（P 之前所有 K 线的最低 low）──
    valley_low = float("inf")
    valley_idx = -1
    for i in range(0, peak_idx):
        l = _safe_float(rows_asc[i].get("low"))
        if l < valley_low:
            valley_low = l
            valley_idx = i

    if valley_low >= peak_high or valley_low <= 0:
        result.block_reason = (
            f"P={peak_high:.2f}（{result.p_date}），波峰前未找到有效波谷"
        )
        return result

    result.v_price = valley_low
    result.v_date = str(rows_asc[valley_idx].get("date", ""))
    result.v_idx = valley_idx

    # ── 3. V 资格校验: V/P < 3/7 ──
    result.vp_ratio = valley_low / peak_high
    result.v_qualified = result.vp_ratio < (3.0 / 7.0)

    # ── 4. 计算三条趋势线 ──
    result.line_75 = valley_low + 0.75 * (peak_high - valley_low)
    result.line_625 = valley_low + 0.625 * (peak_high - valley_low)
    result.line_50 = (peak_high + valley_low) / 2.0

    # ── 5. 找 L（P 之后最低 low，供参考）──
    lowest_low = float("inf")
    lowest_idx = -1
    for i in range(peak_idx, today_idx + 1):
        l = _safe_float(rows_asc[i].get("low"))
        if l < lowest_low:
            lowest_low = l
            lowest_idx = i

    result.l_price = lowest_low
    result.l_date = str(rows_asc[lowest_idx].get("date", "")) if lowest_idx >= 0 else ""

    # ── 6. 当前价格 vs 50% 趋势线 ──
    result.current_price = _safe_float(rows_asc[today_idx].get("close"))
    result.current_date = str(rows_asc[today_idx].get("date", ""))
    if result.line_50 > 0:
        result.current_vs_50 = (
            (result.current_price - result.line_50) / result.line_50
        )

    return result


def format_band_report(r: BandResult) -> str:
    """生成波段分析文字报告."""
    if r.block_reason:
        return f"❌ 无法分析: {r.block_reason}"

    v_status = "✅ 通过" if r.v_qualified else f"❌ 不通过 (V/P={r.vp_ratio:.3f} ≥ 0.4286)"
    trend_dir = "↑ 线上" if r.current_vs_50 >= 0 else "↓ 线下"

    lines = [
        f"=== 波段分析 ({r.current_date}) ===",
        f"P(波峰): {r.p_price:.2f} @ {r.p_date}",
        f"V(前波谷): {r.v_price:.2f} @ {r.v_date}",
        f"V/P: {r.vp_ratio:.3f} → {v_status}",
        f"L(回调最低): {r.l_price:.2f} @ {r.l_date}",
        f"",
        f"--- 趋势线 ---",
        f"75%线:  {r.line_75:.2f}",
        f"62.5%线: {r.line_625:.2f}",
        f"50%线:  {r.line_50:.2f}  ← 趋势生命线",
        f"",
        f"当前价: {r.current_price:.2f} vs 50%线 {r.line_50:.2f} ({r.current_vs_50:+.1%}) {trend_dir}",
    ]
    return "\n".join(lines)
