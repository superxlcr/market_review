"""Compute statistics from trade records."""
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
    avg_hold_days: float = 0.0
    profit_loss_ratio: float = 0.0


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


def build_report(trades: list[TradeRecord],
                 equity_curve: list[dict]) -> Report:
    """Build a Report from trade records and equity curve."""
    report = Report(trades=trades, equity_curve=equity_curve)

    # Filter completed sell trades
    completed = [t for t in trades if t.trade_type == "卖出"]
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
        if t.trade_type == "买入":
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
        sym_completed = [t for t in sym_trades if t.trade_type == "卖出"]
        sym_wins = sum(1 for t in sym_completed if t.pnl_pct > 0)
        sym_loss = sum(1 for t in sym_completed if t.pnl_pct <= 0)
        sym_total = len(sym_completed)

        sum_win = sum(t.pnl_pct for t in sym_completed if t.pnl_pct > 0)
        sum_lose = sum(abs(t.pnl_pct) for t in sym_completed if t.pnl_pct <= 0)
        avg_win = sum_win / sym_wins if sym_wins > 0 else 0.0
        avg_lose = sum_lose / sym_loss if sym_loss > 0 else 0.0

        report.stock_summaries.append(StockSummary(
            symbol_name=sym_trades[0].symbol_name if sym_trades else "",
            symbol=symbol,
            total_trades=sym_total,
            win_trades=sym_wins,
            lose_trades=sym_loss,
            win_rate=sym_wins / sym_total if sym_total > 0 else 0.0,
            cumulative_pnl_pct=sum(t.pnl_pct for t in sym_completed),
            avg_hold_days=0.0,
            profit_loss_ratio=avg_win / avg_lose if avg_lose > 0 else 0.0,
        ))

    return report


def _date_to_int(d: str) -> int:
    """Convert YYYYMMDD or YYYY-MM-DD to int."""
    return int(d.replace("-", ""))
