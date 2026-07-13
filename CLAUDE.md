# CLAUDE.md — Market Review Project Rules

> **THIS FILE IS MANDATORY.** It loads into every session. You cannot skip it.

---

## Pre-Change Checklist (MUST complete BEFORE writing code)

Whenever you are about to modify ANY file:

1. **Scan MEMORY.md** — Read `docs/memory/MEMORY.md` and list which memory files apply to this change.
2. **Read the relevant memories** — Open and read each one from `docs/memory/`. Quote the rule in your response.
3. **State the plan** — What files, what changes, why. Wait for approval before writing code.

## Post-Change Checklist (MUST complete AFTER writing code)

1. **Bump AI version** — Per `ai-version-number.md`. Find `_AI_VERSION` in `dashboard/services/dashboard_service.py` and increment Z (patch) for bug fixes, Y (minor) for features, X (major) for breaking changes.
2. **Change summary table** — Per `change-summary-preference.md`. Output a table of files changed, what changed, why.
3. **Verify** — State how you verified the change works.

## Critical Conventions (violated before — DO NOT REPEAT)

| Rule | Memory File | What It Means |
|------|-------------|---------------|
| Bump version on every change | `ai-version-number.md` | Find `_AI_VERSION`, increment it. No exceptions. |
| Streamlit modules are cached | `streamlit-cache-clear.md` | `mode="w"` only truncates first import. Kill process + clear `__pycache__` for hard restarts. |
| Log levels matter | `logging-convention.md` | INFO for flow, DEBUG for data, WARNING for anomalies. Don't log at wrong level. |
| Dates are always YYYYMMDD | `date-format-convention.md` | Never use `_with_dashes` in DB queries. |
| Cache reads MUST filter by date | `always-filter-by-date.md` | Never bare `LIMIT N` — always `WHERE trade_date = ?`. |
| Red = bullish, Green = bearish | `color-convention.md` | Never flip this. |
| Reuse proven logic | (lesson from wasted branch) | Before writing new code, check if existing code does the same thing. Add parameters instead of rewriting. |

## Project Structure

```
src/marketreview/     — Core library (data layer, tools, rendering)
dashboard/            — Streamlit UI
  pages/              — Individual pages
  services/           — DashboardService (orchestration)
logs/                 — Per-module log files (auto-created)
data/                 — SQLite databases (auto-created)
```
