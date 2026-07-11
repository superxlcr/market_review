"""汇总每个买点的统计；按买点分开导出带配置的明细。"""
from __future__ import annotations
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import WinrateConfig
from .trade_sim import TradeResult


@dataclass
class BuyPointStats:
    buy_point: str
    n: int
    win_rate: float
    big_win_n: int
    small_win_n: int
    stop_n: int
    loss_n: int
    avg_hold_days: float
    expectancy_pct: float


def aggregate(trades: list[TradeResult]) -> dict[str, BuyPointStats]:
    groups: dict[str, list[TradeResult]] = {}
    for t in trades:
        groups.setdefault(t.buy_point, []).append(t)

    out: dict[str, BuyPointStats] = {}
    for bp, ts in groups.items():
        n = len(ts)
        big = sum(1 for t in ts if t.exit_reason == "大胜利")
        small = sum(1 for t in ts if t.exit_reason == "小胜利")
        stop = sum(1 for t in ts if t.exit_reason == "盘中止损")
        loss = sum(1 for t in ts
                   if t.exit_reason in ("收盘止损", "时间止损", "回测结束") and t.pnl_pct < 0)
        wins = sum(1 for t in ts if t.success)
        out[bp] = BuyPointStats(
            buy_point=bp, n=n,
            win_rate=(wins / n) if n else 0.0,
            big_win_n=big, small_win_n=small, stop_n=stop, loss_n=loss,
            avg_hold_days=(sum(t.hold_days for t in ts) / n) if n else 0.0,
            expectancy_pct=(sum(t.pnl_pct for t in ts) / n) if n else 0.0,
        )
    return out


_EXPORT_FIELDS = [
    "buy_point", "code", "name", "signal_date", "entry_date", "entry_price",
    "exit_date", "exit_price", "exit_reason", "mfp_pct", "hold_days", "pnl_pct",
    "success", "short_ma_state", "long_ma_state", "market_cap_yi", "cap_bucket",
    "industry_l1", "industry_l2",
]


def export_rows(trades: list[TradeResult], buy_point: str) -> list[dict]:
    rows = [asdict(t) for t in trades if t.buy_point == buy_point]
    rows.sort(key=lambda r: (r["code"], r["signal_date"]))
    return rows


def export_csv(trades: list[TradeResult], cfg: WinrateConfig,
               buy_point: str, path: str | Path) -> None:
    rows = export_rows(trades, buy_point)
    path = Path(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(f"# winrate export | buy_point={buy_point}\n")
        f.write("# config=" + json.dumps(asdict(cfg), ensure_ascii=False) + "\n")
        writer = csv.DictWriter(f, fieldnames=_EXPORT_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in _EXPORT_FIELDS})
