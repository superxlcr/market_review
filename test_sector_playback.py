"""
自测板块资金回放逻辑（DB 直读，无需 API / 无需 Streamlit）。
用法：.venv/Scripts/python test_sector_playback.py
"""
import sys, os, json, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from marketreview.data.cache_manager import CacheManager

TRADE_DATE = "20260804"
SECTOR_TYPE = "概念"  # or "行业"
SPEED = "2x"
SPEED_MAP = {"1x": 1, "2x": 2, "4x": 4}

def main():
    cm = CacheManager()

    # ── 1. 从 DB 加载数据 ──
    raw = cm.get_sector_flow(TRADE_DATE, SECTOR_TYPE)
    if not raw:
        print(f"❌ DB 无数据: {TRADE_DATE} {SECTOR_TYPE}")
        return
    data = json.loads(raw)
    series = data["series"]
    print(f"✅ 从 DB 加载: {len(series)} 条曲线")

    # ── 2. 展开所有时间点 ──
    all_times = sorted(set(t for _, pts, _ in series for t, _ in pts))
    max_idx = len(all_times) - 1
    print(f"   时间点: {all_times[0]} → {all_times[-1]}, 共 {len(all_times)} 个")

    # ── 3. 模拟播放 ──
    step = SPEED_MAP.get(SPEED, 1)
    print(f"\n── 模拟播放 (step={step}) ──")

    sf_slider = 0  # 模拟 st.session_state.sf_slider
    playing = True

    frames = []
    while playing:
        # 推进 (Streamlit 中在 widget 渲染前)
        if playing:
            sf_slider += step
            if sf_slider >= max_idx:
                playing = False
                sf_slider = max_idx

        current_time = all_times[sf_slider]

        # 每条曲线截断到 current_time
        visible = []
        for name, pts, final in series:
            truncated = [(t, v) for t, v in pts if t <= current_time]
            if truncated:
                visible.append((name, truncated[-1][1]))  # (name, current_val)

        frames.append({
            "idx": sf_slider,
            "time": current_time,
            "top3": visible[:3],
        })

        if len(frames) <= 10 or sf_slider >= max_idx - 3:
            top_str = " | ".join(f"{n} {v:+.1f}亿" for n, v in visible[:3])
            print(f"  [{sf_slider:3d}/{max_idx}] {current_time}  TOP3: {top_str}")

    print(f"\n📊 共 {len(frames)} 帧")
    print(f"   首帧: {frames[0]['time']} (idx={frames[0]['idx']})")
    print(f"   末帧: {frames[-1]['time']} (idx={frames[-1]['idx']})")

    # ── 4. 验证图表截断逻辑 ──
    print(f"\n── 验证截断逻辑 ──")
    # 检查几个关键时间点的截断
    check_times = [all_times[0], all_times[len(all_times)//2], all_times[-1]]
    for ct in check_times:
        count = 0
        for name, pts, final in series:
            truncated = [(t, v) for t, v in pts if t <= ct]
            if truncated:
                count += 1
        print(f"  {ct}: {count}/{len(series)} 条曲线有数据")

    # ── 5. 验证进度 ──
    unique_indices = set(f["idx"] for f in frames)
    print(f"\n   idx 范围: {min(unique_indices)} → {max(unique_indices)}, "
          f"唯一值 {len(unique_indices)} 个 (step={step})")
    if len(unique_indices) < 2:
        print("   ⚠️ idx 没有前进！")
    else:
        print("   ✅ idx 正常递增")

    print("\n✅ 自测完成 — 逻辑层正常，问题可能在 Streamlit widget 层")


if __name__ == "__main__":
    main()
