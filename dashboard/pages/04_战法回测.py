"""战法回测 — 多策略对比."""
import random
import streamlit as st
import plotly.graph_objects as go
from collections import defaultdict
from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS

st.set_page_config(page_title="战法回测", page_icon="🔬", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)


def _render_html_table(rows: list[dict], col_widths: dict[str, str] | None = None) -> None:
    """Render a list of dicts as an auto-wrapping HTML table."""
    if not rows:
        return
    keys = list(rows[0].keys())
    widths = col_widths or {}
    header_html = "".join(
        f'<th style="white-space:nowrap;padding:6px 8px;text-align:left;width:{widths.get(k, "auto")}">'
        f'{k}</th>' for k in keys
    )
    body_rows = []
    for i, row in enumerate(rows):
        bg = "#fafafa" if i % 2 == 0 else "#fff"
        cells = "".join(
            f'<td style="white-space:normal;word-wrap:break-word;overflow-wrap:break-word;'
            f'padding:4px 8px;vertical-align:top;width:{widths.get(k, "auto")}">'
            f'{row.get(k, "")}</td>'
            for k in keys
        )
        body_rows.append(f'<tr style="background:{bg}">{cells}</tr>')
    html = (
        f'<table style="width:100%;border-collapse:collapse;font-size:0.9em;table-layout:auto">'
        f'<thead><tr>{header_html}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        f'</table>'
    )
    st.markdown(html, unsafe_allow_html=True)

svc = DashboardService()

st.title("🔬 战法回测")
st.caption(f"股票池 × 策略日线回测 — 多策略对比 ｜ AI v{DashboardService._AI_VERSION}")

# ── Step 1: Load configs ──
pools = svc.load_backtest_pools()
strategies = svc.load_backtest_strategies()

if not pools:
    st.warning("未找到股票池配置，请在 config/backtest_pools.txt 中配置。")
    st.stop()

if not strategies:
    st.warning("未找到策略配置，请在 config/backtest_strategies.txt 中配置。")
    st.stop()

pool_names = [p.name for p in pools]
strategy_names = [s.name for s in strategies]

col1, col2 = st.columns(2)
with col1:
    selected_pool_name = st.selectbox("股票池", pool_names, key="bt_pool")
with col2:
    selected_strategy_names = st.multiselect(
        "策略对比（可多选）", strategy_names,
        default=strategy_names, key="bt_strategies",
    )

selected_pool = next(p for p in pools if p.name == selected_pool_name)
selected_strategies = [s for s in strategies if s.name in selected_strategy_names]

if not selected_strategies:
    st.info("请至少选择一个策略。")
    st.stop()

col_r1, col_r2, col_r3 = st.columns(3)
with col_r1:
    run_rounds = st.number_input(
        "每策略跑几轮", min_value=1, max_value=100, value=20,
        key="bt_rounds", help="多轮取均值，消除买入顺序随机影响",
    )
with col_r2:
    max_workers = st.number_input(
        "并发数", min_value=1, max_value=16, value=10,
        key="bt_workers", help="并行线程数，建议 4~12",
    )

# ── Expander: 股票池详情 ──
with st.expander("📋 股票池详情", expanded=False):
    latest_td = svc.get_latest_trade_date()
    for s in selected_pool.stocks:
        if s.code:
            exit_display = s.exit_date if s.exit_date != "now" else f"至今({latest_td})"
            st.markdown(f"✅ **{s.name}** → `{s.code}`  {s.entry_date} ~ {exit_display}")
        else:
            st.markdown(f"❌ **{s.name}** → 未找到代码")

# ── Step 2: Load Data ──
if st.button("📥 加载数据", key="bt_load", type="primary"):
    codes = [s.code for s in selected_pool.stocks if s.code]

    if not codes:
        st.error("股票池中没有有效代码。")
    else:
        with st.spinner("正在加载K线数据..."):
            try:
                import datetime as _dt
                from marketreview.backtest.strategy_base import create_strategy

                # Determine date range
                all_dates = [s.entry_date for s in selected_pool.stocks if s.entry_date]
                min_entry = min(all_dates) if all_dates else "20240101"
                max_exit = svc.get_latest_trade_date()

                # Use max lookback across all selected strategies
                lookback = 60
                for sc in selected_strategies:
                    strat = create_strategy(sc.class_name)
                    if strat:
                        lookback = max(lookback, strat.lookback_trading_days)
                actual_buffer = max(365, int(lookback * 2.5))
                buff_dt = _dt.datetime.strptime(min_entry, "%Y%m%d") - _dt.timedelta(days=actual_buffer)
                start_date = buff_dt.strftime("%Y%m%d")

                svc._dp.ensure_data_loaded_for_codes(codes, start_date, max_exit)
                st.session_state.bt_data_loaded = True
                st.session_state.bt_codes = codes
                st.session_state.bt_start = start_date
                st.session_state.bt_end = max_exit
                st.success(
                    f"✅ 已加载 {len(codes)} 只股票, "
                    f"缓冲{actual_buffer}日历日, "
                    f"{start_date}~{max_exit}"
                )
            except Exception as e:
                st.error(f"加载失败: {e}")
                import traceback
                st.code(traceback.format_exc())

# ── Step 3: Run Comparison ──
run_disabled = not st.session_state.get("bt_data_loaded", False)
if st.button("▶ 运行对比", key="bt_run", type="primary", disabled=run_disabled):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from marketreview.backtest.reporter import merge_reports

    total = len(selected_strategies) * run_rounds
    status = st.empty()
    status.info(f"⏳ 已提交 {total} 个回测任务（{len(selected_strategies)}策略 × {run_rounds}轮），等待首个结果返回...")

    reports = {}
    progress = st.progress(0)
    completed = 0

    # Group results by strategy name
    round_results: dict[str, list] = {s.name: [] for s in selected_strategies}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for rnd in range(run_rounds):
            seed = random.randint(0, 2**31 - 1)
            for strategy_cfg in selected_strategies:
                fut = executor.submit(svc.run_backtest, selected_pool, strategy_cfg, seed)
                futures[fut] = (strategy_cfg.name, rnd + 1)

        for fut in as_completed(futures):
            sname, rnd = futures[fut]
            completed += 1
            try:
                report = fut.result()
                round_results[sname].append(report)
            except Exception as e:
                st.error(f"❌ {sname} 第{rnd}轮 运行失败: {e}")
                import traceback
                st.code(traceback.format_exc())

            progress.progress(completed / total)
            status.text(f"已完成 {completed}/{total} — {sname} 第{rnd}轮")

    # Merge round results per strategy
    for sname, round_list in round_results.items():
        if round_list:
            reports[sname] = merge_reports(round_list)

    progress.progress(1.0, "对比完成")
    status.empty()
    st.session_state.bt_reports = reports
    st.session_state.bt_has_reports = True
    st.session_state.bt_rounds_used = run_rounds

# ── Step 4: Display Results ──
if st.session_state.get("bt_has_reports"):
    reports = st.session_state.bt_reports
    strategy_names_list = list(reports.keys())

    if not reports:
        st.info("未产生任何回测报告。")
    else:
        # ── 策略对比汇总表 ──
        rounds_used = st.session_state.get("bt_rounds_used", 1)
        st.subheader(f"📊 策略对比汇总（{rounds_used}轮均值）")
        import datetime as _dt

        comp_rows = []
        for sname, report in reports.items():
            comp_rows.append({
                "策略": sname,
                "交易笔数": f"{report.total_trades:.1f}",
                "胜率": f"{report.win_rate:.1%}",
                "总收益": f"{report.total_return_pct:+.2f}%",
                "最大回撤": f"{report.max_drawdown_pct:.2f}%",
                "平均持仓": f"{report.avg_hold_days:.1f}天",
                "盈亏比": f"{report.profit_loss_ratio:.2f}",
            })
        st.dataframe(comp_rows, use_container_width=True, hide_index=True)

        # ── 净值曲线叠加图 ──
        st.subheader("📈 净值曲线对比")
        fig = go.Figure()

        # Color palette for strategies
        colors = ["#cf2c2c", "#2c6fcf", "#2c9f4f", "#e68a2e", "#8b5cf6", "#ec4899"]

        # Find common min entry date across pool for x-axis trim
        min_entry = min(
            (s.entry_date for s in selected_pool.stocks if s.entry_date),
            default=None
        )

        for i, sname in enumerate(strategy_names_list):
            report = reports[sname]
            color = colors[i % len(colors)]

            # ── Multi-round: show shaded band + mean line ──
            if (report.num_rounds > 1 and report.individual_equity_curves
                    and len(report.individual_equity_curves) > 1):
                # Build date → list of net values from individual curves
                date_vals: dict[str, list[float]] = defaultdict(list)
                for icurve in report.individual_equity_curves:
                    for pt in icurve:
                        d = pt["date"]
                        if min_entry and d < min_entry:
                            continue
                        date_vals[d].append(pt["return_pct"] / 100.0 + 1.0)

                if date_vals:
                    sorted_dates = sorted(date_vals.keys())
                    dt_list = [_dt.datetime.strptime(d, "%Y%m%d") for d in sorted_dates]
                    vals_arrays = [date_vals[d] for d in sorted_dates]
                    means = [sum(v) / len(v) for v in vals_arrays]
                    mins = [min(v) for v in vals_arrays]
                    maxs = [max(v) for v in vals_arrays]

                    # Band (min-max fill)
                    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
                    band_color = f"rgba({r},{g},{b},0.12)"
                    fig.add_trace(go.Scatter(
                        x=dt_list + dt_list[::-1],
                        y=maxs + mins[::-1],
                        fill="toself",
                        fillcolor=band_color,
                        line=dict(width=0),
                        legendgroup=sname,
                        showlegend=False,
                    ))
                    # Mean line
                    fig.add_trace(go.Scatter(
                        x=dt_list, y=means, mode="lines",
                        line=dict(color=color, width=2.5),
                        name=sname,
                        legendgroup=sname,
                    ))
            else:
                # Single round: just draw the line
                if report.equity_curve:
                    if min_entry:
                        curve = [pt for pt in report.equity_curve if pt["date"] >= min_entry]
                    else:
                        curve = report.equity_curve

                    if curve:
                        dates = [_dt.datetime.strptime(pt["date"], "%Y%m%d") for pt in curve]
                        net_values = [pt["return_pct"] / 100.0 + 1.0 for pt in curve]
                        fig.add_trace(go.Scatter(
                            x=dates, y=net_values, mode="lines",
                            line=dict(color=color, width=2),
                            name=sname,
                        ))

        # Baseline at 1.0
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)
        fig.update_layout(
            title="净值曲线（多策略叠加）",
            xaxis_title="日期",
            yaxis_title="净值",
            height=450,
            margin=dict(l=40, r=20, t=40, b=40),
            xaxis=dict(tickformat="%Y-%m", dtick="M1"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── 各策略明细 ──
        st.subheader("📋 各策略明细")
        for sname in strategy_names_list:
            report = reports[sname]
            if report.total_trades == 0:
                with st.expander(f"🔹 {sname} — 无交易"):
                    st.caption("未产生任何交易。")
                continue

            with st.expander(
                f"🔹 {sname} — {report.total_trades:.1f}笔 "
                f"胜率{report.win_rate:.1%} "
                f"收益{report.total_return_pct:+.2f}% "
                f"回撤{report.max_drawdown_pct:.2f}%"
            ):
                # Mini summary
                mc1, mc2, mc3, mc4 = st.columns(4)
                with mc1:
                    st.metric("交易数", report.total_trades,
                              delta=f"赢{report.win_trades}/亏{report.lose_trades}")
                with mc2:
                    st.metric("胜率", f"{report.win_rate:.1%}")
                with mc3:
                    st.metric("总收益", f"{report.total_return_pct:+.2f}%")
                with mc4:
                    st.metric("最大回撤", f"{report.max_drawdown_pct:.2f}%")

                # Trade detail table
                st.markdown("**交易明细**")
                if report.trades:
                    trade_rows = []
                    for t in sorted(report.trades, key=lambda x: x.date):
                        pnl_str = f"{t.pnl_pct:+.2f}%" if "卖出" in t.trade_type else ""
                        trade_rows.append({
                            "日期": t.date,
                            "股票": t.symbol_name,
                            "类型": t.trade_type,
                            "价格": f"{t.price:.2f}",
                            "盈亏": pnl_str,
                            "原因": t.reason,
                            "当前持仓": t.positions_after,
                        })
                    _render_html_table(trade_rows, col_widths={
                        "日期": "5em", "股票": "6em", "类型": "7em",
                        "价格": "4em", "盈亏": "4em",
                    })

                # Per-stock summary
                if report.stock_summaries:
                    st.markdown("**股票明细**")
                    for ss in report.stock_summaries:
                        # Skip stocks with zero activity at all
                        if ss.total_trades == 0 and ss.rejected_signals == 0:
                            continue

                        # Build expander label
                        if ss.total_trades > 0:
                            label = (
                                f"{'🟢' if ss.cumulative_pnl_pct >= 0 else '🔴'} "
                                f"{ss.symbol_name} — {ss.total_trades}笔 "
                                f"胜率{ss.win_rate:.1%} 累计{ss.cumulative_pnl_pct:+.2f}% ({ss.impact_pct:+.2f}%)"
                            )
                            if ss.rejected_signals > 0:
                                label += f"  ⚠️{ss.rejected_signals}次信号未成交"
                        else:
                            label = (
                                f"⚠️ {ss.symbol_name} — "
                                f"0笔成交, {ss.rejected_signals}次信号未成交"
                            )

                        with st.expander(label):
                            # Show all trades (buy/sell/rejected) for this stock
                            stock_trades = [t for t in report.trades if t.symbol == ss.symbol]
                            srows = []
                            for t in stock_trades:
                                pnl_str = f"{t.pnl_pct:+.2f}%" if "卖出" in t.trade_type else ""
                                srows.append({
                                    "日期": t.date,
                                    "类型": t.trade_type,
                                    "价格": f"{t.price:.2f}",
                                    "盈亏": pnl_str,
                                    "原因": t.reason,
                                })
                            _render_html_table(srows, col_widths={
                                "日期": "5em", "类型": "7em",
                                "价格": "4em", "盈亏": "4em",
                            })
