---
name: dashboard-setup
description: How to start/stop the Streamlit dashboard on port 8501
metadata: 
  node_type: memory
  type: reference
  originSessionId: 48ae945a-00c7-4ec6-86d9-41082ccc8e80
---

## Streamlit Dashboard — A股复盘

### URL
- http://localhost:8501

### How to Start (bash background, no popup window)

```bash
# Run from project root:
nohup python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true > /dev/null 2>&1 &
```

### How to Restart (after code changes)

**Use the root scripts — no manual commands:**

```bash
# Git Bash / cmd:
cmd //c clean.bat    # kill processes + clear __pycache__
cmd //c start-dashboard.bat   # start fresh (blocks; use start /b or run in separate terminal)
```

- `clean.bat` — kills streamlit.exe + python.exe, clears `__pycache__` under `dashboard/` and `src/` (skips `.venv`)
- `start-dashboard.bat` — activates venv, clears pycache, starts on port 8501

If running from a single bash terminal, use background mode:
```bash
# Run from project root:
cmd //c clean.bat && nohup .venv/Scripts/python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true > /tmp/streamlit.log 2>&1 &
sleep 4 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8501
```

### How to Stop
```bash
taskkill //f //im streamlit.exe 2>/dev/null
taskkill //f //im python.exe 2>/dev/null
```

### Common Issues
- **修改代码不生效**: 99% 是进程没杀干净 — 旧 Python 进程驻留内存，模块不重载。按上方 Restart 流程，**第 2 步验证必须确认 "all dead"**。
- **端口占用**: 先完整走一遍 Restart 流程

### Related
- [[streamlit-cache-clear]]
- [[data-layer-architecture]]
