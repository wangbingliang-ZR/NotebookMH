"""frontend/flashcard_panel.py - 交互式闪卡面板"""
import streamlit as st
from utils.state_manager import binder
from utils.db_manager import db_pool


def render() -> None:
    vault_uuid = binder.get_state("vault_uuid", "")
    if not vault_uuid:
        st.info("请先选择笔记库。")
        return

    cards = db_pool.list_flashcards(vault_uuid)
    if not cards:
        st.info("暂无闪卡。请在 Studio 中点击「闪卡」生成。")
        return

    idx = st.session_state.get("fc_idx", 0)
    if idx >= len(cards):
        idx = 0
    card = cards[idx]

    st.markdown(f"**卡片 {idx + 1} / {len(cards)}**")

    # 问题面
    st.markdown(
        f'<div style="background:#f0f4ff; border-radius:12px; padding:24px; '
        f'min-height:80px; font-size:16px; margin:8px 0;">{card.question}</div>',
        unsafe_allow_html=True,
    )

    show = st.session_state.get("fc_show", False)
    if not show:
        if st.button("显示答案", key="fc_flip", use_container_width=True):
            st.session_state["fc_show"] = True
            st.rerun()
    else:
        st.markdown(
            f'<div style="background:#e8f5e9; border-radius:12px; padding:24px; '
            f'min-height:80px; font-size:16px; margin:8px 0;">{card.answer}</div>',
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("未掌握", key="fc_0", use_container_width=True):
                db_pool.update_flashcard_mastery(card.id, 0)
                _next(len(cards))
        with c2:
            if st.button("模糊", key="fc_1", use_container_width=True):
                db_pool.update_flashcard_mastery(card.id, 1)
                _next(len(cards))
        with c3:
            if st.button("已掌握", key="fc_2", use_container_width=True):
                db_pool.update_flashcard_mastery(card.id, 2)
                _next(len(cards))

    # 进度
    mastered = sum(1 for c in cards if c.mastery == 2)
    st.progress(mastered / len(cards) if cards else 0, text=f"掌握: {mastered}/{len(cards)}")

    # 重新开始
    if st.button("重新开始", key="fc_reset"):
        st.session_state["fc_idx"] = 0
        st.session_state["fc_show"] = False
        st.rerun()


def _next(total: int) -> None:
    idx = st.session_state.get("fc_idx", 0) + 1
    st.session_state["fc_idx"] = idx if idx < total else 0
    st.session_state["fc_show"] = False
    st.rerun()
