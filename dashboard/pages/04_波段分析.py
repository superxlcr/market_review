"""波段分析页面 — P/V 波峰波谷 + 趋势线叠加K线图.

核心: 波段50%线 = (P+V)/2 = 趋势生命线
     波段62.5%线、75%线 = 回调深浅参考
"""
import datetime as _dt
import logging
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import sys
import os

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.dashboard_service import DashboardService
from marketreview.tools.band_analysis import analyze_band, BandResult
from rendering.charts import plot_kline_with_ma
from rendering.styles import PAGE_CSS

st.set_page_config(page_title="波段分析", page_icon="📐", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()

st.title("📐 波段分析")
st.caption(f"P→V 波段趋势线 · K线叠加 ｜ AI v{DashboardService._AI_VERSION}")


# ═══════════════════════════════════════════════════════════════════
# Chart helper — mirrors plot_kline_with_ma from rendering/charts.py
# ═══════════════════════════════════════════════════════════════════

def _plot_kline_with_band(df: pd.DataFrame, band: BandResult,
                          display_tail: int = 200) -> go.Figure:
    """Reuse plot_kline_with_ma (no MA), then add band lines + lock y-axis."""
    fig = plot_kline_with_ma(df, display_days=display_tail, ma_periods=[])

    if band.p_price <= 0:
        return fig

    # Add band horizontal lines to Row 1
    fig.add_hline(y=band.p_price, line=dict(color="#e53935", width=1.5, dash="dot"),
                  annotation_text=f"P {band.p_price:.2f}", annotation_position="top left",
                  annotation_font=dict(color="#e53935", size=13), row=1, col=1)
    fig.add_hline(y=band.line_75, line=dict(color="#9c27b0", width=1, dash="dash"),
                  annotation_text=f"75% {band.line_75:.2f}", annotation_position="top left",
                  annotation_font=dict(color="#9c27b0", size=12), row=1, col=1)
    fig.add_hline(y=band.line_625, line=dict(color="#ff9800", width=1.2, dash="dash"),
                  annotation_text=f"62.5% {band.line_625:.2f}", annotation_position="top left",
                  annotation_font=dict(color="#ff9800", size=12), row=1, col=1)
    fig.add_hline(y=band.line_50, line=dict(color="#1976d2", width=2, dash="dash"),
                  annotation_text=f"50% {band.line_50:.2f}",
                  annotation_position="bottom left",
                  annotation_font=dict(color="#1976d2", size=13), row=1, col=1)

    # 回调半分位 — 跌破62.5%后每个交易日一个点
    if band.half_retrace_series and band.trigger_625_date:
        plot_df = df.tail(display_tail)
        hr_map = {p["date"]: p["price"] for p in band.half_retrace_series
                  if p["date"] >= band.trigger_625_date}
        # x 范围对齐 K 线，trigger 前填 None（日期统一转 str 防类型不匹配）
        x_full = [str(d) for d in plot_df["date"]]
        y_full = [hr_map.get(d, None) for d in x_full]
        if any(v is not None for v in y_full):
            fig.add_trace(go.Scatter(
                x=x_full, y=y_full, mode="markers",
                marker=dict(color="#00acc1", size=4, symbol="circle"),
                name="回调一半点位",
                connectgaps=False,
                hoverinfo="skip",
            ), row=1, col=1)

    fig.add_hline(y=band.v_price, line=dict(color="#43a047", width=1.5, dash="dot"),
                  annotation_text=f"V {band.v_price:.2f}", annotation_position="bottom left",
                  annotation_font=dict(color="#43a047", size=13), row=1, col=1)

    # # Draw all local valleys as markers (暂时注释，后续发现问题再调出)
    # if band.valleys:
    #     valley_dates = [v.date for v in band.valleys]
    #     valley_prices = [v.price for v in band.valleys]
    #     valley_labels = [f"{v.date}<br>V谷底: {v.price:.2f}" for v in band.valleys]
    #     fig.add_trace(go.Scatter(
    #         x=valley_dates, y=valley_prices,
    #         mode="markers",
    #         marker=dict(color="#00897b", size=10, symbol="triangle-down"),
    #         name="局部谷底",
    #         text=valley_labels,
    #         hoverinfo="text",
    #     ), row=1, col=1)

    # Lock y-axis to visible K-line range
    plot_df = df.tail(display_tail)
    y_min = plot_df["low"].min()
    y_max = plot_df["high"].max()
    y_pad = (y_max - y_min) * 0.1
    fig.update_yaxes(range=[y_min - y_pad, y_max + y_pad], row=1, col=1)

    return fig


# ═══════════════════════════════════════════════════════════════════
# Page UI
# ═══════════════════════════════════════════════════════════════════

# ── Stock selection ──
stocks_data = svc.get_watchlist_stocks()
watchlist = stocks_data.get("matched", [])

stocks_choices = []
if watchlist:
    for s in watchlist:
        label = f"{s['name']} ({s['ts_code']})"
        stocks_choices.append(label)

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    if stocks_choices:
        selected_label = st.selectbox(
            "📌 选择标的", stocks_choices,
            help="自选股列表。也可手动输入代码。",
        )
        selected_code = selected_label.split("(")[-1].rstrip(")")
    else:
        selected_code = st.text_input("🔢 股票代码", "000001.SZ",
                                       help="tushare 格式，如 000657.SZ")
with col2:
    peak_lookback = st.number_input(
        "PEAK_LOOKBACK（交易日）", min_value=60, max_value=500,
        value=300, step=10,
        help="波峰回溯窗口。300 ≈ ~14个月。",
    )
with col3:
    display_tail = st.number_input(
        "图表K线数", min_value=50, max_value=500,
        value=200, step=50,
        help="图表展示最近多少根K线。",
    )

# ── Analyze button ──
if st.button("🔍 分析波段", type="primary", use_container_width=True):
    if not selected_code:
        st.error("请输入股票代码。")
    else:
        with st.spinner(f"加载 {selected_code} K线数据..."):
            try:
                latest_date = svc.get_latest_trade_date()
                fetch_days = peak_lookback + 500
                buff_dt = _dt.datetime.strptime(latest_date, "%Y%m%d") - _dt.timedelta(days=fetch_days)
                start_date = buff_dt.strftime("%Y%m%d")
                svc._dp.ensure_data_loaded_for_codes([selected_code], start_date, latest_date)

                df = svc.get_index_data(selected_code, lookback=fetch_days, end_date=latest_date)
                if df.empty:
                    st.error(f"未找到 {selected_code} 的K线数据。")
                    st.stop()

                rows_asc = df.to_dict("records")
                band = analyze_band(rows_asc, peak_lookback=peak_lookback)

                st.session_state.band_df = df
                st.session_state.band_result = band
                st.session_state.band_code = selected_code

                st.success(f"✅ {selected_code} 波段分析完成")

            except Exception as e:
                st.error(f"加载失败: {e}")
                import traceback
                st.code(traceback.format_exc())

# ── Display results ──
if st.session_state.get("band_result"):
    band: BandResult = st.session_state.band_result
    df: pd.DataFrame = st.session_state.band_df
    code = st.session_state.get("band_code", "")

    if band.block_reason:
        st.warning(f"⚠️ {band.block_reason}")
        st.stop()

    # ── Key metrics ──
    st.divider()
    st.subheader("📊 波段结构")

    mc1, mc2, mc3, mc4 = st.columns(4)
    with mc1:
        st.metric("P（波峰）", f"{band.p_price:.2f}", delta=f"📅 {band.p_date}")
    with mc2:
        st.metric("V（前波谷）", f"{band.v_price:.2f}", delta=f"📅 {band.v_date}")
    with mc3:
        val_50x11 = band.line_50 * 1.1
        cmp_str = f"{val_50x11:.2f} vs {band.line_625:.2f}"
        cmp_delta = "✅ 趋势波段幅度成立" if band.v_qualified else "⚠️ 趋势波段幅度过小"
        st.metric("50%×1.1 vs 62.5%", cmp_str, delta=cmp_delta)
    with mc4:
        st.metric("当前价", f"{band.current_price:.2f}", delta=f"📅 {band.current_date}")

    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        st.metric("75% 回调线", f"{band.line_75:.2f}")
    with tc2:
        st.metric("62.5% 回调线", f"{band.line_625:.2f}")
    with tc3:
        st.metric("50% 趋势线", f"{band.line_50:.2f}",
                  delta="← 生命线，跌破则趋势可疑")

    hr_info = ""
    if band.half_retrace_series:
        hr_latest = band.half_retrace_series[-1]["price"]
        hr_info = f" | 回调半分位: {hr_latest:.2f}（跌破62.5%@{band.trigger_625_date}）"

    st.caption(f"💡 L（峰后最低）= {band.l_price:.2f} @ {band.l_date}{hr_info} | "
               f"K线总数: {band.rows_count} | 波峰距今: {band.rows_count - 1 - band.p_idx} 日 | "
               f"局部谷底: {len(band.valleys)} 个")

    # ── Chart ──
    st.divider()
    st.subheader(f"📈 {code} — 波段趋势线")

    fig = _plot_kline_with_band(df, band, display_tail=display_tail)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
