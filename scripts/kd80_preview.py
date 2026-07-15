"""
KD80 预览：统计 K>80 连续3天的股票数，SMA(3)平滑。
简化版 wave33 — 单条件替代 4 条件。
"""
import sys, io, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from marketreview.data.data_provider import DataProvider
from marketreview.tools.technical import rows_to_df, calc_kd_standard

# Load token from .env
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("TUSHARE_TOKEN="):
                os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()
                break

DP = DataProvider(os.environ["TUSHARE_TOKEN"])

# ── 日期范围 ──
DATES = ["20260319", "20260320", "20260321", "20260322", "20260323",
         "20260324", "20260325", "20260326", "20260327", "20260328",
         "20260329", "20260330", "20260331",
         "20260401", "20260402", "20260403", "20260404", "20260405",
         "20260406", "20260407", "20260408", "20260409", "20260410",
         "20260411", "20260412", "20260413", "20260414", "20260415",
         "20260416", "20260417", "20260418", "20260419", "20260420",
         "20260421", "20260422", "20260423", "20260424", "20260425",
         "20260426", "20260427", "20260428", "20260429", "20260430",
         "20260501", "20260502", "20260503", "20260504", "20260505",
         "20260506", "20260507", "20260508", "20260509", "20260510",
         "20260511", "20260512", "20260513", "20260514", "20260515",
         "20260516", "20260517", "20260518", "20260519", "20260520",
         "20260521", "20260522"]
START_DT = datetime.strptime(DATES[0], "%Y%m%d")
END_DT = datetime.strptime(DATES[-1], "%Y%m%d")
LOOKBACK_DAYS = (END_DT - (START_DT - timedelta(days=90))).days  # ~120d for KD calc

# ── 股票池 ──
stocks = DP.get_stock_list(DATES[-1])
print(f"股票池: {len(stocks)} 只")

# ── 预加载所有 K 线 + 计算 KD ──
# stock_kd[code] = {date_str: K_value}
stock_kd: dict[str, dict[str, float]] = {}
loaded = 0
for s in stocks:
    code = s["ts_code"]
    rows = DP.get_daily(code, end_date=DATES[-1], lookback_days=LOOKBACK_DAYS)
    if len(rows) < 30:
        continue
    df = rows_to_df(rows)
    if len(df) < 21:
        continue
    df = DataProvider.raw_to_qfq(df)
    kd = calc_kd_standard(df)
    # Build date→K map
    date_k_map = {}
    for i, d in enumerate(df["date"]):
        k_val = kd["K"][i]
        if not np.isnan(k_val):
            date_k_map[str(d)] = k_val
    if date_k_map:
        stock_kd[code] = date_k_map
    loaded += 1
    if loaded % 500 == 0:
        print(f"  加载 {loaded}/{len(stocks)}...")

print(f"有效股票: {len(stock_kd)}")

# ── 计算每日 KD80 ──
# 需要交易日前 2 天的数据来判断"连续3天"
# 先找到日期范围内的实际交易日
all_dates_sorted = sorted(set(
    d for kd_map in stock_kd.values() for d in kd_map.keys()
))
dates_in_range = [d for d in all_dates_sorted if DATES[0] <= d <= DATES[-1]]

# Build date index → previous dates
date_idx_map = {d: i for i, d in enumerate(all_dates_sorted)}

def get_kd80_count(target_date: str) -> int:
    """统计 target_date 这天 K>80 连续3天的股票数"""
    ti = date_idx_map.get(target_date)
    if ti is None or ti < 2:
        return 0
    d0 = target_date
    d1 = all_dates_sorted[ti - 1]
    d2 = all_dates_sorted[ti - 2]
    count = 0
    for code, kd_map in stock_kd.items():
        k0 = kd_map.get(d0)
        k1 = kd_map.get(d1)
        k2 = kd_map.get(d2)
        if k0 is None or k1 is None or k2 is None:
            continue
        if k0 > 80 and k1 > 80 and k2 > 80:
            count += 1
    return count

# ── 先算所有日期的 count（含范围外的，用于滚动求和和 SMA3 历史值）──
# 取范围前 25 天也开始算
pre_dates = [d for d in all_dates_sorted if d < DATES[0]][-25:]
all_target_dates = pre_dates + dates_in_range
all_counts = []
for d in all_target_dates:
    c = get_kd80_count(d)
    all_counts.append((d, c))

count_map = {d: c for d, c in all_counts}

# ── 汇总显示表 ──
print(f"\n{'日期':<10} {'KD80':>6} {'SMA3':>8} {'方向':>3}  {'21日累':>8} {'累SMA3':>8} {'方向':>3}  {'w33raw':>7} {'w33S3':>8} {'向':>3}")
print("-" * 80)

# 21-day rolling sums (use pre_dates for early range)
rolling21 = {}
for i, (d, c) in enumerate(all_counts):
    window = all_counts[max(0, i-20):i+1]
    rolling21[d] = sum(w[1] for w in window)

# SMA3 on raw
sma3_raw = {}
for i, (d, c) in enumerate(all_counts):
    if i >= 2:
        sma3_raw[d] = round((all_counts[i][1] + all_counts[i-1][1] + all_counts[i-2][1]) / 3, 1)
    elif i >= 1:
        sma3_raw[d] = round((all_counts[i][1] + all_counts[i-1][1]) / 2, 1)
    else:
        sma3_raw[d] = float(c)

# SMA3 on rolling21
sma3_r21 = {}
r21_items = sorted(rolling21.items())
for i, (d, v) in enumerate(r21_items):
    if i >= 2:
        sma3_r21[d] = round((r21_items[i][1] + r21_items[i-1][1] + r21_items[i-2][1]) / 3, 1)
    elif i >= 1:
        sma3_r21[d] = round((r21_items[i][1] + r21_items[i-1][1]) / 2, 1)
    else:
        sma3_r21[d] = float(v)

# Display only dates in range
# Pre-fetch wave33 raw counts for SMA3 calc
w33_raw = {}
for d in all_target_dates:
    w33 = DP.cache.get_wave33_range(limit=1, end_date=d)
    w33_raw[d] = w33[0]["count"] if w33 else 0
w33_sma3 = {}
w33_items = sorted(w33_raw.items())
for i, (d, v) in enumerate(w33_items):
    if i >= 2:
        w33_sma3[d] = round((w33_items[i][1] + w33_items[i-1][1] + w33_items[i-2][1]) / 3, 1)
    elif i >= 1:
        w33_sma3[d] = round((w33_items[i][1] + w33_items[i-1][1]) / 2, 1)
    else:
        w33_sma3[d] = float(v)

prev_sma = None
prev_rsma = None
prev_wsma = None
for d in dates_in_range:
    c = count_map.get(d, 0)
    s3 = sma3_raw.get(d, 0)
    r21 = rolling21.get(d, 0)
    rs3 = sma3_r21.get(d, 0)
    wr = w33_raw.get(d, 0)
    ws3 = w33_sma3.get(d, 0)

    dir1 = "  "
    if prev_sma is not None:
        if s3 > prev_sma: dir1 = " ↑"
        elif s3 < prev_sma: dir1 = " ↓"
    prev_sma = s3

    dir2 = "  "
    if prev_rsma is not None:
        if rs3 > prev_rsma: dir2 = " ↑"
        elif rs3 < prev_rsma: dir2 = " ↓"
    prev_rsma = rs3

    dir3 = "  "
    if prev_wsma is not None:
        if ws3 > prev_wsma: dir3 = " ↑"
        elif ws3 < prev_wsma: dir3 = " ↓"
    prev_wsma = ws3

    print(f"{d:<10} {c:>6} {s3:>8.1f} {dir1:>3}  {r21:>8} {rs3:>8.1f} {dir2:>3}  {wr:>7} {ws3:>8.1f} {dir3:>3}")
