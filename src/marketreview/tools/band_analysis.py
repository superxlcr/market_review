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
class ValleyPoint:
    """局部谷底."""
    price: float = 0.0
    date: str = ""
    idx: int = -1


@dataclass
class ClosePeak:
    """局部收盘波峰（收盘价局部高点，用于21日收盘高点买点）."""
    price: float = 0.0
    date: str = ""
    idx: int = -1


def find_valleys(
    rows_asc: list[dict],
    start_idx: int,
    end_idx: int,
    neighborhood: int = 10,
) -> list[ValleyPoint]:
    """在 [start_idx, end_idx] 范围内找局部谷底.

    局部谷底: 该 K 线的 low 比左右各 neighborhood 天内的 low 都低.
    """
    valleys: list[ValleyPoint] = []
    n = len(rows_asc)

    for i in range(start_idx, end_idx + 1):
        cur_low = _safe_float(rows_asc[i].get("low"))
        if cur_low <= 0:
            continue

        # 检查左边 neighborhood 天
        left_start = max(0, i - neighborhood)
        left_ok = all(
            cur_low < _safe_float(rows_asc[j].get("low"))
            for j in range(left_start, i)
        )

        # 检查右边 neighborhood 天
        right_end = min(n - 1, i + neighborhood)
        right_ok = all(
            cur_low < _safe_float(rows_asc[j].get("low"))
            for j in range(i + 1, right_end + 1)
        )

        if left_ok and right_ok:
            valleys.append(ValleyPoint(
                price=cur_low,
                date=str(rows_asc[i].get("date", "")),
                idx=i,
            ))

    return valleys


def find_close_peaks(
    rows_asc: list[dict],
    start_idx: int,
    end_idx: int,
    neighborhood: int = 10,
) -> list[ClosePeak]:
    """在 [start_idx, end_idx] 范围内找局部收盘波峰.

    局部收盘波峰: 该 K 线的 close 比左右各 neighborhood 天内的 close 都高.
    逻辑与 find_valleys 对称，反过来而已，但用收盘价而非最高价.
    """
    peaks: list[ClosePeak] = []
    n = len(rows_asc)

    for i in range(start_idx, end_idx + 1):
        cur_close = _safe_float(rows_asc[i].get("close"))
        if cur_close <= 0:
            continue

        # 检查左边 neighborhood 天
        left_start = max(0, i - neighborhood)
        left_ok = all(
            cur_close > _safe_float(rows_asc[j].get("close"))
            for j in range(left_start, i)
        )

        # 检查右边 neighborhood 天
        right_end = min(n - 1, i + neighborhood)
        right_ok = all(
            cur_close > _safe_float(rows_asc[j].get("close"))
            for j in range(i + 1, right_end + 1)
        )

        if left_ok and right_ok:
            peaks.append(ClosePeak(
                price=cur_close,
                date=str(rows_asc[i].get("date", "")),
                idx=i,
            ))

    return peaks



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

    # 局部谷底列表
    valleys: list = field(default_factory=list)

    # 局部收盘波峰列表（P→今日，用于21日收盘高点买点）
    close_peaks: list = field(default_factory=list)

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

    # 回调半分位序列 — 跌破62.5%后，每个交易日一点: [(date, half_retrace_price), ...]
    half_retrace_series: list = field(default_factory=list)
    trigger_625_date: str = ""   # 首次跌破62.5%的日期

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
) -> BandResult:
    """分析一个标的的波段结构.

    Args:
        rows_asc: K线数据，date ASC（已前复权），每行含 open/high/low/close/date
        peak_lookback: 波峰回溯窗口（交易日），默认 300（~14个月）

    Returns:
        BandResult with P, V, trend lines, and qualification status.
    """
    result = BandResult(peak_lookback=peak_lookback)
    result.rows_count = len(rows_asc)

    if len(rows_asc) < 2:
        result.block_reason = f"K线不足（当前{len(rows_asc)}日）"
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

    result.p_price = peak_high
    result.p_date = str(rows_asc[peak_idx].get("date", ""))
    result.p_idx = peak_idx

    # ── 1.5 找 P 之前 lookback 窗口内的所有局部谷底 ──
    valley_search_start = max(0, peak_idx - peak_lookback)
    result.valleys = find_valleys(rows_asc, valley_search_start, peak_idx, neighborhood=5)
    log.info("Found %d local valleys in [%d, %d] (lookback=%d, P@%d)",
             len(result.valleys), valley_search_start, peak_idx, peak_lookback, peak_idx)

    # ── 1.6 找 P→今日 的局部收盘波峰（用于 21日收盘高点 买点）──
    result.close_peaks = find_close_peaks(rows_asc, peak_idx, today_idx, neighborhood=10)
    log.info("Found %d close peaks in [%d, %d]", len(result.close_peaks), peak_idx, today_idx)

    # ── 2. 选 V — 局部谷底中最高且满足 V/P < 3/7 ──
    qualified = [v for v in result.valleys if v.price / peak_high < (3.0 / 7.0)]
    if not qualified:
        result.block_reason = (
            f"P={peak_high:.2f}（{result.p_date}），"
            f"{len(result.valleys)} 个局部谷底中无满足 V/P < 3/7 者"
        )
        return result

    best_v = max(qualified, key=lambda v: v.price)
    result.v_price = best_v.price
    result.v_date = best_v.date
    result.v_idx = best_v.idx
    result.v_qualified = True
    result.vp_ratio = best_v.price / peak_high

    # ── 4. 计算三条趋势线 ──
    result.line_75 = result.v_price + 0.75 * (result.p_price - result.v_price)
    result.line_625 = result.v_price + 0.625 * (result.p_price - result.v_price)
    result.line_50 = (result.p_price + result.v_price) / 2.0

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

    # ── 5.5 回调半分位序列（从 P 起每交易日一点，随 L 下移而下降）──
    running_low = float("inf")
    for i in range(peak_idx, today_idx + 1):
        l = _safe_float(rows_asc[i].get("low"))
        if l < running_low:
            running_low = l
        if running_low < result.line_625 and not result.trigger_625_date:
            result.trigger_625_date = str(rows_asc[i].get("date", ""))
        half = (result.p_price + running_low) / 2.0
        result.half_retrace_series.append({
            "date": str(rows_asc[i].get("date", "")),
            "price": round(half, 2),
        })

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
