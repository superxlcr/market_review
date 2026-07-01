"""波段分析页面 — P/V 波峰波谷 + 趋势线叠加K线图.

核心: 波段50%线 = (P+V)/2 = 趋势生命线
     波段62.5%线、75%线 = 回调深浅参考
"""
import datetime as _dt
import logging
import streamlit as st
import pandas as pd
import sys
import os

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.dashboard_service import DashboardService
from marketreview.tools.band_analysis import analyze_band, BandResult
from rendering.styles import PAGE_CSS
from rendering.band_section import render_band_structure, plot_band_chart

st.set_page_config(page_title="波段分析", page_icon="📐", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()

st.title("📐 波段分析")
st.caption(f"P→V 波段趋势线 · K线叠加 ｜ AI v{DashboardService._AI_VERSION}")




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
    render_band_structure(band)

    # ── Chart ──
    st.divider()
    st.subheader(f"📈 {code} — 波段趋势线")

    fig = plot_band_chart(df, band, display_tail=display_tail)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
