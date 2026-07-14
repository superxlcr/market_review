"""并发基准测试：30 只票 × 多档并发，找最优 max_workers。
单只 3.5s（GIL 瓶颈已缓解到 3.5s），测并发能否线性加速。"""
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

N = 30
WORKERS = [1, 4, 6, 8, 12]   # 1=串行基准

dp = DataProvider(os.environ["TUSHARE_TOKEN"])
basics = [b for b in dp.cache.get_stock_basic() if not b["is_st"]][:N]
codes = [b["ts_code"] for b in basics]
ind_map = dp.cache.get_stock_industries(codes)
# 预加载市值到内存（去掉 get_daily_basic_for_code SQL 差异，纯测 scan_stock CPU）
mv_cache = {c: {r["trade_date"]: float(r["total_mv"]) / 1e4
                for r in dp.cache.get_daily_basic_for_code(c)} for c in codes}
base_cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[], mv_min_yi=0)
print(f"基准: {N}只票, 单只~3.5s, 测 {WORKERS}", flush=True)


def scan_one(b, cfg):
    code = b["ts_code"]
    rows = dp.cache.get_daily(code, limit=2000)
    if not rows:
        return 0
    mvs = mv_cache.get(code, {})
    ind = ind_map.get(code, {})
    return len(scan_stock(code, b.get("name", ""), rows, cfg,
                         ind.get("l1_name", ""), ind.get("l2_name", ""),
                         b.get("list_date", ""), mvs, cache=dp.cache))


results = {}
for w in WORKERS:
    cfg = replace(base_cfg, max_workers=w)
    t0 = time.time()
    if w == 1:
        n = sum(scan_one(b, cfg) for b in basics)
    else:
        with ThreadPoolExecutor(max_workers=w) as ex:
            futs = [ex.submit(scan_one, b, cfg) for b in basics]
            n = sum(f.result() for f in as_completed(futs))
    dt = time.time() - t0
    serial_est = dt if w == 1 else None
    speedup = (results.get(1, dt) * (1 if w == 1 else 1)) / dt if w != 1 else 1.0
    # 加速比 vs 串行(1档)
    speed_vs_serial = results.get(1, dt) / dt if w != 1 and 1 in results else 1.0
    results[w] = dt
    print(f"workers={w}: {dt:.1f}s, {n}笔, 加速比={speed_vs_serial:.2f}x (理论{w}x)", flush=True)

# 结论
print("\n=== 结论 ===", flush=True)
best = min(results.items(), key=lambda x: x[1] if x[0] != 1 else 1e9)
if 1 in results:
    for w in WORKERS:
        if w == 1:
            continue
        speed = results[1] / results[w]
        print(f"  {w}并发: {speed:.2f}x 加速", flush=True)
    # 找加速比最高
    best_w = max((w for w in WORKERS if w != 1), key=lambda w: results[1] / results[w])
    print(f"\n最优并发: {best_w} ({results[best_w]:.1f}s, {results[1]/results[best_w]:.2f}x)", flush=True)
