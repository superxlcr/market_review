# A股复盘系统

基于 Streamlit 的 A 股市场复盘仪表盘，多维度分析市场全景、行业板块与个股追踪。

## 环境要求

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/) 包管理器

```bash
pip install uv
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API Key：

```env
# LLM API（DeepSeek V4 Pro）
OPENAI_API_KEY=你的-deepseek-api-key
OPENAI_API_BASE=https://api.deepseek.com/v1

# Tushare Pro（A股行情数据）
TUSHARE_TOKEN=你的-tushare-token
```

> Tushare Token 可在 [tushare.pro](https://tushare.pro) 注册获取。

### 3. 启动仪表盘

双击 `start-dashboard.bat`，或终端运行：

```bash
.\start-dashboard.bat
```

浏览器打开 [http://localhost:8501](http://localhost:8501) 即可使用。

## 页面导航

| 页面 | 说明 |
|------|------|
| 🎛️ **控制台** | 统一入口，选择交易日，全局生效 |
| 📊 **市场全景** | 大盘涨跌、成交额、K 线图、指数贡献 |
| 🏭 **板块分析** | 行业板块排名、赚钱效应、仓位策略 |
| 📋 **个股追踪** | 自选股技术分析、持仓管理 |

## 项目结构

```
marketreview/
├── dashboard/           # Streamlit 前端
│   ├── app.py           # 入口（多页导航）
│   ├── pages/           # 各功能页面
│   └── services/        # 数据服务层
├── src/marketreview/    # 核心逻辑
│   ├── data/            # 数据提供层（Tushare 封装）
│   ├── tools/           # 分析工具（技术指标、指数贡献等）
│   └── rendering/       # 渲染样式
├── data/                # 本地数据
├── .env.example         # 环境变量模板
└── start-dashboard.bat  # 一键启动
```
