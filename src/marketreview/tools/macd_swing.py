"""
MACD 波段摆动分析 — 从 NGA 牛股计算器 (calc_index.html) 移植。

核心逻辑:
  1. MACD 金叉/死叉 自动划分波段段落
  2. 从波段顶底计算斐波那契回调位 (0.382 / 0.618 / 0.786)
  3. 观察模式信号: 根据现价 vs 各回调位 + 波段底的关系判断
  4. 搓揉线识别: 两日影线配对 + 趋势投票 → 8 种信号

与现有 band_analysis.py 的差异:
  - band_analysis 用回溯窗口找静态极值 (P/V)
  - macd_swing 用 MACD 交叉划分动态波段段落
  - 两种算法的顶底可能不同, 互为参考
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import logging

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# §1 — EMA / MACD 计算
# ═══════════════════════════════════════════════════════════════

def calc_ema(values: list[float], period: int) -> list[float]:
    """计算 EMA。空序列返回空列表。"""
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for v in values[1:]:
        result.append(float(v) * k + result[-1] * (1.0 - k))
    return result


def calc_macd(closes: list[float]) -> list[dict[str, float]]:
    """从收盘价序列计算 MACD (EMA12/EMA26/DEA9)。

    Returns:
        [{date, diff, dea, macd}, ...]  与输入等长.
        macd = (diff - dea) × 2  (标准定义).
    """
    if len(closes) < 26:
        return [{"diff": 0.0, "dea": 0.0, "macd": 0.0} for _ in closes]

    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    diff = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = calc_ema(diff, 9)

    result = []
    for i in range(len(closes)):
        d = diff[i] if i < len(diff) else 0.0
        e = dea[i] if i < len(dea) else 0.0
        result.append({
            "diff": round(d, 6),
            "dea": round(e, 6),
            "macd": round((d - e) * 2.0, 6),
        })
    return result


# ═══════════════════════════════════════════════════════════════
# §2 — MACD 波段顶底检测
# ═══════════════════════════════════════════════════════════════

@dataclass
class MacdSwingResult:
    """MACD 波段摆动分析结果."""
    # 阶段顶/底
    high: float = 0.0        # 阶段顶部价格
    low: float = 0.0         # 阶段底部价格
    high_source: str = ""    # "up-leg-high" | "running-tail-high" | "range"
    low_source: str = ""     # "down-leg-low" | "running-tail-low" | "range"

    # 斐波那契回调位 (从顶部往下跌方向)
    # 仅 fibonacci_valid=True 时有意义 (last_cross_type == "death": 低在前高在后=上升波段回调)
    f382: float = 0.0        # 0.382 回调 = high - diff × 0.382
    f618: float = 0.0        # 0.618 回调 = high - diff × 0.618
    f786: float = 0.0        # 0.786 回调 = high - diff × 0.786
    mid_point: float = 0.0   # 50% 中位线
    fibonacci_valid: bool = True  # False = 高在前低在后, 斐波那契回调不适用

    # 波段幅度信息
    band_range: float = 0.0       # high - low
    band_range_pct: float = 0.0   # (high - low) / low × 100

    # MACD 交叉统计
    golden_cross_count: int = 0   # 金叉次数
    death_cross_count: int = 0    # 死叉次数
    last_cross_type: str = ""     # "golden" | "death" | ""

    # 信号
    signal: str = ""              # 操作建议文字
    signal_class: str = ""        # CSS class

    # 原始 K 线数 / 阻断原因
    rows_count: int = 0
    block_reason: str = ""


def find_macd_swing(
    klines: list[dict[str, Any]],
    window_size: int = 30,
    last_bar_incomplete: bool = False,
) -> MacdSwingResult:
    """用 MACD 金叉/死叉自动划分波段顶底。

    算法 (与 calc_index.html 的 findMacdSwingDefaults 等价):
      1. 扫描全部 K 线的 MACD 交叉
         - 金叉 (DIFF 上穿 DEA): 取上次死叉以来的最低 low → 阶段底部
         - 死叉 (DIFF 下穿 DEA): 取上次金叉以来的最高 high → 阶段顶部
      2. 尾段跟踪: 最后一次交叉之后, 双向追踪新极值
      3. 兜底: 无任何交叉 → 取近 window_size 根 K 线的高低极值
      4. 盘中最后一根 K 线 (last_bar_incomplete=True) 不参与交叉判定,
         但其 price 会计入尾段极值

    Args:
        klines: K 线列表 (date ASC). 每条含 open/high/low/close.
        window_size: 无交叉时的兜底窗口大小 (交易日).
        last_bar_incomplete: True = 最后一根是盘中未收盘K线.

    Returns:
        MacdSwingResult.
    """
    result = MacdSwingResult()
    result.rows_count = len(klines)

    if len(klines) < 2:
        result.block_reason = f"K线不足 (当前 {len(klines)} 日)"
        return result

    # 提取数组
    highs = [float(k.get("high", 0) or 0) for k in klines]
    lows = [float(k.get("low", 0) or 0) for k in klines]
    closes = [float(k.get("close", 0) or 0) for k in klines]

    # 兜底极值 (近 window_size 日)
    recent_n = max(1, min(window_size, len(klines)))
    recent_highs = highs[-recent_n:]
    recent_lows = [l for l in lows[-recent_n:] if l > 0]
    fallback_high = max(recent_highs) if recent_highs else 0.0
    fallback_low = min(recent_lows) if recent_lows else 0.0

    # 计算 MACD
    macd_series = calc_macd(closes)
    if len(macd_series) < 2:
        result.high = fallback_high
        result.low = fallback_low
        result.high_source = "range"
        result.low_source = "range"
        result.block_reason = "MACD 数据不足 (需 ≥26 日)"
        return result

    # 辅助函数: 区间最高/最低
    def segment_high(frm: int, to: int) -> float:
        v = 0.0
        for j in range(max(frm, 0), min(to + 1, len(highs))):
            v = max(v, highs[j])
        return v

    def segment_low(frm: int, to: int) -> float:
        v = float("inf")
        for j in range(max(frm, 0), min(to + 1, len(lows))):
            lv = lows[j]
            if lv > 0:
                v = min(v, lv)
        return v if v != float("inf") else 0.0

    # 交叉扫描
    # 盘中最后一根 K 线不参与交叉判定 (避免闪烁)
    cross_end = len(macd_series) - 1 if last_bar_incomplete else len(macd_series)

    high = 0.0
    low = 0.0
    high_source = "range"
    low_source = "range"
    last_golden_idx = -1
    last_death_idx = -1
    golden_count = 0
    death_count = 0

    # 追踪上一个有效斐波那契 (死叉确认的上升波段).
    # 当最后交叉为金叉时, 回退到上一个上升波段的斐波那契, 而不是什么都不显示.
    prev_fib = (0.0, 0.0, 0.0, 0.0)  # f382, f618, f786, mid

    for i in range(1, cross_end):
        prev_m = macd_series[i - 1]
        curr_m = macd_series[i]
        if not prev_m or not curr_m:
            continue

        # 金叉: DIFF 上穿 DEA
        if prev_m["diff"] <= prev_m["dea"] and curr_m["diff"] > curr_m["dea"]:
            frm = last_death_idx - 1 if last_death_idx > -1 else 0
            low = segment_low(frm, i - 1)
            low_source = "down-leg-low"
            last_golden_idx = i
            golden_count += 1

        # 死叉: DIFF 下穿 DEA
        if prev_m["diff"] >= prev_m["dea"] and curr_m["diff"] < curr_m["dea"]:
            frm = last_golden_idx - 1 if last_golden_idx > -1 else 0
            high = segment_high(frm, i - 1)
            high_source = "up-leg-high"
            last_death_idx = i
            death_count += 1
            # 死叉 = 上升波段结束, 此时 (low, high) 构成有效斐波那契, 保存作为兜底
            if low > 0 and high > 0:
                d = high - low
                prev_fib = (
                    round(high - d * 0.382, 3),
                    round(high - d * 0.618, 3),
                    round(high - d * 0.786, 3),
                    round((high + low) / 2.0, 3),
                )

    # 尾段跟踪: 最后一次交叉后, 双向追踪新极值
    last_idx = len(klines) - 1
    last_cross_idx = max(last_golden_idx, last_death_idx)

    if last_cross_idx > -1:
        # 跟踪新高 (如死叉后顶背离创新高)
        running_high = segment_high(last_cross_idx - 1, last_idx)
        if running_high > high:
            high = running_high
            high_source = "running-tail-high"

        # 跟踪新低 (仅当已有底部值时)
        if low > 0:
            running_low = segment_low(last_cross_idx - 1, last_idx)
            if running_low > 0 and running_low < low:
                low = running_low
                low_source = "running-tail-low"

    # 兜底
    if high <= 0:
        high = fallback_high
        high_source = "range"
    if low <= 0:
        low = fallback_low
        low_source = "range"

    result.high = round(high, 2)
    result.low = round(low, 2)
    result.high_source = high_source
    result.low_source = low_source
    result.golden_cross_count = golden_count
    result.death_cross_count = death_count
    result.last_cross_type = "golden" if last_golden_idx > last_death_idx else "death"

    # ── 斐波那契回调位 ──
    # death 结尾 → 低在前高在后 → 上升波段回调 → 当前斐波那契有效       ✅
    # golden 结尾 → 高在前低在后 → 下跌波段反弹 → 回退到上一个死叉波段   ⚠️
    result.fibonacci_valid = (result.last_cross_type == "death")
    diff = high - low
    result.band_range = round(diff, 2)
    result.band_range_pct = round(diff / low * 100, 1) if low > 0 else 0.0
    if result.fibonacci_valid:
        result.f382 = round(high - diff * 0.382, 3)
        result.f618 = round(high - diff * 0.618, 3)
        result.f786 = round(high - diff * 0.786, 3)
        result.mid_point = round((high + low) / 2.0, 3)
    else:
        # 回退到上一个死叉确认的上升波段斐波那契
        result.f382, result.f618, result.f786, result.mid_point = prev_fib

    return result


def calc_observation_signal(
    swing: MacdSwingResult,
    current_price: float,
    is_new_high: bool = False,
) -> tuple[str, str]:
    """根据 MACD 波段 + 现价 计算观察模式信号。

    Args:
        swing: MACD 波段结果.
        current_price: 当前价格.
        is_new_high: 今天是否创新高 (突破已存顶部).

    Returns:
        (signal_text, css_class)
    """
    now = current_price
    low = swing.low
    f382 = swing.f382
    f618 = swing.f618
    f786 = swing.f786
    mid = swing.mid_point

    if low > 0 and now < low:
        return "破位严禁", "advice-danger"
    if is_new_high:
        return "突破跟进", "advice-danger"
    if low > 0:
        if now < f786:
            return "放弃(极弱)", "advice-normal"
        if now < f618 * 0.99:
            return "跌破618(弱)", "advice-warning"
        if now <= mid * 1.02:
            return "强防生死线", "advice-blue"
        if now <= f382 * 1.03:
            return "常规买点", "advice-cyan"
        return "高位观望", "advice-normal"
    return "观望", "advice-normal"


# ═══════════════════════════════════════════════════════════════
# §3 — 搓揉线识别 (操作建议2)
# ═══════════════════════════════════════════════════════════════

def classify_shadow(kline: dict[str, Any]) -> str:
    """将单根 K 线的影线分为 'upper' / 'lower' / 'none'.

    主影线需同时满足:
      1. ≥ 实体 × 1.5
      2. ≥ 全日振幅 × 40%

    Returns:
        'upper' | 'lower' | 'none'
    """
    o = float(kline.get("open", 0) or 0)
    h = float(kline.get("high", 0) or 0)
    l = float(kline.get("low", 0) or 0)
    c = float(kline.get("close", 0) or 0)

    rng = h - l
    if rng <= 0:
        return "none"

    body = max(abs(c - o), rng * 0.03)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    min_by_body = body * 1.5
    min_by_range = rng * 0.4

    upper_ok = upper_wick >= min_by_body and upper_wick >= min_by_range
    lower_ok = lower_wick >= min_by_body and lower_wick >= min_by_range

    if upper_ok and not lower_ok:
        return "upper"
    if lower_ok and not upper_ok:
        return "lower"
    if upper_ok and lower_ok:
        return "upper" if upper_wick > lower_wick else "lower"
    return "none"


def calculate_trend(closes: list[float], current_price: float) -> str:
    """三票制趋势判断 — 现价vsMA20, MA5vsMA20, MA20斜率, 2/3 定方向.

    Returns:
        'up' | 'down' | 'side'
    """
    prices = [v for v in closes if v > 0]
    now = current_price
    if now > 0:
        prices.append(now)
    if len(prices) < 21:
        return "side"

    def avg_slice(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    ma5 = avg_slice(prices[-5:])
    ma20 = avg_slice(prices[-20:])
    prev_ma20 = avg_slice(prices[-21:-1])
    price = now if now > 0 else prices[-1]

    up_votes = 0
    down_votes = 0

    def vote(a: float, b: float) -> None:
        nonlocal up_votes, down_votes
        margin = (abs(b) or 1.0) * 0.0005
        if a - b > margin:
            up_votes += 1
        elif b - a > margin:
            down_votes += 1

    vote(price, ma20)
    vote(ma5, ma20)
    vote(ma20, prev_ma20)

    if up_votes >= 2:
        return "up"
    if down_votes >= 2:
        return "down"
    return "side"


def calculate_advice2(
    yesterday: dict[str, Any],
    today: dict[str, Any],
    trend: str,
) -> dict[str, str]:
    """搓揉线 + 趋势 + 阴阳 → 操作建议2.

    Args:
        yesterday: 昨日 K 线 {open, high, low, close}
        today: 今日 K 线 {open, high, low, close}
        trend: 趋势方向 'up' | 'down' | 'side'

    Returns:
        {text: str, className: str}
    """
    if trend not in ("up", "down"):
        return {"text": "趋势不明", "className": "advice-normal"}

    yesterday_shadow = classify_shadow(yesterday)
    today_shadow = classify_shadow(today)

    # 阴阳判断
    t_open = float(today.get("open", 0) or 0)
    t_close = float(today.get("close", 0) or 0)
    if t_close > t_open:
        color = "red"     # 阳线
    elif t_close < t_open:
        color = "black"   # 阴线
    else:
        return {"text": "未触发", "className": "advice-normal"}

    # 影线配对
    sequence = ""
    if yesterday_shadow == "lower" and today_shadow == "upper":
        sequence = "lower-upper"
    elif yesterday_shadow == "upper" and today_shadow == "lower":
        sequence = "upper-lower"
    if not sequence:
        return {"text": "未触发", "className": "advice-normal"}

    # 8 种信号映射
    map_key = f"{trend}|{color}|{sequence}"
    mapping: dict[str, dict[str, str]] = {
        "down|black|lower-upper":  {"text": "中继下跌",           "className": "advice-danger"},
        "down|red|lower-upper":    {"text": "支撑位震荡选方向",    "className": "advice-warning"},
        "down|red|upper-lower":    {"text": "支撑位资金抢反弹",    "className": "advice-gold"},
        "down|black|upper-lower":  {"text": "短期止跌",           "className": "advice-blue"},
        "up|black|lower-upper":    {"text": "开始有分歧",         "className": "advice-warning"},
        "up|red|lower-upper":      {"text": "分歧但强势继续看新高","className": "advice-cyan"},
        "up|red|upper-lower":      {"text": "承接力度大但只承接不追高","className": "advice-blue"},
        "up|black|upper-lower":    {"text": "承接低可能出现短期顶","className": "advice-danger"},
    }
    return mapping.get(map_key, {"text": "未触发", "className": "advice-normal"})
