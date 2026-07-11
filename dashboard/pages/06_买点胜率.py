"""买点胜率回测 — 全市场扫描单买点胜率。"""
import io
import os
import sys
import streamlit as st
from dataclasses import replace
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS
from services.dashboard_service import DashboardService
from marketreview.winrate.config import parse_winrate_config, ALL_BUY_POINTS
from marketreview.winrate.reporter import export_rows

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
    short_ma = st.selectbox("短期均线排列", ["无关", "多头", "空头"],
                            index=["无关", "多头", "空头"].index(base.short_ma_arrange))
    long_ma = st.selectbox("长期均线排列", ["无关", "多头", "空头"],
                           index=["无关", "多头", "空头"].index(base.long_ma_arrange))
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

cfg = replace(
    base, buy_points=buy_points, win_threshold_pct=win_th,
    short_ma_arrange=short_ma, long_ma_arrange=long_ma,
    mv_min_yi=mv_min, mv_max_yi=mv_max, start_date=start_date,
    time_stop_days=int(time_stop), max_workers=int(workers),
)

if st.button("▶ 运行扫描", type="primary", disabled=not buy_points):
    prog = st.progress(0.0)
    status = st.empty()

    def cb(done, total):
        prog.progress(done / total)
        status.text(f"已扫描 {done}/{total} 只股票")

    with st.spinner("全市场扫描中..."):
        stats, trades = svc.run_winrate_scan(cfg, progress_cb=cb)
    prog.progress(1.0)
    status.empty()
    st.session_state.wr_stats = stats
    st.session_state.wr_trades = trades

# ── 结果 ──
if st.session_state.get("wr_stats"):
    stats = st.session_state.wr_stats
    trades = st.session_state.wr_trades

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

    # 每个买点独立区块
    for bp, s in stats.items():
        st.markdown(f"### 🎯 {bp} — {s.n}次 胜率{s.win_rate:.1%}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("大胜利", s.big_win_n)
        m2.metric("小胜利", s.small_win_n)
        m3.metric("盘中止损", s.stop_n)
        m4.metric("亏损", s.loss_n)

        rows = export_rows(trades, bp)
        # 导出
        import csv as _csv
        buf = io.StringIO()
        if rows:
            w = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        st.download_button(
            f"⬇ 导出 {bp} 明细CSV", buf.getvalue().encode("utf-8-sig"),
            file_name=f"winrate_{bp}_{cfg.start_date}.csv", mime="text/csv",
            key=f"dl_{bp}",
        )
        # 明细（默认收起，按股票分组）
        with st.expander(f"📋 {bp} 逐笔明细（按股票分组）", expanded=False):
            by_code: dict[str, list] = {}
            for r in rows:
                by_code.setdefault(r["code"], []).append(r)
            for code, crows in by_code.items():
                name = crows[0].get("name", "")
                st.markdown(f"**{name} {code}** — {len(crows)}笔")
                st.dataframe([{
                    "信号日": r["signal_date"], "进场": f'{r["entry_date"]}@{r["entry_price"]}',
                    "出场": f'{r["exit_date"]}@{r["exit_price"]}', "原因": r["exit_reason"],
                    "浮盈%": r["mfp_pct"], "盈亏%": r["pnl_pct"], "持有": r["hold_days"],
                    "短均": r["short_ma_state"], "长均": r["long_ma_state"], "市值": r["cap_bucket"],
                } for r in crows], use_container_width=True, hide_index=True)
