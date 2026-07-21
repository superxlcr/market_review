"""Volume Profile — VWAP + 成交量分布 + POC/HVN/LVN 检测。

用日线 OHLCV 数据构建 Volume Profile。日线没有每笔成交价，采用"典型价格法"：
将当日所有成交量分配到 (H+L+C)/3，多日聚合即得价格×成交量分布。

核心概念：
  VWAP            — 成交量加权均价（选定区间内所有参与者的真实平均成本）
  POC             — Point of Control，成交量最大的价格格子（市场最认可的价值区间）
  HVN             — 高成交量节点，成交量超过均值 1.5× 的格子（密集成交区 = 支撑/阻力）
  LVN             — 低成交量节点，成交量低于均值 0.3× 的格子（成交真空区 = 价格快速穿过）
  价值区域 (VA)    — 包含 70% 成交量的价格区间（市场认为"合理"的范围）
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class VolumeProfileResult:
    """Volume Profile 分析结果"""
    vwap: float                          # 成交量加权均价
    poc: float                           # Point of Control（最大成交量价格）
    poc_volume: float                    # POC 处的成交量
    poc_pct: float                       # POC 成交量占总量的百分比
    value_area_high: float               # 价值区域上沿（70% 成交量上界）
    value_area_low: float                # 价值区域下沿（70% 成交量下界）
    profile: dict[float, float]          # {价格中心: 成交量}，按价格升序
    hvns: list[dict]                     # [{price_center, volume, pct_of_total}]
    lvns: list[dict]                     # [{price_center, volume, pct_of_total}]
    total_volume: float                  # 区间总成交量
    price_min: float                     # 区间最低价
    price_max: float                     # 区间最高价
    bin_size: float                      # 每格价格宽度
    num_bins: int                        # 价格分箱数
    lookback: int                        # 回看 K 线数


def volume_profile(df: pd.DataFrame, lookback: int = 60,
                   num_bins: int = 80,
                   value_area_pct: float = 0.70) -> VolumeProfileResult | None:
    """从日线 OHLCV 构建 Volume Profile。

    算法：
      1. 每根 K 线取典型价格 TP = (H+L+C)/3
      2. 将当日成交量全部分配到 TP 所在的价格格子
      3. 多日聚合后，找到 POC、HVN/LVN、价值区域

    Args:
        df: 含 open/high/low/close/vol 的 DataFrame（ASC 排序，数值化后）
        lookback: 回看最近 N 根 K 线
        num_bins: 价格分箱数（默认 80，≈1.25% 精度）
        value_area_pct: 价值区域百分比（默认 0.70 = 70%）

    Returns:
        VolumeProfileResult，数据不足时返回 None。
    """
    n = len(df)
    if n < lookback:
        return None

    subset = df.iloc[-lookback:]
    high = subset["high"].to_numpy(dtype=float)
    low = subset["low"].to_numpy(dtype=float)
    close = subset["close"].to_numpy(dtype=float)
    vol = subset["vol"].to_numpy(dtype=float)

    # 典型价格 = (H+L+C)/3
    tp = (high + low + close) / 3.0

    # 过滤无效数据
    valid = (vol > 0) & (tp > 0) & np.isfinite(tp)
    tp = tp[valid]
    vol = vol[valid]
    if len(tp) == 0:
        return None

    price_min = float(np.min(low[valid]))
    price_max = float(np.max(high[valid]))
    if price_max <= price_min:
        return None

    # 分箱：每个 TP 映射到一个 bin
    bin_size = (price_max - price_min) / num_bins
    if bin_size <= 0:
        return None

    profile_bins: dict[int, float] = {}   # bin_index → accumulated volume
    for price, v in zip(tp, vol):
        bin_idx = int((price - price_min) / bin_size)
        bin_idx = max(0, min(num_bins - 1, bin_idx))
        profile_bins[bin_idx] = profile_bins.get(bin_idx, 0.0) + float(v)

    total_vol = sum(profile_bins.values())
    if total_vol <= 0:
        return None

    def _price_of(bin_idx: int) -> float:
        """bin 中心价"""
        return round(price_min + (bin_idx + 0.5) * bin_size, 3)

    # ── 构建 price_profile（价格→成交量，升序）──
    price_profile = {_price_of(i): v for i, v in sorted(profile_bins.items())}

    # ── POC ──
    poc_idx = max(profile_bins, key=profile_bins.get)
    poc_price = _price_of(poc_idx)
    poc_vol = profile_bins[poc_idx]
    poc_pct = round(poc_vol / total_vol * 100, 1)

    # ── VWAP ──
    vwap_val = float(np.average(tp, weights=vol))

    # ── 价值区域（value_area_pct% 成交量最密集的 bins）──
    sorted_bins = sorted(profile_bins.items(), key=lambda x: x[1], reverse=True)
    cum = 0.0
    va_indices = []
    for bi, vs in sorted_bins:
        cum += vs
        va_indices.append(bi)
        if cum / total_vol >= value_area_pct:
            break
    va_low = price_min + min(va_indices) * bin_size
    va_high = price_min + (max(va_indices) + 1) * bin_size

    # ── HVN / LVN ──
    avg_vol_per_bin = total_vol / num_bins
    hvns = []
    lvns = []
    for bi, vs in sorted(profile_bins.items()):
        entry = {
            "price_center": _price_of(bi),
            "volume": round(vs, 1),
            "pct_of_total": round(vs / total_vol * 100, 1),
        }
        if vs > avg_vol_per_bin * 1.5:
            hvns.append(entry)
        elif vs < avg_vol_per_bin * 0.3:
            lvns.append(entry)
    # HVN 按成交量降序、LVN 按成交量升序
    hvns.sort(key=lambda x: x["volume"], reverse=True)
    lvns.sort(key=lambda x: x["volume"])

    return VolumeProfileResult(
        vwap=round(vwap_val, 3),
        poc=poc_price,
        poc_volume=round(poc_vol, 1),
        poc_pct=poc_pct,
        value_area_high=round(va_high, 3),
        value_area_low=round(va_low, 3),
        profile=price_profile,
        hvns=hvns,
        lvns=lvns,
        total_volume=round(total_vol, 1),
        price_min=round(price_min, 3),
        price_max=round(price_max, 3),
        bin_size=round(bin_size, 4),
        num_bins=num_bins,
        lookback=lookback,
    )


def volume_profile_summary(vp: VolumeProfileResult,
                           current_price: float | None = None) -> str:
    """生成 Volume Profile 可读摘要（调试/日志用）。"""
    cp = current_price
    lines = [
        f"VWAP(成本线): {vp.vwap:.2f}",
        f"POC(最大成交量): {vp.poc:.2f}  (占{vp.poc_pct:.1f}%)",
        f"价值区域(70%): {vp.value_area_low:.2f} ~ {vp.value_area_high:.2f}",
    ]
    if cp is not None and cp > 0:
        if cp > vp.value_area_high:
            pos = "价值区域上方 ← 高估值区"
        elif cp < vp.value_area_low:
            pos = "价值区域下方 ← 低估/支撑区"
        else:
            pos = "价值区域内 ← 合理估值"
        lines.append(f"当前价 {cp:.2f}: {pos}")

    if vp.hvns:
        top_hvn = vp.hvns[:3]
        lines.append(f"HVN(密集成交/支撑阻力): "
                     + ", ".join(f"{h['price_center']:.2f}({h['pct_of_total']:.1f}%)"
                                 for h in top_hvn))
    if vp.lvns:
        top_lvn = vp.lvns[:3]
        lines.append(f"LVN(成交真空/快速穿过): "
                     + ", ".join(f"{l['price_center']:.2f}({l['pct_of_total']:.1f}%)"
                                 for l in top_lvn))

    return "\n".join(lines)


def find_support_resistance(vp: VolumeProfileResult) -> dict:
    """从 Volume Profile 中提取关键支撑/阻力位。

    支撑 = 当前价下方的 HVN（密集成交=有人护盘）
    阻力 = 当前价上方的 HVN（密集成交=解套抛压）

    Returns:
        {"supports": [{price, strength}], "resistances": [{price, strength}]}
        strength 为 pct_of_total，越大越可靠。
    """
    supports = []
    resistances = []
    for hvn in vp.hvns:
        entry = {"price": hvn["price_center"], "strength": hvn["pct_of_total"]}
        if hvn["price_center"] < vp.vwap:
            supports.append(entry)
        else:
            resistances.append(entry)
    supports.sort(key=lambda x: x["price"], reverse=True)     # 从近到远
    resistances.sort(key=lambda x: x["price"])                 # 从近到远
    return {"supports": supports, "resistances": resistances}
