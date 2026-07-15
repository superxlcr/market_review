"""定位单只扫描慢在哪：分阶段计时 scan_stock 的循环。
不改动 scan_engine 源码，而是复制核心循环逻辑、插入计时。"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    if line.startswith("TUSHARE_TOKEN="):
        os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()

from marketreview.data.data_provider import DataProvider
from marketreview.winrate.scan_engine import prepare_klines, _date_idx, _tag
from marketreview.winrate.config import WinrateConfig, cap_bucket
from marketreview.tools.technical import rows_to_df, calc_atr
from marketreview.tools.band_analysis import analyze_band
from marketreview.winrate.buypoint_defs import detect_buy_points
from marketreview.winrate.trade_sim import simulate_trade
from marketreview.winrate.filters import passes_all

dp = DataProvider(os.environ["TUSHARE_TOKEN"])
basics = [b for b in dp.cache.get_stock_basic() if not b["is_st"]]
# 选一只有数据的票
b = basics[0]
code = b["ts_code"]
rows_desc = dp.cache.get_daily(code, limit=2000)
mv_rows = dp.cache.get_daily_basic_for_code(code)
mv_series = {r["trade_date"]: float(r["total_mv"]) / 1e4 for r in mv_rows}
ind = dp.cache.get_stock_industries([code]).get(code, {})
cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[], mv_min_yi=0)

t_prep0 = time.time()
klines = prepare_klines(rows_desc)
n = len(klines)
t_prep = time.time() - t_prep0
dates = [k["date"] for k in klines]
start = cfg.start_date
end = None if cfg.end_date in ("", "now") else cfg.end_date

# 分阶段累计计时
t_filter = t_band = t_detect = t_sim = t_atr = 0.0
n_days = 0
n_filtered_out = 0
t0 = time.time()
i = 1
while i < n - 1:
    date_T = dates[i]
    if date_T < start or (end and date_T > end):
        i += 1
        continue
    n_days += 1
    df_upto = rows_to_df([klines[j] for j in range(i + 1)])
    mv_yi = mv_series.get(date_T, 0.0)

    s = time.time()
    ok = passes_all(df_upto, cfg, mv_yi, ind.get("l1_name", ""), ind.get("l2_name", ""), b.get("list_date", ""), date_T)
    t_filter += time.time() - s
    if not ok:
        n_filtered_out += 1
        i += 1
        continue

    s = time.time()
    band = analyze_band([klines[j] for j in range(i + 1)], peak_lookback=300)
    t_band += time.time() - s

    s = time.time()
    signals = detect_buy_points(df_upto, band, cfg.buy_points, code=code)
    t_detect += time.time() - s

    s = time.time()
    atr_vals = calc_atr(df_upto, period=14)
    atr_T = float(atr_vals[-1]) if atr_vals and atr_vals[-1] == atr_vals[-1] else 0.0
    t_atr += time.time() - s

    for sig in signals:
        s = time.time()
        tr = simulate_trade(sig, i, klines, cfg, code, b.get("name", ""), atr_T)
        t_sim += time.time() - s
        if tr is None:
            continue
    i += 1

total = time.time() - t0
print(f"=== {code} ({b.get('name','')}) ===", flush=True)
print(f"K线 {n}根, 遍历 {n_days} 天 (过滤掉 {n_filtered_out} 天)", flush=True)
print(f"总耗时 {total:.1f}s", flush=True)
print(f"  prepare_klines(一次): {t_prep:.2f}s", flush=True)
print(f"  passes_all(过滤): {t_filter:.2f}s ({t_filter/total*100:.0f}%)", flush=True)
print(f"  analyze_band: {t_band:.2f}s ({t_band/total*100:.0f}%)", flush=True)
print(f"  detect_buy_points: {t_detect:.2f}s ({t_detect/total*100:.0f}%)", flush=True)
print(f"  calc_atr: {t_atr:.2f}s ({t_atr/total*100:.0f}%)", flush=True)
print(f"  simulate_trade: {t_sim:.2f}s ({t_sim/total*100:.0f}%)", flush=True)
