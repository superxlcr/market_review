---
name: utility-scripts
description: 项目工具脚本：查数据库、杀端口、调试个股、重启 dashboard
metadata: 
  node_type: memory
  type: reference
  originSessionId: fe852660-bf5a-4127-a77d-defa438bc25e
---

# Utility Scripts

项目自带工具脚本，统一放 `scripts/`。所有脚本从项目根目录运行，自动定位 DB 路径和项目结构。

## 脚本清单

### `restart_streamlit.py`（项目根目录）
```bash
.venv/Scripts/python restart_streamlit.py                        # 默认 0.0.0.0:8501
.venv/Scripts/python restart_streamlit.py --bind 127.0.0.1       # 绕过 CLOSE_WAIT 问题
.venv/Scripts/python restart_streamlit.py --port 8502            # 指定端口
```
三步：杀端口进程 → 清 `__pycache__`（跳过 .venv）→ 启动 Streamlit。

### `scripts/db_query.py` — 查数据库
```bash
.venv/Scripts/python scripts/db_query.py --tables                # 列出所有表
.venv/Scripts/python scripts/db_query.py --schema tushare_cache  # 表结构
.venv/Scripts/python scripts/db_query.py --code 002709.SZ --days 10  # 个股最近K线
.venv/Scripts/python scripts/db_query.py --code 002709.SZ --buy  # 查看 buy_points.log
.venv/Scripts/python scripts/db_query.py "SELECT ..."            # 直接执行 SQL
.venv/Scripts/python scripts/db_query.py "SELECT ..." --json     # JSON 输出
```
DB 路径自动定位为 `data/marketreview.db`，不用每次手动写路径。

### `scripts/kill_port.py` — 杀端口
```bash
.venv/Scripts/python scripts/kill_port.py          # 杀 8501
.venv/Scripts/python scripts/kill_port.py 8502     # 杀指定端口
.venv/Scripts/python scripts/kill_port.py --list   # 列出所有监听端口
```

### `scripts/debug_stock.py` — 个股调试
```bash
.venv/Scripts/python scripts/debug_stock.py 002709.SZ                   # 自动最新日期
.venv/Scripts/python scripts/debug_stock.py 002709.SZ --date 20260702   # 指定日期
.venv/Scripts/python scripts/debug_stock.py 002709.SZ -n 500            # 指定拉取天数
```
输出：波段结构报告 + 收盘波峰列表 + 买点列表（含止损和原因）。

## Claude 使用指南

当需要调试时，直接用这些脚本，不要手写 sqlite3/netstat 命令：
- 查数据 → `scripts/db_query.py`
- 杀端口 → `scripts/kill_port.py`  
- 调试个股买点 → `scripts/debug_stock.py`
- 重启 dashboard → `restart_streamlit.py --bind 127.0.0.1`

[[database-schema-reference]] [[dashboard-setup]] [[streamlit-cache-clear]]
