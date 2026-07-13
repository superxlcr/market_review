---
name: mandatory-pre-change-workflow
description: "Before ANY code change: list memories, verify env, restart+verify. Skip = stopped."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 562434d4-216b-4bec-8992-0ef2fa32705d
---

# Mandatory Pre-Change Workflow

**This is a HARD GATE. Do not write a single line of code before completing it.**

## Step 1: List relevant memories

Read `MEMORY.md`. For every memory file that relates to the change, output a table:

| Memory | Rule |
|--------|------|

Key memories that apply to almost every change:
- `ai-version-number.md` — Z bump on every change+restart
- `streamlit-cache-clear.md` — Windows 下杀进程用 Python+wmic，不用 bash taskkill；清 pycache 用 Python 不用 find
- `logging-convention.md` — 用 log.info，禁止 stderr

## Step 2: State the plan

What files, what changes, why. **Wait for user approval before writing code.**

## Step 3: After writing code

1. **Bump Z** in `_AI_VERSION` (every change+restart)
2. **Verify restart actually worked:**
   - Kill Streamlit: Python + wmic（见 `streamlit-cache-clear.md`）
   - Clear pycache: Python `os.walk` + `shutil.rmtree`（见 `streamlit-cache-clear.md`）
   - Start: `.venv/Scripts/python -m streamlit run dashboard/app.py --server.port 8501`
   - **Check startup**: `tail /tmp/streamlit.log` — confirm no import errors
3. **Verify Python compatibility**: No `X | Y` type hints unless Python ≥ 3.10 (project uses `Optional[X]`)

## Why

2026-06-20 wasted an entire morning: taskkill in Git Bash silently failed, pycache wasn't cleared, old .pyc kept loading, ThreadPoolExecutor changes never took effect. `X | None` syntax crashed an older Python. All preventable by reading the memories that already existed.

## Consequence

**User will stop the session immediately if this checklist is skipped.**
