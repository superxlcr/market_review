"""汇总每个买点的统计；按买点分开导出带配置的明细。"""
from __future__ import annotations
import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime
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
                   if t.exit_reason in ("收盘止损", "时间止损") and t.pnl_pct < 0)
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
    "buy_point", "reason", "code", "name", "signal_date", "entry_date", "entry_price",
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


def save_run(trades: list[TradeResult], cfg: WinrateConfig,
             base_dir: str | Path = ".winrate_data") -> str:
    """把一次扫描结果落盘：base_dir/<时间戳>/ 下每买点一个 CSV + 配置快照。

    CSV 为干净表头+数据（无 # 注释），供 scripts/winrate_analysis.py 直接读。
    配置快照记录实际生效的 cfg（含页面上改过的值），服务"改配置看效果"的历史对比。
    返回 run 目录路径。
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(base_dir) / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    for bp in cfg.buy_points:
        rows = export_rows(trades, bp)
        if not rows:
            continue  # 无触发的买点不建空文件
        with open(run_dir / f"{bp}.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_EXPORT_FIELDS)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in _EXPORT_FIELDS})

    with open(run_dir / "config_snapshot.txt", "w", encoding="utf-8") as f:
        f.write(f"# winrate run {ts}\n")
        for k, v in asdict(cfg).items():
            f.write(f"{k}={v}\n")

    return str(run_dir)
