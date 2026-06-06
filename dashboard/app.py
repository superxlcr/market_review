"""
A股复盘 Dashboard — Agent 1 大盘分析视图。
启动: streamlit run dashboard/app.py
"""
import streamlit as st
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marketreview.data.cache_manager import CacheManager
from marketreview.data.data_provider import DataProvider
from marketreview.tools.technical import (
    rows_to_df,
    calc_ma,
    ma_arrangement,
    ma_direction,
    volume_analysis,
    calc_kdj,
    calc_rsi,
    calc_bias,
    kline_pattern,
)

st.set_page_config(page_title="A股复盘", page_icon="📊", layout="wide")

st.markdown("""
<style>
.streamlit-expanderHeader {
    font-size: 1.44em !important;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# ------- Helpers -------


@st.cache_data(ttl=300)
def load_data(code: str, lookback: int = 360, end_date: str = None):
    """Load K-line data via DataProvider (cache + auto-fetch from Tushare)."""
    token = os.environ.get("TUSHARE_TOKEN", "")
    dp = DataProvider(tushare_token=token)
    rows = dp.get_daily(code, lookback_days=lookback)
    df = rows_to_df(rows)
    if end_date and not df.empty:
        # Cache returns dates as YYYYMMDD; normalize to that for comparison
        cutoff = end_date.replace("-", "")
        df = df[df["date"].str.replace("-", "") <= cutoff]
    return df


def get_offset_info(df: pd.DataFrame, period: int):
    """
    Returns (扣抵日, 扣抵价) for MA period.
    扣抵日 = N trading days before today (date-ascending df).
    扣抵价 = close price on that day.
    If today's close > 扣抵价, MA will keep rising; if <, MA will turn down.
    """
    idx = len(df) - 1 - period
    if idx < 0:
        return "N/A", None
    row = df.iloc[idx]
    return str(row["date"])[:10], round(float(row["close"]), 2)


def ma_role(price: float, ma_val: float, direction: str) -> str:
    """Determine MA role: 支撑 / 压制 / 无 (flat → no role)."""
    if direction == "→":
        return "无"
    if price > ma_val:
        return "支撑"
    else:
        return "压制"


def latest_val(series: list[float]) -> float | None:
    """Get latest non-NaN value from a list."""
    for v in reversed(series):
        if not np.isnan(v):
            return round(float(v), 2)
    return None


# ------- Chart -------


def plot_kline_with_ma(df: pd.DataFrame, display_days: int = 60):
    """Plotly candlestick + MA overlay. MAs computed on full data, chart shows last N days."""
    import plotly.graph_objects as go

    # Compute MAs on full dataset (needed for MA240)
    mas = calc_ma(df)

    # Slice to last display_days for display
    plot_df = df.tail(display_days)

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=plot_df["date"], open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"], name="K线",
        increasing_line_color="#e53935", decreasing_line_color="#43a047",
    ))

    ma_colors = {"MA5": "#2196f3", "MA10": "#ff9800", "MA20": "#9c27b0",
                 "MA60": "#4caf50", "MA120": "#ff5722", "MA240": "#795548"}
    for name, color in ma_colors.items():
        if name in mas:
            ma_slice = mas[name][-display_days:]
            fig.add_trace(go.Scatter(
                x=plot_df["date"], y=ma_slice, mode="lines",
                line=dict(color=color, width=1.2), name=name,
            ))

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_white", height=420, margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="top", y=1.08, xanchor="left", x=0),
    )
    fig.update_xaxes(title_text="", showticklabels=False)
    fig.update_yaxes(title_text="价格")
    return fig


# ------- Index Section Builder -------


def render_index_section(code: str, name: str, end_date: str = None):
    """Render a full analysis section for one index."""
    df = load_data(code, end_date=end_date)

    if df.empty:
        st.warning(f"暂无 {name} 数据，请先运行 Agent 1 拉取数据")
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    price = float(latest["close"])

    # --- Row: K-line chart + OHLC table ---
    chart_col, ohlc_col = st.columns([3, 2])

    with chart_col:
        fig = plot_kline_with_ma(df)
        st.plotly_chart(fig, width="stretch")

    with ohlc_col:
        o = float(latest["open"])
        today_vol = float(latest["vol"]) / 1e8   # 手 → 亿
        yesterday_vol = float(prev["vol"]) / 1e8

        st.markdown("**K线数据**")
        prev_close = float(prev["close"])
        chg_pct = (price / prev_close - 1) * 100
        open_vs_prev = (o / prev_close - 1) * 100
        vol_vs_prev = (today_vol / yesterday_vol - 1) * 100

        chg_color = "#e53935" if chg_pct >= 0 else "#43a047"
        open_color = "#e53935" if o >= prev_close else "#43a047"
        vol_color = "#e53935" if vol_vs_prev >= 0 else "#43a047"
        sign_p = "+" if chg_pct >= 0 else ""
        sign_o = "+" if open_vs_prev >= 0 else ""
        sign_v = "+" if vol_vs_prev >= 0 else ""

        st.html(f"""
        <div style="font-size:18px;line-height:2;">
            <div>最新价：<span style="color:{chg_color};font-weight:bold;">{price:.2f}</span></div>
            <div>今日开盘：<span style="color:{open_color};">{o:.2f}（{sign_o}{open_vs_prev:.2f}%）</span></div>
            <div>涨跌幅：<span style="color:{chg_color};font-weight:bold;">{sign_p}{chg_pct:.2f}%</span></div>
            <div>昨日收盘：<span>{prev_close:.2f}</span></div>
            <div>今日成交量：<span style="color:{vol_color};">{today_vol:.2f}亿（{sign_v}{vol_vs_prev:.2f}%）</span></div>
            <div>昨日成交量：<span style="color:#333;">{yesterday_vol:.2f}亿</span></div>
        </div>
        """)

        st.markdown("**K线形态**")
        st.info("🚧 TODO — 形态识别逻辑待后续讨论确定")

    st.divider()

    # --- Row: MA table + Volume table ---
    ma_col, vol_col = st.columns([3, 2])

    with ma_col:
        st.markdown("**均线系统**")
        mas = calc_ma(df)
        ma_periods = [5, 10, 20, 60, 120, 240]
        ma_dirs = {}
        for p in ma_periods:
            ma_dirs[f"MA{p}"] = ma_direction(mas[f"MA{p}"])

        # Build colored HTML table
        def _dir_color(d: str) -> str:
            if d == "↑": return "#e53935"
            if d == "↓": return "#43a047"
            return "#999"
        def _role_color(r: str) -> str:
            if "支撑" in r: return "#e53935"
            if "压制" in r: return "#43a047"
            return "#999"

        rows_html = ""
        for p in ma_periods:
            ma_key = f"MA{p}"
            ma_val = latest_val(mas[ma_key])
            direction = ma_dirs.get(ma_key, "→")
            role = ma_role(price, ma_val, direction) if ma_val else "N/A"
            offset_date, offset_price = get_offset_info(df, p)
            val_str = f"{ma_val:.2f}" if ma_val else "N/A"
            off_str = f"{offset_price:.2f}" if offset_price else "N/A"
            rows_html += f"""<tr>
                <td style="font-weight:600;text-align:center;">{ma_key}</td>
                <td style="text-align:right;">{val_str}</td>
                <td style="color:{_dir_color(direction)};font-weight:bold;text-align:center;">{direction}</td>
                <td style="color:{_role_color(role)};font-weight:bold;text-align:center;">{role}</td>
                <td style="color:#888;text-align:center;">{offset_date}</td>
                <td style="color:#888;text-align:right;">{off_str}</td>
            </tr>"""

        st.html(f"""
        <table style="width:100%;font-size:15px;border-collapse:collapse;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
                <th style="text-align:center;">均线</th>
                <th style="text-align:right;">值</th>
                <th style="text-align:center;">方向</th>
                <th style="text-align:center;">作用</th>
                <th style="text-align:center;">扣抵日</th>
                <th style="text-align:right;">扣抵价</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        """)
        st.caption("扣抵: 今日收盘 > 扣抵价 → MA继续上行；今日收盘 < 扣抵价 → MA拐头下行")

        arrangement = ma_arrangement(df)
        st.markdown(f"**均线排列:** {arrangement}")

    with vol_col:
        st.markdown("**成交量分析**")
        vol = volume_analysis(df)
        vol_rows = [
            {"指标": "今日量", "值": f"{vol.get('latest_vol', 0):.0f}"},
            {"指标": "5日均量", "值": f"{vol.get('ma5_vol', 0):.0f}"},
            {"指标": "vs MA5", "值": f"{vol.get('vs_ma5_pct', 0):+.1f}%"},
            {"指标": "vs MA20", "值": f"{vol.get('vs_ma20_pct', 0):+.1f}%"},
            {"指标": "量能判定", "值": vol.get("label", "N/A")},
        ]
        st.dataframe(pd.DataFrame(vol_rows), hide_index=True, width="stretch")

    st.divider()

    # --- Row: Technical Indicators ---
    st.markdown("**技术指标**")
    kdj = calc_kdj(df)
    rsi6 = calc_rsi(df, 6)
    bias = calc_bias(df)

    ind_cols = st.columns(5)
    indicators = [
        ("KDJ-K", latest_val(kdj["K"]), None),
        ("KDJ-D", latest_val(kdj["D"]), None),
        ("KDJ-J", latest_val(kdj["J"]), "J<0超卖 J>100超买"),
        ("RSI(6)", latest_val(rsi6), "<30超卖 >70超买"),
        ("BIAS(6)", latest_val(bias["BIAS6"]), "负乖离=超跌"),
    ]
    for i, (label, val, hint) in enumerate(indicators):
        with ind_cols[i]:
            st.metric(label, f"{val:.2f}" if val else "N/A",
                     help=hint)


# ------- Page -------

# Resolve trade date: query param ?date=YYYYMMDD, or latest from cache
_query_date = st.query_params.get("date", None)
if _query_date:
    _raw_date = _query_date
else:
    _resolve_dp = DataProvider(tushare_token=os.environ.get("TUSHARE_TOKEN", ""))
    _raw_date = _resolve_dp.get_latest_trade_date("000001.SH")
    if not _raw_date:
        _raw_date = datetime.now().strftime("%Y%m%d")
# Normalize to consistent formats (handle both YYYYMMDD and YYYY-MM-DD inputs)
_raw_clean = _raw_date.replace("-", "")
_display_date = f"{_raw_clean[:4]}-{_raw_clean[4:6]}-{_raw_clean[6:8]}"
_trade_date_yyyymmdd = _raw_clean

st.title(f"📊 A股复盘 Dashboard — {_display_date}")
st.caption("Agent 1 — 大盘分析")

# ============ 市场概览 ============
st.header("📈 市场概览")


@st.cache_data(ttl=300)
def load_market_overview(trade_date: str):
    """Fetch complete market overview via DataProvider (no direct Tushare calls)."""
    try:
        token = os.environ.get("TUSHARE_TOKEN", "")
        if not token:
            return None
        dp = DataProvider(tushare_token=token)

        # --- Today ---
        today = dp.get_market_breadth(trade_date)
        if today is None:
            return {"error": f"无法获取 {trade_date} 市场数据"}

        # --- Yesterday (walk back calendar days to find previous trading day) ---
        from datetime import datetime, timedelta
        dt = datetime.strptime(trade_date, "%Y%m%d")
        yesterday = None
        for i in range(1, 10):
            prev_date = (dt - timedelta(days=i)).strftime("%Y%m%d")
            result = dp.get_market_breadth(prev_date)
            if result is not None:
                yesterday = result
                break

        # --- 10-day trend: use DataProvider to find trading days ---
        index_rows = dp.get_daily("000001.SH", lookback_days=360)
        all_trading_dates = sorted(set(
            r["date"].replace("-", "") for r in index_rows
        ), reverse=True)

        # Only include trading days up to the requested date, then take first 10
        trading_dates = [td for td in all_trading_dates if td <= trade_date]

        trend = []
        for td in trading_dates:
            if len(trend) >= 10:
                break
            day_data = dp.get_market_breadth(td)
            if day_data is not None:
                trend.append({
                    "date": td,
                    "total_yi": day_data["total_yi"],
                    "up": day_data["up"],
                    "down": day_data["down"],
                })
        trend.reverse()  # chronological order

        totals = [d["total_yi"] for d in trend]
        avg_5d = round(sum(totals[-5:]) / min(5, len(totals)), 0) if totals else 0
        avg_10d = round(sum(totals) / len(totals), 0) if totals else 0

        return {
            "today": today,
            "yesterday": yesterday,
            "trend": trend,
            "avg_5d": avg_5d,
            "avg_10d": avg_10d,
        }
    except Exception as e:
        return {"error": str(e)}


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
    card_left, card_right = st.columns(2)

    # ---- Card 1: 涨跌数量比 + 市场情绪 ----
    with card_left:
        _up = today["up"]
        _flat = today["flat"]
        _down = today["down"]
        _ul = today["up_limit"]
        _dl = today["down_limit"]
        _total = _up + _flat + _down
        _up_pct = _up / _total * 100 if _total else 0

        # Yesterday comparison HTML
        yest_html = ""
        if yesterday:
            _yup, _yflat, _ydown = yesterday["up"], yesterday["flat"], yesterday["down"]
            _yul, _ydl = yesterday["up_limit"], yesterday["down_limit"]
            hints = []
            up_chg = _up - _yup
            if abs(up_chg) > 50:
                hints.append(f'上涨家数{"↑" if up_chg > 0 else "↓"}{abs(up_chg)}')
            dl_chg = _dl - _ydl
            if dl_chg > 3:
                hints.append(f'跌停数↑{dl_chg}')
            hint_str = "  |  ".join(hints) if hints else ""
            hint_color = "#e53935" if up_chg >= 0 else "#43a047"

            yest_html = f"""
            <div style="margin-top:10px;padding-top:8px;border-top:1px dashed #e0e0e0;font-size:14px;color:#999;">
                昨日：<span style="color:#e53935;">{_yup}</span>:<span>{_yflat}</span>:<span style="color:#43a047;">{_ydown}</span>
                涨停 {_yul} | 跌停 {_ydl}
            </div>
            <div style="margin-top:2px;font-size:13px;color:{hint_color};">{hint_str}</div>
            """

        st.html(f"""
        <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:16px;">
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
            <div style="margin-top:4px;font-size:16px;color:#e53935;font-weight:bold;">
                市场情绪：涨 {_up_pct:.1f}% 家
            </div>
            <div style="margin-top:6px;font-size:16px;">
                <span style="color:#e53935;">涨停 {_ul}</span>
                <span style="color:#999;margin:0 8px;">|</span>
                <span style="color:#43a047;">跌停 {_dl}</span>
            </div>
            {yest_html}
        </div>
        """)

    # ---- Card 2: 成交额 ----
    with card_right:
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
            <div style="margin-top:2px;font-size:16px;color:{color};">
                {'放量' if change>=0 else '缩量'} {abs(change):,.0f}亿（{sign}{change_pct:.1f}%）
            </div>
            """

        exchange_parts = [f'上证 {sh_yi:,.0f}亿', f'深证 {sz_yi:,.0f}亿']
        if bj_yi > 0:
            exchange_parts.append(f'北证 {bj_yi:,.0f}亿')

        st.html(f"""
        <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:16px;">
            <div style="font-size:17px;color:#888;margin-bottom:8px;">两市成交额（亿元）</div>
            <div style="font-size:34px;font-weight:bold;">{total_yi:,.0f}<span style="font-size:17px;color:#888;">亿</span></div>
            <div style="margin-top:4px;">{delta_html}</div>
            <div style="margin-top:8px;font-size:16px;">
                {" &nbsp;|&nbsp; ".join(exchange_parts)}
            </div>
            {yest_turnover_html}
        </div>
        """)

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

st.divider()

# ============ 上证指数 ============
with st.expander("📈 上证指数 000001.SH", expanded=True):
    render_index_section("000001.SH", "上证指数", end_date=_trade_date_yyyymmdd)

st.divider()

# ============ 创业板指 ============
with st.expander("📉 创业板指 399006.SZ", expanded=False):
    render_index_section("399006.SZ", "创业板指", end_date=_trade_date_yyyymmdd)

# ============ Agent 1 分析报告 ============
st.divider()
st.header("🤖 Agent 1 最新分析报告")
report_path = os.path.join(os.path.dirname(__file__), "..", "report.md")
if os.path.exists(report_path):
    with open(report_path, "r", encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("尚未生成分析报告。运行 `python -m src.marketreview.main YYYYMMDD` 后此处会显示 Agent 1 的 LLM 输出。")
