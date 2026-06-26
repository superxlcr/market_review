"""
A股复盘 Dashboard — 多页面入口。
启动: streamlit run dashboard/app.py
"""
import streamlit as st

st.set_page_config(page_title="A股复盘", page_icon="📊", layout="wide")

# ── 窄侧栏 + 字重 ──
st.markdown("""
<style>
[data-testid="stSidebar"] {
    min-width: 140px !important;
    max-width: 140px !important;
}
[data-testid="stSidebar"] .st-emotion-cache-1qg05tj {
    font-size: 14px;
}
[data-testid="stSidebarNavLink"] {
    font-size: 14px;
}
</style>
""", unsafe_allow_html=True)

pg = st.navigation([
    st.Page("pages/00_控制台.py", title="控制台", icon="🎛️", default=True),
    st.Page("pages/01_市场全景.py", title="市场全景", icon="📊"),
    st.Page("pages/02_板块分析.py", title="板块分析", icon="🏭"),
    st.Page("pages/03_个股追踪.py", title="个股追踪", icon="📋"),
    st.Page("pages/04_战法回测.py", title="战法回测", icon="🔬"),
])

pg.run()
