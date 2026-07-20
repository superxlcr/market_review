"""扫描引擎：单只股票 walk-forward（闸1持仓→闸2过滤+买点→模拟），多线程并行。"""
from __future__ import annotations
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from marketreview.tools.technical import rows_to_df, calc_ma, calc_atr
from marketreview.tools.band_analysis import analyze_band, find_valleys
from marketreview.data.data_provider import DataProvider
from marketreview.log_util import get_logger
from .config import WinrateConfig, cap_bucket
from .filters import passes_all, ma_group_state
from .buypoint_defs import detect_buy_points
from .trade_sim import simulate_trade, TradeResult

log = get_logger(__name__)

_MA_PERIODS = [5, 10, 20, 55, 60, 120, 144, 240]


def prepare_klines(rows_desc: list[dict], asset_class: str = "stock") -> list[dict]:
    """rows_desc(date DESC, raw) → date ASC、（stock:qfq / index:raw）、每行带 ma5..ma240 与 date 字符串。"""
    df = rows_to_df(rows_desc)
    if df.empty:
        return []
    if asset_class == "stock":
        df = DataProvider.raw_to_qfq(df)   # 个股需前复权
    # index: 不 qfq（adj_factor=1.0，指数本身连续；调了是 no-op 但语义误导）
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
               industry_l1: str, industry_l2: str, industry_l3: str,
               list_date: str, mv_series: dict[str, float],
               concept_info: dict | None = None,
               band_lookback: int = 300,
               asset_class: str = "stock") -> list[TradeResult]:
    klines = prepare_klines(rows_desc, asset_class=asset_class)
    n = len(klines)
    if n < 60:
        return []

    dates = [k["date"] for k in klines]
    # 只在配置的时间窗内找信号
    start = cfg.start_date
    end = None if cfg.end_date in ("", "now") else cfg.end_date

    # 一次预算全周期 valleys（neighborhood=5）：V 是 P 之前的谷底，离 today 远（V/P<3/7 约束），
    # 右边早满 5 天，全量预算与每天重算等价（边界候选不可能是 V）。analyze_band 复用省大头。
    all_lows = [float(k.get("low") or 0.0) for k in klines]
    all_dates = [str(k.get("date", "")) for k in klines]
    all_valleys = find_valleys(all_lows, all_dates, 0, n - 1, neighborhood=5)

    # 一次建全周期 DataFrame（klines 已 ASC + 数值化，等价于 rows_to_df 但只建一次），
    # 循环里 iloc 切片取视图，避免每天重建 df_upto（原 2.94s/只，42%）。
    df_full = pd.DataFrame(klines)

    results: list[TradeResult] = []
    # 按 标的×买点 各自持仓：next_ok[买点]=该买点下次可建仓的最早 idx。
    # 买点之间互不影响——一起跑只为共用数据/band 提效；某买点持仓中，仅它自己不重复建仓。
    next_ok: dict[str, int] = {}
    prev_band = None   # 上一交易日的 BandResult（P 不变时跨天复用）
    prev_band_i = -1
    i = 1
    while i < n - 1:
        date_T = dates[i]
        if date_T < start or (end and date_T > end):
            i += 1
            continue

        df_upto = df_full.iloc[:i + 1]   # 截至 T 的视图（消费者只读不改）
        mv_yi = mv_series.get(date_T, 0.0)

        if not passes_all(df_upto, cfg, mv_yi, industry_l1, industry_l2, list_date, date_T):
            i += 1
            continue

        # compute_close_peaks=False: close_peaks 仅 21日高点买点用，
        # 该买点暂未纳入胜率分析（STAGE=trial，未注册到 _NAME_MAP），跳过省 ~0.5s/只。
        # 将来启用 21日高点时改回 True。
        # pre_valleys=全周期预算 valleys 复用；prev_band=P 不变时跨天复用（95% 天命中）。
        band = analyze_band([klines[j] for j in range(i + 1)], peak_lookback=band_lookback,
                            compute_close_peaks=False, pre_valleys=all_valleys,
                            prev_band=prev_band, prev_i=prev_band_i)
        prev_band = band
        prev_band_i = i
        signals = detect_buy_points(df_upto, band, cfg.buy_points, code=code)
        # 过滤持仓中的买点（各买点各自持仓，互不影响）
        signals = [s for s in signals if i >= next_ok.get(s.buy_point, 0)]
        if not signals:
            i += 1
            continue

        # ATR@T（仅启用 ATR 止损时才计算，否则跳过省 0.8s/只）
        if cfg.use_atr_stop:
            atr_vals = calc_atr(df_upto, period=14)
            atr_T = float(atr_vals[-1]) if atr_vals and atr_vals[-1] == atr_vals[-1] else 0.0
        else:
            atr_T = 0.0

        for sig in signals:
            tr = simulate_trade(sig, i, klines, cfg, code, name, atr_T,
                                asset_class=asset_class)
            if tr is None:
                continue
            _tag(tr, df_upto, mv_yi, industry_l1, industry_l2, industry_l3,
                 concept_info)
            results.append(tr)
            # 该买点跳过自己的持仓期：下次可建仓 = 出场日之后（不影响其它买点）
            exit_next = _date_idx(dates, tr.exit_date) + 1
            if exit_next > next_ok.get(sig.buy_point, 0):
                next_ok[sig.buy_point] = exit_next
        i += 1

    return results


def _date_idx(dates: list[str], d: str) -> int:
    try:
        return dates.index(d)
    except ValueError:
        return len(dates) - 1


def _tag(tr: TradeResult, df_upto, mv_yi, l1, l2, l3,
         concept_info: dict | None = None):
    tr.short_ma_state = ma_group_state(df_upto, [5, 10, 20])
    tr.long_ma_state = ma_group_state(df_upto, [60, 120, 240])
    tr.market_cap_yi = round(mv_yi, 1)
    tr.cap_bucket = cap_bucket(mv_yi) if mv_yi > 0 else ""
    tr.industry_l1 = l1
    tr.industry_l2 = l2
    tr.industry_l3 = l3
    if concept_info:
        tr.concept_i = concept_info.get("concept_i", "")
        tr.concept_n = concept_info.get("concept_n", "")


def run_scan(dp: DataProvider, cfg: WinrateConfig, progress_cb=None,
              timing_sink: list | None = None) -> list[TradeResult]:
    """全市场并行扫描。数据须已预加载到 cache。

    timing_sink: 传入空 list，每只标的的耗时/线程名/笔数会 append 进去，
                 末尾追加一行 __TOTAL__ 总耗时。供页面写 scan_timing.csv 观测并发效果。
    """
    if cfg.asset_class == "index":
        # ETF 模式：标的池来自 cfg.index_pool（UI 选中的指数），无 is_st/行业/概念
        universe = [{"ts_code": c, "name": c, "list_date": ""} for c in cfg.index_pool]
        ind_map = {}
        concept_map = {}
    else:
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
        ind_map = dp.cache.get_stock_industries(codes)  # {code:{l1_name,l2_name,l3_name}}
        concept_map = dp._get_or_build_concept_map(codes) if dp.cache.has_concepts() else {}

    def _one(b: dict) -> list[TradeResult]:
        code = b["ts_code"]
        t_start = time.perf_counter()
        rows_desc = dp.cache.get_daily(code, limit=2000)
        if not rows_desc:
            if timing_sink is not None:
                timing_sink.append({"code": code, "name": b.get("name", ""),
                                     "elapsed": time.perf_counter() - t_start,
                                     "thread": threading.current_thread().name,
                                     "completed_at": time.time(), "trades_n": 0})
            return []
        # index 模式无市值/行业/概念 → 空 dict（指数无这些概念）
        if cfg.asset_class == "stock":
            mv_rows = dp.cache.get_daily_basic_for_code(code)
            mv_series = {r["trade_date"]: float(r["total_mv"]) / 1e4 for r in mv_rows}
        else:
            mv_series = {}
        ind = ind_map.get(code, {})
        ci = concept_map.get(code, {})
        trades = scan_stock(
            code, b.get("name", ""), rows_desc, cfg,
            ind.get("l1_name", ""), ind.get("l2_name", ""),
            ind.get("l3_name", ""),
            b.get("list_date", ""), mv_series,
            concept_info=ci,
            asset_class=cfg.asset_class,
        )
        if timing_sink is not None:
            timing_sink.append({"code": code, "name": b.get("name", ""),
                                "elapsed": time.perf_counter() - t_start,
                                "thread": threading.current_thread().name,
                                "completed_at": time.time(), "trades_n": len(trades)})
        return trades

    all_trades: list[TradeResult] = []
    total = len(universe)
    done = 0
    scan_t0 = time.perf_counter()
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
    scan_elapsed = time.perf_counter() - scan_t0
    log.info("扫描完成: %d只股票, 共 %d 笔交易, 耗时 %.1fs (并发 %d)",
             total, len(all_trades), scan_elapsed, cfg.max_workers)
    if timing_sink is not None:
        timing_sink.append({"code": "__TOTAL__", "name": "",
                            "elapsed": scan_elapsed,
                            "thread": "", "completed_at": time.time(),
                            "trades_n": len(all_trades)})
    return all_trades
