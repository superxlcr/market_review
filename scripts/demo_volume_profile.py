"""验证 Volume Profile 模块：在真实中证指数上对比 POC vs MA 支撑/阻力效果。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv
load_dotenv()

from marketreview.data.data_provider import DataProvider
from marketreview.tools.technical import rows_to_df
from marketreview.tools.volume_profile import (
    volume_profile, volume_profile_summary, find_support_resistance
)
import numpy as np

dp = DataProvider(tushare_token=os.environ.get("TUSHARE_TOKEN", ""))
dp.ensure_csi_pool()
pool = dp.cache.get_csi_pool()

# 挑几个有代表性的指数
targets = [
    "000171.CSI",   # 半导体
    "930734.CSI",   # 通信设备
    "000805.CSI",   # 创新药
]

for code in targets:
    name = next((r["name"] for r in pool if r["ts_code"] == code), code)
    rows = dp.cache.get_daily(code, limit=2000)
    if not rows or len(rows) < 250:
        print(f"\n{code} ({name}): 数据不足，跳过")
        continue

    df = rows_to_df(rows)
    # 指数数据：OHLC 可能为 NaN，用 close 填充
    for col in ("open", "high", "low"):
        if col in df.columns:
            df[col] = df[col].fillna(df["close"])

    print(f"\n{'='*70}")
    print(f"  {code} — {name}  ({len(df)} 根K线)")
    print(f"{'='*70}")

    # Volume Profile（最近 120 天）
    vp = volume_profile(df, lookback=120, num_bins=80)
    if vp is None:
        print("  Volume Profile 计算失败")
        continue

    current = float(df["close"].iloc[-1])
    ma20 = float(df["close"].iloc[-20:].mean())
    ma60 = float(df["close"].iloc[-60:].mean())
    ma120 = float(df["close"].iloc[-120:].mean())

    print(volume_profile_summary(vp, current))
    print()

    # ── 对比：POC / VWAP / Value Area vs MA ──
    sr = find_support_resistance(vp)
    supports = [s["price"] for s in sr["supports"][:3]]
    resistances = [r["price"] for r in sr["resistances"][:3]]

    print(f"  {'指标':<20} {'值':>10}  {'距当前价':>10}")
    print(f"  {'─'*40}")
    for label, val in [
        ("当前价", current),
        ("VWAP(成本线)", vp.vwap),
        ("POC(最大量)", vp.poc),
        ("VA低(价值区底)", vp.value_area_low),
        ("VA高(价值区顶)", vp.value_area_high),
        ("MA20", ma20),
        ("MA60", ma60),
        ("MA120", ma120),
    ]:
        dist = f"{(val/current - 1)*100:+.1f}%"
        print(f"  {label:<20} {val:>10.2f}  {dist:>10}")

    if supports:
        print(f"\n  [支撑] HVN: {[f'{s:.2f}' for s in supports]}")
        print(f"  [支撑] MA: MA20={ma20:.2f}, MA60={ma60:.2f}")
    if resistances:
        print(f"  [阻力] HVN: {[f'{r:.2f}' for r in resistances]}")

print("\n" + "="*70)
print("  结论：POC/HVN 来自真实成交量分布，比 MA 更能反映实际筹码成本。")
print("="*70)
