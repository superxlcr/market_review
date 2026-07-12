"""扫描引擎：单只股票 walk-forward（闸1持仓→闸2过滤+买点→模拟），多线程并行。"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed

from marketreview.tools.technical import rows_to_df, calc_ma, calc_atr
from marketreview.tools.band_analysis import analyze_band
from marketreview.data.data_provider import DataProvider
from marketreview.log_util import get_logger
from .config import WinrateConfig, cap_bucket
from .filters import passes_all, ma_group_state
from .buypoint_defs import detect_buy_points
from .trade_sim import simulate_trade, TradeResult

log = get_logger(__name__)

_MA_PERIODS = [5, 10, 20, 55, 60, 120, 144, 240]


def prepare_klines(rows_desc: list[dict]) -> list[dict]:
    """rows_desc(date DESC, raw) → date ASC、qfq、每行带 ma5..ma240 与 date 字符串。"""
    df = rows_to_df(rows_desc)
    if df.empty:
        return []
    df = DataProvider.raw_to_qfq(df)
    mas = calc_ma(df, _MA_PERIODS)
    out: list[dict] = []
    for i, (_, r) in enumerate(df.iterrows()):
        d = r.to_dict()
        raw_date = str(r["date"])
        d["date"] = raw_date if raw_date.isdigit() else raw_date.replace("-", "")[:8]
        for p in _MA_PERIODS:
            vals = mas[f"MA{p}"]
            d[f"ma{p}"] = float(vals[i]) if i < len(vals) and vals[i] == vals[i] else 0.0  # NaN→0
        out.append(d)
    return out


def scan_stock(code: str, name: str, rows_desc: list[dict], cfg: WinrateConfig,
               industry_l1: str, industry_l2: str, list_date: str,
               mv_series: dict[str, float], band_lookback: int = 300) -> list[TradeResult]:
    klines = prepare_klines(rows_desc)
    n = len(klines)
    if n < 60:
        return []

    dates = [k["date"] for k in klines]
    # 只在配置的时间窗内找信号
    start = cfg.start_date
    end = None if cfg.end_date in ("", "now") else cfg.end_date

    results: list[TradeResult] = []
    i = 1
    while i < n - 1:
        date_T = dates[i]
        if date_T < start or (end and date_T > end):
            i += 1
            continue

        df_upto = rows_to_df([  # 截至 T 的 DataFrame（已 qfq，用 klines 直接切）
            klines[j] for j in range(i + 1)
        ])
        mv_yi = mv_series.get(date_T, 0.0)

        if not passes_all(df_upto, cfg, mv_yi, industry_l1, industry_l2, list_date, date_T):
            i += 1
            continue

        band = analyze_band([klines[j] for j in range(i + 1)], peak_lookback=band_lookback)
        signals = detect_buy_points(df_upto, band, cfg.buy_points)
        if not signals:
            i += 1
            continue

        # ATR@T（用于 ATR 止损）
        atr_vals = calc_atr(df_upto, period=14)
        atr_T = float(atr_vals[-1]) if atr_vals and atr_vals[-1] == atr_vals[-1] else 0.0

        # position-less：每个信号独立评估，不跳过持仓期（持仓/冷却规则改到分析层做）
        made: list[TradeResult] = []
        for sig in signals:
            tr = simulate_trade(sig, i, klines, cfg, code, name, atr_T)
            if tr is not None:
                _tag(tr, df_upto, mv_yi, industry_l1, industry_l2)
                made.append(tr)

        results.extend(made)
        i += 1

    return results


def _tag(tr: TradeResult, df_upto, mv_yi, l1, l2):
    tr.short_ma_state = ma_group_state(df_upto, [5, 10, 20])
    tr.long_ma_state = ma_group_state(df_upto, [60, 120, 240])
    tr.market_cap_yi = round(mv_yi, 1)
    tr.cap_bucket = cap_bucket(mv_yi) if mv_yi > 0 else ""
    tr.industry_l1 = l1
    tr.industry_l2 = l2


def run_scan(dp: DataProvider, cfg: WinrateConfig, progress_cb=None) -> list[TradeResult]:
    """全市场并行扫描。数据须已预加载到 cache。"""
    basics = dp.cache.get_stock_basic()   # [{ts_code,name,list_date,is_st}]
    if cfg.debug_code:
        want = cfg.debug_code.strip().upper()
        universe = [b for b in basics
                    if b["ts_code"].upper() == want or b["ts_code"].split(".")[0] == want]
        if not universe:
            log.warning("调试标的 %s 未在 stock_basic 中找到，返回空", cfg.debug_code)
            return []
        log.info("调试模式：只扫描 %s（绕过 is_st 过滤）", universe[0]["ts_code"])
    else:
        universe = [b for b in basics if not b.get("is_st")]
    codes = [b["ts_code"] for b in universe]
    ind_map = dp.cache.get_stock_industries(codes)  # {code:{l1_name,l2_name,...}}

    def _one(b: dict) -> list[TradeResult]:
        code = b["ts_code"]
        rows_desc = dp.cache.get_daily(code, limit=2000)
        if not rows_desc:
            return []
        mv_rows = dp.cache.get_daily_basic_for_code(code)  # Task 6 新增
        mv_series = {r["trade_date"]: float(r["total_mv"]) / 1e4 for r in mv_rows}
        ind = ind_map.get(code, {})
        return scan_stock(
            code, b.get("name", ""), rows_desc, cfg,
            ind.get("l1_name", ""), ind.get("l2_name", ""),
            b.get("list_date", ""), mv_series,
        )

    all_trades: list[TradeResult] = []
    total = len(universe)
    done = 0
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
        futs = {ex.submit(_one, b): b for b in universe}
        for fut in as_completed(futs):
            done += 1
            try:
                all_trades.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                log.warning("scan_stock 失败 %s: %s", futs[fut].get("ts_code"), e)
            if progress_cb:
                progress_cb(done, total)
    log.info("扫描完成: %d只股票, 共 %d 笔交易", total, len(all_trades))
    return all_trades
