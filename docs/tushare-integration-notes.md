# Tushare 数据集成踩坑记录

> 记录 Agent 1 开发过程中 Tushare 数据集成的所有问题和解决方案，供后续 Agent 开发参考。

---

## 1. 架构决策

**数据源：Tushare Pro**（单一源，避免多源数据不一致）

数据流：
```
Agent Tool → DataProvider.get_daily()
  → CacheManager.get_daily()  [SQLite 缓存]
  → 缓存不足 → ts.pro_bar()  [Tushare API]
  → 写入缓存 → 返回数据
```

关键文件：
- [data_provider.py](../src/marketreview/data/data_provider.py) — 抽象数据接口
- [cache_manager.py](../src/marketreview/data/cache_manager.py) — SQLite 缓存

---

## 2. API 端点选择

### 踩坑：`pro_api().daily()` 不返回指数数据

```python
# ❌ 对指数代码返回空 DataFrame
api = ts.pro_api()
df = api.daily(ts_code='000001.SH', ...)  # 0 rows!
```

`daily` 端点只能查个股，指数需要用 `index_daily`。

### 踩坑：`pro_bar()` 对指数触发 `index_daily` 频率限制

```python
# ⚠️ asset='I' 内部调 index_daily，免费版 1次/小时
ts.pro_bar(ts_code='000001.SH', asset='I', ...)
```

### 最终方案（[data_provider.py:57-91](../src/marketreview/data/data_provider.py#L57-L91)）

```python
def _fetch_from_api(self, code, start, end):
    # 1. 先试 pro_bar（兼容所有 token 等级）
    df = ts.pro_bar(ts_code=code, asset=asset, freq='D',
                    start_date=start, end_date=end, adj='qfq')
    # 2. 被限流则 fallback 到 pro_api 端点
    # 3. 指数用 api.index_daily()，个股用 api.daily()
```

---

## 3. 权限等级与限流

### 免费版限制

| 端点 | 频率 | 影响 |
|------|------|------|
| `index_daily` | **1次/小时** | Agent 1 跑一次需要拉 2 个指数 → 2 小时 |
| `daily`（个股） | 较高 | 权重股 20 只够用 |
| `daily_basic` | 较高 | 市场宽度够用 |

### 解决方案：升级到 Level 1

去 [tushare.pro](https://tushare.pro) → 用户中心 → 捐赠 200 元 → 获得 2000 积分 → 自动升级权限。

升级后 `index_daily` 从 1次/小时 → 足够日常使用。

### 注意：积分 ≠ 等级

- **积分**：用来下载特定数据集（财务数据等），不提升 API 频率
- **等级权限**：提升所有 API 调用频率。通过捐赠获得。

---

## 4. 缓存策略

### 首次拉取：2x 回看天数

```python
# data_provider.py:38
start_date = (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")
```

`lookback_days=120` → 首次拉取 240 天 → ~160 个交易日。

MA60 需要 ≥60 个数据点，KDJ (n=9) 需要额外窗口，2x 确保所有指标能正确计算。

### 增量更新

```python
# data_provider.py:34-36
if cached:
    oldest = cached[-1]["date"].replace("-", "")
    start_date = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1))
```

有缓存后只拉增量部分，不会重复拉全量。

---

## 5. LLM 配置

### 踩坑：YAML 中 `llm: openai/deepseek-v4-pro` 不生效

CrewAI 1.14.x 原生 provider 不认识非标准模型名，需要 litellm fallback。

### 最终方案（[crew.py:13-27](../src/marketreview/crew.py#L13-L27)）

```python
# 在 crew.py 中用 LLM() 显式构造，从 .env 读配置
def _build_llm():
    return LLM(
        model=f"openai/{os.environ['MODEL']}",
        api_key=os.environ['OPENAI_API_KEY'],
        base_url=os.environ['OPENAI_API_BASE'] + '/v1',  # DeepSeek 需要 /v1
    )
```

### .env 配置

```env
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.deepseek.com
MODEL=deepseek-v4-pro
TUSHARE_TOKEN=xxx
```

---

## 6. 已知问题

### market_breadth 工具返回空

`GetMarketBreadthTool` 调用的 `api.daily_basic()` 返回空 DataFrame。原因待排查（可能是该接口需要额外权限或参数格式不对）。Agent 报告中会显示"数据缺失"并在分析中说明。

### Windows 控制台 GBK 编码乱码

CrewAI 的 event bus 输出 emoji 字符（✨🔧✅）在 Windows GBK 终端显示乱码。**不影响功能**，只在开发调试时看到。Dashboard (Streamlit) 不受影响。

### 日期格式

- Tushare API 传参：`"20250604"` (YYYYMMDD, 无分隔符)
- SQLite 缓存存储：`"2025-06-04"` (YYYY-MM-DD)
- `pro_bar` 返回的 `trade_date` 是 **整数** (如 `20250604`)，需要 `astype(str)` 转换

---

## 7. 调试速查

```bash
# 测试 Tushare 连接
uv run python -c "
import os; from dotenv import load_dotenv; load_dotenv()
import tushare as ts
ts.set_token(os.environ['TUSHARE_TOKEN'])
api = ts.pro_api()
df = api.index_daily(ts_code='000001.SH', start_date='20250101', end_date='20250606')
print(f'{len(df)} rows')
"

# 测试 LLM 连接
uv run python -c "
import os; from dotenv import load_dotenv; load_dotenv()
from openai import OpenAI
client = OpenAI(api_key=os.environ['OPENAI_API_KEY'],
                base_url=os.environ['OPENAI_API_BASE'] + '/v1')
r = client.chat.completions.create(model=os.environ['MODEL'],
    messages=[{'role':'user','content':'OK'}], max_tokens=5)
print(r.choices[0].message.content)
"

# 查看缓存状态
uv run python -c "
from src.marketreview.data.cache_manager import CacheManager
cm = CacheManager()
for c in ['000001.SH','399006.SZ']:
    r = cm.get_daily(c)
    print(f'{c}: {len(r)} rows, {r[-1][\"date\"]} ~ {r[0][\"date\"]}')
"

# 清缓存重跑
rm -f data/marketreview.db
rm -f report.md
uv run python -m src.marketreview.main 20250604
```
