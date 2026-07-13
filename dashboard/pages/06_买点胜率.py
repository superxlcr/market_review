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

# 就绪状态：缓存 + 范围一致性
_cov_range = st.session_state.get("wr_cov_range")
_cov_cache = st.session_state.get("wr_cov_cache")
_range_match = (_cov_range == (prep_start, prep_end))
_data_ready = bool(_cov_cache and _range_match and _cov_cache.get("ready")
                   and not _cov_cache.get("missing_dates"))

# 状态条
if not _cov_cache:
    st.info("⏳ 数据未准备：请先点「数据准备」拉取扫描范围内的日 K 数据。")
elif not _range_match:
    st.warning("⚠️ 扫描日期已变更，数据准备结果失效，请重新点「数据准备」。")
elif _cov_cache.get("error"):
    st.error(f"❌ 校验失败：{_cov_cache['error']}，请重试「数据准备」。")
elif _data_ready:
    st.success(f"✅ 数据就绪：覆盖 {_cov_cache['total_dates']} 个交易日，"
               f"最低覆盖率 {_cov_cache['min_ratio']:.0%}。")
else:
    miss = _cov_cache.get("missing_dates", [])
    st.warning(f"⚠️ 数据未就绪：缺口 {len(miss)} 天"
               + (f"（{', '.join(miss[:5])}…）" if miss else "")
               + "，请重试「数据准备」补齐。")

col_prep, _ = st.columns([1, 3])
with col_prep:
    if st.button("📦 数据准备", help="按上方范围拉取/校验全市场日 K + 复权因子"):
        prog = st.progress(0.0)
        status = st.empty()
        status.text("数据准备中（首次全市场可能十几分钟）…")

        def _prep_cb(*args):
            # ensure_data_loaded 的 progress_cb 签名是 (phase, cur, total) 或 (phase, cur, total, label)
            # 取最后两个数字作为 (cur, total)
            if len(args) >= 2 and isinstance(args[-2], (int, float)) and isinstance(args[-1], (int, float)):
                cur, total = args[-2], args[-1]
                if total:
                    prog.progress(min(cur / total, 1.0))
                    status.text(f"数据准备中… {cur}/{total}")
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

    with st.spinner("全市场扫描中..."):
        stats, trades = svc.run_winrate_scan(cfg, progress_cb=cb)
    saved_dir = save_run(trades, cfg)
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
