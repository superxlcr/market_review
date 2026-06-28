"""
Shared OHLCV section renderer — used by 01_市场全景 (indices) and
02_板块分析 (industries).

Usage:
    from rendering.index_section import render_ohlcv_section

    # For indices:
    df = service.get_index_data("000001.SH", end_date=date)
    render_ohlcv_section(df, "000001.SH", "上证指数", service, "index")

    # For industries:
    df = service.get_industry_daily("801081.SI", end_date=date, lookback=240)
    render_ohlcv_section(df, "801081.SI", "半导体", service, "industry")
"""

import streamlit as st
import pandas as pd
import numpy as np

from marketreview.tools.technical import (
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
from rendering.styles import vol_color_ramp
from rendering.charts import plot_kline_with_ma
from marketreview.log_util import get_logger

_log = get_logger("rendering.index_section")


def latest_val(series: list[float]) -> float | None:
    """Get latest non-NaN value from a list."""
    for v in reversed(series):
        if not np.isnan(v):
            return round(float(v), 2)
    return None


def render_ohlcv_section(
    df: pd.DataFrame,
    code: str,
    name: str,
    service,                       # DashboardService
    section_type: str,             # "index" | "industry"
    industry_level: str = None,    # L1/L2/L3 — required when section_type="industry"
):
    """Render a full OHLCV analysis section for one index or industry.

    Args:
        df: OHLCV DataFrame, date ASC, with close/open/high/low/vol/amount.
        code: Index or industry code (e.g. "000001.SH", "801081.SI").
        name: Display name.
        service: DashboardService instance.
        section_type: "index" → show 权重贡献; "industry" → show 成分股分析.
        industry_level: "L1"/"L2"/"L3" for industry constituent lookup.
    """
    if section_type not in ("index", "industry", "stock"):
        raise ValueError(f"section_type must be 'index', 'industry', or 'stock', got {section_type!r}")

    if df.empty:
        st.warning(f"暂无 {name} 数据，请先加载数据")
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    price = float(latest["close"])

    # ── Row: K-line chart + OHLC table ──
    chart_col, ohlc_col = st.columns([3, 2])

    with chart_col:
        chart_ma_periods = [5, 10, 20, 55, 144, 240] if section_type == "stock" else [5, 10, 20, 60, 120, 240]
        fig = plot_kline_with_ma(df, ma_periods=chart_ma_periods)
        st.plotly_chart(fig, width="stretch")

    with ohlc_col:
        o = float(latest["open"])
        today_amount = float(latest["amount"]) / 1e5   # 千元 → 亿
        yesterday_amount = float(prev["amount"]) / 1e5

        st.markdown("**K线数据**")
        prev_close = float(prev["close"])
        chg_pct = (price / prev_close - 1) * 100
        open_vs_prev = (o / prev_close - 1) * 100
        amount_vs_prev = (today_amount / yesterday_amount - 1) * 100

        chg_color = "#e53935" if chg_pct >= 0 else "#43a047"
        open_color = "#e53935" if o >= prev_close else "#43a047"
        amount_color = "#e53935" if amount_vs_prev >= 0 else "#43a047"
        sign_p = "+" if chg_pct >= 0 else ""
        sign_o = "+" if open_vs_prev >= 0 else ""
        sign_a = "+" if amount_vs_prev >= 0 else ""

        st.html(f"""
        <div style="font-size:18px;line-height:2;">
            <div>最新价：<span style="color:{chg_color};font-weight:bold;">{price:.2f}</span></div>
            <div>今日开盘：<span style="color:{open_color};">{o:.2f}（{sign_o}{open_vs_prev:.2f}%）</span></div>
            <div>涨跌幅：<span style="color:{chg_color};font-weight:bold;">{sign_p}{chg_pct:.2f}%</span></div>
            <div>昨日收盘：<span>{prev_close:.2f}</span></div>
            <div>今日成交额：<span style="color:{amount_color};">{today_amount:.2f}亿（{sign_a}{amount_vs_prev:.2f}%）</span></div>
            <div>昨日成交额：<span style="color:#333;">{yesterday_amount:.2f}亿</span></div>
        </div>
        """)

        st.markdown("**K线形态**")
        patterns = service.get_kline_patterns(df, obj_type=section_type)
        if patterns:
            for p in patterns:
                dir_color = "#e53935" if "偏多" in p["direction"] else "#43a047"
                st.html(f"""
                <div style="padding:8px 12px;margin:4px 0;
                    border-left:4px solid {dir_color};
                    background:{dir_color}0a;border-radius:4px;">
                    <span style="font-weight:bold;font-size:16px;color:{dir_color};">
                    {p['name']} — {p['direction']}</span>
                    <br><span style="font-size:13px;color:#666;">{p['note']}</span>
                </div>
                """)
        else:
            st.caption("无明确多空意义")

    st.divider()

    # ── Row: MA table + Volume table ──
    ma_col, vol_col = st.columns([3, 2])

    with ma_col:
        st.markdown("**均线分析**")
        # ── 根据类型选择均线周期 ──
        if section_type == "stock":
            ma_periods = [5, 10, 20, 55, 144, 240]
            medium_long_periods = [55, 144, 240]
        else:
            ma_periods = [5, 10, 20, 60, 120, 240]
            medium_long_periods = [60, 120, 240]
        mas = calc_ma(df, ma_periods)
        ma_dirs = {}
        for p in ma_periods:
            ma_dirs[f"MA{p}"] = ma_direction(mas[f"MA{p}"])

        # Build colored HTML table
        def _dir_color(d: str) -> str:
            if d == "↑": return "#e53935"
            if d == "↓": return "#43a047"
            return "#999"
        def _role_color(r: str) -> str:
            if "支撑" in r or "向上" in r: return "#e53935"
            if "压制" in r or "向下" in r: return "#43a047"
            return "#999"

        rows_html = ""
        for p in ma_periods:
            ma_key = f"MA{p}"
            ma_val = latest_val(mas[ma_key])
            direction = ma_dirs.get(ma_key, "→")
            role = get_ma_role(price, ma_val, direction) if ma_val else "N/A"
            offset = get_offset_info(df, p)
            offset_date = offset["offset_date"]
            offset_amount = offset["offset_amount_yi"]
            offset_vs_pct = offset["vs_today_pct"]
            avg_amount = offset["avg_offset_amount_yi"]
            avg_vs_pct = offset["avg_vs_today_pct"]
            window = offset["window"]
            val_str = f"{ma_val:.2f}" if ma_val else "N/A"
            if offset_amount is not None and offset_vs_pct is not None:
                sign_v = "+" if offset_vs_pct > 0 else ""
                off_str = f"{offset_amount:.2f}亿（{sign_v}{offset_vs_pct:.1f}%）"
                off_color = vol_color_ramp(offset_vs_pct)
            else:
                off_str = "N/A"
                off_color = "#999"

            # 后续均量: window=1 (MA5/10) 与扣抵量相同，显示"—"
            if avg_amount is not None and avg_vs_pct is not None and window > 1:
                sign_a = "+" if avg_vs_pct > 0 else ""
                avg_str = f"{avg_amount:.2f}亿（{sign_a}{avg_vs_pct:.1f}%）"
                avg_color = vol_color_ramp(avg_vs_pct)
                avg_hint = f"扣抵日+后续{window - 1}日均量"
            else:
                avg_str = "—"
                avg_color = "#999"
                avg_hint = ""

            rows_html += f"""<tr>
                <td style="font-weight:600;text-align:center;">{ma_key}</td>
                <td style="text-align:right;">{val_str}</td>
                <td style="color:{_dir_color(direction)};font-weight:bold;text-align:center;">{direction}</td>
                <td style="color:{_role_color(role)};font-weight:bold;text-align:center;">{role}</td>
                <td style="color:#888;text-align:center;">{offset_date}</td>
                <td style="color:{off_color};font-weight:bold;text-align:right;">{off_str}</td>
                <td style="color:{avg_color};font-weight:bold;text-align:right;" title="{avg_hint}">{avg_str}</td>
            </tr>"""

        st.html(f"""
        <table style="width:100%;font-size:15px;border-collapse:collapse;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
                <th style="text-align:center;">均线</th>
                <th style="text-align:right;">值</th>
                <th style="text-align:center;">方向</th>
                <th style="text-align:center;">作用</th>
                <th style="text-align:center;">扣抵日</th>
                <th style="text-align:right;">扣抵量</th>
                <th style="text-align:right;">后续均量</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        """)
        st.caption("扣抵量: 扣抵日当日量 vs 今日量 | 后续均量: 扣抵日+后续4天窗口均量（MA5/10不适用）| 红色=安全 绿色=危险 灰色=持平")

        arrangement = ma_arrangement(df, medium_long_periods=medium_long_periods)
        st.markdown(f"**均线排列:** {arrangement}")

    with vol_col:
        st.markdown("**成交额分析**")
        vol = volume_analysis(df)
        _log.info("%s: vol keys=%s ma5_deduct=%s ma10_deduct=%s vs_ma5=%s vs_ma10=%s",
                  name, sorted(vol.keys()),
                  vol.get("ma5_deduct_yi"), vol.get("ma10_deduct_yi"),
                  vol.get("vs_ma5_deduct_pct"), vol.get("vs_ma10_deduct_pct"))

        def _amt_trend_color(t: str) -> str:
            if "上升" in t or "上行" in t: return "#e53935"
            if "下降" in t or "下行" in t: return "#43a047"
            return "#999"

        def _amt_cross_color(cs: str) -> str:
            if "金叉" in cs: return "#e53935"
            if "死叉" in cs: return "#43a047"
            return "#999"

        # Build styled amount analysis table
        amt_rows = []
        # 1. 今日成交额
        lv = vol.get("latest_amount_yi")
        amt_rows.append(("今日成交额", f"{lv:.2f}亿" if lv else "N/A", None))
        # 2. 5日成交额趋势
        t5 = vol.get("trend_5d", "")
        amt_rows.append(("5日额趋势", t5, _amt_trend_color(t5)))
        # 3. MA5 扣抵量
        d5 = vol.get("ma5_deduct_yi")
        vd5 = vol.get("vs_ma5_deduct_pct")
        if vd5 is not None:
            sign_d5 = "+" if vd5 > 0 else ""
            amt_rows.append(("MA5 扣抵量", f"{d5:.2f}亿（{sign_d5}{vd5:.1f}%）" if d5 else "N/A", "#e53935" if vd5 > 0 else ("#43a047" if vd5 < 0 else "#999")))
        else:
            amt_rows.append(("MA5 扣抵量", "N/A", None))
        # 4. MA10 扣抵量
        d10 = vol.get("ma10_deduct_yi")
        vd10 = vol.get("vs_ma10_deduct_pct")
        if vd10 is not None:
            sign_d10 = "+" if vd10 > 0 else ""
            amt_rows.append(("MA10 扣抵量", f"{d10:.2f}亿（{sign_d10}{vd10:.1f}%）" if d10 else "N/A", "#e53935" if vd10 > 0 else ("#43a047" if vd10 < 0 else "#999")))
        else:
            amt_rows.append(("MA10 扣抵量", "N/A", None))
        # 5. 5日均量
        m5 = vol.get("ma5_yi")
        v5 = vol.get("vs_ma5_pct", 0)
        sign5 = "+" if v5 > 0 else ""
        amt_rows.append(("5日均量", f"{m5:.2f}亿（{sign5}{v5:.1f}%）" if m5 else "N/A", "#e53935" if v5 > 0 else ("#43a047" if v5 < 0 else "#999")))
        # 6. 10日均量
        m10 = vol.get("ma10_yi")
        v10 = vol.get("vs_ma10_pct", 0)
        sign10 = "+" if v10 > 0 else ""
        amt_rows.append(("10日均量", f"{m10:.2f}亿（{sign10}{v10:.1f}%）" if m10 else "N/A", "#e53935" if v10 > 0 else ("#43a047" if v10 < 0 else "#999")))
        # 7. 20日均量
        m20 = vol.get("ma20_yi")
        v20 = vol.get("vs_ma20_pct", 0)
        sign20 = "+" if v20 > 0 else ""
        amt_rows.append(("20日均量", f"{m20:.2f}亿（{sign20}{v20:.1f}%）" if m20 else "N/A", "#e53935" if v20 > 0 else ("#43a047" if v20 < 0 else "#999")))
        # 8. 5日10日均量状态
        cs = vol.get("cross_state") or "—"
        cd = vol.get("cross_days", 0)
        if cd and cs in ("金叉", "死叉"):
            cs_str = f"{cs} {cd}天"
        else:
            cs_str = cs
        amt_rows.append(("5日10日均量状态", cs_str, _amt_cross_color(cs_str)))

        amt_html = ""
        for label, value, color in amt_rows:
            color_attr = f"color:{color};" if color else ""
            amt_html += f"""<tr>
                <td style="color:#888;text-align:left;">{label}</td>
                <td style="{color_attr}font-weight:bold;text-align:right;">{value}</td>
            </tr>"""

        st.html(f"""
        <table style="width:100%;font-size:15px;border-collapse:collapse;">
            <tbody>{amt_html}</tbody>
        </table>
        """)

    st.divider()

    # ── Row: Technical Indicators ──
    st.markdown("**技术指标**")

    # Short-term trend (shared by KD & RSI)
    mas = calc_ma(df, [5, 10, 20])
    def _ma_trend(idx: int) -> str:
        m5, m10, m20 = mas["MA5"][idx], mas["MA10"][idx], mas["MA20"][idx]
        if any(np.isnan(v) for v in [m5, m10, m20]):
            return "盘整"
        if m5 > m10 > m20:
            return "多头"
        elif m5 < m10 < m20:
            return "空头"
        return "盘整"

    today_trend = _ma_trend(-1)
    yesterday_trend = _ma_trend(-2) if len(df) >= 2 else "盘整"

    if today_trend == "盘整" and yesterday_trend == "多头":
        trend_label = "多头转盘整"
        trend_color = "#ef6c00"
    elif today_trend == "盘整" and yesterday_trend == "空头":
        trend_label = "空头转盘整"
        trend_color = "#ef6c00"
    elif today_trend == "多头":
        trend_label = "多头趋势"
        trend_color = "#c62828"
    elif today_trend == "空头":
        trend_label = "空头趋势"
        trend_color = "#2e7d32"
    else:
        trend_label = "盘整"
        trend_color = "#888"

    st.html(f"""
    <div style="font-size:14px;margin-bottom:6px;color:#888;">
        短期趋势（MA5/MA10/MA20）：<span style="color:{trend_color};font-weight:bold;">{trend_label}</span>
    </div>
    """)

    kd = calc_kd(df)
    kd_div = detect_kd_divergence(df, kd["K"], kd["D"])
    bias = calc_bias(df, [10, 20])

    k_val = latest_val(kd["K"])
    d_val = latest_val(kd["D"])

    # ---- helpers ----
    def _short_date(d: str | None) -> str:
        """Normalize date string to MM-DD."""
        if not d:
            return ""
        clean = d.replace("-", "").strip()
        return f"{clean[4:6]}-{clean[6:8]}" if len(clean) >= 8 else d

    def _kd_zone(kv: float | None, dv: float | None) -> str:
        if kv is None or dv is None:
            return "N/A"
        if kv > 80 and dv > 80:
            return "超买区"
        if kv < 20 and dv < 20:
            return "超卖区"
        return "常态区"

    # KD difference & convergence warning
    kd_diff = round(abs(k_val - d_val), 1) if k_val is not None and d_val is not None else None
    if kd_diff is not None and kd_diff >= 20:
        diff_label = f"差值 {kd_diff:.1f} ⚠"
        diff_hint = "KD 开口≥20，大概率收敛，注意反向调整"
        diff_color = "#ef6c00"
    elif kd_diff is not None:
        diff_label = f"差值 {kd_diff:.1f}"
        diff_hint = "KD 开口正常"
        diff_color = "#888"
    else:
        diff_label = "N/A"
        diff_hint = ""
        diff_color = "#888"

    # KD divergence signal text
    div = kd_div
    div_signal = "—"
    div_color = "#999"
    ref = _short_date(div.get("reference_date", ""))

    if div["type"]:
        parts = []
        if div["kd_divergence"]:
            parts.append("KD")
        elif div["k_divergence"]:
            parts.append("K")
        elif div["d_divergence"]:
            parts.append("D")
        which = "/".join(parts)
        cmp = _short_date(div.get("divergence_date", ""))
        days_val = div.get("days", 0) or 0
        if days_val > 0:
            div_signal = f"{div['type']} · {which} · {days_val}天"
        else:
            div_signal = f"{div['type']} · {which}"
        if ref and cmp:
            div_signal += f"\n{ref} 新高 vs {cmp}" if div["type"] == "顶背离" else f"\n{ref} 新低 vs {cmp}"
        # 顶背离=看跌=绿, 底背离=站稳=红
        div_color = "#2e7d32" if div["type"] == "顶背离" else "#c62828"
    elif div.get("direction"):
        days_val = div.get("days", 0) or 0
        if div["direction"] == "top":
            div_signal = f"新高不背离"
            div_color = "#c62828"  # 看多=红
        else:
            div_signal = f"新低不背离"
            div_color = "#2e7d32"  # 看空=绿
        if days_val > 0:
            div_signal += f" · {days_val}天"
        if ref:
            div_signal += f"\n{ref} 新高" if div["direction"] == "top" else f"\n{ref} 新低"

    # Zone color: 超买=看空=绿, 超卖=看多=红
    kd_zone = _kd_zone(k_val, d_val)
    if kd_zone == "超买区":
        zone_color = "#2e7d32"
    elif kd_zone == "超卖区":
        zone_color = "#c62828"
    else:
        zone_color = "#888"

    # --- KD Card ---
    st.markdown("**KD 指标**")
    st.html(f"""
    <table style="width:100%;font-size:18px;border-collapse:collapse;table-layout:fixed;">
        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:16px;">
            <th style="text-align:center;width:10%;">指标</th>
            <th style="text-align:center;width:14%;">K</th>
            <th style="text-align:center;width:14%;">D</th>
            <th style="text-align:center;width:14%;">超买/超卖</th>
            <th style="text-align:center;width:8%;">KD 差值</th>
            <th style="text-align:center;width:40%;">信号</th>
        </tr></thead>
        <tbody><tr>
            <td style="text-align:center;font-weight:600;width:10%;">KD(9,3,3)</td>
            <td style="text-align:center;font-weight:bold;font-size:20px;">{f"{k_val:.2f}" if k_val else "N/A"}</td>
            <td style="text-align:center;font-weight:bold;font-size:20px;">{f"{d_val:.2f}" if d_val else "N/A"}</td>
            <td style="text-align:center;color:{zone_color};font-weight:bold;">{kd_zone}</td>
            <td style="text-align:center;color:{diff_color};font-weight:bold;font-size:17px;" title="{diff_hint}">{diff_label}</td>
            <td style="text-align:center;color:{div_color};font-weight:bold;white-space:pre-line;font-size:17px;">{div_signal}</td>
        </tr></tbody>
    </table>
    """)
    st.caption("K,D 双线 > 80 超买 | K,D 双线 < 20 超卖 | 背离周期边界 = 20 / 80 | |K-D| ≥ 20 大概率收敛")
    if kd_diff is not None and kd_diff >= 20:
        st.caption(f"💡 {diff_hint}")

    # --- RSI Card ---
    st.markdown("**RSI 指标**")
    rsi_all = calc_rsi(df)
    rsi_vals = rsi_all["RSI1"]  # all three identical at (9,9,9)
    rsi_val = latest_val(rsi_vals)
    rsi_div = detect_rsi_divergence(df, rsi_vals, kd["K"], kd["D"])

    # RSI zone
    def _rsi_zone(rv: float | None) -> str:
        if rv is None:
            return "N/A"
        if rv > 70:
            return "超买区"
        if rv < 30:
            return "超卖区"
        return "常态区"

    rsi_zone = _rsi_zone(rsi_val)
    # 超买=看空=绿, 超卖=看多=红
    if rsi_zone == "超买区":
        rsi_zone_color = "#2e7d32"
    elif rsi_zone == "超卖区":
        rsi_zone_color = "#c62828"
    else:
        rsi_zone_color = "#888"

    # RSI divergence signal
    rdiv = rsi_div
    rsi_signal = "—"
    rsi_sig_color = "#999"
    rref = _short_date(rdiv.get("reference_date", ""))
    if rdiv["type"]:
        rcmp = _short_date(rdiv.get("divergence_date", ""))
        days_val = rdiv.get("days", 0) or 0
        rsi_signal = f"{rdiv['type']}"
        if days_val > 0:
            rsi_signal += f" · {days_val}天"
        if rref and rcmp:
            rsi_signal += f"\n{rref} 新高 vs {rcmp}" if rdiv["type"] == "顶背离" else f"\n{rref} 新低 vs {rcmp}"
        rsi_sig_color = "#2e7d32" if rdiv["type"] == "顶背离" else "#c62828"
    elif rdiv.get("direction"):
        days_val = rdiv.get("days", 0) or 0
        if rdiv["direction"] == "top":
            rsi_signal = "新高不背离"
            rsi_sig_color = "#c62828"
        else:
            rsi_signal = "新低不背离"
            rsi_sig_color = "#2e7d32"
        if days_val > 0:
            rsi_signal += f" · {days_val}天"
        if rref:
            rsi_signal += f"\n{rref} 新高" if rdiv["direction"] == "top" else f"\n{rref} 新低"

    # RSI vs K comparison — only meaningful in matching trend
    rsi_vs_k = "—"
    rsi_vs_k_color = "#999"
    if rsi_val is not None and k_val is not None:
        if today_trend == "多头" and rsi_val > k_val:
            rsi_vs_k = "强度充足"
            rsi_vs_k_color = "#c62828"  # 看多=红
        elif today_trend == "空头" and rsi_val < k_val:
            rsi_vs_k = "强度不足"
            rsi_vs_k_color = "#2e7d32"  # 看空=绿

    st.html(f"""
    <table style="width:100%;font-size:18px;border-collapse:collapse;table-layout:fixed;">
        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:16px;">
            <th style="text-align:center;width:10%;">指标</th>
            <th style="text-align:center;width:28%;">RSI</th>
            <th style="text-align:center;width:14%;">超买/超卖</th>
            <th style="text-align:center;width:8%;">vs KD</th>
            <th style="text-align:center;width:40%;">信号</th>
        </tr></thead>
        <tbody><tr>
            <td style="text-align:center;font-weight:600;width:10%;">RSI(9,9,9)</td>
            <td style="text-align:center;font-weight:bold;font-size:20px;">{f"{rsi_val:.2f}" if rsi_val else "N/A"}</td>
            <td style="text-align:center;color:{rsi_zone_color};font-weight:bold;">{rsi_zone}</td>
            <td style="text-align:center;color:{rsi_vs_k_color};font-weight:bold;">{rsi_vs_k}</td>
            <td style="text-align:center;color:{rsi_sig_color};font-weight:bold;white-space:pre-line;font-size:17px;">{rsi_signal}</td>
        </tr></tbody>
    </table>
    """)
    if rsi_val is not None:
        st.caption("RSI > 70 超买 | RSI < 30 超卖 | 背离周期边界 = 50 | 多头 RSI>K=强度充足 | 空头 RSI<K=强度不足")
    else:
        st.caption("RSI 数据不足")

    # --- BIAS Card (skip for stocks — ATR-normalised patterns replace it) ---
    if section_type != "stock":
        st.markdown("**BIAS 乖离率**")
        binfo = bias_status(bias, [10, 20])

        def _bias_cell(key: str) -> str:
            entry = binfo.get(key, {})
            val = entry.get("value")
            if val is None:
                return "N/A"
            s = f"{val:.2f}"
            if entry.get("status"):
                s += f' <span style="color:{entry["color"]};font-weight:bold;">({entry["status"]})</span>'
            return s

        b10_html = _bias_cell("BIAS10")
        b20_html = _bias_cell("BIAS20")

        st.html(f"""
        <table style="width:100%;font-size:18px;border-collapse:collapse;table-layout:fixed;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:16px;">
                <th style="text-align:center;width:10%;">指标</th>
                <th style="text-align:center;">10日乖离</th>
                <th style="text-align:center;">月线乖离(20日)</th>
            </tr></thead>
            <tbody><tr>
                <td style="text-align:center;font-weight:600;width:10%;">BIAS</td>
                <td style="text-align:center;font-weight:bold;font-size:20px;">{b10_html}</td>
                <td style="text-align:center;font-weight:bold;font-size:20px;">{b20_html}</td>
            </tr></tbody>
        </table>
        """)
        st.caption("10日乖离 > 10 短线超买 | < -10 短线超卖 | 月线乖离(20日) > 7 超买 | < -7 超卖")

    # ── 成分股分析 (industry) ──
    if section_type == "industry":
        _trade_date = st.session_state.get("trade_date")
        if not _trade_date or not industry_level:
            return

        _log.info("Loading constituents for industry=%s level=%s date=%s",
                  name, industry_level, _trade_date)
        const = service.get_industry_constituents(name, industry_level, _trade_date)

        if not const["top_cap"] and not const["top_movers"]:
            st.caption("暂无成分股数据")
            return

        st.divider()

        cap_col, mov_col = st.columns(2)

        with cap_col:
            st.markdown("**🏦 大市值权重股**")
            if const["top_cap"]:
                rows = ""
                for i, s in enumerate(const["top_cap"]):
                    pct = s["pct_change"]
                    pct_color = "#e53935" if pct >= 0 else "#43a047"
                    sign = "+" if pct >= 0 else ""
                    mv_yi = s["total_mv"] / 1e4  # 万元 → 亿
                    mv_pct = s.get("mv_pct", 0)
                    rows += f"""<tr>
                        <td style="text-align:center;color:#888;">{i + 1}</td>
                        <td style="color:#888;font-size:14px;">{s['ts_code']}</td>
                        <td style="font-weight:600;">{s['name']}</td>
                        <td style="text-align:right;">{mv_yi:.0f}亿</td>
                        <td style="text-align:right;color:#888;">{mv_pct:.1f}%</td>
                        <td style="text-align:right;color:{pct_color};font-weight:bold;">{sign}{pct:.2f}%</td>
                    </tr>"""
                st.html(f"""
                <table style="width:100%;font-size:15px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
                        <th style="text-align:center;">#</th>
                        <th style="text-align:left;">代码</th>
                        <th style="text-align:left;">名称</th>
                        <th style="text-align:right;">总市值</th>
                        <th style="text-align:right;">市值占比</th>
                        <th style="text-align:right;">涨跌幅</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
                """)
            else:
                st.caption("无市值数据")

        with mov_col:
            st.markdown("**📈 今日异动股**")
            if const["top_movers"]:
                rows = ""
                for i, s in enumerate(const["top_movers"]):
                    pct = s["pct_change"]
                    pct_color = "#e53935" if pct >= 0 else "#43a047"
                    sign = "+" if pct >= 0 else ""
                    mv_yi = s["total_mv"] / 1e4  # 万元 → 亿
                    mv_pct = s.get("mv_pct", 0)
                    rows += f"""<tr>
                        <td style="text-align:center;color:#888;">{i + 1}</td>
                        <td style="color:#888;font-size:14px;">{s['ts_code']}</td>
                        <td style="font-weight:600;">{s['name']}</td>
                        <td style="text-align:right;color:{pct_color};font-weight:bold;">{sign}{pct:.2f}%</td>
                        <td style="text-align:right;">{mv_yi:.0f}亿</td>
                        <td style="text-align:right;color:#888;">{mv_pct:.1f}%</td>
                    </tr>"""
                st.html(f"""
                <table style="width:100%;font-size:15px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
                        <th style="text-align:center;">#</th>
                        <th style="text-align:left;">代码</th>
                        <th style="text-align:left;">名称</th>
                        <th style="text-align:right;">涨跌幅</th>
                        <th style="text-align:right;">总市值</th>
                        <th style="text-align:right;">市值占比</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
                """)
            else:
                st.caption("无涨跌幅数据")

        return

    # ── 权重贡献 (index only) ──

    st.divider()
    st.markdown("**权重贡献**")
    _trade_date = st.session_state.get("trade_date")
    contrib = service.get_index_contribution(code, trade_date=_trade_date)

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
        freq = service.get_industry_frequency(code, trade_date=_trade_date)
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
