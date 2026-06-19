"""
Agent 2 — 板块分析页面
行业板块涨跌排名 + 技术分析 expander（复用市场全景框架）
"""
import streamlit as st
import sys
import os
import numpy as np
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from marketreview.tools.technical import (
    rows_to_df,
    calc_ma,
    ma_arrangement,
    ma_direction,
    volume_analysis,
    calc_kd,
    calc_rsi,
    calc_bias,
    bias_status,
    detect_kd_divergence,
    detect_rsi_divergence,
    get_offset_info,
    get_ma_role,
)
from services.dashboard_service import DashboardService
from rendering.styles import vol_color_ramp, up_down_color, PAGE_CSS
from rendering.charts import plot_kline_with_ma

st.markdown(PAGE_CSS, unsafe_allow_html=True)


def latest_val(series):
    """Get latest non-NaN value from a list."""
    for v in reversed(series):
        if not np.isnan(v):
            return round(float(v), 2)
    return None


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
        title = (
            f"{ind['name']} ({ind['level']})  "
            f"<span style='color:{color};'>{sign}{chg:.2f}%</span>  "
            f"{reasons_html}"
        )

        with st.expander(title, expanded=False):
            _render_industry_expander(_service, ind["code"], ind["name"], _td)


def _render_industry_expander(service, code, name, end_date):
    """Render full technical analysis for one industry — mirrors render_index_section()."""
    df = service.get_industry_daily(code, end_date=end_date)
    if df.empty:
        st.warning(f"暂无 {name} 数据")
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    price = float(latest["close"])

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
        o = float(latest["open"])
        prev_close = float(prev["close"])
        chg_pct = (price / prev_close - 1) * 100
        open_vs_prev = (o / prev_close - 1) * 100

        today_amt = float(latest["amount"]) / 1e5 if latest.get("amount") else 0
        yesterday_amt = float(prev["amount"]) / 1e5 if prev.get("amount") else 0
        amt_vs_prev = (
            (today_amt / yesterday_amt - 1) * 100 if yesterday_amt else 0
        )

        chg_color = "#e53935" if chg_pct >= 0 else "#43a047"
        sign_p = "+" if chg_pct >= 0 else ""
        sign_o = "+" if open_vs_prev >= 0 else ""
        sign_a = "+" if amt_vs_prev >= 0 else ""

        st.html(f"""
        <div style="font-size:18px;line-height:2;">
            <div>最新价：<span style="color:{chg_color};font-weight:bold;">
                {price:.2f}</span></div>
            <div>今日开盘：<span style="color:{chg_color};">
                {o:.2f}（{sign_o}{open_vs_prev:.2f}%）</span></div>
            <div>涨跌幅：<span style="color:{chg_color};font-weight:bold;">
                {sign_p}{chg_pct:.2f}%</span></div>
            <div>昨日收盘：<span>{prev_close:.2f}</span></div>
            <div>今日成交额：<span>
                {today_amt:.2f}亿（{sign_a}{amt_vs_prev:.2f}%）</span></div>
            <div>昨日成交额：<span>{yesterday_amt:.2f}亿</span></div>
        </div>
        """)

        st.markdown("**K线形态**")
        patterns = service.get_kline_patterns(df)
        if patterns:
            for p in patterns:
                dir_color = "#e53935" if "偏多" in p["direction"] else "#43a047"
                st.html(f"""
                <div style="padding:8px 12px;margin:4px 0;
                    border-left:4px solid {dir_color};
                    background:{dir_color}0a;border-radius:4px;">
                    <span style="font-weight:bold;font-size:16px;
                                 color:{dir_color};">
                    {p['name']} — {p['direction']}</span>
                    <br><span style="font-size:13px;color:#666;">{p['note']}</span>
                </div>
                """)
        else:
            st.caption("无明确多空意义")

    st.divider()

    # ── 均线 + 成交量 表格 ──
    ma_col, vol_col = st.columns([3, 2])

    with ma_col:
        st.markdown("**均线分析**")
        mas = calc_ma(df)
        ma_periods = [5, 10, 20, 60, 120, 240]
        ma_dirs = {}
        for p in ma_periods:
            ma_dirs[f"MA{p}"] = ma_direction(mas[f"MA{p}"])

        def _d_col(d):
            if d == "↑":
                return "#e53935"
            if d == "↓":
                return "#43a047"
            return "#999"

        def _r_col(r):
            if "支撑" in r or "向上" in r:
                return "#e53935"
            if "压制" in r or "向下" in r:
                return "#43a047"
            return "#999"

        rows_html = ""
        for p in ma_periods:
            mk = f"MA{p}"
            mv = latest_val(mas[mk])
            direction = ma_dirs.get(mk, "→")
            role = get_ma_role(price, mv, direction) if mv else "N/A"

            off = get_offset_info(df, p)
            off_date = off.get("offset_date", "")[:10] if off else ""
            off_amt = (
                f"{off['offset_amount_yi']:,.0f}亿"
                if off and off.get("offset_amount_yi") else "N/A"
            )

            rows_html += f"""<tr>
                <td style="font-weight:600;">{mk}</td>
                <td style="text-align:right;">{mv:.2f}</td>
                <td style="text-align:center;color:{_d_col(direction)};">
                    {direction}</td>
                <td style="text-align:center;color:{_r_col(role)};">{role}</td>
                <td style="font-size:12px;color:#888;">{off_date}</td>
                <td style="font-size:12px;color:#888;text-align:right;">
                    {off_amt}</td>
            </tr>"""

        st.html(f"""
        <table style="width:100%;font-size:14px;border-collapse:collapse;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                <th>均线</th><th>值</th><th>方向</th><th>作用</th>
                <th>扣抵日</th><th>扣抵量</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        """)

        arrangement = ma_arrangement(mas)
        st.caption(f"排列：{arrangement}")

    with vol_col:
        st.markdown("**成交量分析**")
        vol = volume_analysis(df)
        st.html(f"""
        <table style="width:100%;font-size:14px;border-collapse:collapse;">
            <tr><td style="color:#888;">今日成交额</td>
                <td style="text-align:right;font-weight:bold;">
                {vol.get('latest_amount_yi', 0):,.0f}亿</td></tr>
            <tr><td style="color:#888;">5日均量</td>
                <td style="text-align:right;">
                {vol.get('ma5_yi', 0):,.0f}亿</td></tr>
            <tr><td style="color:#888;">今日vs5日均量</td>
                <td style="text-align:right;
                    color:{vol_color_ramp(vol.get('vs_ma5_pct', 0))};
                    font-weight:bold;">
                {vol.get('vs_ma5_pct', 0):+.1f}%</td></tr>
            <tr><td style="color:#888;">10日均量</td>
                <td style="text-align:right;">
                {vol.get('ma10_yi', 0):,.0f}亿</td></tr>
            <tr><td style="color:#888;">今日vs10日均量</td>
                <td style="text-align:right;
                    color:{vol_color_ramp(vol.get('vs_ma10_pct', 0))};
                    font-weight:bold;">
                {vol.get('vs_ma10_pct', 0):+.1f}%</td></tr>
            <tr><td style="color:#888;">量能趋势(5日)</td>
                <td style="text-align:right;">
                {vol.get('trend_5d', '—')}</td></tr>
            <tr><td style="color:#888;">均量状态</td>
                <td style="text-align:right;">
                {vol.get('cross_state', '—')}
                {f"({vol.get('cross_days', 0)}天)"
                 if vol.get('cross_days') else ""}</td></tr>
        </table>
        """)

    st.divider()

    # ── 技术指标行 ──
    kd_k = latest_val(calc_kd(df)["k"]) or 0
    kd_d_val = latest_val(calc_kd(df)["d"]) or 0
    if kd_k > 80 and kd_d_val > 80:
        kd_zone = "🔥 超买区"
    elif kd_k < 20 and kd_d_val < 20:
        kd_zone = "❄️ 超卖区"
    else:
        kd_zone = "➖ 常态区"

    rsi_val = latest_val(calc_rsi(df))
    if rsi_val and rsi_val > 70:
        rsi_zone = "🔥 超买区"
    elif rsi_val and rsi_val < 30:
        rsi_zone = "❄️ 超卖区"
    else:
        rsi_zone = "➖ 常态区"

    kd_div = detect_kd_divergence(df)
    rsi_div = detect_rsi_divergence(df)
    kd_div_str = (
        f"{kd_div['type']} ({kd_div.get('days', 0)}天)"
        if kd_div.get("type") else "无"
    )
    rsi_div_str = (
        f"{rsi_div['type']} ({rsi_div.get('days', 0)}天)"
        if rsi_div.get("type") else "无"
    )

    bias10_val = latest_val(calc_bias(df, 10)) or 0.0
    bias20_val = latest_val(calc_bias(df, 20)) or 0.0
    b10s = bias_status(bias10_val, 10)
    b20s = bias_status(bias20_val, 20)

    ic1, ic2, ic3, ic4 = st.columns(4)

    with ic1:
        st.markdown("**KD 指标**")
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>K：<b>{kd_k:.1f}</b></div>
            <div>D：<b>{kd_d_val:.1f}</b></div>
            <div>区间：{kd_zone}</div>
            <div>背离：{kd_div_str}</div>
        </div>
        """)

    with ic2:
        st.markdown("**RSI 指标**")
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>RSI(12)：<b>{rsi_val:.1f}</b></div>
            <div>区间：{rsi_zone}</div>
            <div>背离：{rsi_div_str}</div>
        </div>
        """)

    with ic3:
        st.markdown("**BIAS 乖离率**")
        st.html(f"""
        <div style="font-size:15px;line-height:2;">
            <div>BIAS10：<b>{bias10_val:+.2f}%</b></div>
            <div style="color:#888;">{b10s}</div>
            <div>BIAS20：<b>{bias20_val:+.2f}%</b></div>
            <div style="color:#888;">{b20s}</div>
        </div>
        """)

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
