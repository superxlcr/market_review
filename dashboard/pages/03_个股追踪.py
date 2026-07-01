"""
Agent 3 — 个股追踪页面
展示自选个股的技术分析，每只个股以 expander 形式展示。
"""
import datetime as _dt
import streamlit as st
import sys
import os
import numpy as np
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS
from services.dashboard_service import DashboardService
from rendering.index_section import render_ohlcv_section

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Date guard ──
_td = st.session_state.get("trade_date")
if not _td:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

# ── Strategy guard ──
_strategy_class = st.session_state.get("selected_strategy_class")
_strategy_name = st.session_state.get("selected_strategy_name", "")
if not _strategy_class:
    st.warning("⚠️ 尚未选择战法策略，请前往「控制台」设置")
    st.stop()

st.title("📋 个股追踪")
st.caption("Agent 3 — 个股技术分析")

st.markdown(
    f"📅 当前日期：<span style='color:#e53935;font-weight:bold;'>"
    f"{_td[:4]}-{_td[4:6]}-{_td[6:8]}</span>"
    f" &nbsp;|&nbsp; 📊 战法：<span style='color:#1976d2;font-weight:bold;'>"
    f"{_strategy_name}</span>",
    unsafe_allow_html=True,
)

st.divider()

_service = DashboardService()

# ── 加载自选个股 ──
_stocks_data = _service.get_watchlist_stocks()
_stocks = _stocks_data["matched"]
_unmatched = _stocks_data["unmatched"]

if _unmatched:
    _names = "、".join(_unmatched)
    st.warning(f"⚠️ {len(_unmatched)} 个名称未匹配：**{_names}**")

if not _stocks:
    st.info("暂无自选个股，请在 `config/watchlist_stocks.txt` 中配置")
    st.stop()

# ── 逐只渲染 ──
from marketreview.tools.technical import calc_atr
from marketreview.tools.band_analysis import analyze_band
from rendering.band_section import render_band_structure, plot_band_chart

for s in _stocks:
    code = s["ts_code"]
    name = s["name"]
    industry = s["industry"]

    # 加载个股 K 线
    df = _service.get_index_data(code, lookback=360, end_date=_td)

    if df.empty:
        with st.expander(
            f"{name} ({code}) — {industry} | ⚠️ 无数据", expanded=False
        ):
            st.warning(f"暂无 {name} 的 K 线数据")
        continue

    # 计算涨跌幅
    latest_close = float(df["close"].iloc[-1])
    if len(df) >= 2:
        prev_close = float(df["close"].iloc[-2])
        chg_pct = (latest_close / prev_close - 1) * 100
    else:
        chg_pct = 0.0

    chg_sign = "+" if chg_pct >= 0 else ""
    chg_color = "#e53935" if chg_pct >= 0 else "#43a047"

    # ── ATR 实体判定（用于标题状态标签）──
    atr_vals = calc_atr(df, period=14)
    atr = next((v for v in reversed(atr_vals) if not np.isnan(v)), None)

    if atr and atr > 0:
        body = abs(float(df["close"].iloc[-1]) - float(df["open"].iloc[-1]))
        entity_atr = body / atr
        if entity_atr >= 0.5:
            entity_label = "长阳" if chg_pct >= 0 else "长阴"
        elif entity_atr >= 0.25:
            entity_label = "中阳" if chg_pct >= 0 else "中阴"
        else:
            entity_label = "小阳" if chg_pct >= 0 else "小阴"
    else:
        entity_label = "阳线" if chg_pct >= 0 else "阴线"

    # ── Info line above expander ──
    info_line = (
        f"{name} ({code}) — {industry}  ·  "
        f"<span style='color:{chg_color};font-weight:bold;'>{chg_sign}{chg_pct:.2f}%</span>"
        f"  <span style='font-size:13px;color:#888;'>{entity_label}</span>"
    )
    st.html(f"<div style='margin-bottom:2px;font-size:15px;'>{info_line}</div>")

    with st.expander(f"{name} ({code})", expanded=False):
        # ── 战法信号检查 ──
        result = _service.check_stock_signal(
            ts_code=code, name=name,
            trade_date=_td, strategy_class=_strategy_class,
        )
        msg = result["message"]

        # 用 HTML callout 代替 st.success/warning/info，确保内联颜色标签生效
        _callout_css = {
            "success": "background:#d4edda;border-left:4px solid #28a745;color:#155724;",
            "warning": "background:#fff3cd;border-left:4px solid #ffc107;color:#856404;",
            "info":    "background:#d1ecf1;border-left:4px solid #17a2b8;color:#0c5460;",
            "error":   "background:#f8d7da;border-left:4px solid #dc3545;color:#721c24;",
        }
        if result.get("error"):
            style = _callout_css["error"]
        elif result["has_signal"] and result["price_reachable"]:
            style = _callout_css["success"]
        elif result["has_signal"] and not result["price_reachable"]:
            style = _callout_css["warning"]
        else:
            style = _callout_css["info"]

        st.markdown(
            f'<div style="{style} padding:0.75rem 1rem; border-radius:0.25rem; '
            f'margin:0.5rem 0; line-height:1.7;">{msg}</div>',
            unsafe_allow_html=True,
        )

        render_ohlcv_section(df, code, name, _service, section_type="stock")

    # ── 波段分析（独立 expander）──
    with st.expander(f"📐 {name} — 波段结构", expanded=False):
        band_lookback = 300
        fetch_days = band_lookback + 500
        buff_dt = _dt.datetime.strptime(_td, "%Y%m%d") - _dt.timedelta(days=fetch_days)
        start_date = buff_dt.strftime("%Y%m%d")
        try:
            _service._dp.ensure_data_loaded_for_codes([code], start_date, _td)
        except Exception:
            pass
        band_df = _service.get_index_data(code, lookback=fetch_days, end_date=_td)
        if band_df.empty:
            st.warning("暂无足量K线数据")
        else:
            rows_asc = band_df.to_dict("records")
            band = analyze_band(rows_asc, peak_lookback=band_lookback)
            render_band_structure(band)
            st.divider()
            st.caption(f"📈 {name} — 波段趋势线")
            band_fig = plot_band_chart(band_df, band, display_tail=200)
            if band_fig:
                st.plotly_chart(band_fig, use_container_width=True)

st.divider()
st.caption("编辑自选个股：修改 `config/watchlist_stocks.txt` 后刷新页面")
