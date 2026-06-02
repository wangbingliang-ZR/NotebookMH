"""frontend/review_panel.py - 错题复盘面板"""
import streamlit as st
from utils.state_manager import binder
from utils.db_manager import db_pool


def render() -> None:
    vault_uuid = binder.get_state("vault_uuid", "")
    if not vault_uuid:
        st.info("请先选择笔记库。")
        return

    st.markdown("### 错题复盘")

    wrongs = db_pool.list_wrong_answers(vault_uuid, mastered=0)
    if not wrongs:
        st.info("暂无错题记录。")
        return

    st.caption(f"待复习: {len(wrongs)} 道")

    idx = st.session_state.get("review_idx", 0)
    if idx >= len(wrongs):
        idx = 0
        st.session_state["review_idx"] = 0

    item = wrongs[idx]

    st.markdown(f"**题目 {idx + 1} / {len(wrongs)}**")
    st.markdown(item.question)

    if st.button("显示正确答案", key="review_show"):
        st.session_state["review_show"] = True

    if st.session_state.get("review_show", False):
        st.markdown(f"**正确答案: {item.correct_answer}**")
        if item.explanation:
            st.info(f"解析: {item.explanation}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("已掌握", key="review_mastered", use_container_width=True):
                db_pool.mark_wrong_answer_mastered(item.id)
                st.session_state["review_show"] = False
                _next(len(wrongs))
        with c2:
            if st.button("继续复习", key="review_next", use_container_width=True):
                st.session_state["review_show"] = False
                _next(len(wrongs))


def _next(total: int) -> None:
    idx = st.session_state.get("review_idx", 0) + 1
    st.session_state["review_idx"] = idx if idx < total else 0
    st.rerun()
