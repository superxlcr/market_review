"""
A股复盘 Dashboard — Agent 1 大盘分析视图。
启动: streamlit run dashboard/app.py
"""
import streamlit as st
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS
from rendering.charts import plot_kline_with_ma
from rendering.technical_section import (
    render_ohlc_card,
    render_kline_patterns,
    render_ma_table,
    render_ma_arrangement,
    render_volume_section,
    render_short_term_trend,
    render_kd_section,
    render_rsi_section,
    render_bias_section,
)

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ------- Index Section Builder -------


def render_index_section(service: DashboardService, code: str, name: str, end_date: str = None):
    """Render a full analysis section for one index."""
    df = service.get_index_data(code, end_date=end_date)

    if df.empty:
        st.warning(f"暂无 {name} 数据，请先运行 Agent 1 拉取数据")
        return

    # --- Row: K-line chart + OHLC table ---
    chart_col, ohlc_col = st.columns([3, 2])

    with chart_col:
        fig = plot_kline_with_ma(df)
        st.plotly_chart(fig, width="stretch")

    with ohlc_col:
        render_ohlc_card(df)
        render_kline_patterns(service, df)

    st.divider()

    # --- Row: MA table + Volume table ---
    ma_col, vol_col = st.columns([3, 2])

    with ma_col:
        render_ma_table(df, show_avg_amount=True)
        render_ma_arrangement(df)

    with vol_col:
        render_volume_section(df, variant="full")

    st.divider()

    # --- Row: Technical Indicators ---
    st.markdown("**技术指标**")
    trend_label = render_short_term_trend(df)
    render_kd_section(df, layout="table")
    render_rsi_section(df, trend_label, layout="table")
    render_bias_section(df, layout="table")

    # --- 权重贡献 ---
    st.divider()
    st.markdown("**权重贡献**")
    contrib = service.get_index_contribution(code, end_date)

    if contrib is None:
        st.caption("暂无权重贡献数据")
    else:
        idx = contrib["index"]
        # Summary line — colored per convention (red=up, green=down)
        chg_sign = "+" if idx["chg_pts"] >= 0 else ""
        chg_color = "#e53935" if idx["chg_pts"] >= 0 else "#43a047"
        st.markdown(
            f'指数收盘 <span style="color:{chg_color};font-weight:bold;font-size:18px;">'
            f'{idx["close"]:.2f}</span> ｜ '
            f'涨跌 <span style="color:{chg_color};font-weight:bold;font-size:18px;">'
            f'{chg_sign}{idx["chg_pts"]:.2f} 点 ({chg_sign}{idx["chg_pct"]:.2f}%)</span>',
            unsafe_allow_html=True,
        )

        st.caption("权重基于流通市值每日动态计算")

        left_col, right_col = st.columns(2)

        # --- 领涨 Top 10 ---
        with left_col:
            st.markdown(
                '<span style="color:#e53935;font-size:19px;font-weight:bold;">'
                '🔥 领涨 Top 10</span>',
                unsafe_allow_html=True,
            )
            if contrib["gainers"]:
                rows_html = ""
                for g in contrib["gainers"]:
                    rows_html += f"""<tr>
                        <td style="color:#888;font-size:16px;">{g['code']}</td>
                        <td style="font-weight:600;">{g['name']}</td>
                        <td style="color:#888;">{g['industry']}</td>
                        <td style="text-align:right;">{g['weight']:.2f}</td>
                        <td style="text-align:right;color:#e53935;font-weight:bold;">+{g['chg_pct']:.2f}</td>
                        <td style="text-align:right;color:#e53935;font-weight:bold;">+{g['contrib']:.2f}</td>
                    </tr>"""
                st.html(f"""
                <table style="width:100%;font-size:17px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:14px;">
                        <th style="text-align:left;">代码</th>
                        <th style="text-align:left;">名称</th>
                        <th style="text-align:left;">行业</th>
                        <th style="text-align:right;">权重%</th>
                        <th style="text-align:right;">涨幅%</th>
                        <th style="text-align:right;">贡献</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
                """)
            else:
                st.caption("无数据")

        # --- 领跌 Top 10 ---
        with right_col:
            st.markdown(
                '<span style="color:#43a047;font-size:19px;font-weight:bold;">'
                '❄️ 领跌 Top 10</span>',
                unsafe_allow_html=True,
            )
            if contrib["losers"]:
                rows_html = ""
                for l in contrib["losers"]:
                    rows_html += f"""<tr>
                        <td style="color:#888;font-size:16px;">{l['code']}</td>
                        <td style="font-weight:600;">{l['name']}</td>
                        <td style="color:#888;">{l['industry']}</td>
                        <td style="text-align:right;">{l['weight']:.2f}</td>
                        <td style="text-align:right;color:#43a047;font-weight:bold;">{l['chg_pct']:.2f}</td>
                        <td style="text-align:right;color:#43a047;font-weight:bold;">{l['contrib']:.2f}</td>
                    </tr>"""
                st.html(f"""
                <table style="width:100%;font-size:17px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:14px;">
                        <th style="text-align:left;">代码</th>
                        <th style="text-align:left;">名称</th>
                        <th style="text-align:left;">行业</th>
                        <th style="text-align:right;">权重%</th>
                        <th style="text-align:right;">跌幅%</th>
                        <th style="text-align:right;">贡献</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
                """)
            else:
                st.caption("无数据")

        # --- 近5日行业频次（出现 ≥3 天） ---
        freq = service.get_industry_frequency(code, end_date)
        if freq and (freq["gainers"] or freq["losers"]):
            st.markdown("---")
            st.caption("近 5 个交易日行业频次统计（同日贡献占比 ≥10% 或出现 ≥2 次即计数，出现 ≥3 天才展示）")

            f_left, f_right = st.columns(2)

            with f_left:
                st.markdown(
                    '<span style="color:#e53935;font-size:16px;font-weight:bold;">'
                    '🔥 频繁领涨行业</span>',
                    unsafe_allow_html=True,
                )
                if freq["gainers"]:
                    rows = ""
                    for item in freq["gainers"]:
                        rows += f"""<tr>
                            <td style="color:#888;font-size:14px;">{item['code']}</td>
                            <td style="font-weight:600;">{item['industry']}</td>
                            <td style="text-align:center;color:#e53935;font-weight:bold;">{item['days']}天</td>
                        </tr>"""
                    st.html(f"""
                    <table style="width:100%;font-size:16px;border-collapse:collapse;">
                        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
                            <th style="text-align:left;">代码</th>
                            <th style="text-align:left;">行业</th>
                            <th style="text-align:center;">出现天数</th>
                        </tr></thead>
                        <tbody>{rows}</tbody>
                    </table>
                    """)
                else:
                    st.caption("无行业满足 ≥3 天")

            with f_right:
                st.markdown(
                    '<span style="color:#43a047;font-size:16px;font-weight:bold;">'
                    '❄️ 频繁领跌行业</span>',
                    unsafe_allow_html=True,
                )
                if freq["losers"]:
                    rows = ""
                    for item in freq["losers"]:
                        rows += f"""<tr>
                            <td style="color:#888;font-size:14px;">{item['code']}</td>
                            <td style="font-weight:600;">{item['industry']}</td>
                            <td style="text-align:center;color:#43a047;font-weight:bold;">{item['days']}天</td>
                        </tr>"""
                    st.html(f"""
                    <table style="width:100%;font-size:16px;border-collapse:collapse;">
                        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
                            <th style="text-align:left;">代码</th>
                            <th style="text-align:left;">行业</th>
                            <th style="text-align:center;">出现天数</th>
                        </tr></thead>
                        <tbody>{rows}</tbody>
                    </table>
                    """)
                else:
                    st.caption("无行业满足 ≥3 天")


# ------- Page -------

# ======== Init DashboardService ========
_service = DashboardService()

# ── Date guard ──
_trade_date_yyyymmdd = st.session_state.get("trade_date")
if not _trade_date_yyyymmdd:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

_display_date = f"{_trade_date_yyyymmdd[:4]}-{_trade_date_yyyymmdd[4:6]}-{_trade_date_yyyymmdd[6:8]}"

st.title(f"📊 市场全景 — {_display_date}")
st.caption("Agent 1 — 大盘分析")

# ============ AI 市场全景总览 ============
_ai_cache = _service.get_ai_summary(_trade_date_yyyymmdd)
if _ai_cache and "summary" in _ai_cache:
    st.info(f"🤖 {_ai_cache['summary']['content']}")

# ============ 市场概览 ============
st.header("📈 市场概览")


@st.cache_data(ttl=300)
def load_market_overview(trade_date: str):
    """Fetch complete market overview via DashboardService."""
    svc = DashboardService()
    return svc.get_market_overview(trade_date)


overview = load_market_overview(_trade_date_yyyymmdd)

if overview is None:
    st.info("TUSHARE_TOKEN 未配置，无法加载市场概览")
elif "error" in overview:
    st.error(f"市场数据获取失败: {overview['error']}")
else:
    today = overview["today"]
    yesterday = overview["yesterday"]
    trend = overview["trend"]

    # ======== Row 1: 涨跌比 (left) + 成交额 (right) ========

    # ---- Card 1: 涨跌数量比 + 市场情绪 ----
    _up = today["up"]
    _flat = today["flat"]
    _down = today["down"]
    _ul = today["up_limit"]
    _dl = today["down_limit"]
    _total = _up + _flat + _down
    _up_pct = _up / _total * 100 if _total else 0
    _down_pct = _down / _total * 100 if _total else 0
    if _up >= _down:
        _sentiment_label, _sentiment_pct, _sentiment_color = "涨", _up_pct, "#e53935"
    else:
        _sentiment_label, _sentiment_pct, _sentiment_color = "跌", _down_pct, "#43a047"

    yest_html = ""
    if yesterday:
        _yup, _yflat, _ydown = yesterday["up"], yesterday["flat"], yesterday["down"]
        _yul, _ydl = yesterday["up_limit"], yesterday["down_limit"]
        hints = []
        up_chg = _up - _yup
        if abs(up_chg) > 50:
            hints.append(f'上涨家数{"↑" if up_chg > 0 else "↓"}{abs(up_chg)}')
        hint_str = "  |  ".join(hints) if hints else ""
        hint_color = "#e53935" if up_chg >= 0 else "#43a047"

        yest_html = f"""
        <div style="margin-top:10px;padding-top:8px;border-top:1px dashed #e0e0e0;font-size:14px;color:#999;">
            昨日：<span style="color:#e53935;">{_yup}</span>:<span>{_yflat}</span>:<span style="color:#43a047;">{_ydown}</span>
            涨停 {_yul} | 跌停 {_ydl}
        </div>
        <div style="margin-top:2px;font-size:13px;color:{hint_color};">{hint_str}</div>
        """

    card1_html = f"""
    <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:16px;flex:1;">
        <div style="font-size:17px;color:#888;margin-bottom:8px;">涨跌数量比</div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <span style="color:#e53935;font-size:34px;font-weight:bold;">{_up}</span>
            <span style="color:#888;font-size:17px;">涨</span>
            <span style="color:#9e9e9e;font-size:24px;">:</span>
            <span style="color:#9e9e9e;font-size:34px;font-weight:bold;">{_flat}</span>
            <span style="color:#888;font-size:17px;">平</span>
            <span style="color:#9e9e9e;font-size:24px;">:</span>
            <span style="color:#43a047;font-size:34px;font-weight:bold;">{_down}</span>
            <span style="color:#888;font-size:17px;">跌</span>
        </div>
        <div style="margin-top:4px;font-size:16px;color:{_sentiment_color};font-weight:bold;">
            市场情绪：{_sentiment_label} {_sentiment_pct:.1f}% 家
        </div>
        <div style="margin-top:6px;font-size:16px;">
            <span style="color:#e53935;">涨停 {_ul}</span>
            <span style="color:#999;margin:0 8px;">|</span>
            <span style="color:#43a047;">跌停 {_dl}</span>
        </div>
        {yest_html}
    </div>"""

    # ---- Card 2: 成交额 ----
    total_yi = today["total_yi"]
    sh_yi = today["sh_yi"]
    sz_yi = today["sz_yi"]
    bj_yi = today["bj_yi"]

    delta_html = ""
    yest_turnover_html = ""
    if yesterday:
        prev_yi = yesterday["total_yi"]
        change = total_yi - prev_yi
        change_pct = (total_yi / prev_yi - 1) * 100 if prev_yi else 0
        color = "#e53935" if change >= 0 else "#43a047"
        sign = "+" if change >= 0 else ""
        delta_html = f'<span style="color:{color};font-size:16px;">{sign}{change:,.0f}亿（{sign}{change_pct:.1f}%）</span>'

        yest_parts = [f'上证 {yesterday["sh_yi"]:,.0f}亿', f'深证 {yesterday["sz_yi"]:,.0f}亿']
        if yesterday["bj_yi"] > 0:
            yest_parts.append(f'北证 {yesterday["bj_yi"]:,.0f}亿')

        yest_turnover_html = f"""
        <div style="margin-top:10px;padding-top:8px;border-top:1px dashed #e0e0e0;font-size:14px;color:#999;">
            昨日：{yesterday["total_yi"]:,.0f}亿（{" | ".join(yest_parts)}）
        </div>
        """

    exchange_parts = [f'上证 {sh_yi:,.0f}亿', f'深证 {sz_yi:,.0f}亿']
    if bj_yi > 0:
        exchange_parts.append(f'北证 {bj_yi:,.0f}亿')

    card2_html = f"""
    <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:16px;flex:1;">
        <div style="font-size:17px;color:#888;margin-bottom:8px;">两市成交额（亿元）</div>
        <div style="font-size:34px;font-weight:bold;">{total_yi:,.0f}<span style="font-size:17px;color:#888;"> 亿</span></div>
        <div style="margin-top:4px;">{delta_html}</div>
        <div style="margin-top:8px;font-size:16px;">
            {" &nbsp;|&nbsp; ".join(exchange_parts)}
        </div>
        {yest_turnover_html}
    </div>"""

    st.html(f"""
    <div style="display:flex;gap:16px;align-items:stretch;">
        {card1_html}
        {card2_html}
    </div>""")

    # ======== Row 2: 10日成交额趋势 ========
    st.divider()

    if trend:
        import plotly.graph_objects as go
        from datetime import datetime

        # Format dates: "20260605" → "06-05"
        def _fmt_date(date_str: str) -> str:
            try:
                return datetime.strptime(date_str, "%Y%m%d").strftime("%m-%d")
            except Exception:
                return date_str

        labels = [_fmt_date(d["date"]) for d in trend]
        amounts = [d["total_yi"] for d in trend]

        # Bar colors: 涨多=红, 跌多=绿
        bar_colors = ["#e53935" if d.get("up", 0) >= d.get("down", 0) else "#43a047" for d in trend]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=labels, y=amounts, marker_color=bar_colors,
            text=[f"{a/10000:.2f}万亿" for a in amounts],
            textposition="outside", textfont=dict(size=12, color="#555"),
            hovertemplate="%{x}<br>成交额: %{y:,.0f}亿<extra></extra>",
        ))

        fig.update_layout(
            template="plotly_white", height=330,
            margin=dict(l=20, r=20, t=50, b=30),
            showlegend=False,
            yaxis_title="成交额（亿元）",
            xaxis=dict(title="", type="category", tickangle=0),
        )
        # Give bar labels breathing room
        y_min = min(amounts) * 0.85
        y_max = max(amounts) * 1.18
        fig.update_yaxes(range=[y_min, y_max])

        # Chart + avg summary side by side
        chart_col, info_col = st.columns([5, 1])
        with chart_col:
            st.caption("近10日成交额趋势  |  🟥 涨多  🟩 跌多")
            st.plotly_chart(fig, width="stretch")
        with info_col:
            # Today vs 5d/10d average comparison
            today_yi = today["total_yi"]
            avg5 = overview["avg_5d"]
            avg10 = overview["avg_10d"]

            def _vs_tag(val: float, avg: float) -> str:
                if not avg:
                    return ""
                pct = (val / avg - 1) * 100
                if pct >= 0:
                    return f'<span style="color:#e53935;font-size:14px;">▲ 高于 {pct:.1f}%</span>'
                else:
                    return f'<span style="color:#43a047;font-size:14px;">▼ 低于 {abs(pct):.1f}%</span>'

            vs5_tag = _vs_tag(today_yi, avg5)
            vs10_tag = _vs_tag(today_yi, avg10)

            st.html(f"""
            <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:16px;margin-top:30px;">
                <div style="font-size:16px;color:#888;">5日均量 {vs5_tag}</div>
                <div style="font-size:26px;font-weight:bold;">{avg5:,.0f}<span style="font-size:13px;color:#888;"> 亿</span></div>
                <div style="font-size:16px;color:#888;margin-top:12px;">10日均量 {vs10_tag}</div>
                <div style="font-size:26px;font-weight:bold;">{avg10:,.0f}<span style="font-size:13px;color:#888;"> 亿</span></div>
            </div>
            """)
    else:
        st.info("暂无成交额趋势数据")

# ======== Row 3: 3浪3选股趋势 ========
st.divider()
st.markdown("**📈 3浪3选股趋势**")
st.caption("近15日  |  🟥 趋势上行  🟩 趋势下降  |  ⬛折线 = 20日盈利数量")

wave33_col, wave33_info = st.columns([5, 1])

with wave33_col:
    import plotly.graph_objects as go

    w33_data = _service.get_wave33_data(chart_days=15, rolling_days=21,
                                        end_date=_trade_date_yyyymmdd)
    w33_dates_raw = w33_data["dates"]
    w33_counts = w33_data["counts"]
    w33_profit = w33_data["profit_counts"]

    # Format dates to MM-DD
    def _fmt_w33_date(d: str) -> str:
        clean = d.replace("-", "")
        return f"{clean[4:6]}-{clean[6:8]}" if len(clean) >= 8 else d

    _w33_dates = [_fmt_w33_date(d) for d in w33_dates_raw]

    if w33_counts:
        _w33_red = "rgba(229,57,53,0.55)"
        _w33_green = "rgba(67,160,71,0.55)"
        _w33_trend_series = w33_data.get("trend_series", [])
        _w33_bar_colors = [
            _w33_red if d == "up" else _w33_green
            for d in _w33_trend_series
        ] or [_w33_red] * len(w33_counts)  # fallback: all red

        _w33_fig = go.Figure()
        _w33_fig.add_trace(go.Bar(
            x=_w33_dates, y=w33_counts, marker_color=_w33_bar_colors,
            text=[str(c) for c in w33_counts],
            textposition="outside", textfont=dict(size=12, color="#555"),
            hovertemplate="%{x}<br>3浪3: %{y}只<extra></extra>",
        ))
        _w33_fig.add_trace(go.Scatter(
            x=_w33_dates, y=w33_profit,
            mode="lines+markers+text",
            line=dict(color="#212121", width=3),
            marker=dict(color="#212121", size=10, line=dict(color="#fff", width=2)),
            text=[str(c) for c in w33_profit],
            textposition="bottom center",
            textfont=dict(size=12, color="#212121"),
            hovertemplate="%{x}<br>20日盈利: %{y}只<extra></extra>",
        ))
        _w33_y_max = max(w33_counts) * 1.18 if w33_counts else 100
        _w33_fig.update_layout(
            template="plotly_white", height=330,
            margin=dict(l=40, r=10, t=10, b=50),
            showlegend=False,
            yaxis=dict(title="股票数量", range=[0, _w33_y_max]),
            xaxis=dict(title="", type="category", tickangle=0),
        )
        st.plotly_chart(_w33_fig, width="stretch")
    else:
        st.info("暂无 3浪3 数据，请先在控制台加载数据")

with wave33_info:
    trend = w33_data.get("trend", {})
    _trend_label = trend.get("label", "维持，盘整中")
    _trend_dir = trend.get("direction", "flat")
    _trend_color = "#e53935" if _trend_dir == "up" else ("#43a047" if _trend_dir == "down" else "#888")

    _w33_today = w33_counts[-1] if w33_counts else 0
    _w33_profit_today = w33_profit[-1] if w33_profit else 0
    _w33_profit_pct = _w33_profit_today / _w33_today * 100 if _w33_today else 0
    _w33_day_count = w33_data.get("latest_day_count", 0)
    _w33_day_new = w33_data.get("latest_day_new", 0)

    # Build date range label for the rolling window
    def _fmt_ymd(d: str) -> str:
        clean = d.replace("-", "")
        return f"{clean[4:6]}-{clean[6:8]}" if len(clean) >= 8 else d

    _w33_ws = w33_data.get("last_window_start", "")
    _w33_we = w33_data.get("last_window_end", "")
    _w33_range_label = f"（{_fmt_ymd(_w33_ws)} - {_fmt_ymd(_w33_we)}）" if _w33_ws and _w33_we else ""

    st.html(f"""
    <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:20px;margin-top:0px;">
        <div style="font-size:16px;color:#888;margin-bottom:4px;">今日 3浪3{_w33_range_label}</div>
        <div style="font-size:34px;font-weight:bold;">{_w33_today}<span style="font-size:13px;color:#888;"> 只</span></div>
        <div style="font-size:16px;color:#888;margin-top:10px;">当日选出 · 其中新增</div>
        <div style="font-size:20px;color:#333;font-weight:bold;">{_w33_day_count} 只<span style="color:#888;font-weight:normal;"> · </span><span style="color:#333;">{_w33_day_new} 只</span></div>
        <div style="font-size:16px;color:#888;margin-top:10px;">20日盈利数量</div>
        <div style="font-size:20px;color:#333;font-weight:bold;">{_w33_profit_today} 只<span style="color:#888;font-weight:normal;">（{_w33_profit_pct:.1f}%）</span></div>
        <div style="font-size:16px;color:#888;margin-top:16px;">变化趋势</div>
        <div style="font-size:19px;color:{_trend_color};font-weight:bold;">{_trend_label}</div>
    </div>
    """)

# ============ 上证指数 ============
with st.expander("📈 上证指数 000001.SH", expanded=True):
    # AI 导语
    if _ai_cache and "guide/sh_index" in _ai_cache:
        st.info(f"🤖 {_ai_cache['guide/sh_index']['content']}")
    render_index_section(_service, "000001.SH", "上证指数", end_date=_trade_date_yyyymmdd)

st.divider()

# ============ 创业板指 ============
with st.expander("📉 创业板指 399006.SZ", expanded=True):
    # AI 导语
    if _ai_cache and "guide/cz_index" in _ai_cache:
        st.info(f"🤖 {_ai_cache['guide/cz_index']['content']}")
    render_index_section(_service, "399006.SZ", "创业板指", end_date=_trade_date_yyyymmdd)

