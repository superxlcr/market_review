"""波段分析页面 — P/V 波峰波谷 + 趋势线叠加K线图.

核心: 波段50%线 = (P+V)/2 = 趋势生命线
     波段62.5%线、75%线 = 回调深浅参考
"""
import datetime as _dt
import logging
import streamlit as st
import pandas as pd
import numpy as np
import sys
import os

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.dashboard_service import DashboardService
from marketreview.tools.band_analysis import analyze_band, BandResult
from marketreview.tools.technical import calc_atr
from marketreview.tools.buy_points import find_all_buy_points, load_buy_point_config, compute_ma_probes
from rendering.styles import PAGE_CSS
from rendering.band_section import render_band_structure, plot_band_chart, render_buy_point_table, render_ma_probes

st.set_page_config(page_title="波段分析", page_icon="📐", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()

st.title("📐 波段分析")
st.caption(f"P→V 波段趋势线 · K线叠加 ｜ AI v{DashboardService._AI_VERSION}")




# ── Trade date (pre-compute for stock filtering) ──
latest_date = svc.get_latest_trade_date()
recent_dates = svc.get_recent_trading_dates(latest_date, count=120)
date_labels = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in recent_dates]

# ── Stock selection: watchlist first, then all A-share ──
stocks_data = svc.get_watchlist_stocks()
watchlist = stocks_data.get("matched", [])
watchlist_codes = {s["ts_code"] for s in watchlist}

all_stocks = svc._dp.cache.get_stock_basic()
# Filter to stocks listed on or before the default (latest) date
default_date = recent_dates[0] if recent_dates else latest_date
all_stocks = [s for s in all_stocks if s.get("list_date", "99999999") <= default_date]

wl_options: list[str] = []
other_options: list[str] = []
for s in all_stocks:
    label = f"{s['name']} ({s['ts_code']})"
    if s["ts_code"] in watchlist_codes:
        wl_options.append(label)
    else:
        other_options.append(label)
wl_options.sort()
other_options.sort()

stock_options = wl_options + other_options

col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
with col1:
    selected_label = st.selectbox(
        "📌 选择标的", stock_options,
        help="自选股排最前面。全 A 股可搜索。",
    )
    selected_code = selected_label.split("(")[-1].rstrip(")")
with col2:
    selected_date_label = st.selectbox(
        "📅 交易日", date_labels,
        help="选择分析截止交易日，默认为最新。",
    )
    selected_date = selected_date_label.replace("-", "")
with col3:
    peak_lookback = st.number_input(
        "PEAK_LOOKBACK（交易日）", min_value=60, max_value=500,
        value=300, step=10,
        help="波峰回溯窗口。300 ≈ ~14个月。",
    )
with col4:
    display_tail = st.number_input(
        "图表K线数", min_value=50, max_value=500,
        value=150, step=50,
        help="图表展示最近多少根K线。",
    )

# ── Analyze button ──
if st.button("🔍 分析波段", type="primary", use_container_width=True):
    if not selected_code:
        st.error("请输入股票代码。")
    else:
        with st.spinner(f"加载 {selected_code} K线数据..."):
            try:
                fetch_days = peak_lookback + 500
                buff_dt = _dt.datetime.strptime(selected_date, "%Y%m%d") - _dt.timedelta(days=fetch_days)
                start_date = buff_dt.strftime("%Y%m%d")
                svc._dp.ensure_data_loaded_for_codes([selected_code], start_date, selected_date)

                df = svc.get_index_data(selected_code, lookback=fetch_days, end_date=selected_date)
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

    fig = plot_band_chart(df, band, display_tail=display_tail,
                           ma_periods=[20, 60, 120, 240])
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # ── 买点提示 ──
    atr_vals = calc_atr(df, period=14)
    atr = next((v for v in reversed(atr_vals) if not np.isnan(v)), None)
    bp_config = load_buy_point_config()
    position_capital = bp_config.get("单个仓位资金", 0.0)
    buy_points = find_all_buy_points(df, band,
                                      ts_code=code,
                                      atr=atr,
                                      trend_direction="flat",
                                      position_capital=position_capital)
    render_buy_point_table(buy_points)

    # ── MA 探底记录 ──
    ma_probes = compute_ma_probes(df, band)
    render_ma_probes(ma_probes)
