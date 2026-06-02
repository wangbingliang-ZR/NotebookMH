"""frontend/quiz_panel.py - 交互式测验面板"""
import json
import streamlit as st
from utils.state_manager import binder
from utils.db_manager import db_pool


def render() -> None:
    vault_uuid = binder.get_state("vault_uuid", "")
    if not vault_uuid:
        st.info("请先选择笔记库。")
        return

    questions = db_pool.list_quiz_unanswered(vault_uuid)
    if not questions:
        st.info("暂无未答测验题。请在 Studio 中点击「测验」生成。")
        return

    idx = st.session_state.get("quiz_idx", 0)
    if idx >= len(questions):
        idx = 0
        st.session_state["quiz_idx"] = 0
    q = questions[idx]

    st.markdown(f"**题目 {idx + 1} / {len(questions)}**")
    st.markdown(q.question)

    try:
        options = json.loads(q.options)
    except (json.JSONDecodeError, TypeError):
        options = []

    if options:
        user_choice = st.radio("请选择答案", options, key=f"quiz_choice_{q.id}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("提交答案", key=f"quiz_submit_{q.id}", use_container_width=True):
                choice_letter = user_choice[0] if user_choice else ""
                is_correct = db_pool.answer_quiz(q.id, choice_letter)
                if is_correct:
                    st.success("回答正确！")
                    _next_question(len(questions))
                else:
                    st.error(f"回答错误。正确答案是 {q.correct}。")
                    db_pool.save_wrong_answer(
                        vault_uuid=vault_uuid,
                        question=q.question,
                        user_answer=choice_letter,
                        correct_answer=q.correct,
                        explanation=q.explanation or "",
                    )
                    _next_question(len(questions))
                if q.explanation:
                    st.info(f"解析: {q.explanation}")
        with col2:
            if st.button("跳过此题", key=f"quiz_skip_{q.id}", use_container_width=True):
                _next_question(len(questions))
    else:
        st.warning("题目选项加载失败。")
        if st.button("下一题", key=f"quiz_next_{q.id}"):
            _next_question(len(questions))


def _next_question(total: int) -> None:
    idx = st.session_state.get("quiz_idx", 0) + 1
    st.session_state["quiz_idx"] = idx if idx < total else 0
    st.rerun()
