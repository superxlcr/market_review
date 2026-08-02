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

st.title("📋 个股追踪")
st.caption("Agent 3 — 个股技术分析")

st.markdown(
    f"📅 当前日期：<span style='color:#e53935;font-weight:bold;'>"
    f"{_td[:4]}-{_td[4:6]}-{_td[6:8]}</span>",
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

# ── 3浪3 趋势方向（市场整体）──
_w33 = _service.get_wave33_data(chart_days=15, rolling_days=21, end_date=_td)
_trend_direction = _w33.get("trend", {}).get("direction", "flat")

# ── 逐只渲染 ──
from marketreview.tools.technical import calc_atr
from marketreview.tools.band_analysis import analyze_band
from marketreview.tools.buy_points import find_all_buy_points, load_buy_point_config, compute_ma_probes
from rendering.band_section import render_band_structure, plot_band_chart, render_buy_point_table, render_ma_probes
from marketreview.tools.macd_swing import (
    find_macd_swing, calc_macd,
    calc_observation_signal, calculate_trend, classify_shadow, calculate_advice2,
)

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
        # ── 战法信号检查（暂时关闭）──
        # result = _service.check_stock_signal(
        #     ts_code=code, name=name,
        #     trade_date=_td, strategy_class=_strategy_class,
        # )
        # msg = result["message"]
        #
        # _callout_css = {
        #     "success": "background:#d4edda;border-left:4px solid #28a745;color:#155724;",
        #     "warning": "background:#fff3cd;border-left:4px solid #ffc107;color:#856404;",
        #     "info":    "background:#d1ecf1;border-left:4px solid #17a2b8;color:#0c5460;",
        #     "error":   "background:#f8d7da;border-left:4px solid #dc3545;color:#721c24;",
        # }
        # if result.get("error"):
        #     style = _callout_css["error"]
        # elif result["has_signal"] and result["price_reachable"]:
        #     style = _callout_css["success"]
        # elif result["has_signal"] and not result["price_reachable"]:
        #     style = _callout_css["warning"]
        # else:
        #     style = _callout_css["info"]
        #
        # st.markdown(
        #     f'<div style="{style} padding:0.75rem 1rem; border-radius:0.25rem; '
        #     f'margin:0.5rem 0; line-height:1.7;">{msg}</div>',
        #     unsafe_allow_html=True,
        # )

        render_ohlcv_section(df, code, name, _service, section_type="stock")

    # ── 共享数据加载（波段分析 + NGA分析 共用）──
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
        st.warning(f"⚠️ {name} 暂无足量K线数据，跳过结构分析")
    else:
        # ── NGA分析 ──
        with st.expander(f"🧮 {name} — NGA分析", expanded=False):
            nga_rows = band_df.to_dict("records")
            last_bar_date = str(nga_rows[-1].get("date", ""))
            nga_incomplete = (last_bar_date == _td)

            swing = find_macd_swing(nga_rows, window_size=30,
                                    last_bar_incomplete=nga_incomplete)

            if swing.block_reason:
                st.warning(f"⚠️ {swing.block_reason}")
            else:
                nga_price = float(nga_rows[-1].get("close", 0) or 0)
                nga_new_high = nga_price > swing.high and swing.high > 0

                signal_text, signal_class = calc_observation_signal(
                    swing, nga_price, nga_new_high
                )

                # ── 搓揉线 ──
                closes_full = [float(r.get("close", 0) or 0) for r in nga_rows]
                trend = calculate_trend(closes_full, nga_price)
                advice2 = {"text": "数据不足", "className": "advice-normal"}
                if len(nga_rows) >= 2:
                    advice2 = calculate_advice2(nga_rows[-2], nga_rows[-1], trend)

                # ── 指标卡片 ──
                c1, c2, c3, c4, c5 = st.columns(5)
                high_date_short = swing.high_date[4:8] if len(swing.high_date) >= 8 else swing.high_date
                low_date_short = swing.low_date[4:8] if len(swing.low_date) >= 8 else swing.low_date
                with c1:
                    st.metric("阶段顶部", f"{swing.high:.2f}",
                              delta=f"@{high_date_short} · {swing.high_source}")
                with c2:
                    st.metric("阶段底部", f"{swing.low:.2f}",
                              delta=f"@{low_date_short} · {swing.low_source}")
                with c3:
                    st.metric("波段幅度", f"{swing.band_range:.2f}",
                              delta=f"{swing.band_range_pct:+.1f}%")
                with c4:
                    st.metric("当前价", f"{nga_price:.2f}",
                              delta=f"{'突破新高' if nga_new_high else ''}")
                with c5:
                    signal_color = {
                        "advice-danger": "#f5222d", "advice-warning": "#e6a23c",
                        "advice-blue": "#1890ff", "advice-cyan": "#13c2c2",
                        "advice-normal": "#bfbfbf", "advice-gold": "#faad14",
                    }.get(signal_class, "#bfbfbf")
                    st.html(f"""
                    <div style="border:1px solid #e0e0e0;border-radius:0.5rem;padding:0.5rem 0.5rem;">
                        <div style="font-size:0.75rem;color:#888;margin-bottom:0.25rem;">💡 操作建议</div>
                        <div style="font-size:1.2rem;font-weight:700;color:{signal_color};">{signal_text}</div>
                    </div>
                    """)

                # ── 斐波那契卡片 ──
                st.divider()
                if not swing.fibonacci_valid:
                    st.caption("⚠️ 斐波那契显示上一波段 — 当前为筑底反弹，非回调")

                fc1, fc2, fc3, fc4 = st.columns(4)
                with fc1:
                    dist_382 = (nga_price / swing.f382 - 1) * 100 if swing.f382 > 0 else 0
                    highlight_382 = abs(dist_382) <= 3.0
                    bg_382 = "background:#e6f7ff;border:2px solid #13c2c2;" if highlight_382 else ""
                    st.html(f"""
                    <div style="border-radius:0.5rem;padding:0.5rem;text-align:center;{bg_382}">
                        <div style="font-size:0.7rem;color:#888;">0.382 常规买点</div>
                        <div style="font-size:1.3rem;font-weight:700;color:#13c2c2;">{swing.f382}</div>
                        <div style="font-size:0.7rem;color:#888;">距现价 {dist_382:+.1f}%</div>
                    </div>
                    """)
                with fc2:
                    dist_618 = (nga_price / swing.f618 - 1) * 100 if swing.f618 > 0 else 0
                    highlight_618 = abs(dist_618) <= 3.0
                    bg_618 = "background:#fffbe6;border:2px solid #faad14;" if highlight_618 else ""
                    st.html(f"""
                    <div style="border-radius:0.5rem;padding:0.5rem;text-align:center;{bg_618}">
                        <div style="font-size:0.7rem;color:#888;">0.618 强防生死线 ⭐</div>
                        <div style="font-size:1.3rem;font-weight:700;color:#faad14;">{swing.f618}</div>
                        <div style="font-size:0.7rem;color:#888;">距现价 {dist_618:+.1f}%</div>
                    </div>
                    """)
                with fc3:
                    dist_786 = (nga_price / swing.f786 - 1) * 100 if swing.f786 > 0 else 0
                    st.html(f"""
                    <div style="border-radius:0.5rem;padding:0.5rem;text-align:center;">
                        <div style="font-size:0.7rem;color:#888;">0.786 深坑</div>
                        <div style="font-size:1.3rem;font-weight:700;color:#f5222d;">{swing.f786}</div>
                        <div style="font-size:0.7rem;color:#888;">距现价 {dist_786:+.1f}%</div>
                    </div>
                    """)
                with fc4:
                    dist_mid = (nga_price / swing.mid_point - 1) * 100 if swing.mid_point > 0 else 0
                    st.html(f"""
                    <div style="border-radius:0.5rem;padding:0.5rem;text-align:center;">
                        <div style="font-size:0.7rem;color:#888;">50% 中位线</div>
                        <div style="font-size:1.3rem;font-weight:700;color:#909399;">{swing.mid_point}</div>
                        <div style="font-size:0.7rem;color:#888;">距现价 {dist_mid:+.1f}%</div>
                    </div>
                    """)

                # ── 信号详情 + 搓揉线 ──
                st.divider()
                det1, det2 = st.columns(2)
                with det1:
                    st.caption(
                        f"MACD: 金叉×{swing.golden_cross_count} 死叉×{swing.death_cross_count} "
                        f"| 最后交叉: {'金叉' if swing.last_cross_type == 'golden' else '死叉' if swing.last_cross_type == 'death' else '无'}"
                    )
                with det2:
                    if len(nga_rows) >= 2:
                        y_shadow = classify_shadow(nga_rows[-2])
                        t_shadow = classify_shadow(nga_rows[-1])
                        paired = y_shadow != 'none' and t_shadow != 'none' and y_shadow != t_shadow
                        st.caption(
                            f"搓揉线: {'✅' if paired else '❌'} "
                            f"昨{y_shadow}→今{t_shadow}"
                            f" | 趋势: {trend} | 信号: **{advice2.get('text', '—')}**"
                        )
                    else:
                        st.caption("搓揉线: 数据不足")

                # ── 图表 ──
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots

                display_tail = 50
                plot_df = band_df.tail(display_tail).copy()
                date_short = plot_df["date"].astype(str).str[4:]

                macd_full = calc_macd(closes_full)
                macd_tail = macd_full[-display_tail:] if len(macd_full) >= display_tail else macd_full

                fig = make_subplots(
                    rows=3, cols=1, shared_xaxes=True,
                    vertical_spacing=0.03,
                    row_heights=[0.55, 0.225, 0.225],
                )

                # Row 1: K线 + 均线 + 斐波那契
                fig.add_trace(go.Candlestick(
                    x=date_short, open=plot_df["open"], high=plot_df["high"],
                    low=plot_df["low"], close=plot_df["close"], name="K线",
                    increasing_line_color="#e53935", decreasing_line_color="#43a047",
                    hovertemplate="%{x}<br>O:%{open:.2f} H:%{high:.2f} L:%{low:.2f} C:%{close:.2f}<extra></extra>",
                ), row=1, col=1)

                # 均线 (全量计算, 截尾画图)
                ma_configs = [
                    (5, "#2196f3", 1.0), (10, "#ff9800", 1.0),
                    (20, "#9c27b0", 1.2), (60, "#4caf50", 1.2),
                    (120, "#795548", 1.0), (240, "#e91e63", 1.0),
                ]
                full_closes = band_df["close"].tolist()
                for period, color, width in ma_configs:
                    if len(full_closes) >= period:
                        ma_full = [sum(full_closes[max(0, i - period + 1):i + 1]) / min(i + 1, period)
                                   for i in range(len(full_closes))]
                        ma_tail = ma_full[-display_tail:]
                        fig.add_trace(go.Scatter(
                            x=date_short, y=ma_tail, mode="lines",
                            line=dict(color=color, width=width), name=f"MA{period}",
                            hovertemplate=f"MA{period}: %{{y:.2f}}<extra></extra>",
                        ), row=1, col=1)

                # 斐波那契水平线
                fib_dash = "dash" if swing.fibonacci_valid else "dot"
                for price, label, color in [
                    (swing.f382, "0.382", "#13c2c2"),
                    (swing.f618, "0.618", "#faad14"),
                    (swing.f786, "0.786", "#f5222d"),
                    (swing.mid_point, "50%", "#909399"),
                ]:
                    if price > 0:
                        fig.add_hline(y=price, line=dict(color=color, width=1.0, dash=fib_dash),
                                      annotation_text=f"{label} {price:.2f}",
                                      annotation_position="top left",
                                      annotation_font=dict(color=color, size=9),
                                      row=1, col=1)

                # 顶/底线
                fig.add_hline(y=swing.high, line=dict(color="#cc96f8", width=1.2, dash="dot"),
                              annotation_text=f"顶 {swing.high:.2f}",
                              annotation_position="top left",
                              annotation_font=dict(color="#cc96f8", size=9), row=1, col=1)
                fig.add_hline(y=swing.low, line=dict(color="#ff5252", width=1.2, dash="dot"),
                              annotation_text=f"底 {swing.low:.2f}",
                              annotation_position="bottom left",
                              annotation_font=dict(color="#ff5252", size=9), row=1, col=1)

                # Row 2: MACD 柱
                macd_x = date_short.tolist()
                macd_vals = [m["macd"] for m in macd_tail]
                macd_colors = ["#e53935" if v >= 0 else "#43a047" for v in macd_vals]
                fig.add_trace(go.Bar(
                    x=macd_x, y=macd_vals, marker_color=macd_colors,
                    name="MACD", hovertemplate="MACD: %{y:.4f}<extra></extra>",
                ), row=2, col=1)

                # Row 3: DIFF + DEA
                diff_vals = [m["diff"] for m in macd_tail]
                dea_vals = [m["dea"] for m in macd_tail]
                fig.add_trace(go.Scatter(
                    x=macd_x, y=diff_vals, mode="lines",
                    line=dict(color="#2196f3", width=1.2), name="DIFF",
                ), row=3, col=1)
                fig.add_trace(go.Scatter(
                    x=macd_x, y=dea_vals, mode="lines",
                    line=dict(color="#ff9800", width=1.2), name="DEA",
                ), row=3, col=1)

                fig.add_hline(y=0, line=dict(color="#888", width=0.5), row=2, col=1)
                fig.add_hline(y=0, line=dict(color="#888", width=0.5), row=3, col=1)

                y_min = plot_df["low"].min()
                y_max = plot_df["high"].max()
                y_pad = (y_max - y_min) * 0.12
                fig.update_yaxes(range=[y_min - y_pad, y_max + y_pad], row=1, col=1)

                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    template="plotly_white", height=600,
                    margin=dict(l=10, r=10, t=5, b=20),
                    legend=dict(orientation="h", yanchor="top", y=1.08, xanchor="left", x=0, font=dict(size=10)),
                    hovermode="x unified",
                )
                fig.update_xaxes(showticklabels=False, row=1, col=1)
                fig.update_xaxes(showticklabels=False, row=2, col=1)
                fig.update_xaxes(title_text="日期", showticklabels=True, row=3, col=1)
                fig.update_yaxes(title_text="价格", row=1, col=1)
                fig.update_yaxes(title_text="MACD", row=2, col=1)
                fig.update_yaxes(title_text="DIFF/DEA", row=3, col=1)

                st.plotly_chart(fig, use_container_width=True)

        # ── 波段分析 ──
        with st.expander(f"📐 {name} — 波段结构", expanded=False):
            rows_asc = band_df.to_dict("records")
            band = analyze_band(rows_asc, peak_lookback=band_lookback)
            render_band_structure(band)
            st.divider()
            st.caption(f"📈 {name} — 波段趋势线")
            band_fig = plot_band_chart(band_df, band, display_tail=150,
                                        ma_periods=[20, 60, 120, 240])
            if band_fig:
                st.plotly_chart(band_fig, use_container_width=True)

            # ── 买点提示 ──
            bp_config = load_buy_point_config()
            position_capital = bp_config.get("单个仓位资金", 0.0)
            buy_points = find_all_buy_points(band_df, band,
                                              ts_code=code,
                                              atr=atr,
                                              trend_direction=_trend_direction,
                                              position_capital=position_capital)
            render_buy_point_table(buy_points)
            # ── MA 探底记录（暂隐藏，趋势行情下参考价值有限）──
            # ma_probes = compute_ma_probes(band_df, band)
            # render_ma_probes(ma_probes)

st.divider()
st.caption("编辑自选个股：修改 `config/watchlist_stocks.txt` 后刷新页面")
