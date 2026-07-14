"""band 跨天复用优化的等价性测试：
逐日对比 全量版 vs 优化版（pre_valleys + prev_band），关键字段必须完全一致。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
for line in open(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), encoding="utf-8"):
    if line.startswith("TUSHARE_TOKEN="):
        os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()

from marketreview.data.data_provider import DataProvider
from marketreview.tools.band_analysis import analyze_band, find_valleys

dp = DataProvider(os.environ["TUSHARE_TOKEN"])


def _eq_fields(b1, b2):
    """对比关键字段（P/V/L/趋势线/trigger_625/valleys 数量/current）。"""
    return (b1.p_price == b2.p_price and b1.p_idx == b2.p_idx
            and b1.v_price == b2.v_price and b1.v_idx == b2.v_idx
            and b1.v_qualified == b2.v_qualified
            and b1.line_50 == b2.line_50 and b1.line_625 == b2.line_625
            and b1.line_75 == b2.line_75
            and b1.l_price == b2.l_price
            and b1.trigger_625_date == b2.trigger_625_date
            and b1.current_price == b2.current_price
            and b1.current_vs_50 == b2.current_vs_50
            and len(b1.valleys) == len(b2.valleys)
            and b1.block_reason == b2.block_reason)


def test_band_reuse_equivalent_to_full():
    """逐日对比：全量 analyze_band vs 优化版（pre_valleys+prev_band）必须等价。"""
    b = [x for x in dp.cache.get_stock_basic() if not x["is_st"]][0]
    rows_desc = dp.cache.get_daily(b["ts_code"], limit=2000)
    klines_asc = list(reversed(rows_desc))
    n = len(klines_asc)
    assert n >= 60

    # 全周期预算 valleys
    lows = [float(r.get("low") or 0.0) for r in klines_asc]
    dates = [str(r.get("date", "")) for r in klines_asc]
    all_valleys = find_valleys(lows, dates, 0, n - 1, neighborhood=5)

    prev_band = None
    prev_i = -1
    mismatches = 0
    # 从第60天起逐日对比（前60天数据不足意义不大）
    for i in range(60, n):
        rows_upto = klines_asc[:i + 1]
        # 全量版：什么都不传
        full = analyze_band(rows_upto, peak_lookback=300, compute_close_peaks=False)
        # 优化版：传 pre_valleys + prev_band
        opt = analyze_band(rows_upto, peak_lookback=300, compute_close_peaks=False,
                           pre_valleys=all_valleys, prev_band=prev_band, prev_i=prev_i)
        if not _eq_fields(full, opt):
            mismatches += 1
            if mismatches <= 3:
                print(f"  mismatch @ i={i} date={dates[i]}: "
                      f"full(P={full.p_price}@{full.p_idx},V={full.v_price}@{full.v_idx},L={full.l_price}) "
                      f"opt(P={opt.p_price}@{opt.p_idx},V={opt.v_price}@{opt.v_idx},L={opt.l_price})")
        prev_band = opt
        prev_i = i

    total = n - 60
    print(f"对比 {total} 天，不一致 {mismatches} 天")
    assert mismatches == 0, f"P 复用优化不等价：{mismatches}/{total} 天不一致"
