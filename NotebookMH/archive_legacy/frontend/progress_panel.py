"""frontend/progress_panel.py - 学习进度看板"""
import streamlit as st
from utils.state_manager import binder
from utils.db_manager import db_pool


def render() -> None:
    vault_uuid = binder.get_state("vault_uuid", "")
    user_id = binder.get_state("user_id", "anonymous")

    if not vault_uuid:
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        doc_count = db_pool.count_documents(vault_uuid)
        st.metric("来源数", f"{doc_count}/50")

    with col2:
        notes = db_pool.list_notes(vault_uuid, user_id)
        st.metric("笔记", len(notes))

    with col3:
        cards = db_pool.list_flashcards(vault_uuid)
        mastered = sum(1 for c in cards if c.mastery == 2)
        total = len(cards)
        st.metric("闪卡掌握", f"{mastered}/{total}" if total else "0/0")

    with col4:
        wrongs = db_pool.list_wrong_answers(vault_uuid, mastered=0)
        st.metric("待复习错题", len(wrongs))
