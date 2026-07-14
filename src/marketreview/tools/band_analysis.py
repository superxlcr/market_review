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
    lows: list[float],
    dates: list[str],
    start_idx: int,
    end_idx: int,
    neighborhood: int = 10,
) -> list[ValleyPoint]:
    """在 [start_idx, end_idx] 范围内找局部谷底.

    局部谷底: 该 K 线的 low 比左右各 neighborhood 天内的 low 都低.
    入参用预算好的 lows/dates 数组（由 analyze_band 入口提取一次），
    避免循环内反复 _safe_float + dict.get（原 253万次调用的大头）。
    """
    valleys: list[ValleyPoint] = []
    n = len(lows)
    if start_idx > end_idx or start_idx >= n:
        return valleys
    end_i = min(end_idx, n - 1)

    for i in range(start_idx, end_i + 1):
        cur_low = lows[i]
        if cur_low <= 0:
            continue

        # 检查左边 neighborhood 天（数组索引，遇不满足即 break）
        left_start = max(0, i - neighborhood)
        left_ok = True
        for j in range(left_start, i):
            if cur_low >= lows[j]:
                left_ok = False
                break
        if not left_ok:
            continue

        # 检查右边 neighborhood 天
        right_end = min(n - 1, i + neighborhood)
        right_ok = True
        for j in range(i + 1, right_end + 1):
            if cur_low >= lows[j]:
                right_ok = False
                break

        if left_ok and right_ok:
            valleys.append(ValleyPoint(price=cur_low, date=dates[i], idx=i))

    return valleys


def find_close_peaks(
    closes: list[float],
    dates: list[str],
    start_idx: int,
    end_idx: int,
    neighborhood: int = 10,
) -> list[ClosePeak]:
    """在 [start_idx, end_idx] 范围内找局部收盘波峰.

    局部收盘波峰: 该 K 线的 close 比左右各 neighborhood 天内的 close 都高.
    逻辑与 find_valleys 对称，反过来而已，但用收盘价而非最高价.
    入参用预算好的 closes/dates 数组。
    """
    peaks: list[ClosePeak] = []
    n = len(closes)
    if start_idx > end_idx or start_idx >= n:
        return peaks
    end_i = min(end_idx, n - 1)

    for i in range(start_idx, end_i + 1):
        cur_close = closes[i]
        if cur_close <= 0:
            continue

        left_start = max(0, i - neighborhood)
        left_ok = True
        for j in range(left_start, i):
            if cur_close <= closes[j]:
                left_ok = False
                break
        if not left_ok:
            continue

        right_end = min(n - 1, i + neighborhood)
        right_ok = True
        for j in range(i + 1, right_end + 1):
            if cur_close <= closes[j]:
                right_ok = False
                break

        if left_ok and right_ok:
            peaks.append(ClosePeak(price=cur_close, date=dates[i], idx=i))

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
    compute_close_peaks: bool = True,
    pre_valleys: list[ValleyPoint] | None = None,
    prev_band: "BandResult | None" = None,
    prev_i: int = -1,
) -> BandResult:
    """分析一个标的的波段结构.

    Args:
        rows_asc: K线数据，date ASC（已前复权），每行含 open/high/low/close/date
        peak_lookback: 波峰回溯窗口（交易日），默认 300（~14个月）
        compute_close_peaks: 是否计算 close_peaks（仅 High21 买点用）。
            胜率扫描不用 High21，传 False 跳过省 ~0.5s/只。
        pre_valleys: 标的全周期预算好的局部谷底列表（neighborhood=5）。
            传入时按 [peak-lookback, peak] 过滤子集复用，跳过 find_valleys 重算
            （P 不变时 V/valleys 不变，跨天复用省大头）。None 则内部重算。
        prev_band: 上一交易日的 BandResult（含 prev_i），用于 P 不变时跨天复用。
            P 不变判定：T+1.high ≤ prev P.price 且 prev P.idx 仍在 [T+1-lookback, T+1] 窗口内。
            不变则复用 P/V/valleys/趋势线/trigger_625，只 O(1) 更新 L/half_retrace。

    Returns:
        BandResult with P, V, trend lines, and qualification status.
    """
    result = BandResult(peak_lookback=peak_lookback)
    result.rows_count = len(rows_asc)

    if len(rows_asc) < 2:
        result.block_reason = f"K线不足（当前{len(rows_asc)}日）"
        return result

    today_idx = len(rows_asc) - 1

    # ── 0. P 不变快路径：跨天复用 prev_band（在数组提取前，避免每天重提全数组）──
    # P 不变判定：今天没创新高、旧 P 仍在窗口内、与 prev 严格相邻。
    # 满足则 P/V/valleys/趋势线/trigger_625 全不变（实测 95% 天），只取今天 1 根的 high/low/close/date。
    today_row = rows_asc[today_idx]
    today_high = _safe_float(today_row.get("high"))
    today_low = _safe_float(today_row.get("low"))
    today_close = _safe_float(today_row.get("close"))
    today_date = str(today_row.get("date", ""))
    if (prev_band is not None and prev_band.p_idx >= 0
            and prev_i == today_idx - 1):
        lookback_start_now = max(0, today_idx - peak_lookback)
        if (today_high <= prev_band.p_price
                and prev_band.p_idx >= lookback_start_now
                and prev_band.line_50 > 0):
            peak_idx = prev_band.p_idx
            result.p_price = prev_band.p_price
            result.p_date = prev_band.p_date
            result.p_idx = prev_band.p_idx
            result.v_price = prev_band.v_price
            result.v_date = prev_band.v_date
            result.v_idx = prev_band.v_idx
            result.vp_ratio = prev_band.vp_ratio
            result.v_qualified = prev_band.v_qualified
            result.valleys = prev_band.valleys
            result.line_75 = prev_band.line_75
            result.line_625 = prev_band.line_625
            result.line_50 = prev_band.line_50
            # L 增量
            if today_low < prev_band.l_price:
                result.l_price = today_low
                result.l_date = today_date
            else:
                result.l_price = prev_band.l_price
                result.l_date = prev_band.l_date
            # half_retrace 增量：running_low = min(prev 终值, today_low)
            running_low = min(prev_band.l_price, today_low)
            result.trigger_625_date = prev_band.trigger_625_date
            if running_low < result.line_625 and not result.trigger_625_date:
                result.trigger_625_date = today_date
            half = (result.p_price + running_low) / 2.0
            result.half_retrace_series = list(prev_band.half_retrace_series)
            result.half_retrace_series.append({"date": today_date, "price": round(half, 2)})
            # close_peaks：胜率扫描跳过；个股页重算（P 不变但今天可能新峰）
            if compute_close_peaks:
                highs_full = [_safe_float(r.get("high")) for r in rows_asc]
                closes_full = [_safe_float(r.get("close")) for r in rows_asc]
                dates_full = [str(r.get("date", "")) for r in rows_asc]
                result.close_peaks = find_close_peaks(closes_full, dates_full, peak_idx, today_idx, neighborhood=10)
            result.current_price = today_close
            result.current_date = today_date
            result.current_vs_50 = ((today_close - result.line_50) / result.line_50
                                     if result.line_50 > 0 else 0.0)
            log.debug("analyze_band: P 不变复用 prev_band (P@%d, today=%d)", peak_idx, today_idx)
            return result

    # 预算数组（仅 P 变的 5% 天走到这里）：一次提取 high/low/close/date
    highs = [_safe_float(r.get("high")) for r in rows_asc]
    lows = [_safe_float(r.get("low")) for r in rows_asc]
    closes = [_safe_float(r.get("close")) for r in rows_asc]
    dates = [str(r.get("date", "")) for r in rows_asc]

    # ── 1. 找波段新高 P ──
    lookback_start = max(0, today_idx - peak_lookback)
    peak_high = 0.0
    peak_idx = -1

    for i in range(lookback_start, today_idx + 1):
        h = highs[i]
        if h > peak_high:
            peak_high = h
            peak_idx = i

    if peak_idx < 0 or peak_high <= 0:
        result.block_reason = f"近{peak_lookback}日内未找到有效波峰"
        return result

    result.p_price = peak_high
    result.p_date = dates[peak_idx]
    result.p_idx = peak_idx

    # ── 1.5 找 P 之前 lookback 窗口内的所有局部谷底 ──
    valley_search_start = max(0, peak_idx - peak_lookback)
    if pre_valleys is not None:
        # 复用预算好的全周期 valleys，按 [valley_search_start, peak_idx] 过滤子集
        result.valleys = [v for v in pre_valleys
                          if valley_search_start <= v.idx <= peak_idx]
        log.info("Reused %d local valleys (filtered) in [%d, %d] (P@%d)",
                 len(result.valleys), valley_search_start, peak_idx, peak_idx)
    else:
        result.valleys = find_valleys(lows, dates, valley_search_start, peak_idx, neighborhood=5)
        log.info("Found %d local valleys in [%d, %d] (lookback=%d, P@%d)",
                 len(result.valleys), valley_search_start, peak_idx, peak_lookback, peak_idx)

    # ── 1.6 找 P→今日 的局部收盘波峰（仅 High21 买点用，胜率扫描可跳过）──
    if compute_close_peaks:
        result.close_peaks = find_close_peaks(closes, dates, peak_idx, today_idx, neighborhood=10)
        log.info("Found %d close peaks in [%d, %d]", len(result.close_peaks), peak_idx, today_idx)

    # ── 2. 选 V — 局部谷底中最高且满足 V/P < 3/7 ──
    qualified = [v for v in result.valleys if v.price / peak_high < (3.0 / 7.0)]
    if qualified:
        best_v = max(qualified, key=lambda v: v.price)
        result.v_qualified = True
    elif result.valleys:
        # 无合格谷底 → 兜底：选 V/P 比值最低的（最接近阈值）
        best_v = min(result.valleys, key=lambda v: v.price / peak_high)
        result.v_qualified = False
    else:
        result.block_reason = (
            f"P={peak_high:.2f}（{result.p_date}），未找到任何局部谷底"
        )
        return result

    result.v_price = best_v.price
    result.v_date = best_v.date
    result.v_idx = best_v.idx
    result.vp_ratio = best_v.price / peak_high

    # ── 4. 计算三条趋势线 ──
    result.line_75 = result.v_price + 0.75 * (result.p_price - result.v_price)
    result.line_625 = result.v_price + 0.625 * (result.p_price - result.v_price)
    result.line_50 = (result.p_price + result.v_price) / 2.0

    # ── 5. 找 L（P 之后最低 low，供参考）──
    lowest_low = float("inf")
    lowest_idx = -1
    for i in range(peak_idx, today_idx + 1):
        l = lows[i]
        if l < lowest_low:
            lowest_low = l
            lowest_idx = i

    result.l_price = lowest_low
    result.l_date = dates[lowest_idx] if lowest_idx >= 0 else ""

    # ── 5.5 回调半分位序列（从 P 起每交易日一点，随 L 下移而下降）──
    running_low = float("inf")
    for i in range(peak_idx, today_idx + 1):
        l = lows[i]
        if l < running_low:
            running_low = l
        if running_low < result.line_625 and not result.trigger_625_date:
            result.trigger_625_date = dates[i]
        half = (result.p_price + running_low) / 2.0
        result.half_retrace_series.append({
            "date": dates[i],
            "price": round(half, 2),
        })

    # ── 6. 当前价格 vs 50% 趋势线 ──
    result.current_price = closes[today_idx]
    result.current_date = dates[today_idx]
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
