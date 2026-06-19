"""
Shared technical analysis rendering components.

Used by both 01_市场全景.py (index analysis, layout='table')
and 02_板块分析.py (industry analysis, layout='card').

Each function is self-contained: it takes a DataFrame and computes
what it needs internally.  Callers arrange the layout (columns, dividers)
as they see fit.
"""

import numpy as np
import streamlit as st

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
from rendering.styles import vol_color_ramp, up_down_color


# ── tiny helpers ──

def latest_val(series):
    """Get latest non-NaN value from a list."""
    for v in reversed(series):
        if not np.isnan(v):
            return round(float(v), 2)
    return None


def _short_date(d):
    """Normalize date string to MM-DD."""
    if not d:
        return ""
    clean = d.replace("-", "").strip()
    return f"{clean[4:6]}-{clean[6:8]}" if len(clean) >= 8 else d


# ═══════════════════════════════════════════════════════════════════
# Block 1: OHLC card
# ═══════════════════════════════════════════════════════════════════

def render_ohlc_card(df):
    """
    Render OHLC summary card (latest price, open, chg%, prev close, amount).
    To be placed in the right column next to the K-line chart.
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    price = float(latest["close"])
    o = float(latest["open"])
    prev_close = float(prev["close"])

    chg_pct = (price / prev_close - 1) * 100
    open_vs_prev = (o / prev_close - 1) * 100

    today_amount = float(latest["amount"]) / 1e5  # 千元→亿
    yesterday_amount = float(prev["amount"]) / 1e5
    amount_vs_prev = (today_amount / yesterday_amount - 1) * 100 if yesterday_amount else 0

    chg_color = "#e53935" if chg_pct >= 0 else "#43a047"
    open_color = "#e53935" if o >= prev_close else "#43a047"
    amount_color = "#e53935" if amount_vs_prev >= 0 else "#43a047"
    sign_p = "+" if chg_pct >= 0 else ""
    sign_o = "+" if open_vs_prev >= 0 else ""
    sign_a = "+" if amount_vs_prev >= 0 else ""

    st.markdown("**K线数据**")
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


# ═══════════════════════════════════════════════════════════════════
# Block 2: K-line patterns
# ═══════════════════════════════════════════════════════════════════

def render_kline_patterns(service, df):
    """Render K-line pattern cards from DashboardService.get_kline_patterns()."""
    st.markdown("**K线形态**")
    patterns = service.get_kline_patterns(df)
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


# ═══════════════════════════════════════════════════════════════════
# Block 3: MA table
# ═══════════════════════════════════════════════════════════════════

def _dir_color(d):
    if d == "↑": return "#e53935"
    if d == "↓": return "#43a047"
    return "#999"


def _role_color(r):
    if "支撑" in r or "向上" in r: return "#e53935"
    if "压制" in r or "向下" in r: return "#43a047"
    return "#999"


def render_ma_table(df, show_avg_amount=True):
    """
    Render MA analysis table.

    Parameters:
        show_avg_amount: If True, show the 后续均量 column (7 cols, used by 01).
                         If False, show 6 cols without 后续均量 (used by 02).
    """
    st.markdown("**均线分析**")
    mas = calc_ma(df)
    ma_periods = [5, 10, 20, 60, 120, 240]

    price = float(df.iloc[-1]["close"])

    ma_dirs = {}
    for p in ma_periods:
        ma_dirs[f"MA{p}"] = ma_direction(mas[f"MA{p}"])

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

        if show_avg_amount:
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

        if show_avg_amount:
            rows_html += f"""<tr>
                <td style="font-weight:600;text-align:center;">{ma_key}</td>
                <td style="text-align:right;">{val_str}</td>
                <td style="color:{_dir_color(direction)};font-weight:bold;text-align:center;">{direction}</td>
                <td style="color:{_role_color(role)};font-weight:bold;text-align:center;">{role}</td>
                <td style="color:#888;text-align:center;">{offset_date}</td>
                <td style="color:{off_color};font-weight:bold;text-align:right;">{off_str}</td>
                <td style="color:{avg_color};font-weight:bold;text-align:right;" title="{avg_hint}">{avg_str}</td>
            </tr>"""
        else:
            off_date_compact = offset_date[:10] if offset_date else ""
            if offset_amount is not None:
                off_amt_compact = f"{offset_amount:,.0f}亿"
            else:
                off_amt_compact = "N/A"
            rows_html += f"""<tr>
                <td style="font-weight:600;">{ma_key}</td>
                <td style="text-align:right;">{val_str}</td>
                <td style="text-align:center;color:{_dir_color(direction)};">{direction}</td>
                <td style="text-align:center;color:{_role_color(role)};">{role}</td>
                <td style="font-size:12px;color:#888;">{off_date_compact}</td>
                <td style="font-size:12px;color:#888;text-align:right;">{off_amt_compact}</td>
            </tr>"""

    if show_avg_amount:
        header_html = """<thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;font-size:13px;">
            <th style="text-align:center;">均线</th>
            <th style="text-align:right;">值</th>
            <th style="text-align:center;">方向</th>
            <th style="text-align:center;">作用</th>
            <th style="text-align:center;">扣抵日</th>
            <th style="text-align:right;">扣抵量</th>
            <th style="text-align:right;">后续均量</th>
        </tr></thead>"""
        caption = "扣抵量: 扣抵日当日量 vs 今日量 | 后续均量: 扣抵日+后续4天窗口均量（MA5/10不适用）| 红色=安全 绿色=危险 灰色=持平"
    else:
        header_html = """<thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
            <th>均线</th><th>值</th><th>方向</th><th>作用</th>
            <th>扣抵日</th><th>扣抵量</th>
        </tr></thead>"""
        caption = ""

    st.html(f"""
    <table style="width:100%;font-size:{15 if show_avg_amount else 14}px;border-collapse:collapse;">
        {header_html}
        <tbody>{rows_html}</tbody>
    </table>
    """)
    if caption:
        st.caption(caption)


def render_ma_arrangement(df):
    """Render the MA arrangement line (多头/空头/盘整)."""
    arrangement = ma_arrangement(df)
    st.markdown(f"**均线排列:** {arrangement}")


# ═══════════════════════════════════════════════════════════════════
# Block 4: Volume analysis
# ═══════════════════════════════════════════════════════════════════

def render_volume_section(df, variant="full"):
    """
    Render volume/amount analysis table.

    Parameters:
        variant: 'full' — detailed table with 扣抵量 (01 市场全景)
                 'compact' — simpler table (02 板块分析)
    """
    st.markdown("**成交额分析**")
    vol = volume_analysis(df)

    if variant == "full":
        _render_volume_full(vol)
    else:
        _render_volume_compact(vol)


def _amt_trend_color(t):
    if "上升" in t or "上行" in t: return "#e53935"
    if "下降" in t or "下行" in t: return "#43a047"
    return "#999"


def _amt_cross_color(cs):
    if "金叉" in cs: return "#e53935"
    if "死叉" in cs: return "#43a047"
    return "#999"


def _render_volume_full(vol):
    """Detailed volume table with 扣抵量 (for 01 index analysis)."""
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
        amt_rows.append(("MA5 扣抵量", f"{d5:.2f}亿（{sign_d5}{vd5:.1f}%）" if d5 else "N/A",
                         "#e53935" if vd5 > 0 else ("#43a047" if vd5 < 0 else "#999")))
    else:
        amt_rows.append(("MA5 扣抵量", "N/A", None))
    # 4. MA10 扣抵量
    d10 = vol.get("ma10_deduct_yi")
    vd10 = vol.get("vs_ma10_deduct_pct")
    if vd10 is not None:
        sign_d10 = "+" if vd10 > 0 else ""
        amt_rows.append(("MA10 扣抵量", f"{d10:.2f}亿（{sign_d10}{vd10:.1f}%）" if d10 else "N/A",
                         "#e53935" if vd10 > 0 else ("#43a047" if vd10 < 0 else "#999")))
    else:
        amt_rows.append(("MA10 扣抵量", "N/A", None))
    # 5. 5日均量
    m5 = vol.get("ma5_yi")
    v5 = vol.get("vs_ma5_pct", 0)
    sign5 = "+" if v5 > 0 else ""
    amt_rows.append(("5日均量", f"{m5:.2f}亿（{sign5}{v5:.1f}%）" if m5 else "N/A",
                     "#e53935" if v5 > 0 else ("#43a047" if v5 < 0 else "#999")))
    # 6. 10日均量
    m10 = vol.get("ma10_yi")
    v10 = vol.get("vs_ma10_pct", 0)
    sign10 = "+" if v10 > 0 else ""
    amt_rows.append(("10日均量", f"{m10:.2f}亿（{sign10}{v10:.1f}%）" if m10 else "N/A",
                     "#e53935" if v10 > 0 else ("#43a047" if v10 < 0 else "#999")))
    # 7. 20日均量
    m20 = vol.get("ma20_yi")
    v20 = vol.get("vs_ma20_pct", 0)
    sign20 = "+" if v20 > 0 else ""
    amt_rows.append(("20日均量", f"{m20:.2f}亿（{sign20}{v20:.1f}%）" if m20 else "N/A",
                     "#e53935" if v20 > 0 else ("#43a047" if v20 < 0 else "#999")))
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


def _render_volume_compact(vol):
    """Compact volume table (for 02 industry analysis)."""
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


# ═══════════════════════════════════════════════════════════════════
# Block 5: Short-term trend
# ═══════════════════════════════════════════════════════════════════

def render_short_term_trend(df):
    """
    Render short-term trend line (MA5/MA10/MA20) and return the trend label.

    Returns:
        trend_label: '多头趋势' | '空头趋势' | '多头转盘整' | '空头转盘整' | '盘整'
    """
    mas = calc_ma(df, [5, 10, 20])

    def _ma_trend(idx):
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
    return trend_label


# ═══════════════════════════════════════════════════════════════════
# Block 6: KD indicator
# ═══════════════════════════════════════════════════════════════════

def _kd_zone(kv, dv):
    if kv is None or dv is None:
        return "N/A"
    if kv > 80 and dv > 80:
        return "超买区"
    if kv < 20 and dv < 20:
        return "超卖区"
    return "常态区"


def render_kd_section(df, layout="table"):
    """
    Render KD indicator section.

    Parameters:
        layout: 'table' — detailed table with K/D/zone/diff/signal (01 市场全景)
                'card'  — compact card with K/D/zone/divergence (02 板块分析)
    """
    kd = calc_kd(df)
    kd_div = detect_kd_divergence(df, kd["K"], kd["D"])
    k_val = latest_val(kd["K"])
    d_val = latest_val(kd["D"])
    zone = _kd_zone(k_val, d_val)

    if layout == "table":
        _render_kd_table(k_val, d_val, zone, kd_div)
    else:
        _render_kd_card(k_val, d_val, zone, kd_div)


def _render_kd_table(k_val, d_val, zone, div):
    """Detailed KD table (01 style)."""
    # Zone color: 超买=看空=绿, 超卖=看多=红
    if zone == "超买区":
        zone_color = "#2e7d32"
    elif zone == "超卖区":
        zone_color = "#c62828"
    else:
        zone_color = "#888"

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

    # Divergence signal text
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
        div_color = "#2e7d32" if div["type"] == "顶背离" else "#c62828"
    elif div.get("direction"):
        days_val = div.get("days", 0) or 0
        if div["direction"] == "top":
            div_signal = "新高不背离"
            div_color = "#c62828"
        else:
            div_signal = "新低不背离"
            div_color = "#2e7d32"
        if days_val > 0:
            div_signal += f" · {days_val}天"
        if ref:
            div_signal += f"\n{ref} 新高" if div["direction"] == "top" else f"\n{ref} 新低"

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
            <td style="text-align:center;color:{zone_color};font-weight:bold;">{zone}</td>
            <td style="text-align:center;color:{diff_color};font-weight:bold;font-size:17px;" title="{diff_hint}">{diff_label}</td>
            <td style="text-align:center;color:{div_color};font-weight:bold;white-space:pre-line;font-size:17px;">{div_signal}</td>
        </tr></tbody>
    </table>
    """)
    st.caption("K,D 双线 > 80 超买 | K,D 双线 < 20 超卖 | 背离周期边界 = 20 / 80 | |K-D| ≥ 20 大概率收敛")
    if kd_diff is not None and kd_diff >= 20:
        st.caption(f"💡 {diff_hint}")


def _render_kd_card(k_val, d_val, zone, div):
    """Compact KD card (02 style)."""
    kd_k = k_val or 0
    kd_d_val = d_val or 0

    if kd_k > 80 and kd_d_val > 80:
        kd_zone_str = "🔥 超买区"
    elif kd_k < 20 and kd_d_val < 20:
        kd_zone_str = "❄️ 超卖区"
    else:
        kd_zone_str = "➖ 常态区"

    kd_div_str = (
        f"{div['type']} ({div.get('days', 0)}天)"
        if div.get("type") else "无"
    )

    st.markdown("**KD 指标**")
    st.html(f"""
    <div style="font-size:15px;line-height:2;">
        <div>K：<b>{kd_k:.1f}</b></div>
        <div>D：<b>{kd_d_val:.1f}</b></div>
        <div>区间：{kd_zone_str}</div>
        <div>背离：{kd_div_str}</div>
    </div>
    """)


# ═══════════════════════════════════════════════════════════════════
# Block 7: RSI indicator
# ═══════════════════════════════════════════════════════════════════

def _rsi_zone(rv):
    if rv is None:
        return "N/A"
    if rv > 70:
        return "超买区"
    if rv < 30:
        return "超卖区"
    return "常态区"


def render_rsi_section(df, trend_label="盘整", layout="table"):
    """
    Render RSI indicator section.

    Parameters:
        trend_label: Short-term trend label from render_short_term_trend()
        layout: 'table' — detailed table with RSI/zone/vsKD/signal (01 市场全景)
                'card'  — compact card with RSI/zone/divergence (02 板块分析)
    """
    rsi_all = calc_rsi(df)
    rsi_vals = rsi_all["RSI1"]
    rsi_val = latest_val(rsi_vals)

    # Need KD for divergence detection and vsKD comparison
    kd = calc_kd(df)
    rsi_div = detect_rsi_divergence(df, rsi_vals, kd["K"], kd["D"])
    k_val = latest_val(kd["K"])

    zone = _rsi_zone(rsi_val)

    if layout == "table":
        _render_rsi_table(rsi_val, zone, rsi_div, k_val, trend_label)
    else:
        _render_rsi_card(rsi_val, zone, rsi_div)


def _render_rsi_table(rsi_val, zone, rdiv, k_val, trend_label):
    """Detailed RSI table (01 style)."""
    # Zone color: 超买=看空=绿, 超卖=看多=红
    if zone == "超买区":
        zone_color = "#2e7d32"
    elif zone == "超卖区":
        zone_color = "#c62828"
    else:
        zone_color = "#888"

    # Divergence signal
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

    # RSI vs K comparison
    rsi_vs_k = "—"
    rsi_vs_k_color = "#999"
    if rsi_val is not None and k_val is not None:
        if trend_label == "多头趋势" and rsi_val > k_val:
            rsi_vs_k = "强度充足"
            rsi_vs_k_color = "#c62828"
        elif trend_label == "空头趋势" and rsi_val < k_val:
            rsi_vs_k = "强度不足"
            rsi_vs_k_color = "#2e7d32"

    st.markdown("**RSI 指标**")
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
            <td style="text-align:center;color:{zone_color};font-weight:bold;">{zone}</td>
            <td style="text-align:center;color:{rsi_vs_k_color};font-weight:bold;">{rsi_vs_k}</td>
            <td style="text-align:center;color:{rsi_sig_color};font-weight:bold;white-space:pre-line;font-size:17px;">{rsi_signal}</td>
        </tr></tbody>
    </table>
    """)
    if rsi_val is not None:
        st.caption("RSI > 70 超买 | RSI < 30 超卖 | 背离周期边界 = 50 | 多头 RSI>K=强度充足 | 空头 RSI<K=强度不足")
    else:
        st.caption("RSI 数据不足")


def _render_rsi_card(rsi_val, zone, rdiv):
    """Compact RSI card (02 style)."""
    if rsi_val and rsi_val > 70:
        rsi_zone_str = "🔥 超买区"
    elif rsi_val and rsi_val < 30:
        rsi_zone_str = "❄️ 超卖区"
    else:
        rsi_zone_str = "➖ 常态区"

    rsi_div_str = (
        f"{rdiv['type']} ({rdiv.get('days', 0)}天)"
        if rdiv.get("type") else "无"
    )

    st.markdown("**RSI 指标**")
    st.html(f"""
    <div style="font-size:15px;line-height:2;">
        <div>RSI(9)：<b>{rsi_val:.1f}</b></div>
        <div>区间：{rsi_zone_str}</div>
        <div>背离：{rsi_div_str}</div>
    </div>
    """)


# ═══════════════════════════════════════════════════════════════════
# Block 8: BIAS indicator
# ═══════════════════════════════════════════════════════════════════

def render_bias_section(df, layout="table"):
    """
    Render BIAS indicator section.

    Parameters:
        layout: 'table' — 3-column BIAS table (01 市场全景)
                'card'  — compact BIAS card (02 板块分析)
    """
    bias = calc_bias(df, [10, 20])
    binfo = bias_status(bias, [10, 20])
    bias10_val = binfo.get("BIAS10", {}).get("value") or 0.0
    bias20_val = binfo.get("BIAS20", {}).get("value") or 0.0

    if layout == "table":
        _render_bias_table(binfo)
    else:
        _render_bias_card(bias10_val, bias20_val, binfo)


def _bias_cell(entry):
    val = entry.get("value")
    if val is None:
        return "N/A"
    s = f"{val:.2f}"
    if entry.get("status"):
        s += f' <span style="color:{entry["color"]};font-weight:bold;">({entry["status"]})</span>'
    return s


def _render_bias_table(binfo):
    """Detailed BIAS table (01 style)."""
    b10_html = _bias_cell(binfo.get("BIAS10", {}))
    b20_html = _bias_cell(binfo.get("BIAS20", {}))

    st.markdown("**BIAS 乖离率**")
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


def _render_bias_card(bias10_val, bias20_val, binfo):
    """Compact BIAS card (02 style)."""
    b10s = binfo.get("BIAS10", {}).get("status") or "—"
    b20s = binfo.get("BIAS20", {}).get("status") or "—"

    st.markdown("**BIAS 乖离率**")
    st.html(f"""
    <div style="font-size:15px;line-height:2;">
        <div>BIAS10：<b>{bias10_val:+.2f}%</b></div>
        <div style="color:#888;">{b10s}</div>
        <div>BIAS20：<b>{bias20_val:+.2f}%</b></div>
        <div style="color:#888;">{b20s}</div>
    </div>
    """)
