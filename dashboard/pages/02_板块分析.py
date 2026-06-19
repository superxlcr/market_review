"""
Agent 2 — 板块分析页面
行业板块涨跌排名 + 技术分析 expander（复用市场全景框架）
"""
import streamlit as st
import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from marketreview.tools.technical import ma_arrangement
from services.dashboard_service import DashboardService
from rendering.styles import up_down_color, PAGE_CSS
from rendering.charts import plot_kline_with_ma
from rendering.technical_section import (
    render_ohlc_card,
    render_kline_patterns,
    render_ma_table,
    render_volume_section,
    render_short_term_trend,
    render_kd_section,
    render_rsi_section,
    render_bias_section,
)

st.markdown(PAGE_CSS, unsafe_allow_html=True)


# ── Date guard ──
_td = st.session_state.get("trade_date")
if not _td:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

st.title("🏭 板块分析")
_cd = f"{_td[:4]}-{_td[4:6]}-{_td[6:8]}"
st.caption(f"📅 {_cd}  |  申万行业分类 · 市值加权聚合")

_service = DashboardService()

# ── Section 1: AI 行业总结导语 ──
sector_summary = _service.get_ai_sector_summary(_td)
if sector_summary:
    st.info(sector_summary["content"])
else:
    st.caption("🤖 AI 行业总结尚未生成（切换日期时将自动生成）")

st.divider()

# ── Section 2: TOP 5 / BOTTOM 5 ──
st.subheader("📊 今日行业涨跌排名")

ranking = _service.get_industry_ranking(_td)
if not ranking:
    st.warning("暂无行业数据，请先在控制台加载数据")
    st.stop()

top5 = ranking[:5]
bottom5 = ranking[-5:]

col_g, col_l = st.columns(2)


def _render_rank_card(ind, rank, is_gainer):
    chg = ind["chg_pct"]
    color = up_down_color(chg)
    sign = "+" if chg >= 0 else ""
    level_tag = f"<span style='font-size:11px;color:#888;'>{ind['level']}</span>"
    sc = ind.get("stock_count", 0)
    up_ratio = f"{ind['up_count']}/{sc} ↑" if sc else ""
    amount_str = f"{ind.get('amount_yi', 0):.0f}亿" if ind.get("amount_yi") else ""

    if is_gainer:
        icons = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        icon = icons[rank]
    else:
        icons = ["5️⃣", "4️⃣", "🥉", "🥈", "🥇"]
        icon = icons[4 - rank]

    st.html(f"""
    <div style="border:1px solid #e0e0e0;border-radius:8px;
                padding:10px 14px;margin:4px 0;">
        <span style="font-size:18px;">{icon}</span>
        <span style="font-weight:600;font-size:16px;">{ind['name']}</span>
        {level_tag}
        <span style="color:{color};font-weight:bold;font-size:18px;
                     float:right;">{sign}{chg:.2f}%</span>
        <br><span style="font-size:12px;color:#888;">{up_ratio}  {amount_str}</span>
    </div>
    """)


with col_g:
    st.markdown("**🥇 领涨 TOP 5**")
    for i, ind in enumerate(top5):
        _render_rank_card(ind, i, True)

with col_l:
    st.markdown("**📉 领跌 TOP 5**")
    for i, ind in enumerate(reversed(bottom5)):
        _render_rank_card(ind, i, False)

st.divider()

def _render_industry_expander(service, code, name, end_date):
    """Render full technical analysis for one industry — mirrors render_index_section()."""
    df = service.get_industry_daily(code, end_date=end_date)
    if df.empty:
        st.warning(f"暂无 {name} 数据")
        return

    latest = df.iloc[-1]

    # ── AI 行业导语 ──
    ai_guide = service.get_ai_sector_guide(end_date, code)
    if ai_guide:
        st.info(ai_guide["content"])

    # ── K线图 + OHLC ──
    chart_col, ohlc_col = st.columns([3, 2])

    with chart_col:
        fig = plot_kline_with_ma(df)
        st.plotly_chart(fig, width="stretch")

    with ohlc_col:
        render_ohlc_card(df)
        render_kline_patterns(service, df)

    st.divider()

    # ── 均线 + 成交量 ──
    ma_col, vol_col = st.columns([3, 2])

    with ma_col:
        render_ma_table(df, show_avg_amount=False)
        arrangement = ma_arrangement(df)
        st.caption(f"排列：{arrangement}")

    with vol_col:
        render_volume_section(df, variant="compact")

    st.divider()

    # ── 技术指标行 ──
    trend_label = render_short_term_trend(df)

    ic1, ic2, ic3, ic4 = st.columns(4)

    with ic1:
        render_kd_section(df, layout="card")

    with ic2:
        render_rsi_section(df, trend_label, layout="card")

    with ic3:
        render_bias_section(df, layout="card")

    with ic4:
        st.markdown("**涨跌结构**")
        up_c = latest.get("up_count", 0)
        down_c = latest.get("down_count", 0)
        flat_c = latest.get("flat_count", 0)
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>上涨：<b style="color:#e53935;">{up_c}</b></div>
            <div>下跌：<b style="color:#43a047;">{down_c}</b></div>
            <div>平盘：<b style="color:#999;">{flat_c}</b></div>
        </div>
        """)


# ── Section 3: 行业详细分析 Expander 列表 ──
st.subheader("🔍 行业详细分析")

analysis_set = _service.get_industry_analysis_set(_td)
if not analysis_set:
    st.info("暂无需要分析的行业（TOP5涨跌 + 权重贡献 + 频繁行业 去重后为空）")
else:
    for ind in analysis_set:
        reasons_html = " ".join(
            f"<span style='background:#f0f0f0;padding:2px 8px;"
            f"border-radius:4px;font-size:12px;margin-right:4px;'>{r}</span>"
            for r in ind["reasons"]
        )
        chg = ind["chg_pct"]
        sign = "+" if chg >= 0 else ""
        color = up_down_color(chg)
        # st.expander label is plain-text only — put rich info inside
        title = f"{ind['name']} ({ind['level']})  {sign}{chg:.2f}%"

        with st.expander(title, expanded=False):
            st.html(f"""
            <div style="margin-bottom:6px;font-size:15px;">
                <span style="color:{color};font-weight:bold;">{sign}{chg:.2f}%</span>
                &nbsp;{reasons_html}
            </div>
            """)
            _render_industry_expander(_service, ind["code"], ind["name"], _td)
