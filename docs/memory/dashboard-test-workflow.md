---
name: dashboard-test-workflow
description: "Always test data backfill/loading through dashboard UI, not CLI scripts"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: ae5a34d2-5eaa-4293-8197-32a6358f9fcf
---

Data backfill, industry_daily calculation, or any data loading triggers should ALWAYS be tested through the Streamlit dashboard UI (控制台页面), NOT via command-line Python scripts.

**Why:** The dashboard is the real user-facing flow — it includes progress callbacks, UI state handling, and real-world timing that CLI scripts miss. Testing through the dashboard catches UX issues that raw scripts cannot.

**How to apply:** After code changes that affect data loading, simply tell the user "改好了，去控制台触发一下试试" and let them interact with the dashboard. Only use CLI scripts for read-only queries (e.g., checking DB state, counting rows).
