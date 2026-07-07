"""波段结构渲染 — 复用于 04_波段分析 和 03_个股追踪."""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import BuyPoint
from rendering.charts import plot_kline_with_ma


def plot_band_chart(df: pd.DataFrame, band: BandResult,
                    display_tail: int = 200,
                    ma_periods: list[int] | None = None) -> go.Figure:
    """K线图叠加波段趋势线 + 回调一半点位."""
    if ma_periods is None:
        ma_periods = []
    fig = plot_kline_with_ma(df, display_days=display_tail, ma_periods=ma_periods)

    if band.p_price <= 0:
        return fig

    # Add band horizontal lines to Row 1
    fig.add_hline(y=band.p_price, line=dict(color="#e53935", width=1.5, dash="dot"),
                  annotation_text=f"P {band.p_price:.2f}", annotation_position="top left",
                  annotation_font=dict(color="#e53935", size=13), row=1, col=1)
    fig.add_hline(y=band.line_75, line=dict(color="rgba(156,39,176,0.5)", width=1, dash="dash"),
                  annotation_text=f"75% {band.line_75:.2f}", annotation_position="top left",
                  annotation_font=dict(color="#9c27b0", size=12), row=1, col=1)
    fig.add_hline(y=band.line_625, line=dict(color="rgba(255,152,0,0.5)", width=1.2, dash="dash"),
                  annotation_text=f"62.5% {band.line_625:.2f}", annotation_position="top left",
                  annotation_font=dict(color="#ff9800", size=12), row=1, col=1)
    fig.add_hline(y=band.line_50, line=dict(color="rgba(25,118,210,0.5)", width=2, dash="dash"),
                  annotation_text=f"50% {band.line_50:.2f}",
                  annotation_position="bottom left",
                  annotation_font=dict(color="#1976d2", size=13), row=1, col=1)

    # 回调半分位 — 跌破62.5%后每个交易日一个点
    if band.half_retrace_series and band.trigger_625_date:
        plot_df = df.tail(display_tail)
        hr_map = {p["date"]: p["price"] for p in band.half_retrace_series
                  if p["date"] >= band.trigger_625_date}
        x_full = [str(d) for d in plot_df["date"]]
        y_full = [hr_map.get(d, None) for d in x_full]
        if any(v is not None for v in y_full):
            fig.add_trace(go.Scatter(
                x=x_full, y=y_full, mode="markers",
                marker=dict(color="#00acc1", size=4, symbol="circle"),
                name="回调一半点位",
                connectgaps=False,
                hoverinfo="skip",
            ), row=1, col=1)

    fig.add_hline(y=band.v_price, line=dict(color="#43a047", width=1.5, dash="dot"),
                  annotation_text=f"V {band.v_price:.2f}", annotation_position="bottom left",
                  annotation_font=dict(color="#43a047", size=13), row=1, col=1)

    # Lock y-axis to visible K-line range
    plot_df = df.tail(display_tail)
    y_min = plot_df["low"].min()
    y_max = plot_df["high"].max()
    y_pad = (y_max - y_min) * 0.1
    fig.update_yaxes(range=[y_min - y_pad, y_max + y_pad], row=1, col=1)

    # ── 扣抵日标记（三角形，放在 K 线下方）──
    _OFFSET_COLORS = {20: "#2196f3", 60: "#ff9800", 120: "#9c27b0", 240: "#4caf50"}
    n_total = len(df)
    for period, color in _OFFSET_COLORS.items():
        idx = n_total - 1 - period
        if idx >= 0 and idx >= n_total - display_tail:
            offset_date = str(df["date"].iloc[idx])
            offset_low = float(df["low"].iloc[idx])
            offset_y = offset_low - (y_max - y_min) * 0.03
            fig.add_trace(go.Scatter(
                x=[offset_date], y=[offset_y],
                mode="markers",
                marker=dict(
                    color=color, size=14, symbol="triangle-up",
                    line=dict(color="white", width=1),
                ),
                name=f"扣抵MA{period}",
                hovertemplate=f"扣抵日 MA{period}<br>%{{x}}<extra></extra>",
            ), row=1, col=1)

    return fig


def render_band_structure(band: BandResult) -> None:
    """渲染波段结构指标卡片（P/V/趋势线/回调一半 + 时效提示）."""

    if band.block_reason:
        st.warning(f"⚠️ {band.block_reason}")
        return

    # ── 缩小 metric 数值 ──
    st.markdown(
        """<style>[data-testid="stMetricValue"]{font-size:1.5rem!important}</style>""",
        unsafe_allow_html=True,
    )

    # ── Big metric card（当前价 / 回调一半用大字号）──
    def _big_metric(label: str, value: str, delta: str = "") -> str:
        delta_html = (
            f'<div style="font-size:0.85rem;color:#555;margin-top:0.35rem;">{delta}</div>'
            if delta else ""
        )
        return f"""
        <div style="border:1px solid #e0e0e0;border-radius:0.5rem;padding:0.75rem 0.5rem;">
            <div style="font-size:0.75rem;color:#888;margin-bottom:0.25rem;">{label}</div>
            <div style="font-size:2.2rem;font-weight:700;line-height:1.2;">{value}</div>
            {delta_html}
        </div>
        """

    st.divider()
    st.subheader("📊 波段结构")

    # ── Row 1: P / V / 50%×1.1 vs 62.5% / 当前价 ──
    mc1, mc2, mc3, mc4 = st.columns(4)
    with mc1:
        st.metric("P（波峰）", f"{band.p_price:.2f}", delta=f"📅 {band.p_date}")
    with mc2:
        st.metric("V（前波谷）", f"{band.v_price:.2f}", delta=f"📅 {band.v_date}")
    with mc3:
        val_50x11 = band.line_50 * 1.1
        cmp_str = f"{val_50x11:.2f} vs {band.line_625:.2f}"
        cmp_delta = "✅ 趋势波段幅度成立" if band.v_qualified else "⚠️ 趋势波段幅度过小"
        st.metric("50%×1.1 vs 62.5%", cmp_str, delta=cmp_delta)
    with mc4:
        st.html(_big_metric("当前价", f"{band.current_price:.2f}", f"📅 {band.current_date}"))

    pullback_days = band.rows_count - 1 - band.p_idx  # 从P至今的交易日数

    # ── Row 2: 75% / 62.5% / 50% / 回调一半 ──
    tc1, tc2, tc3, tc4 = st.columns(4)
    with tc1:
        if pullback_days > 13:
            st.metric("75% 回调线", f"{band.line_75:.2f}",
                      delta=f"⚠️ 回调{pullback_days}天，已超13天（支撑时效已过）")
        else:
            st.metric("75% 回调线", f"{band.line_75:.2f}",
                      delta=f"回调{pullback_days}天（13天内有效支撑）")
    with tc2:
        if pullback_days > 21:
            st.metric("62.5% 回调线", f"{band.line_625:.2f}",
                      delta=f"⚠️ 回调{pullback_days}天，已超21天（支撑时效已过）")
        else:
            st.metric("62.5% 回调线", f"{band.line_625:.2f}",
                      delta=f"回调{pullback_days}天（21天内有效支撑）")
    with tc3:
        st.metric("50% 趋势线", f"{band.line_50:.2f}",
                  delta="← 生命线，跌破则趋势可疑")
    with tc4:
        if band.trigger_625_date:  # 只有跌破62.5%后才激活回调一半
            hr_latest = band.half_retrace_series[-1]["price"] if band.half_retrace_series else 0
            if pullback_days >= 13:
                delta_str = (f"📅 跌破62.5%@{band.trigger_625_date} ｜ "
                             f"📌 回调{pullback_days}天 ≥ 13天，关注突破")
            else:
                delta_str = (f"📅 跌破62.5%@{band.trigger_625_date} ｜ "
                             f"回调{pullback_days}天 < 13天")
            st.html(_big_metric("回调一半", f"{hr_latest:.2f}", delta_str))
        else:
            st.html(_big_metric("回调一半", "—", "尚未跌破62.5%"))

    # ── 底部汇总 ──
    st.caption(f"💡 L（峰后最低）= {band.l_price:.2f} @ {band.l_date} | "
               f"K线总数: {band.rows_count} | 波峰距今: {pullback_days} 日 | "
               f"局部谷底: {len(band.valleys)} 个")


def render_buy_point_table(buy_points: list[BuyPoint]) -> None:
    """渲染买点提示表格 — 类型/位置/价格/距离/盘中止损/收盘止损/仓位/原因."""
    if not buy_points:
        st.caption("暂无符合条件的买点")
        return

    st.markdown(
        "**🎯 买点提示** "
        "<span style='font-size:13px;color:#888;'>已过滤涨幅超2倍涨跌幅的买点</span>",
        unsafe_allow_html=True,
    )

    rows_html = ""
    for bp in buy_points:
        dist_sign = "+" if bp.distance_pct >= 0 else ""
        dist_color = "#e53935" if bp.distance_pct >= 0 else "#43a047"

        # 类型标签颜色
        if bp.type == "突破":
            type_color = "#e53935"
        elif bp.type == "重新突破":
            type_color = "#ef6c00"
        else:
            type_color = "#1976d2"

        # 盘中止损单元格
        intra_cell = "—"
        if bp.intraday_stop > 0:
            intra_cell = (
                f'{bp.intraday_stop:.2f}'
                f'<span style="font-size:14px;color:#888;">'
                f' (-{bp.intraday_stop_pct:.1f}% | {bp.intraday_stop_reason})'
                f'</span>'
            )

        rows_html += f"""<tr>
            <td style="color:{type_color};font-weight:bold;text-align:center;">{bp.type}</td>
            <td style="font-weight:600;text-align:center;">{bp.position}</td>
            <td style="text-align:right;font-weight:bold;">{bp.price:.2f}</td>
            <td style="color:{dist_color};font-weight:bold;text-align:right;">{dist_sign}{bp.distance_pct}%</td>
            <td style="text-align:right;font-size:17px;">{intra_cell}</td>
            <td style="text-align:center;color:#888;font-size:19px;padding:0 10px;">{bp.position_size}</td>
            <td style="color:#555;font-size:16px;">{bp.reason}</td>
        </tr>"""

    st.html(f"""
    <table style="width:100%;font-size:16px;border-collapse:collapse;">
        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
            <th style="text-align:center;width:8%;">类型</th>
            <th style="text-align:center;width:10%;">位置</th>
            <th style="text-align:right;width:9%;">价格</th>
            <th style="text-align:right;width:7%;">距离</th>
            <th style="text-align:right;width:22%;">盘中止损</th>
            <th style="text-align:center;width:6%;">仓位</th>
            <th style="text-align:left;">原因</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
    """)


def render_ma_probes(probes: dict[int, list[dict]]) -> None:
    """渲染 MA 探底记录 — 开盘在MA上方、盘中跌破MA的日期."""
    if not probes or all(len(v) == 0 for v in probes.values()):
        return

    st.caption("")  # spacer
    st.markdown("**📊 MA 探底记录（P → 至今）**")
    st.caption("前日收盘站上 MA，当日最低跌破 MA，看收盘能否站稳")

    for period in [60, 120, 240]:
        probe_list = probes.get(period, [])
        if not probe_list:
            continue
        rows = ""
        for pr in probe_list:
            ma_dir = pr.get("ma_dir", "")
            dir_color = "#e53935" if ma_dir == "↑" else ("#43a047" if ma_dir == "↓" else "#888")
            # 量能对比
            off_pct = pr.get("offset_vs_pct")
            avg_pct = pr.get("avg_vs_pct")
            if off_pct is not None and avg_pct is not None:
                off_sign = "+" if off_pct >= 0 else ""
                avg_sign = "+" if avg_pct >= 0 else ""
                off_color = "#e53935" if off_pct >= 0 else "#43a047"
                avg_color = "#e53935" if avg_pct >= 0 else "#43a047"
                vol_cell = (
                    f'<span style="color:{off_color};">扣抵 {off_sign}{off_pct}%</span>'
                    f' &nbsp;'
                    f'<span style="color:{avg_color};">均量 {avg_sign}{avg_pct}%</span>'
                )
            else:
                vol_cell = '<span style="color:#888;">—</span>'
            # 收盘站回
            recovered_icon = "✅" if pr.get("recovered") else "❌"

            rows += (
                f'<tr>'
                f'<td style="text-align:center;">{pr["date"]}</td>'
                f'<td style="text-align:right;">{pr.get("ma_price", "—")}</td>'
                f'<td style="text-align:center;color:{dir_color};font-weight:bold;">{ma_dir}</td>'
                f'<td style="text-align:center;font-size:17px;">{vol_cell}</td>'
                f'<td style="text-align:center;font-size:19px;">{recovered_icon}</td>'
                f'<td style="text-align:right;font-weight:bold;">{pr["max_penetration"]}%</td>'
                f'</tr>'
            )
        st.html(f"""
        <div style="margin-bottom:8px;">
        <span style="font-weight:600;font-size:19px;">MA{period}</span>
        <span style="color:#888;font-size:17px;"> — {len(probe_list)} 次探底</span>
        <table style="width:100%;font-size:19px;border-collapse:collapse;margin-top:4px;">
            <thead><tr style="border-bottom:1px solid #e0e0e0;color:#888;font-size:17px;">
                <th style="text-align:center;width:16%;">日期</th>
                <th style="text-align:right;width:12%;">MA价格</th>
                <th style="text-align:center;width:8%;">方向</th>
                <th style="text-align:center;width:34%;">5日均量对比</th>
                <th style="text-align:center;width:12%;">收盘站回</th>
                <th style="text-align:right;width:18%;">最大穿透</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
        </div>
        """)
