"""东方财富板块资金流数据抓取。

实时盘中数据，无 SQLite 缓存 — 用 st.cache_data(ttl=60) 短期缓存。
逻辑抄自 .temp/sector_flow_dashboard.html。
"""

import requests
import time as _time
from datetime import datetime

# ── API base ──
_HOST = "https://push2delay.eastmoney.com"

# ── fs 参数 ──
FS_INDUSTRY = "m:90+t:2"   # 行业板块
FS_CONCEPT  = "m:90+t:3"   # 概念板块

# ── 篮子/统计概念过滤 (与 HTML BLOCK 数组同步) ──
BASKET_KEYWORDS = [
    "融资融券","富时","罗素","MSCI","标普","道琼斯","股通","北向","北上",
    "大盘","中盘","小盘","沪深300","上证50","上证180","中证","创业板综","科创板","AH股",
    "含H股","含B股","含可转债","重仓","预盈","预增","预减","预亏","高送转","破净","国企改革",
    "央企","标准普尔","权重","深成","HS300","沪深","深证","上证","全指","成份","成分",
    "百元股","热股","振幅","昨日","涨停","跌停","连板","近端次新","次新股","龙头","白马股","蓝筹",
    "风格","趋势股","茅指数","组合","微盘","ST股","低价","举牌","红利","扭亏","季报","年报","中报",
]

# ── 行业白名单 (东财自有行业，与 HTML SW2 Set 同步) ──
INDUSTRY_WHITELIST = {
    "IT服务Ⅱ","一般零售","专业工程","专业服务","专业连锁Ⅱ","专用设备","个护用品","中药Ⅱ",
    "乘用车","互联网电商","休闲食品","体育Ⅱ","保险Ⅱ","元件","光学光电子","其他家电Ⅱ",
    "其他电子Ⅱ","养殖业","军工电子Ⅱ","农业综合Ⅱ","农产品加工","农化制品","冶钢原料",
    "出版","动物保健Ⅱ","包装印刷","化妆品","化学制品","化学制药","化学原料","化学纤维",
    "医疗器械","医疗服务","医疗美容","医药商业","半导体","厨卫电器","商用车","地面兵装Ⅱ",
    "基础建设","塑料","多元金融","家居用品","家电零部件Ⅱ","小家电","工程咨询服务Ⅱ",
    "工程机械","广告营销","影视院线","房地产开发","房地产服务","房屋建设Ⅱ","摩托车及其他",
    "教育","数字媒体","旅游及景区","旅游零售Ⅱ","普钢","服装家纺","林业Ⅱ","橡胶","水泥",
    "汽车服务","汽车零部件","油服工程","油气开采Ⅱ","消费电子","渔业","游戏Ⅱ","炼化及贸易",
    "焦炭Ⅱ","煤炭开采","照明设备Ⅱ","燃气Ⅱ","物流","特钢Ⅱ","环保设备Ⅱ","环境治理",
    "玻璃玻纤","生物制品","电力","电子化学品Ⅱ","电视广播Ⅱ","白色家电","白酒Ⅱ","种植业",
    "纺织制造","综合Ⅱ","自动化设备","航天装备Ⅱ","航海装备Ⅱ","航空机场","航空装备Ⅱ",
    "航运港口","装修建材","装修装饰Ⅱ","计算机设备","证券Ⅱ","调味发酵品Ⅱ","贸易Ⅱ",
    "轨交设备Ⅱ","软件开发","通信服务","通信设备","通用设备","造纸","酒店餐饮","铁路公路",
    "非白酒","非金属材料Ⅱ","食品加工","饮料乳品","饰品","饲料","黑色家电",
    "电力设备","有色金属","机器人","银行",
}


# ──────────────────────────────────────────────
#  API 抓取
# ──────────────────────────────────────────────

def fetch_sector_list(industry: bool = False, timeout: float = 15.0) -> list[dict]:
    """拉取板块列表，按主力净流入排序。

    概念: fs=m:90+t:3, 行业: fs=m:90+t:2
    返回: [{code, name, flow_yi}, ...] 按 flow_yi 降序
    """
    fs = FS_INDUSTRY if industry else FS_CONCEPT
    merged: dict[str, dict] = {}
    for pn in range(1, 9):
        url = (f"{_HOST}/api/qt/clist/get?fid=f62&po=1&pz=100&pn={pn}"
               f"&np=1&fltt=2&invt=2&fs={fs}&fields=f12,f14,f62")
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            break
        for item in diff:
            code = item.get("f12")
            if code and str(code) not in merged:
                merged[str(code)] = {
                    "code": str(code),
                    "name": str(item.get("f14", "")),
                    "flow_yi": float(item.get("f62", 0)) / 1e8,
                }
        if len(diff) < 100:
            break
    return sorted(merged.values(), key=lambda x: x["flow_yi"], reverse=True)


def fetch_intraday_flow(code: str, timeout: float = 15.0) -> list[tuple[str, float]]:
    """拉取单板块 1 分钟分时主力资金流曲线。

    secid=90.{code}, klt=1
    返回: [("09:30", 1.23), ("09:31", 1.45), ...] 累计净流入(亿)
    """
    url = (f"{_HOST}/api/qt/stock/fflow/kline/get?lmt=0&klt=1"
           f"&secid=90.{code}"
           f"&fields1=f1,f2,f3,f7"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65")
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    klines = (data.get("data") or {}).get("klines") or []
    result = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        ts = parts[0]
        hhmm = ts.split(" ")[-1][:5] if " " in ts else ts[:5]
        try:
            val = float(parts[1])
            result.append((hhmm, round(val / 1e8, 4)))
        except (ValueError, TypeError):
            pass
    return result


# ──────────────────────────────────────────────
#  过滤
# ──────────────────────────────────────────────

def _is_basket(name: str) -> bool:
    return any(kw in name for kw in BASKET_KEYWORDS)


def _clean_name(name: str, industry: bool = False) -> str:
    if industry:
        return name.rstrip("ⅡⅢ")
    return name


def filter_sectors(sectors: list[dict], industry: bool = False,
                   blocked_names: set[str] | None = None) -> list[dict]:
    """过滤板块列表。概念用黑名单，行业用白名单，再剔用户屏蔽。"""
    blocked = blocked_names or set()
    result = []
    for s in sectors:
        name = s["name"]
        display_name = _clean_name(name, industry)
        if display_name in blocked:
            continue
        if industry:
            if name not in INDUSTRY_WHITELIST:
                continue
        elif _is_basket(name):
            continue
        s["display_name"] = display_name
        result.append(s)
    return result


# ──────────────────────────────────────────────
#  异动检测
# ──────────────────────────────────────────────

def detect_anomalies(
    current: dict[str, tuple[str, float]],   # code -> (name, flow_yi)
    previous: dict[str, tuple[str, float]],
    top_n: int = 3,
    floor_yi: float = 2.0,
) -> tuple[list[tuple], list[tuple]]:
    """对比当前与之前快照，检测急流入/急流出。

    返回 (inflows, outflows) 各为 [(name, delta_yi, current_yi), ...]
    """
    deltas = []
    for code, (cname, cur_val) in current.items():
        if code in previous:
            pname, prev_val = previous[code]
            delta = cur_val - prev_val
            if abs(delta) >= floor_yi:
                deltas.append((cname, delta, cur_val))

    inflows = [(n, d, v) for n, d, v in deltas if d >= floor_yi]
    outflows = [(n, -d, v) for n, d, v in deltas if d <= -floor_yi]
    inflows.sort(key=lambda x: x[1], reverse=True)
    outflows.sort(key=lambda x: x[1], reverse=True)  # 正数排序
    return inflows[:top_n], outflows[:top_n]


# ──────────────────────────────────────────────
#  主入口
# ──────────────────────────────────────────────

def fetch_all(industry: bool = False, top_n: int = 8,
              blocked_names: set[str] | None = None) -> dict:
    """主入口：拉板块列表 → 过滤 → 选 TOP/BOTTOM → 拉分时 → 汇总。

    返回:
      sectors:   全量过滤后列表 [{code, name, display_name, flow_yi}]
      series:    [(display_name, [(HH:MM, flow_yi), ...], final_yi), ...] 按 final 降序
      snapshot:  {code: (display_name, flow_yi)}  当前时刻快照
      last_time: 最新数据时间 HH:MM
      kind:      "概念" | "行业"
    """
    t0 = _time.perf_counter()
    sectors = fetch_sector_list(industry=industry)
    filtered = filter_sectors(sectors, industry=industry, blocked_names=blocked_names)

    # Top N inflow + bottom N outflow
    top_in = filtered[:top_n]
    bottom_out = filtered[-top_n:] if len(filtered) >= top_n else []
    seen: set[str] = set()
    selected = []
    for s in top_in + bottom_out:
        if s["code"] not in seen:
            seen.add(s["code"])
            selected.append(s)

    # 拉分时曲线
    selected_series = []
    for s in selected:
        try:
            raw = fetch_intraday_flow(s["code"])
            if raw:
                final = raw[-1][1]
                selected_series.append((s["display_name"], raw, final))
        except Exception:
            pass

    selected_series.sort(key=lambda x: x[2], reverse=True)

    last_time = ""
    if selected_series and selected_series[0][1]:
        last_time = selected_series[0][1][-1][0]

    snapshot = {s["code"]: (s["display_name"], s["flow_yi"]) for s in filtered}

    elapsed = _time.perf_counter() - t0
    return {
        "sectors": filtered,
        "series": selected_series,
        "snapshot": snapshot,
        "last_time": last_time,
        "kind": "行业" if industry else "概念",
        "elapsed": round(elapsed, 2),
    }


# ──────────────────────────────────────────────
#  关键时间点快照 (md 导出用)
# ──────────────────────────────────────────────

_KEY_MOMENTS = ["09:35", "10:00", "10:30", "11:00", "11:30",
                "13:05", "13:30", "14:00", "14:30", "14:57"]

def get_key_snapshots(series: list, all_times: list[str] | None = None) -> list[dict]:
    """返回关键时刻各板块累计净流入快照。

    返回: [{time: "09:35", ranking: [{name, flow_yi}, ...]}, ...]
    """
    if not series:
        return []

    # 找出每个关键时刻最接近的数据点
    snapshots = []
    for moment in _KEY_MOMENTS:
        ranking = []
        for name, pts, _ in series:
            # 找 <= moment 的最大时间点
            best = None
            for t, v in pts:
                if t <= moment:
                    best = (name, v)
            if best is not None:
                ranking.append({"name": best[0], "flow_yi": best[1]})
        ranking.sort(key=lambda x: x["flow_yi"], reverse=True)
        if ranking:
            snapshots.append({"time": moment, "ranking": ranking})
    return snapshots


def generate_flow_md(data: dict) -> str:
    """生成板块资金流 markdown 片段（供 journal data.md 使用）。"""
    series = data["series"]
    if not series:
        return ""

    snapshots = get_key_snapshots(series)
    if not snapshots:
        return ""

    kind = data["kind"]
    lines = [f"## 板块资金流（{kind} · 主力净流入）\n"]

    # 选取 4 个关键快照：开盘后、午前、午后、收盘
    pick_keys = {"09:35": "开盘后", "10:30": "早盘", "11:30": "午前",
                 "14:00": "午后", "14:57": "收盘"}
    for snap in snapshots:
        label = pick_keys.get(snap["time"])
        if not label:
            continue
        lines.append(f"### {label}（{snap['time']}）\n")
        lines.append("| 排名 | 板块 | 累计净流入 |")
        lines.append("|------|------|-----------|")
        for i, r in enumerate(snap["ranking"][:5], 1):
            sign = "+" if r["flow_yi"] >= 0 else ""
            lines.append(f"| {i} | {r['name']} | {sign}{r['flow_yi']:.1f}亿 |")
        lines.append("")

    # 最终排名 TOP5 + BOTTOM5
    lines.append("### 收盘排名\n")
    lines.append("**TOP 5 流入**\n")
    lines.append("| 排名 | 板块 | 累计净流入 |")
    lines.append("|------|------|-----------|")
    for i, (name, _, final) in enumerate(series[:5], 1):
        lines.append(f"| {i} | {name} | +{final:.1f}亿 |")

    lines.append("\n**BOTTOM 5 流出**\n")
    lines.append("| 排名 | 板块 | 累计净流入 |")
    lines.append("|------|------|-----------|")
    for i, (name, _, final) in enumerate(series[-5:], 1):
        lines.append(f"| {i} | {name} | {final:.1f}亿 |")

    return "\n".join(lines)
