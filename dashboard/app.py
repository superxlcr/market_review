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
    st.Page("pages/08_板块资金流.py", title="板块资金", icon="💰"),
    st.Page("pages/03_个股追踪.py", title="个股追踪", icon="📋"),
    st.Page("pages/04_波段分析.py", title="波段分析", icon="📐"),
    st.Page("pages/05_NGA分析.py", title="NGA分析", icon="🧮"),
    st.Page("pages/06_买点胜率.py", title="买点胜率", icon="🎯"),
    st.Page("pages/07_ETF胜率.py", title="ETF胜率", icon="📈"),
])

pg.run()
