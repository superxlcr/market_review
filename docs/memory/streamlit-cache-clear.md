---
name: streamlit-cache-clear
description: How to properly clear Streamlit Python module cache on Windows after code changes
metadata:
  node_type: memory
  type: project
  tags:
    - dashboard
    - streamlit
    - cache
    - windows
  originSessionId: 48ae945a-00c7-4ec6-86d9-41082ccc8e80
---

# Streamlit Module Cache Clearing (Windows)

## 最快方式：用项目自带的 restart 脚本

```bash
.venv/Scripts/python restart_streamlit.py
```

这个脚本做了三件事：① 杀端口 8501 上的进程 → ② 清项目 pycache（跳过 .venv）→ ③ 启动 Streamlit。

## When pycache causes problems

**症状：** 代码改了、进程杀了重启了，但渲染结果还是旧的。典型场景：
- 给函数/方法新增了返回值字段，调用方拿到 `None` 或不生效
- 改了列表推导/条件分支逻辑，图表颜色/文案没变
- 新增了 streamlit status handler 的 phase，但进度条不动

**根因：** Python 导入模块时优先用 `.pyc` 字节码。如果 `.pyc` 时间戳比 `.py` 新（Windows 下常见），旧代码就一直跑。

## 手动清理流程（如果 restart 脚本不够用）

### 1. 杀进程 — 用 Python + wmic（Git Bash 下最可靠）

`taskkill`、`pkill`、`netstat | awk` 在 Git Bash 下经常静默失败。用 Python 直调 wmic：

```bash
python -c "
import subprocess as sp
out = sp.check_output('wmic process where \"name=\\\"python.exe\\\"\" get processid,commandline', shell=True).decode('utf-8', errors='ignore')
for l in out.split('\n'):
    if 'streamlit' in l.lower():
        pid = l.strip().split()[-1]
        if pid.isdigit():
            print(f'Killing PID {pid}...')
            sp.run(f'taskkill /F /PID {pid}', shell=True, capture_output=True)
"
```

杀掉后验证（应无 streamlit 进程）：

```bash
python -c "
import subprocess as sp
out = sp.check_output('wmic process where \"name=\\\"python.exe\\\"\" get commandline', shell=True).decode()
for l in out.split('\n'):
    if 'streamlit' in l.lower(): print(l.strip()[:120])
"
```

### 2. 清 pycache（跳过 .venv）

```bash
python -c "
import os, shutil
for root, dirs, files in os.walk('.'):
    if '__pycache__' in dirs and '.venv' not in root:
        shutil.rmtree(os.path.join(root, '__pycache__'))
"
```

### 3. 重启

```bash
nohup .venv/Scripts/python -m streamlit run dashboard/app.py --server.port 8501 > /tmp/streamlit.log 2>&1 &
sleep 6 && curl -s -o /dev/null -w '%{http_code}' http://localhost:8501
```

## 已知问题：Python312 僵尸进程

偶尔会出现一个 Python312 的 streamlit 进程（非 .venv），杀掉后会复活。该进程绑不上端口（.venv 已占 8501），不影响功能，但会干扰 wmic 诊断。如果反复出现，用 `restart_streamlit.py` 脚本即可 — 它按端口杀而非按进程名杀，不会遗漏。

## When to delete the database

Only when:
- Schema changed (added/removed columns)
- Data is visibly corrupted/wrong
- Fetch window parameters changed significantly

Otherwise keep it — re-fetching takes several minutes.

Related: [[dashboard-setup]] [[data-layer-architecture]]
