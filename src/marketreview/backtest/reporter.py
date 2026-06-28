"""Compute statistics from trade records."""
from collections import defaultdict
from dataclasses import dataclass, field
from .broker import TradeRecord


@dataclass
class StockSummary:
    """Per-stock trade statistics."""
    symbol_name: str
    symbol: str
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0.0
    cumulative_pnl_pct: float = 0.0
    impact_pct: float = 0.0          # 对总净值的贡献 (profit / 1M)
    avg_hold_days: float = 0.0
    profit_loss_ratio: float = 0.0
    rejected_signals: int = 0
    rejection_reasons: list = field(default_factory=list)


@dataclass
class Report:
    """Full backtest report."""
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_days: float = 0.0
    avg_win_pct: float = 0.0
    avg_lose_pct: float = 0.0
    profit_loss_ratio: float = 0.0
    stock_summaries: list[StockSummary] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    individual_equity_curves: list[list[dict]] = field(default_factory=list)
    num_rounds: int = 1


def build_report(trades: list[TradeRecord],
                 equity_curve: list[dict]) -> Report:
    """Build a Report from trade records and equity curve."""
    report = Report(trades=trades, equity_curve=equity_curve)

    # Filter completed sell trades (include addon sells)
    completed = [t for t in trades if t.trade_type in ("卖出", "加仓卖出")]
    report.total_trades = len(completed)
    report.win_trades = sum(1 for t in completed if t.pnl_pct > 0)
    report.lose_trades = sum(1 for t in completed if t.pnl_pct <= 0)
    report.win_rate = report.win_trades / report.total_trades \
        if report.total_trades > 0 else 0.0

    # Aggregate PnL
    wins = [t for t in completed if t.pnl_pct > 0]
    losses = [t for t in completed if t.pnl_pct <= 0]
    report.avg_win_pct = sum(t.pnl_pct for t in wins) / len(wins) \
        if wins else 0.0
    report.avg_lose_pct = sum(abs(t.pnl_pct) for t in losses) / len(losses) \
        if losses else 0.0
    report.profit_loss_ratio = report.avg_win_pct / report.avg_lose_pct \
        if report.avg_lose_pct > 0 else 0.0

    # Total return from equity curve
    if equity_curve:
        report.total_return_pct = equity_curve[-1]["return_pct"]
        # Max drawdown
        peak = 0.0
        max_dd = 0.0
        for pt in equity_curve:
            if pt["equity"] > peak:
                peak = pt["equity"]
            dd = (peak - pt["equity"]) / peak * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        report.max_drawdown_pct = max_dd

    # Average hold days — match buy/sell pairs (calendar days approximation)
    buys_by_symbol: dict[str, list[TradeRecord]] = {}
    for t in trades:
        if t.trade_type in ("买入", "开盘买入", "盘中买入", "加仓买入"):
            buys_by_symbol.setdefault(t.symbol, []).append(t)
    hold_days_list = []
    for t in completed:
        symbol_buys = buys_by_symbol.get(t.symbol, [])
        for i, b in enumerate(symbol_buys):
            if b.date <= t.date:
                d1 = _date_to_int(b.date)
                d2 = _date_to_int(t.date)
                hold_days_list.append(max(1, int((d2 - d1) * 0.7)))  # ~70% calendar→trading
                symbol_buys.pop(i)
                break
    report.avg_hold_days = sum(hold_days_list) / len(hold_days_list) \
        if hold_days_list else 0.0

    # Per-stock summaries
    stock_map: dict[str, list[TradeRecord]] = {}
    for t in trades:
        stock_map.setdefault(t.symbol, []).append(t)

    for symbol, sym_trades in stock_map.items():
        sym_completed = [t for t in sym_trades if t.trade_type in ("卖出", "加仓卖出")]
        sym_rejected = [t for t in sym_trades if t.trade_type == "信号未成交"]
        sym_wins = sum(1 for t in sym_completed if t.pnl_pct > 0)
        sym_loss = sum(1 for t in sym_completed if t.pnl_pct <= 0)
        sym_total = len(sym_completed)

        sum_win = sum(t.pnl_pct for t in sym_completed if t.pnl_pct > 0)
        sum_lose = sum(abs(t.pnl_pct) for t in sym_completed if t.pnl_pct <= 0)
        avg_win = sum_win / sym_wins if sym_wins > 0 else 0.0
        avg_lose = sum_lose / sym_loss if sym_loss > 0 else 0.0

        # Dollar-weighted cumulative return (not simple sum of %)
        total_cost = 0.0
        total_profit = 0.0
        for t in sym_completed:
            if t.shares > 0 and t.price > 0:
                buy_price = t.price / (1.0 + t.pnl_pct / 100.0)
                cost_basis = t.shares * buy_price
                total_cost += cost_basis
                total_profit += t.shares * t.price - cost_basis
        cumulative = total_profit / total_cost * 100.0 if total_cost > 0 else 0.0

        report.stock_summaries.append(StockSummary(
            symbol_name=sym_trades[0].symbol_name if sym_trades else "",
            symbol=symbol,
            total_trades=sym_total,
            win_trades=sym_wins,
            lose_trades=sym_loss,
            win_rate=sym_wins / sym_total if sym_total > 0 else 0.0,
            cumulative_pnl_pct=cumulative,
            impact_pct=total_profit / 1_000_000 * 100.0,
            avg_hold_days=0.0,
            profit_loss_ratio=avg_win / avg_lose if avg_lose > 0 else 0.0,
            rejected_signals=len(sym_rejected),
            rejection_reasons=[t.reason for t in sym_rejected],
        ))

    return report


def merge_reports(reports: list[Report]) -> Report:
    """Merge multiple backtest reports into one with averaged metrics."""
    n = len(reports)
    if n == 0:
        return Report()
    if n == 1:
        r = reports[0]
        r.individual_equity_curves = [r.equity_curve]
        r.num_rounds = 1
        return r

    merged = Report(
        trades=[],
        num_rounds=n,
        individual_equity_curves=[r.equity_curve for r in reports],
    )

    # ── Simple averages ──
    merged.total_trades = sum(r.total_trades for r in reports) / n
    merged.win_trades = sum(r.win_trades for r in reports) / n
    merged.lose_trades = sum(r.lose_trades for r in reports) / n
    merged.win_rate = sum(r.win_rate for r in reports) / n
    merged.total_return_pct = sum(r.total_return_pct for r in reports) / n
    merged.max_drawdown_pct = sum(r.max_drawdown_pct for r in reports) / n
    merged.avg_hold_days = sum(r.avg_hold_days for r in reports) / n
    merged.avg_win_pct = sum(r.avg_win_pct for r in reports) / n
    merged.avg_lose_pct = sum(r.avg_lose_pct for r in reports) / n
    merged.profit_loss_ratio = sum(r.profit_loss_ratio for r in reports) / n

    # ── Equity curve: average by date ──
    date_map: dict[str, list[dict]] = defaultdict(list)
    for r in reports:
        for pt in r.equity_curve:
            date_map[pt["date"]].append(pt)

    for date in sorted(date_map.keys()):
        pts = date_map[date]
        merged.equity_curve.append({
            "date": date,
            "equity": sum(p["equity"] for p in pts) / len(pts),
            "return_pct": sum(p["return_pct"] for p in pts) / len(pts),
        })

    # ── Trades & stock summaries: use median round (closest to avg return) ──
    avg_return = merged.total_return_pct
    median_round = min(reports, key=lambda r: abs(r.total_return_pct - avg_return))
    merged.trades = list(median_round.trades)
    merged.stock_summaries = list(median_round.stock_summaries)

    return merged


def _date_to_int(d: str) -> int:
    """Convert YYYYMMDD or YYYY-MM-DD to int."""
    return int(d.replace("-", ""))
