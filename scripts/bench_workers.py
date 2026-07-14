"""并发基准测试：找最优 max_workers。用同一批股票测不同并发的耗时。"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    if line.startswith("TUSHARE_TOKEN="):
        os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from marketreview.data.data_provider import DataProvider
from marketreview.winrate.scan_engine import scan_stock
from marketreview.winrate.config import WinrateConfig

N_STOCKS = 12
WORKERS = [4, 8, 12]

dp = DataProvider(os.environ["TUSHARE_TOKEN"])
basics = [b for b in dp.cache.get_stock_basic() if not b["is_st"]][:N_STOCKS]
codes = [b["ts_code"] for b in basics]
ind_map = dp.cache.get_stock_industries(codes)
base_cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[], mv_min_yi=0)
print(f"基准: {N_STOCKS}只票, 单只串行~14.5s", flush=True)


def scan_one(b, cfg):
    code = b["ts_code"]
    rows = dp.cache.get_daily(code, limit=2000)
    if not rows:
        return 0
    mv = dp.cache.get_daily_basic_for_code(code)
    mvs = {r["trade_date"]: float(r["total_mv"]) / 1e4 for r in mv}
    ind = ind_map.get(code, {})
    return len(scan_stock(code, b.get("name", ""), rows, cfg,
                         ind.get("l1_name", ""), ind.get("l2_name", ""),
                         b.get("list_date", ""), mvs, cache=dp.cache))


for w in WORKERS:
    cfg = replace(base_cfg, max_workers=w)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=w) as ex:
        futs = [ex.submit(scan_one, b, cfg) for b in basics]
        n = sum(f.result() for f in as_completed(futs))
    dt = time.time() - t0
    print(f"workers={w}: {dt:.1f}s, {n}笔, 单只均{dt/N_STOCKS:.1f}s", flush=True)
