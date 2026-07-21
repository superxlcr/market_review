"""Debug: trace turtle strategy signal → trade flow for one ETF index."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marketreview.data.data_provider import DataProvider
from marketreview.winrate.scan_engine import prepare_klines, scan_stock
from marketreview.winrate.buypoint_defs import detect_buy_points
from marketreview.winrate.trade_sim import simulate_trade, BuyPointSignal
from marketreview.winrate.config import WinrateConfig, ETF_BUY_POINTS
from marketreview.tools.band_analysis import analyze_band
from dataclasses import replace
from dotenv import load_dotenv
import pandas as pd

load_dotenv()
dp = DataProvider(tushare_token=os.environ.get("TUSHARE_TOKEN", ""))
dp.ensure_csi_pool()

pool = dp.cache.get_csi_pool()
print(f"Pool has {len(pool)} indices")

# Find indices that actually have data, test first few
import random
tested = 0
for r in pool:
    if tested >= 5:
        break
    rows = dp.cache.get_daily(r['ts_code'], limit=2000)
    if not rows or len(rows) < 200:
        continue
    tested += 1

    # Run scan_stock for this index
    buy_points_to_test = ["20日突破", "海龟S1", "海龟S2"]
    cfg = WinrateConfig()
    cfg = replace(cfg, asset_class="index", buy_points=buy_points_to_test,
                  start_date="20230101", end_date="now")

    trades = scan_stock(
        r['ts_code'], r.get('name', ''), rows, cfg,
        "", "", "", "", {},
        asset_class="index",
    )

    from collections import Counter
    bp_counts = Counter(t.buy_point for t in trades)
    print(f"\n{r['ts_code']} ({r['name']}): {len(rows)} rows, trades={dict(bp_counts)}")
    for t in trades[:3]:
        print(f"  {t.buy_point}: entry={t.entry_date} exit={t.exit_date} "
              f"pnl={t.pnl_pct:+.2f}% reason={t.exit_reason}")
