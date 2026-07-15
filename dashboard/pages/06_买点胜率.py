"""买点胜率回测 — 全市场扫描单买点胜率。"""
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
from marketreview.winrate.config import parse_winrate_config, ALL_BUY_POINTS
from marketreview.winrate.reporter import save_run

st.set_page_config(page_title="买点胜率", page_icon="🎯", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()
st.title("🎯 买点胜率回测")
st.caption(f"全市场扫描 · 单买点胜率 ｜ AI v{DashboardService._AI_VERSION}")

base = parse_winrate_config("config/winrate_config.txt")

# ── 配置区 ──
c1, c2, c3 = st.columns(3)
with c1:
    buy_points = st.multiselect("买点（可多选）", ALL_BUY_POINTS, default=base.buy_points)
    win_th = st.number_input("判赢阈值%（盘中浮盈）", 1.0, 50.0, base.win_threshold_pct)
with c2:
    short_ma = st.multiselect("短期均线排列（空=不限）", ["多头", "空头", "盘整"],
                              default=base.short_ma_states)
    long_ma = st.multiselect("长期均线排列（空=不限）", ["多头", "空头", "盘整"],
                             default=base.long_ma_states)
with c3:
    mv_min = st.number_input("市值下限(亿)", 0.0, 100000.0, base.mv_min_yi)
    mv_max = st.number_input("市值上限(亿, 0=不限)", 0.0, 100000.0, base.mv_max_yi)

c4, c5, c6 = st.columns(3)
with c4:
    start_date = st.text_input("开始日期(YYYYMMDD)", base.start_date)
with c5:
    time_stop = st.number_input("时间止损天数", 1, 250, base.time_stop_days)
with c6:
    workers = st.number_input("并发数", 1, 16, base.max_workers)

_ALL_MARKET = "（全市场扫描）"
_dbg_stocks = svc._dp.cache.get_stock_basic()
debug_options = [_ALL_MARKET] + [
    f"{s['name']} ({s['ts_code']})"
    for s in sorted(_dbg_stocks, key=lambda x: x["ts_code"])
]
_dbg_idx = 0
if base.debug_code:
    for _i, _lbl in enumerate(debug_options):
        if _lbl.endswith(f"({base.debug_code})"):
            _dbg_idx = _i
            break
debug_label = st.selectbox(
    "🐞 调试标的（默认全市场；可输入名字/代码搜索，选中则只跑单只）",
    debug_options, index=_dbg_idx,
)
debug_code = "" if debug_label == _ALL_MARKET else debug_label.split("(")[-1].rstrip(")")

cfg = replace(
    base, buy_points=buy_points, win_threshold_pct=win_th,
    short_ma_states=short_ma, long_ma_states=long_ma,
    mv_min_yi=mv_min, mv_max_yi=mv_max, start_date=start_date,
    time_stop_days=int(time_stop), max_workers=int(workers),
    debug_code=debug_code.strip(),
)

# ── 数据准备（拉取/校验扫描范围内的日 K，作为运行扫描的前置门禁）──
_PREP_LOOKBACK_CAL = 600   # 预热缓冲日历日（盖 band300+MA240+3浪3，留余量）


def _prep_range(start_date: str, end_date: str) -> tuple[str, str]:
    """数据准备范围 = [start_date - 600日历日, end_date]。end_date='now' 用最新缓存日。"""
    sd = datetime.strptime(start_date.replace("-", ""), "%Y%m%d")
    prep_start = (sd - timedelta(days=_PREP_LOOKBACK_CAL)).strftime("%Y%m%d")
    prep_end = "" if end_date in ("", "now") else end_date.replace("-", "")
    if not prep_end:
        # now → 用代理股票最新缓存日（与主路径一致）
        prep_end = svc._dp.cache.get_latest_date("000001.SZ") or start_date
        prep_end = prep_end.replace("-", "")
    return prep_start, prep_end


prep_start, prep_end = _prep_range(start_date, cfg.end_date)
st.caption(f"📦 数据准备范围：`{prep_start}` ~ `{prep_end}` "
           f"（扫描窗前推 {_PREP_LOOKBACK_CAL} 日历日预热）")

# 就绪状态：缓存 + 范围一致性（K线 + wave33 双门禁）
_cov_range = st.session_state.get("wr_cov_range")
_cov_cache = st.session_state.get("wr_cov_cache")
_range_match = (_cov_range == (prep_start, prep_end))
_kline = (_cov_cache or {}).get("kline", {}) if _range_match else {}
_wave33 = (_cov_cache or {}).get("wave33", {}) if _range_match else {}
_kd80 = (_cov_cache or {}).get("kd80", {}) if _range_match else {}
_kline_ready = bool(_kline.get("ready"))
_wave33_ready = bool(_wave33.get("ready"))
_kd80_ready = bool(_kd80.get("ready"))
_data_ready = _kline_ready and _wave33_ready and _kd80_ready

# 状态条
if not _cov_cache:
    st.info("⏳ 数据未准备：请先点「数据准备」拉取扫描范围内的日 K + 3浪3 + KD80 数据。")
elif not _range_match:
    st.warning("⚠️ 扫描日期已变更，数据准备结果失效，请重新点「数据准备」。")
elif _kline.get("error") or _wave33.get("error") or _kd80.get("error"):
    errs = [e for e in [_kline.get("error"), _wave33.get("error"), _kd80.get("error")] if e]
    st.error(f"❌ 校验失败：{' / '.join(errs)}，请重试「数据准备」。")
elif _data_ready:
    kline_n = _kline.get("total_dates", 0)
    st.success(f"✅ 数据就绪：K线覆盖 {kline_n} 个交易日，3浪3 + KD80 全覆盖。")
else:
    kline_miss = _kline.get("missing_dates", [])
    w33_miss = _wave33.get("missing_dates", [])
    kd80_miss = _kd80.get("missing_dates", [])
    msgs = []
    if kline_miss:
        msgs.append(f"K线缺口 {len(kline_miss)} 天"
                    + (f"（{', '.join(kline_miss[:5])}…）" if kline_miss else ""))
    if w33_miss:
        msgs.append(f"3浪3 缺算 {len(w33_miss)} 天"
                    + (f"（{', '.join(w33_miss[:5])}…）" if w33_miss else ""))
    if kd80_miss:
        msgs.append(f"KD80 缺算 {len(kd80_miss)} 天"
                    + (f"（{', '.join(kd80_miss[:5])}…）" if kd80_miss else ""))
    st.warning("⚠️ 数据未就绪：" + "，".join(msgs) + "。请重试「数据准备」补齐。")

col_prep, _ = st.columns([1, 3])
with col_prep:
    if st.button("📦 数据准备", help="按上方范围拉取/校验全市场日 K + 复权因子"):
        prog = st.progress(0.0)
        status = st.empty()
        status.text("数据准备中（首次全市场可能十几分钟）…")

        def _prep_cb(*args):
            # ensure_data_loaded 的 progress_cb 签名：(phase, cur, total, [label])
            # phase="init"|"chunk"|"index"|"basic"|"validate"|"done" 等，cur/total 在固定位置 args[1]/args[2]
            if len(args) >= 3 and isinstance(args[1], (int, float)) and isinstance(args[2], (int, float)):
                cur, total = args[1], args[2]
                phase = args[0]
                if total:
                    prog.progress(min(cur / total, 1.0))
                    label = args[3] if len(args) >= 4 else ""
                    status.text(f"数据准备中 [{phase}] {cur}/{total}" + (f" {label}" if label else ""))
                else:
                    status.text(f"数据准备中 [{phase}]…")
            elif args:
                status.text(f"数据准备中… {args[0]}")

        try:
            svc.prepare_winrate_data(prep_start, prep_end, progress_cb=_prep_cb)
        except Exception as e:
            st.error(f"数据准备出错：{e}")
        else:
            st.session_state.wr_cov_cache = svc.check_winrate_coverage(prep_start, prep_end)
            st.session_state.wr_cov_range = (prep_start, prep_end)
        prog.progress(1.0)
        status.empty()
        st.rerun()

# ── 运行扫描（数据未就绪时禁用）──
if st.button("▶ 运行扫描", type="primary",
             disabled=not (buy_points and _data_ready),
             help="数据就绪后可用" if _data_ready else "请先完成「数据准备」"):
    prog = st.progress(0.0)
    status = st.empty()

    def cb(done, total):
        prog.progress(done / total)
        status.text(f"已扫描 {done}/{total} 只股票")

    timing_sink = []   # 收集每只标的耗时/线程名，写 scan_timing.csv 观测并发
    import time as _time
    _t0 = _time.perf_counter()
    with st.spinner("全市场扫描中..."):
        stats, trades = svc.run_winrate_scan(cfg, progress_cb=cb, timing_sink=timing_sink)
    _elapsed = _time.perf_counter() - _t0
    # scan_meta 写进 config_snapshot（含总耗时/票数/并发），便于历史对比
    total_stocks = len([t for t in timing_sink if t.get("code") != "__TOTAL__"])
    scan_meta = {"elapsed": round(_elapsed, 1), "total_stocks": total_stocks,
                 "max_workers": cfg.max_workers, "trades_n": len(trades)}
    saved_dir = save_run(trades, cfg, scan_meta=scan_meta)
    # 写 scan_timing.csv：每只标的 code/name/elapsed/thread/完成时间戳/笔数
    if timing_sink:
        import csv as _csv
        with open(f"{saved_dir}/scan_timing.csv", "w", encoding="utf-8-sig",
                  newline="") as f:
            w = _csv.DictWriter(f, fieldnames=["code", "name", "elapsed", "thread",
                                               "completed_at", "trades_n"])
            w.writeheader()
            for row in timing_sink:
                row["elapsed"] = round(row.get("elapsed", 0), 2)
                row["completed_at"] = round(row.get("completed_at", 0), 2)
                w.writerow(row)
    prog.progress(1.0)
    status.empty()
    st.session_state.wr_stats = stats
    st.session_state.wr_saved_dir = saved_dir

# ── 结果（仅汇总；逐笔明细见 CSV，避免页面卡顿）──
if st.session_state.get("wr_stats"):
    stats = st.session_state.wr_stats
    saved_dir = st.session_state.get("wr_saved_dir", "")
    if saved_dir:
        st.success(
            f"✅ 明细已保存到 `{saved_dir}`（每买点一个 CSV + config_snapshot.txt）。"
            f" 分析用 `python scripts/winrate_analysis.py`（默认读最新 run）。"
        )

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

    # 每个买点独立区块（仅指标；逐笔明细请看 CSV）
    for bp, s in stats.items():
        st.markdown(f"### 🎯 {bp} — {s.n}次 胜率{s.win_rate:.1%}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("大胜利", s.big_win_n)
        m2.metric("小胜利", s.small_win_n)
        m3.metric("盘中止损", s.stop_n)
        m4.metric("亏损", s.loss_n)
