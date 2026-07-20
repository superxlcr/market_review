"""族群效应分析 — 对比 concept_n / concept_i / industry_l1 / industry_l2_l3 的集群胜率。

用法: .venv/Scripts/python scripts/analyze_cluster_effect.py [csv_path]
默认: .winrate_data/20260716_110303/回调一半严格.csv
"""
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

sys.stdout.reconfigure(encoding="utf-8")


@dataclass
class Signal:
    code: str
    name: str
    signal_date: str  # YYYYMMDD
    success: bool
    industry_l1: str
    industry_l2: str
    industry_l3: str
    concept_i: str      # pipe-separated
    concept_n: str      # pipe-separated

    def labels_i(self) -> List[str]:
        """I 型概念标签（同花顺行业），按 | 拆分"""
        return [t.strip() for t in self.concept_i.split("|") if t.strip()]

    def labels_n(self) -> List[str]:
        """N 型概念标签（同花顺概念），按 | 拆分"""
        return [t.strip() for t in self.concept_n.split("|") if t.strip()]


def load_signals(path: str) -> List[Signal]:
    signals = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            signals.append(Signal(
                code=row["code"],
                name=row["name"],
                signal_date=str(row.get("signal_date", "")).strip(),
                success=row.get("success", "").strip().lower() == "true",
                industry_l1=row.get("industry_l1", "").strip(),
                industry_l2=row.get("industry_l2", "").strip(),
                industry_l3=row.get("industry_l3", "").strip(),
                concept_i=row.get("concept_i", "").strip(),
                concept_n=row.get("concept_n", "").strip(),
            ))
    return signals


def count_peers(
    signals: List[Signal],
    label_fn,  # Signal -> List[str] (labels for this signal)
    window_days: int,
    min_peers: int,
) -> Tuple[int, int, int, int]:
    """返回 (clustered_win, clustered_total, solo_win, solo_total)

    对每个 signal，找所有同行 signals 中共享至少一个 label 且在 ±window_days 内的。
    """
    # 按日期索引：date -> list of (idx, signal)
    date_to_signals: Dict[str, List[Tuple[int, Signal]]] = defaultdict(list)
    for i, s in enumerate(signals):
        date_to_signals[s.signal_date].append((i, s))

    sorted_dates = sorted(date_to_signals.keys())

    # 为每个 signal 预计算 label 集合
    idx_labels: Dict[int, Set[str]] = {}
    for i, s in enumerate(signals):
        idx_labels[i] = set(label_fn(s))

    clustered_win = 0
    clustered_total = 0
    solo_win = 0
    solo_total = 0

    for i, s in enumerate(signals):
        my_labels = idx_labels[i]
        if not my_labels:
            continue

        my_date_idx = sorted_dates.index(s.signal_date)

        # 收集窗口内的所有 labels
        peer_count = 0
        seen_peers = set()  # 避免同 code 多日信号重复计数

        for offset in range(-window_days, window_days + 1):
            w_idx = my_date_idx + offset
            if 0 <= w_idx < len(sorted_dates):
                w_date = sorted_dates[w_idx]
                for peer_i, peer_s in date_to_signals[w_date]:
                    if peer_i == i:
                        continue
                    if peer_s.code in seen_peers:
                        continue
                    peer_labels = idx_labels[peer_i]
                    if my_labels & peer_labels:  # 有交集
                        peer_count += 1
                        seen_peers.add(peer_s.code)

        if peer_count >= min_peers:
            clustered_total += 1
            if s.success:
                clustered_win += 1
        else:
            solo_total += 1
            if s.success:
                solo_win += 1

    return clustered_win, clustered_total, solo_win, solo_total


def analyze(
    signals: List[Signal],
    name: str,
    label_fn,
):
    """对一种分类体系跑多组参数"""
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")

    windows = [1, 2, 3]
    thresholds = [2, 3, 4]

    for w in windows:
        for t in thresholds:
            cw, ct, sw, st = count_peers(signals, label_fn, w, t)
            if ct == 0 and st == 0:
                continue
            cwr = cw / ct * 100 if ct > 0 else 0
            swr = sw / st * 100 if st > 0 else 0
            diff = cwr - swr
            total = ct + st
            clustered_pct = ct / total * 100 if total > 0 else 0
            print(
                f"  +/-{w}d, >= {t}票 | "
                f"集群 WR={cwr:.1f}% ({ct}票, {clustered_pct:.0f}%) | "
                f"孤狼 WR={swr:.1f}% ({st}票) | "
                f"差值 {diff:+.1f}pp"
            )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ".winrate_data/20260716_110303/回调一半严格.csv"
    print(f"Loading: {path}")
    signals = load_signals(path)
    print(f"Total signals: {len(signals)}")
    total_win = sum(1 for s in signals if s.success)
    print(f"Overall WR: {total_win}/{len(signals)} = {total_win/len(signals)*100:.1f}%")

    # 检查数据完整性
    has_l3 = sum(1 for s in signals if s.industry_l3)
    has_i = sum(1 for s in signals if s.concept_i)
    has_n = sum(1 for s in signals if s.concept_n)
    print(f"Has L3: {has_l3}/{len(signals)}, Has concept_i: {has_i}/{len(signals)}, Has concept_n: {has_n}/{len(signals)}")

    # === 4 种分类体系 ===

    # 1. N 型概念标签
    analyze(signals, "N 型概念标签 (concept_n, |分隔)", lambda s: s.labels_n())

    # 2. I 型行业标签
    analyze(signals, "I 型行业标签 (concept_i, |分隔)", lambda s: s.labels_i())

    # 3. 申万 L1
    analyze(signals, "申万 L1 行业", lambda s: [s.industry_l1] if s.industry_l1 else [])

    # 4. 申万 L2
    analyze(signals, "申万 L2 行业", lambda s: [s.industry_l2] if s.industry_l2 else [])

    # 5. 申万 L3
    analyze(signals, "申万 L3 行业", lambda s: [s.industry_l3] if s.industry_l3 else [])

    # === 组合：concept_n + concept_i ===
    analyze(signals, "组合: N+I 型标签", lambda s: s.labels_n() + s.labels_i())


if __name__ == "__main__":
    main()
