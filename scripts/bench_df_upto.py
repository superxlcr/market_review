"""精确测 df_upto 构造 vs 消费的耗时占比。"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    if line.startswith("TUSHARE_TOKEN="):
        os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()

from marketreview.data.data_provider import DataProvider
from marketreview.winrate.scan_engine import prepare_klines, _tag, _wave33_state
from marketreview.winrate.config import WinrateConfig
from marketreview.tools.technical import rows_to_df, calc_atr
from marketreview.tools.band_analysis import analyze_band, find_valleys
from marketreview.winrate.buypoint_defs import detect_buy_points
from marketreview.winrate.filters import passes_all
from marketreview.winrate.trade_sim import simulate_trade

dp = DataProvider(os.environ["TUSHARE_TOKEN"])
b = [x for x in dp.cache.get_stock_basic() if not x["is_st"]][0]
code = b["ts_code"]
rows_desc = dp.cache.get_daily(code, limit=2000)
mv_rows = dp.cache.get_daily_basic_for_code(code)
mv_series = {r["trade_date"]: float(r["total_mv"]) / 1e4 for r in mv_rows}
ind = dp.cache.get_stock_industries([code]).get(code, {})
cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[], mv_min_yi=0)

klines = prepare_klines(rows_desc)
n = len(klines)
dates = [k["date"] for k in klines]
start = cfg.start_date
end = None if cfg.end_date in ("", "now") else cfg.end_date
all_lows = [float(k.get("low") or 0.0) for k in klines]
all_dates = [str(k.get("date", "")) for k in klines]
all_valleys = find_valleys(all_lows, all_dates, 0, n - 1, neighborhood=5)

t_build = 0.0   # 构造 df_upto
t_passes = 0.0  # passes_all（含内部 calc_ma）
t_band = 0.0
t_detect = 0.0
t_tag = 0.0
n_pass = 0
prev_band = None
prev_i = -1
i = 1
while i < n - 1:
    date_T = dates[i]
    if date_T < start or (end and date_T > end):
        i += 1; continue
    t0 = time.time()
    df_upto = rows_to_df([klines[j] for j in range(i + 1)])
    t_build += time.time() - t0
    mv_yi = mv_series.get(date_T, 0.0)

    t0 = time.time()
    ok = passes_all(df_upto, cfg, mv_yi, ind.get("l1_name", ""), ind.get("l2_name", ""), b.get("list_date", ""), date_T)
    t_passes += time.time() - t0
    if not ok:
        i += 1; continue
    n_pass += 1

    t0 = time.time()
    band = analyze_band([klines[j] for j in range(i + 1)], peak_lookback=300, compute_close_peaks=False,
                        pre_valleys=all_valleys, prev_band=prev_band, prev_i=prev_i)
    t_band += time.time() - t0
    prev_band = band; prev_i = i

    t0 = time.time()
    signals = detect_buy_points(df_upto, band, cfg.buy_points, code=code)
    t_detect += time.time() - t0

    if cfg.use_atr_stop:
        atr_vals = calc_atr(df_upto, period=14)
        atr_T = float(atr_vals[-1])
    else:
        atr_T = 0.0
    for sig in signals:
        tr = simulate_trade(sig, i, klines, cfg, code, b.get("name", ""), atr_T)
        if tr is None: continue
        t0 = time.time()
        _tag(tr, df_upto, mv_yi, ind.get("l1_name", ""), ind.get("l2_name", ""), dp.cache)
        t_tag += time.time() - t0
    i += 1

total = t_build + t_passes + t_band + t_detect + t_tag
print(f"=== {code} 遍历 {n} 天 (passes_all通过 {n_pass} 天) ===")
print(f"总(非idle): {total:.2f}s")
print(f"  构造 df_upto: {t_build:.2f}s ({t_build/total*100:.0f}%)")
print(f"  passes_all:   {t_passes:.2f}s ({t_passes/total*100:.0f}%)")
print(f"  analyze_band: {t_band:.2f}s ({t_band/total*100:.0f}%)")
print(f"  detect_buy_points: {t_detect:.2f}s ({t_detect/total*100:.0f}%)")
print(f"  _tag(每笔): {t_tag:.2f}s ({t_tag/total*100:.0f}%)")
