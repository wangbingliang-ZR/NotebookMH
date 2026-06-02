"""app.py — NotebookMH 入口"""
import traceback

import nest_asyncio
import streamlit as st

import config
from ui import sidebar, chat_panel, studio_panel

nest_asyncio.apply()

st.set_page_config(
    page_title="NotebookMH", page_icon="📓",
    layout="wide", initial_sidebar_state="expanded",
)
st.markdown(
    '<meta name="google" content="notranslate">'
    '<style>body, .stApp, [class*="st-"] { translate: no !important; }</style>',
    unsafe_allow_html=True,
)
st.markdown("""
<style>
.stButton button { padding: 0.25rem 0.75rem; }
section[data-testid="stSidebar"] .streamlit-expanderHeader { font-weight: 600; }
@media (max-width: 1100px) {
  [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
}
</style>
""", unsafe_allow_html=True)

def _clear_studio_state():
    """清理 Studio 结果缓存"""
    for k in list(st.session_state.keys()):
        if k.startswith(("_studio_result_", "_studio_running_")):
            del st.session_state[k]


def _cleanup_on_vault_switch():
    """切库/刷新时清理临时 state"""
    current = st.session_state.get("vault_uuid", "")
    last = st.session_state.get("_last_vault", "")
    if current != last:
        st.session_state["_last_vault"] = current
        _clear_studio_state()


# 全局异常兜底：sidebar
st.markdown("<div style='display:none'>sidebar</div>", unsafe_allow_html=True)
try:
    sidebar.render()
except Exception:
    with st.sidebar:
        st.error("侧边栏加载失败")
        st.caption("请刷新页面或检查数据库状态")

user_id = st.session_state.get("user_id", "anonymous")
vault_uuid = st.session_state.get("vault_uuid", "")

if not vault_uuid:
    st.markdown("## 👋 欢迎使用 NotebookMH")
    st.markdown(
        "**第一步**: 在左侧输入用户名\n\n"
        "**第二步**: 在左侧“新建笔记库”\n\n"
        "**第三步**: 上传资料并开始对话"
    )
    st.stop()

_cleanup_on_vault_switch()


def _render_top_metrics(vault_uuid: str, user_id: str) -> None:
    from core.db import db_manager
    docs = db_manager.list_documents(vault_uuid)
    notes = db_manager.list_notes(vault_uuid, user_id)
    cards = db_manager.list_flashcards(vault_uuid)
    wrongs = db_manager.list_wrong_answers(vault_uuid, only_unmastered=True)
    cols = st.columns(4)
    cols[0].metric("来源", f"{len(docs)} / 50")
    cols[1].metric("笔记", len(notes))
    cols[2].metric("闪卡", len(cards))
    cols[3].metric("待复习错题", len(wrongs))


st.markdown("<div style='display:none'>metrics</div>", unsafe_allow_html=True)
try:
    _render_top_metrics(vault_uuid, user_id)
    st.divider()
except Exception:
    st.error("指标加载失败")

try:
    left, right = st.columns([5, 3], gap="large")
    with left:
        chat_panel.render()
    with right:
        studio_panel.render()
except Exception:
    st.error("应用出现异常，请查看下方详情或刷新重试。")
    st.code(traceback.format_exc())
