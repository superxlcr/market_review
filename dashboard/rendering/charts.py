"""
Plotly chart builders for the dashboard.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from marketreview.tools.technical import calc_ma


def plot_kline_with_ma(df: pd.DataFrame, display_days: int = 60):
    """Plotly candlestick + MA overlay + amount bar. MAs computed on full data, chart shows last N days."""
    mas = calc_ma(df)
    plot_df = df.tail(display_days)

    # Convert amount from 千元 to 亿
    amount_yi = plot_df["amount"].to_numpy() / 1e5

    # Bar colors: red=close>=open (bullish), green=close<open (bearish)
    bar_colors = [
        "#e53935" if plot_df.iloc[i]["close"] >= plot_df.iloc[i]["open"] else "#43a047"
        for i in range(len(plot_df))
    ]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.65, 0.35],
        subplot_titles=("", ""),
    )

    # --- Row 1: Candlestick + MA ---
    fig.add_trace(go.Candlestick(
        x=plot_df["date"], open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"], name="K线",
        increasing_line_color="#e53935", decreasing_line_color="#43a047",
    ), row=1, col=1)

    ma_colors = {"MA5": "#2196f3", "MA10": "#ff9800", "MA20": "#9c27b0",
                 "MA60": "#4caf50", "MA120": "#ff5722", "MA240": "#795548"}
    for name, color in ma_colors.items():
        if name in mas:
            ma_slice = mas[name][-display_days:]
            fig.add_trace(go.Scatter(
                x=plot_df["date"], y=ma_slice, mode="lines",
                line=dict(color=color, width=1.2), name=name,
            ), row=1, col=1)

    # --- Row 2: Amount bars ---
    fig.add_trace(go.Bar(
        x=plot_df["date"], y=amount_yi,
        marker_color=bar_colors,
        name="成交额",
        hovertemplate="%{x}<br>成交额: %{y:.0f}亿<extra></extra>",
    ), row=2, col=1)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_white", height=520, margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="top", y=1.08, xanchor="left", x=0),
    )
    fig.update_xaxes(title_text="", showticklabels=False, row=1, col=1)
    fig.update_xaxes(title_text="", showticklabels=False, row=2, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交额（亿）", row=2, col=1)
    return fig


def plot_turnover_trend(trend: list[dict]):
    """10-day turnover bar chart with up/down color coding."""
    if not trend:
        return None

    dates = [d["date"] for d in trend]
    amounts = [d["total_yi"] for d in trend]
    colors = []
    for i, amt in enumerate(amounts):
        if i == 0:
            colors.append("#e53935" if amounts[i] >= amounts[i+1] else "#43a047")
        elif i == len(amounts) - 1:
            colors.append("#e53935" if amounts[i] >= amounts[i-1] else "#43a047")
        else:
            colors.append("#e53935" if amounts[i] >= amounts[i-1] else "#43a047")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=dates, y=amounts, marker_color=colors,
        text=[f"{a:,.0f}亿" for a in amounts],
        textposition="outside", textfont_size=11,
    ))
    fig.update_layout(
        template="plotly_white", height=280, margin=dict(l=20, r=20, t=10, b=20),
        showlegend=False,
    )
    fig.update_xaxes(title_text="")
    fig.update_yaxes(title_text="成交额（亿）")
    return fig
