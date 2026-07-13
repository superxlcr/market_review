---
name: dashboard-page-registration
description: Dashboard pages are registered explicitly in app.py via st.Page — not auto-discovered from pages/
metadata: 
  node_type: memory
  type: reference
  originSessionId: d3d3f1ba-7940-40e1-ae7e-2b3f04781e74
---

The Streamlit dashboard uses **explicit** navigation in [dashboard/app.py](dashboard/app.py): a `st.navigation([st.Page("pages/XX_名.py", title=..., icon=...), ...])` list. It does **NOT** auto-discover files in `dashboard/pages/`.

Consequences (each of these bit us once):
- **Adding a page**: creating `pages/06_买点胜率.py` is not enough — you must also add a `st.Page("pages/06_买点胜率.py", ...)` entry to the `st.navigation([...])` list in app.py, or it never shows in the sidebar.
- **Hiding/archiving a page**: moving `pages/05_战法回测.py` out of `pages/` while app.py still references it raises `StreamlitAPIException: Unable to create Page ... could not be found`. Remove (or repoint) its `st.Page(...)` line in app.py.
- Pages MAY call `st.set_page_config(...)` even though app.py already does (e.g. `04_波段分析.py`, `06_买点胜率.py`) — allowed in the current Streamlit version.

After any page add/move/rename, restart via `restart_streamlit.py` (kills 8501 → clears pycache → starts). Note the restart script's "No startup errors" line does NOT execute app.py's navigation, so it will not catch a bad `st.Page` path — verify every `pages/*.py` referenced in app.py exists.

Related: [[dashboard-setup]] [[streamlit-cache-clear]]
