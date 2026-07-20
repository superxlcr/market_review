"""ETF/行业指数 买点胜率回测 — 用中证行业/主题指数测各买点胜率。"""
import os
import sys
from datetime import datetime, timedelta
import streamlit as st
from dataclasses import replace
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS
from services.dashboard_service import DashboardService
from marketreview.winrate.config import parse_winrate_config, ETF_BUY_POINTS
from marketreview.winrate.reporter import save_run

st.set_page_config(page_title="ETF胜率", page_icon="📈", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()
st.title("📈 ETF/行业指数 胜率回测")
st.caption(f"中证行业/主题指数 · 单买点胜率 ｜ AI v{DashboardService._AI_VERSION}")

base = parse_winrate_config("config/winrate_config_etf.txt", asset_class="index")

# ── 标的池：从 csi_index_pool 缓存选（首次用拉取）──
svc._dp.ensure_csi_pool()
pool = svc._dp.cache.get_csi_pool()  # [{ts_code, name, category, list_date}]
pool_labels = {r["ts_code"]: f"{r['name']} ({r['ts_code']})" for r in pool}
pool_codes = [r["ts_code"] for r in pool]

# ── 配置区 ──
c1, c2, c3 = st.columns(3)
with c1:
    buy_points = st.multiselect("买点（可多选）", ETF_BUY_POINTS, default=list(ETF_BUY_POINTS))
    win_th = st.number_input("判赢阈值%（盘中浮盈）", 1.0, 50.0, base.win_threshold_pct)
with c2:
    short_ma = st.multiselect("短期均线排列（空=不限）", ["多头", "空头", "盘整"],
                              default=base.short_ma_states)
    long_ma = st.multiselect("长期均线排列（空=不限）", ["多头", "空头", "盘整"],
                             default=base.long_ma_states)
with c3:
    time_stop = st.number_input("时间止损天数", 1, 250, base.time_stop_days)
    workers = st.number_input("并发数", 1, 16, base.max_workers)

c4, c5 = st.columns(2)
with c4:
    start_date = st.text_input("开始日期(YYYYMMDD)", base.start_date)
with c5:
    # 指数池多选：默认全选
    sel_codes = st.multiselect(
        "指数池（默认全选 %d 个）" % len(pool_codes),
        pool_codes,
        default=pool_codes,
        format_func=lambda c: pool_labels.get(c, c),
    )

# 调试标的（单指数）
_ALL = "（跑选中的指数池）"
debug_options = [_ALL] + [pool_labels[c] for c in pool_codes]
debug_label = st.selectbox("🐞 调试标的（默认跑指数池；选中则只跑单只）", debug_options)
debug_code = "" if debug_label == _ALL else debug_label.split("(")[-1].rstrip(")")

cfg = replace(
    base, buy_points=buy_points, win_threshold_pct=win_th,
    short_ma_states=short_ma, long_ma_states=long_ma,
    start_date=start_date, time_stop_days=int(time_stop),
    max_workers=int(workers),
    index_pool=[debug_code] if debug_code else list(sel_codes),
    debug_code=debug_code.strip(),
)

# ── 数据准备 ──
_PREP_LOOKBACK_CAL = 600

def _prep_range(start_date: str, end_date: str) -> tuple[str, str]:
    sd = datetime.strptime(start_date.replace("-", ""), "%Y%m%d")
    prep_start = (sd - timedelta(days=_PREP_LOOKBACK_CAL)).strftime("%Y%m%d")
    prep_end = "" if end_date in ("", "now") else end_date.replace("-", "")
    if not prep_end:
        prep_end = svc._dp.cache.get_latest_date("000001.SZ") or start_date
        prep_end = prep_end.replace("-", "")
    return prep_start, prep_end

prep_start, prep_end = _prep_range(start_date, cfg.end_date)
st.caption(f"📦 数据准备范围：`{prep_start}` ~ `{prep_end}` "
           f"（扫描窗前推 {_PREP_LOOKBACK_CAL} 日历日预热）｜ 指数池 {len(cfg.index_pool)} 个")

_cov_range = st.session_state.get("etf_cov_range")
_cov_cache = st.session_state.get("etf_cov_cache")
_range_match = (_cov_range == (prep_start, prep_end))
_kline = (_cov_cache or {}).get("kline", {}) if _range_match else {}
_kline_ready = bool(_kline.get("ready"))
_data_ready = _kline_ready

if not _cov_cache:
    st.info("⏳ 数据未准备：请先点「数据准备」拉取选中指数的 K 线。")
elif not _range_match:
    st.warning("⚠️ 扫描日期或指数池已变更，数据准备结果失效，请重新点「数据准备」。")
elif _kline.get("error"):
    st.error(f"❌ 校验失败：{_kline.get('error')}，请重试「数据准备」。")
elif _data_ready:
    bl = _kline.get("blacklisted_count", 0)
    unavail = _kline.get("unavailable_count", 0)
    no_ohlc = _kline.get("no_ohlc_count", 0)
    late = _kline.get("late_starter_count", 0)
    notes = []
    if bl:
        notes.append(f"{bl} 个黑名单跳过")
    if unavail:
        notes.append(f"{unavail} 个 tushare 无数据")
    if no_ohlc:
        notes.append(f"{no_ohlc} 个无OHLC（无法波段分析）")
    if late:
        notes.append(f"{late} 个新指数（上市晚，部分覆盖）")
    extra = f"（{'，'.join(notes)}）" if notes else ""
    st.success(f"✅ 数据就绪：{_kline.get('total', len(cfg.index_pool))} 个指数 K线覆盖。{extra}")
else:
    miss_cnt = _kline.get("missing_count", len(_kline.get("missing_dates", [])))
    bl = _kline.get("blacklisted_count", 0)
    unavail = _kline.get("unavailable_count", 0)
    no_ohlc = _kline.get("no_ohlc_count", 0)
    late = _kline.get("late_starter_count", 0)
    parts = [f"⚠️ 数据未就绪：{miss_cnt} 个指数 K线缺口"]
    skip_parts = []
    if bl:
        skip_parts.append(f"{bl} 个黑名单跳过")
    if unavail:
        skip_parts.append(f"{unavail} 个 tushare 无数据")
    if no_ohlc:
        skip_parts.append(f"{no_ohlc} 个无OHLC（无法波段分析）")
    if late:
        skip_parts.append(f"{late} 个新指数（部分覆盖）")
    if skip_parts:
        parts.append(f"（{'，'.join(skip_parts)}）")
    parts.append("。请重试「数据准备」补齐。")
    st.warning("".join(parts))

col_prep, _ = st.columns([1, 3])
with col_prep:
    if st.button("📦 数据准备", help="拉取/校验选中指数的日 K"):
        prog = st.progress(0.0)
        status = st.empty()
        status.text("数据准备中（首次拉取选中指数可能几分钟）…")

        def _prep_cb(*args):
            if len(args) >= 3 and isinstance(args[1], (int, float)) and isinstance(args[2], (int, float)):
                cur, total = args[1], args[2]
                if total:
                    prog.progress(min(cur / total, 1.0))
                    status.text(f"数据准备中 [{args[0]}] {cur}/{total}")
                else:
                    status.text(f"数据准备中 [{args[0]}]…")
            elif args:
                status.text(f"数据准备中… {args[0]}")

        try:
            svc.prepare_winrate_data_etf(prep_start, prep_end, cfg.index_pool, progress_cb=_prep_cb)
        except Exception as e:
            st.error(f"数据准备出错：{e}")
        else:
            st.session_state.etf_cov_cache = svc.check_winrate_coverage_etf(
                prep_start, prep_end, cfg.index_pool,
                scan_start=start_date.replace("-", ""))
            st.session_state.etf_cov_range = (prep_start, prep_end)
        prog.progress(1.0)
        status.empty()
        st.rerun()

# ── 运行扫描 ──
if st.button("▶ 运行扫描", type="primary",
             disabled=not (buy_points and cfg.index_pool and _data_ready),
             help="数据就绪后可用" if _data_ready else "请先完成「数据准备」"):
    prog = st.progress(0.0)
    status = st.empty()

    # 过滤黑名单 + 无OHLC指数，避免空数据干扰扫描
    from services.dashboard_service import DashboardService
    blacklist = DashboardService.load_etf_blacklist()
    no_ohlc_codes = set(_kline.get("no_ohlc_codes", []))
    scan_pool = [c for c in cfg.index_pool if c not in blacklist and c not in no_ohlc_codes]
    if not scan_pool:
        st.error("选中的指数全部在黑名单中，无可扫描标的。")
    else:
        cfg_clean = replace(cfg, index_pool=scan_pool)

        def cb(done, total):
            prog.progress(done / total)
            status.text(f"已扫描 {done}/{total} 个指数")

        timing_sink = []
        import time as _time
        _t0 = _time.perf_counter()
        with st.spinner(f"ETF 指数扫描中（{len(scan_pool)} 个）..."):
            stats, trades = svc.run_winrate_scan_etf(cfg_clean, progress_cb=cb, timing_sink=timing_sink)
        _elapsed = _time.perf_counter() - _t0
        scan_meta = {"elapsed": round(_elapsed, 1),
                     "total_indices": len(scan_pool),
                     "max_workers": cfg_clean.max_workers, "trades_n": len(trades)}
        saved_dir = save_run(trades, cfg_clean, scan_meta=scan_meta,
                             base_dir=".winrate_data_etf")
        prog.progress(1.0)
        status.empty()
        st.session_state.etf_stats = stats
        st.session_state.etf_saved_dir = saved_dir

# ── 结果 ──
if "etf_stats" in st.session_state:
    stats = st.session_state.etf_stats
    saved_dir = st.session_state.get("etf_saved_dir", "")
    if saved_dir:
        if stats:
            st.success(f"✅ ETF 明细已保存到 `{saved_dir}`（每买点一个 CSV + config_snapshot.txt）。")
        else:
            st.info(f"ℹ️ 扫描完成，但未触发任何买点。配置已保存到 `{saved_dir}`。")
    if not stats:
        st.warning("当前买点/参数组合在 %s~%s 期间无触发记录，尝试放宽 MA 筛选或调整买点。" %
                   (start_date, cfg.end_date))
    else:
        st.subheader("📊 买点对比汇总")
        st.dataframe([{
            "买点": s.buy_point, "触发次数": s.n,
            "胜率": f"{s.win_rate:.1%}",
            "大胜利率": f"{(s.big_win_n / s.n if s.n else 0):.1%}",
            "小胜利率": f"{(s.small_win_n / s.n if s.n else 0):.1%}",
            "止损率": f"{(s.stop_n / s.n if s.n else 0):.1%}",
            "亏损率": f"{(s.loss_n / s.n if s.n else 0):.1%}",
            "平均持有天": f"{s.avg_hold_days:.1f}",
            "期望收益": f"{s.expectancy_pct:+.2f}%",
        } for s in stats.values()], use_container_width=True, hide_index=True)

        for bp, s in stats.items():
            st.markdown(f"### 🎯 {bp} — {s.n}次 胜率{s.win_rate:.1%}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("大胜利", s.big_win_n)
            m2.metric("小胜利", s.small_win_n)
            m3.metric("盘中止损", s.stop_n)
            m4.metric("亏损", s.loss_n)
