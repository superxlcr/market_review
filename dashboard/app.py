"""
A股复盘 Dashboard — Agent 1 大盘分析视图。
启动: streamlit run dashboard/app.py
"""
import streamlit as st
import os
import sys
import pandas as pd
import numpy as np

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marketreview.data.cache_manager import CacheManager
from marketreview.tools.technical import (
    rows_to_df,
    calc_ma,
    ma_arrangement,
    volume_analysis,
    calc_kdj,
    calc_rsi,
    calc_bias,
    kline_pattern,
)

st.set_page_config(page_title="A股复盘", page_icon="📊", layout="wide")

# ------- Helpers -------


@st.cache_data(ttl=300)
def load_data(code: str, lookback: int = 360):
    """Load cached K-line data for a code."""
    cm = CacheManager()
    rows = cm.get_daily(code, limit=lookback)
    return rows_to_df(rows)


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
    """Determine MA role: 支撑 or 压制."""
    if price > ma_val:
        return "支撑" if direction == "↑" else "⚠压制"
    else:
        return "压制" if direction == "↓" else "⚠支撑"


def latest_val(series: list[float]) -> float | None:
    """Get latest non-NaN value from a list."""
    for v in reversed(series):
        if not np.isnan(v):
            return round(float(v), 2)
    return None


# ------- Chart -------


def plot_kline_with_ma(df: pd.DataFrame, title: str):
    """Plotly candlestick + MA overlay + volume."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    mas = calc_ma(df)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=[0.7, 0.3],
    )

    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="K线",
        increasing_line_color="#e53935", decreasing_line_color="#43a047",
    ), row=1, col=1)

    ma_colors = {"MA5": "#2196f3", "MA10": "#ff9800", "MA20": "#9c27b0",
                 "MA60": "#4caf50", "MA120": "#ff5722", "MA240": "#795548"}
    for name, color in ma_colors.items():
        if name in mas:
            fig.add_trace(go.Scatter(
                x=df["date"], y=mas[name], mode="lines",
                line=dict(color=color, width=1.2), name=name,
            ), row=1, col=1)

    vol_colors = ["#e53935" if c >= o else "#43a047" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["vol"], name="成交量",
        marker_color=vol_colors, opacity=0.5,
    ), row=2, col=1)

    fig.update_layout(
        title=title, xaxis_rangeslider_visible=False,
        template="plotly_white", height=480, margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="top", y=1.12, xanchor="left", x=0),
    )
    fig.update_xaxes(title_text="", row=2, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    return fig


# ------- Index Section Builder -------


def render_index_section(code: str, name: str):
    """Render a full analysis section for one index."""
    df = load_data(code)

    if df.empty:
        st.warning(f"暂无 {name} 数据，请先运行 Agent 1 拉取数据")
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    price = float(latest["close"])
    change_pct = (price / float(prev["close"]) - 1) * 100

    # --- Header ---
    st.subheader(f"📈 {name}  {code}")
    st.metric(
        label="最新价", value=f"{price:.2f}",
        delta=f"{change_pct:+.2f}%",
    )

    # --- Row: K-line chart + OHLC table ---
    chart_col, ohlc_col = st.columns([3, 2])

    with chart_col:
        fig = plot_kline_with_ma(df, f"{name} K线 + 均线")
        st.plotly_chart(fig, width="stretch")

    with ohlc_col:
        o, h, l, c = float(latest["open"]), float(latest["high"]), float(latest["low"]), price
        body = abs(c - o)
        total = h - l
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        st.markdown("**K线数据**")
        ohlc_df = pd.DataFrame({
            "项目": ["开盘", "最高", "最低", "收盘", "实体", "上影", "下影"],
            "数值": [f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{c:.2f}",
                    f"{body:.2f}", f"{upper_wick:.2f}", f"{lower_wick:.2f}"],
        })
        st.dataframe(ohlc_df, hide_index=True, width="stretch")

        candle = kline_pattern(df)
        st.markdown(f"**K线形态:** {candle.get('type', 'N/A')}")
        st.caption(candle.get("interpretation", ""))

    st.divider()

    # --- Row: MA table + Volume table ---
    ma_col, vol_col = st.columns([3, 2])

    with ma_col:
        st.markdown("**均线系统**")
        mas = calc_ma(df)
        ma_periods = [5, 10, 20, 60, 120, 240]
        ma_dirs = {}
        for p in ma_periods:
            ma_dirs[f"MA{p}"] = _ma_direction(mas[f"MA{p}"])

        ma_rows = []
        for p in ma_periods:
            ma_key = f"MA{p}"
            ma_val = latest_val(mas[ma_key])
            direction = ma_dirs.get(ma_key, "→")
            role = ma_role(price, ma_val, direction) if ma_val else "N/A"
            offset_date, offset_price = get_offset_info(df, p)
            ma_rows.append({
                "均线": ma_key,
                "值": f"{ma_val:.2f}" if ma_val else "N/A",
                "方向": direction,
                "作用": role,
                "扣抵日": offset_date,
                "扣抵价": f"{offset_price:.2f}" if offset_price else "N/A",
            })

        st.dataframe(pd.DataFrame(ma_rows), hide_index=True, width="stretch")
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


def _ma_direction(ma_values: list[float]) -> str:
    """Determine MA direction (lightweight, no polyfit needed)."""
    valid = [v for v in ma_values[-5:] if not np.isnan(v)]
    if len(valid) < 2:
        return "→"
    if valid[-1] > valid[0]:
        return "↑"
    elif valid[-1] < valid[0]:
        return "↓"
    return "→"


# ------- Page -------

st.title("📊 A股复盘 Dashboard")
st.caption("Agent 1 — 大盘分析")

# ============ 市场概览 ============
st.header("📈 市场概览")

# Try to read breadth from cache/tool output
cm = CacheManager()
# Check if we have the data in report.md for basic numbers
breadth_col1, breadth_col2, breadth_col3 = st.columns(3)

with breadth_col1:
    st.markdown("**涨跌比**")
    st.info("等待 market_breadth 工具就绪\n\n运行 Agent 1 后此处显示：\n- 上涨/下跌家数\n- 涨停/跌停数")

with breadth_col2:
    st.markdown("**成交额**")
    # Compute from cached data
    try:
        df_sh = load_data("000001.SH")
        df_cy = load_data("399006.SZ")
        if not df_sh.empty and not df_cy.empty:
            sh_amt = float(df_sh["amount"].iloc[-1]) / 1e8
            cy_amt = float(df_cy["amount"].iloc[-1]) / 1e8
            sh_amt_prev = float(df_sh["amount"].iloc[-2]) / 1e8
            cy_amt_prev = float(df_cy["amount"].iloc[-2]) / 1e8
            total = sh_amt + cy_amt
            total_prev = sh_amt_prev + cy_amt_prev
            delta = (total / total_prev - 1) * 100 if total_prev else 0
            st.metric("两市成交额（估算）", f"{total:.0f} 亿", delta=f"{delta:+.1f}%")
            st.caption(f"上证 {sh_amt:.0f}亿 | 创业板 {cy_amt:.0f}亿")
    except Exception:
        st.info("暂无成交额数据")

with breadth_col3:
    st.markdown("**量能趋势**")
    if not df_sh.empty:
        recent_vols = [float(df_sh["amount"].iloc[-(i+1)]) / 1e8 for i in range(5)]
        vol_trend = "↑ 放量" if recent_vols[0] > recent_vols[1] else ("↓ 缩量" if recent_vols[0] < recent_vols[1] else "→ 持平")
        st.metric("近5日量能趋势", vol_trend)
        st.caption(f"今日: {recent_vols[0]:.0f}亿 | 昨日: {recent_vols[1]:.0f}亿")

st.divider()

# ============ 上证指数 ============
st.header("上证指数")
render_index_section("000001.SH", "上证指数")

st.divider()

# ============ 创业板指 ============
st.header("创业板指")
render_index_section("399006.SZ", "创业板指")

# ============ Agent 1 分析报告 ============
st.divider()
st.header("🤖 Agent 1 最新分析报告")
report_path = os.path.join(os.path.dirname(__file__), "..", "report.md")
if os.path.exists(report_path):
    with open(report_path, "r", encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("尚未生成分析报告。运行 `python -m src.marketreview.main YYYYMMDD` 后此处会显示 Agent 1 的 LLM 输出。")
