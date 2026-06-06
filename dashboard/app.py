"""
A股复盘 Dashboard — Agent 1 大盘分析视图。
启动: streamlit run dashboard/app.py
"""
import streamlit as st
import sqlite3
import json
import os
import sys

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

def load_latest_data(code: str):
    """Load most recent cached data for a code."""
    cm = CacheManager()
    rows = cm.get_daily(code, limit=120)
    return rows_to_df(rows)


def plot_kline_with_ma(df, title: str):
    """Plotly candlestick + MA overlay chart."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    mas = calc_ma(df)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=[0.7, 0.3],
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="K线",
        increasing_line_color="#e53935", decreasing_line_color="#43a047",
    ), row=1, col=1)

    # MA lines
    colors = {"MA5": "#2196f3", "MA10": "#ff9800", "MA20": "#9c27b0", "MA60": "#4caf50", "MA120": "#ff5722", "MA240": "#795548"}
    for name, color in colors.items():
        if name in mas:
            fig.add_trace(go.Scatter(
                x=df["date"], y=mas[name], mode="lines",
                line=dict(color=color, width=1.2), name=name,
            ), row=1, col=1)

    # Volume bars
    colors_vol = ["#e53935" if c >= o else "#43a047" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["vol"], name="成交量",
        marker_color=colors_vol, opacity=0.5,
    ), row=2, col=1)

    fig.update_layout(
        title=title, xaxis_rangeslider_visible=False,
        template="plotly_white", height=450, margin=dict(l=20, r=20, t=40, b=20),
    )
    fig.update_xaxes(title_text="", row=2, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)

    return fig


# ------- Page -------

st.title("📊 A股复盘 Dashboard")
st.caption(f"Agent 1 — 大盘分析")

col1, col2 = st.columns(2)

# --- 上证指数 ---
with col1:
    st.subheader("📈 上证指数 000001.SH")
    try:
        df_sh = load_latest_data("000001.SH")
        if not df_sh.empty:
            latest = df_sh.iloc[-1]
            prev = df_sh.iloc[-2]
            change_pct = (latest["close"] / prev["close"] - 1) * 100
            st.metric(
                label="最新价", value=f"{latest['close']:.2f}",
                delta=f"{change_pct:+.2f}%",
            )

            # K-line chart
            fig = plot_kline_with_ma(df_sh, "上证指数 K线 + 均线")
            st.plotly_chart(fig, use_container_width=True)

            # Technical summary
            ma_arr = ma_arrangement(df_sh)
            vol = volume_analysis(df_sh)
            kdj = calc_kdj(df_sh)
            rsi = calc_rsi(df_sh, 6)
            bias = calc_bias(df_sh)
            candle = kline_pattern(df_sh)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("均线排列", ma_arr)
                st.metric("量能", vol.get("label", "N/A"),
                          delta=f"vs MA5: {vol.get('vs_ma5_pct', 0):+.1f}%")
            with c2:
                import pandas as pd
                import numpy as np
                k_val = [v for v in kdj["K"] if not pd.isna(v)][-1]
                d_val = [v for v in kdj["D"] if not pd.isna(v)][-1]
                rsi_val = [v for v in rsi if not pd.isna(v)][-1]
                st.metric("KDJ-K", f"{k_val:.1f}")
                st.metric("KDJ-D", f"{d_val:.1f}")
                st.metric("RSI(6)", f"{rsi_val:.1f}")
            with c3:
                bias6 = [v for v in bias["BIAS6"] if not pd.isna(v)][-1]
                st.metric("BIAS(6)", f"{bias6:.2f}%")
                st.metric("K线形态", candle.get("type", "N/A"),
                          help=candle.get("interpretation", ""))
        else:
            st.warning("暂无上证指数数据，请先运行 Agent 1 拉取数据")
    except Exception as e:
        st.error(f"上证指数加载失败: {e}")

# --- 创业板指 ---
with col2:
    st.subheader("📈 创业板指 399006.SZ")
    try:
        df_cy = load_latest_data("399006.SZ")
        if not df_cy.empty:
            latest = df_cy.iloc[-1]
            prev = df_cy.iloc[-2]
            change_pct = (latest["close"] / prev["close"] - 1) * 100
            st.metric(
                label="最新价", value=f"{latest['close']:.2f}",
                delta=f"{change_pct:+.2f}%",
            )

            fig = plot_kline_with_ma(df_cy, "创业板指 K线 + 均线")
            st.plotly_chart(fig, use_container_width=True)

            ma_arr = ma_arrangement(df_cy)
            vol = volume_analysis(df_cy)
            kdj = calc_kdj(df_cy)
            rsi = calc_rsi(df_cy, 6)
            bias = calc_bias(df_cy)
            candle = kline_pattern(df_cy)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("均线排列", ma_arr)
                st.metric("量能", vol.get("label", "N/A"),
                          delta=f"vs MA5: {vol.get('vs_ma5_pct', 0):+.1f}%")
            with c2:
                import pandas as pd
                import numpy as np
                k_val = [v for v in kdj["K"] if not pd.isna(v)][-1]
                d_val = [v for v in kdj["D"] if not pd.isna(v)][-1]
                rsi_val = [v for v in rsi if not pd.isna(v)][-1]
                st.metric("KDJ-K", f"{k_val:.1f}")
                st.metric("KDJ-D", f"{d_val:.1f}")
                st.metric("RSI(6)", f"{rsi_val:.1f}")
            with c3:
                bias6 = [v for v in bias["BIAS6"] if not pd.isna(v)][-1]
                st.metric("BIAS(6)", f"{bias6:.2f}%")
                st.metric("K线形态", candle.get("type", "N/A"),
                          help=candle.get("interpretation", ""))
        else:
            st.warning("暂无创业板指数据，请先运行 Agent 1 拉取数据")
    except Exception as e:
        st.error(f"创业板指加载失败: {e}")

# --- Agent 1 LLM 输出（如果存在） ---
st.divider()
st.subheader("🤖 Agent 1 最新分析报告")
report_path = os.path.join(os.path.dirname(__file__), "..", "report.md")
if os.path.exists(report_path):
    with open(report_path, "r", encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("尚未生成分析报告。运行 `python -m src.marketreview.main YYYYMMDD` 后此处会显示 Agent 1 的 LLM 输出。")
