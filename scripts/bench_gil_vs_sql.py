"""诊断：并发不加速是 GIL 还是 SQLite 锁？
A组=正常 scan_stock（含SQLite: wave33查询+市值预加载已缓存）
B组=去掉 SQLite 写入路径的对照（wave33_state 返回空，跳过 wave33 SQL）
看两组的 4并发加速比。"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    if line.startswith("TUSHARE_TOKEN="):
        os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from marketreview.data.data_provider import DataProvider
from marketreview.winrate import scan_engine as SE
from marketreview.winrate.config import WinrateConfig

dp = DataProvider(os.environ["TUSHARE_TOKEN"])
N = 12
basics = [b for b in dp.cache.get_stock_basic() if not b["is_st"]][:N]
codes = [b["ts_code"] for b in basics]
ind_map = dp.cache.get_stock_industries(codes)
# 预加载市值到内存（去掉 get_daily_basic_for_code 的 SQL）
mv_cache = {}
for c in codes:
    mv_cache[c] = {r["trade_date"]: float(r["total_mv"]) / 1e4
                   for r in dp.cache.get_daily_basic_for_code(c)}
base_cfg = WinrateConfig(min_list_days=0, long_ma_states=[], short_ma_states=[], mv_min_yi=0)


def scan_one(b, cfg, use_wave33):
    code = b["ts_code"]
    rows = dp.cache.get_daily(code, limit=2000)  # 这也是 SQL
    if not rows:
        return 0
    mvs = mv_cache.get(code, {})
    ind = ind_map.get(code, {})
    # B组: cache=None → _wave33_state 返回空，跳过 wave33 SQL
    cache = dp.cache if use_wave33 else None
    return len(SE.scan_stock(code, b.get("name", ""), rows, cfg,
                             ind.get("l1_name", ""), ind.get("l2_name", ""),
                             b.get("list_date", ""), mvs, cache=cache))


for label, use_w33 in [("A组(含wave33SQL)", True), ("B组(跳过wave33SQL)", False)]:
    print(f"\n--- {label} ---", flush=True)
    # 串行1只测基准
    t0 = time.time()
    scan_one(basics[0], base_cfg, use_w33)
    single = time.time() - t0
    print(f"  串行1只: {single:.1f}s", flush=True)
    # 4并发12只
    for w in [4, 8]:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=w) as ex:
            futs = [ex.submit(scan_one, b, base_cfg, use_w33) for b in basics]
            n = sum(f.result() for f in as_completed(futs))
        dt = time.time() - t0
        speedup = (single * N) / dt if dt > 0 else 0
        print(f"  {w}并发{x if False else ''}: {dt:.1f}s, 加速比={speedup:.2f}x (理论{w}x)", flush=True)
