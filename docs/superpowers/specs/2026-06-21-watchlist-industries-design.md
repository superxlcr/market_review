# 自选行业 — 设计文档

> 日期：2026-06-21
> 状态：待实现

## 1. 概述

在板块分析页（`02_板块分析.py`）新增 ⭐ 自选行业区块。用户通过配置文件指定关注的行业名称，系统自动匹配 SW2021 全量分类（~511 个，不限 63 个展示行业），在控制台初始化时拉取日线数据，板块分析页独立展示。

---

## 2. 配置文件

### 2.1 路径与格式

- **配置文件：** `config/watchlist_industries.txt`（Git 忽略，不追踪）
- **示例文件：** `config/watchlist_industries.example.txt`（Git 追踪，含注释说明）
- **格式：** 纯文本，每行一个行业名称，`#` 开头为注释行

```
# 自选行业列表 — 板块分析页 ⭐ 自选区块
# 名称匹配 SW2021 行业分类，支持 L1/L2/L3 任意层级
# 修改后下次控制台应用日期时生效
半导体
光伏设备
白酒
```

### 2.2 匹配规则

- 读取所有非空、非 `#` 注释行，`strip()` 后得到名称列表
- 在 `industry_classify` 表中精确匹配（`WHERE industry_name = ?`）
- 匹配成功 → 解析出 `industry_code`、`level`
- 匹配失败 → 控制台输出警告日志，跳过

### 2.3 示例文件内容

```txt
# 自选行业列表示例
# 使用方法：
#   1. 复制本文件为 watchlist_industries.txt
#   2. 删除不需要的行业，添加你想关注的行业
#   3. 名称需与申万 SW2021 行业分类完全一致
#
# 提示：可在控制台的「行业分类规则」展开栏查看完整行业列表
# 或查询数据库：SELECT industry_name, level FROM industry_classify ORDER BY level, industry_name;
```

### 2.4 Git 配置

- `.gitignore` 新增 `config/watchlist_industries.txt`
- `config/watchlist_industries.example.txt` 正常追踪

---

## 3. 数据初始化（控制台）

### 3.1 文件位置

`dashboard/pages/00_控制台.py` — 在行业分类规则 expander 下方新增。

### 3.2 加载时机

在数据加载阶段（`_ensure_industry_daily()` 之后），读取配置文件并拉取自选行业的日线数据。

流程：
```
1. 读取 config/watchlist_industries.txt
2. 解析行业名称列表
3. 在 industry_classify 表精确匹配 → (code, name, level)
4. 对匹配成功的行业，调用 _ensure_industry_daily(code) 拉取日线数据
5. 匹配失败的名称 → logger.warning
```

### 3.3 控制台 UI

在「行业分类规则」expander 下方新增「⭐ 自选行业」expander：

```
┌─ ⭐ 自选行业 ────────────────────────┐
│ 配置文件：config/watchlist_industries.txt │
│                                       │
│ #  行业名称      Level  Code       状态 │
│ 1  半导体        L2     SWXXX...   ✅  │
│ 2  光伏设备      L3     SWXXX...   ✅  │
│ 3  白酒          L2     SWXXX...   ✅  │
│                                       │
│ （后续将支持自选个股）               │
└───────────────────────────────────────┘
```

---

## 4. 板块分析页 UI

### 4.1 页面布局

从上到下：

```
1. AI 行业总结导语 (st.info)
2. 🔥 TOP5 / ❄️ BOTTOM5 排名卡片
3. ⭐ 自选行业（新增）
4. 🔍 行业详细分析（去重：排除已在自选区的行业）
```

### 4.2 自选区块 UI

完全复刻「行业详细分析」的 expander 样式：

- **上榜理由：** 统一标注 `⭐ 自选`
- **排序：** 按当日涨跌幅降序排列
- **展开内容：** 复用 `render_ohlcv_section()` 渲染完整技术分析
- **空状态：** 若配置文件为空或无匹配 → 显示 "暂无自选行业，请在 config/watchlist_industries.txt 中配置"

### 4.3 去重规则

自选行业优先展示。若某行业同时属于自选和分析集（TOP5 / BOTTOM5 / 频繁领涨）：

- **自选区展示**（带 `⭐ 自选` 标签）
- **分析集跳过**该行业

去重在 `get_industry_analysis_set()` 返回后、渲染前处理，不修改 service 层逻辑。

---

## 5. Service 层变更

### 5.1 DashboardService 新增方法

```python
def get_watchlist_industries(self) -> list[dict]:
    """读取配置文件，返回匹配成功的自选行业列表。
    
    Returns:
        list[dict]: [{"code": "SWxxx", "name": "半导体", "level": "L2"}, ...]
    """

def get_watchlist_industry_daily(
    self, code: str, end_date: str, lookback: int
) -> pd.DataFrame:
    """获取自选行业的日线数据。代理到 DataProvider.get_industry_daily()。"""
```

### 5.2 DataProvider 新增方法

```python
def ensure_watchlist_industry_data(self, codes: list[str], end_date: str):
    """确保自选行业的日线数据已缓存。对未缓存的行业调用 _ensure_industry_daily()。"""
```

---

## 6. 涉及文件清单

| 文件 | 变更 |
|------|------|
| `config/watchlist_industries.example.txt` | 新增 — 示例配置文件 |
| `config/watchlist_industries.txt` | 新增 — 用户实际配置（Git 忽略） |
| `.gitignore` | 修改 — 新增 `config/watchlist_industries.txt` |
| `dashboard/pages/00_控制台.py` | 修改 — 新增自选行业数据加载 + UI 信息块 |
| `dashboard/pages/02_板块分析.py` | 修改 — 新增自选区块渲染 + 分析集去重 |
| `dashboard/services/dashboard_service.py` | 修改 — 新增自选相关方法 |
| `src/marketreview/data/data_provider.py` | 修改 — 新增批量确保数据方法 |

---

## 7. 扩展预留

- 自选个股用独立配置文件 `config/watchlist_stocks.txt`，与行业分离
- `03_个股追踪.py` 目前是占位页，后续对接自选个股配置
