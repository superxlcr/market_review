---
name: visual-companion-setup
description: How to start the visual companion server for design mockups
metadata: 
  node_type: memory
  type: reference
  originSessionId: ce9ebd5d-9eba-4ebd-bcd3-4377f2c4bf1e
---

## Visual Companion Server (2026-06-04, fresh session)

### Location
- Directory: `<project_root>/.superpowers/brainstorm/<session_id>/` (created per brainstorming session)
- Content: `content/`
- State: `state/`
- Server: Managed by `start-server.sh` (superpowers)
- Port: 63123
- URL: http://localhost:63123

### How to Start
```bash
# Path depends on Claude Code plugin install location. Example:
bash "<claude_plugins>/superpowers/<version>/skills/brainstorming/scripts/start-server.sh" --project-dir "<project_root>"
# Runs in background; read state/server-info for port
```

### How to Stop
```bash
taskkill //F //PID <pid>
# Find PID: netstat -ano | grep LISTENING | grep '63123'
# Or use: scripts/stop-server.sh <session_dir>
```

### Previous Session (deprecated)
- Port 60508, directory `555-1780498702/` — killed, cache issues

### Server Features
- Custom `server.py` (NOT plain `python -m http.server`)
- `Content-Type: text/html; charset=utf-8` for HTML files
- `Cache-Control: no-cache, no-store, must-revalidate`
- Binds to 127.0.0.1:60508

### index.html
- Default iframe loads `agent3-design.html` (currently)
- Top navbar + left sidebar navigation
- All files wrapped with `<!DOCTYPE html>` + `<meta charset="utf-8">` + styles

### Key Files
| File | Content |
|------|---------|
| combined-dashboard.html | Agent 1+2 full dashboard mockup |
| agent1-design.html | Agent 1 detailed design |
| agent2-design.html | Agent 2 detailed design |
| agent3-design.html | Agent 3 revised design (default) |
| flow-state.html | Pydantic Flow State model |
| data-model-v3.html | SQLite schema |
| pipeline-v3.html | Architecture pipeline |
| custom-groups-v2.html | Custom groups two-table design |

### Common Issues
- **乱码**: Make sure using `server.py` not `python -m http.server`. The custom server adds charset to Content-Type.
- **旧内容**: Server sends no-cache headers now. If still seeing old content, kill all processes on 60508 and restart.
- **Port occupied**: `netstat -ano | grep ':60508'` → `taskkill //F //PID <pid>`

**Why:** Quick reference for restarting the visual companion across sessions.
**How to apply:** Run the start command whenever the companion is down.
