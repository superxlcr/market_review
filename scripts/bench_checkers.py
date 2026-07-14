"""定位 detect_buy_points 内部哪个 checker 最慢。"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    if line.startswith("TUSHARE_TOKEN="):
        os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()

from marketreview.data.data_provider import DataProvider
from marketreview.winrate.scan_engine import prepare_klines
from marketreview.tools.technical import rows_to_df
from marketreview.tools.band_analysis import analyze_band
from marketreview.winrate.buypoint_defs import _NAME_MAP

dp = DataProvider(os.environ["TUSHARE_TOKEN"])
b = [x for x in dp.cache.get_stock_basic() if not x["is_st"]][0]
code = b["ts_code"]
rows = dp.cache.get_daily(code, limit=2000)
klines = prepare_klines(rows)

# 取最后一天的数据测每个 checker
df_upto = rows_to_df(klines)
band = analyze_band(klines, peak_lookback=300)

print(f"=== {code} 单日各 checker 耗时 ===", flush=True)
totals = {}
for name, (kind, checker) in _NAME_MAP.items():
    t0 = time.time()
    if kind in ("volnode", "random"):
        checker.check(df_upto, band, code=code)
    else:
        checker.check(df_upto, band)
    dt = time.time() - t0
    totals[name] = dt
    print(f"  {name}: {dt*1000:.0f}ms", flush=True)

print(f"\n总计 {sum(totals.values())*1000:.0f}ms/天", flush=True)
# 排序找最慢
print("\n最慢5个:", flush=True)
for name, dt in sorted(totals.items(), key=lambda x: -x[1])[:5]:
    print(f"  {name}: {dt*1000:.0f}ms", flush=True)
