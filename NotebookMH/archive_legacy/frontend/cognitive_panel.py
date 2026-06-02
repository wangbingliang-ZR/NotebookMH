"""
frontend/cognitive_panel.py - 认知控制面板 (Phase 2B)

职责：
  - 三态模式切换：Learning / Quizzing / Review
  - 模式切换时强制清空上一状态流
  - 调用 CognitiveEngine.generate_response() 执行状态路由
  - 根据返回类型渲染不同 UI：
      socratic  → 导师追问卡片
      quiz      → 测验题展示 + 推理输入框
      diagnostic→ 诊断报告 + 重试引导
      review    → 错题回顾追问

严禁在 app.py 中写入具体 UI 逻辑。
"""

import asyncio
import logging
from typing import Any, Dict, List

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from core.cognitive_engine import CognitiveState, get_cognitive_engine
from frontend.guardian_monitor import (
    consume_recovery_message,
    evaluate_deadlock,
    record_user_input,
)
from frontend.neural_panel import get_state_sink
from utils.state_manager import binder

logger = logging.getLogger(__name__)

_COG = get_cognitive_engine()
_STATE_SINK = get_state_sink()

# Streamlit session_state 键名常量
_SSK_STATE = "nb_mh_cognitive_state"
_SSK_HISTORY = "nb_mh_cognitive_history"
_SSK_QUIZ_ACTIVE = "nb_mh_quiz_active"


# ---------------------------------------------------------------------------
# 公共渲染接口
# ---------------------------------------------------------------------------

def render() -> None:
    """渲染认知控制主面板 — NotebookLM 风格对话界面。"""
    if st is None:
        return

    # ── 初始化 session state ─────────────────────────────
    if _SSK_STATE not in st.session_state:
        st.session_state[_SSK_STATE] = CognitiveState.LEARNING.value
    if _SSK_HISTORY not in st.session_state:
        from utils.db_manager import db_pool
        vault_uuid = binder.get_state("vault_uuid", "")
        user_id = binder.get_state("user_id", "anonymous")
        saved = db_pool.load_chat_history(vault_uuid, user_id) if vault_uuid else []
        st.session_state[_SSK_HISTORY] = [
            {"role": row.role, "content": row.content, "type": row.msg_type}
            for row in saved
        ]

    current_state_str = st.session_state[_SSK_STATE]
    current_state = CognitiveState(current_state_str)

    # ── 模式切换按钮组 ─────────────────────────────────────
    st.markdown("#### 认知模式")
    mode_cols = st.columns(3)
    with mode_cols[0]:
        if st.button(
            "深度剖析 (Learning)",
            key="btn_mode_learning",
            use_container_width=True,
            type="primary" if current_state == CognitiveState.LEARNING else "secondary",
        ):
            _switch_mode(CognitiveState.LEARNING)
    with mode_cols[1]:
        if st.button(
            "实战测验 (Quizzing)",
            key="btn_mode_quizzing",
            use_container_width=True,
            type="primary" if current_state == CognitiveState.QUIZZING else "secondary",
        ):
            _switch_mode(CognitiveState.QUIZZING)
    with mode_cols[2]:
        if st.button(
            "错题清算 (Review)",
            key="btn_mode_review",
            use_container_width=True,
            type="primary" if current_state == CognitiveState.REVIEW else "secondary",
        ):
            _switch_mode(CognitiveState.REVIEW)

    st.caption(f"当前状态: **{current_state.value.upper()}**")
    st.divider()

    # ── 消费 Guardian 恢复消息 ─────────────────────────────
    recovery_msg = consume_recovery_message()
    if recovery_msg:
        _append_history("assistant", recovery_msg, "recovery")

    # ── 渲染历史对话流 ─────────────────────────────────────
    _render_history()

    # ── 建议问题 ──────────────────────────────────────────
    history = st.session_state.get(_SSK_HISTORY, [])
    if not history and current_state == CognitiveState.LEARNING:
        vault_uuid_q = binder.get_state("vault_uuid", "")
        suggested = db_pool.get_suggested_questions(vault_uuid_q) if vault_uuid_q else []
        if suggested:
            st.markdown("**试试问这些：**")
            q_cols = st.columns(min(len(suggested), 3))
            for i, q in enumerate(suggested[:3]):
                with q_cols[i]:
                    if st.button(q, key=f"suggest_{i}"):
                        st.session_state["pending_question"] = q
                        st.rerun()

    # ── 输入区 ─────────────────────────────────────────────
    vault_uuid = binder.get_state("vault_uuid", "default_vault")

    if current_state == CognitiveState.QUIZZING and st.session_state.get(_SSK_QUIZ_ACTIVE):
        placeholder = "输入你的推理过程..."
    else:
        placeholder = {
            CognitiveState.LEARNING: "提出你的问题，导师不会直接给答案...",
            CognitiveState.QUIZZING: "点击上方按钮获取题目，然后在此输入推理...",
            CognitiveState.REVIEW: "回顾之前的薄弱点，尝试回答...",
        }.get(current_state, "在此输入...")

    user_input = st.text_input(
        "你的输入",
        placeholder=placeholder,
        key="nb_mh_cognitive_input",
    )

    # 检查是否有建议问题点击
    pending = st.session_state.pop("pending_question", None)
    if pending:
        _execute_turn(pending, current_state, vault_uuid)
        return

    if st.button("提交", key="btn_cognitive_submit"):
        if not user_input.strip():
            st.warning("输入不能为空。")
            return
        _execute_turn(user_input.strip(), current_state, vault_uuid)

    if st.button("清空对话", key="btn_clear_chat"):
        from utils.db_manager import db_pool
        vault_uuid = binder.get_state("vault_uuid", "")
        user_id = binder.get_state("user_id", "anonymous")
        if vault_uuid:
            db_pool.clear_chat_history(vault_uuid, user_id)
        st.session_state[_SSK_HISTORY] = []
        st.rerun()


def _switch_mode(new_state: CognitiveState) -> None:
    """切换认知模式，清空上一状态的临时流。"""
    old_state = st.session_state.get(_SSK_STATE)
    if old_state == new_state.value:
        return

    st.session_state[_SSK_STATE] = new_state.value
    if st.session_state[_SSK_HISTORY]:
        from utils.db_manager import db_pool
        vault_uuid = binder.get_state("vault_uuid", "")
        user_id = binder.get_state("user_id", "anonymous")
        if vault_uuid:
            db_pool.clear_chat_history(vault_uuid, user_id)
        st.session_state[_SSK_HISTORY] = []
        st.rerun()


def _render_history() -> None:
    """渲染当前模式下的对话历史。"""
    history: List[Dict[str, Any]] = st.session_state.get(_SSK_HISTORY, [])
    if not history:
        st.info("当前模式暂无对话。开始输入吧。")
        return

    for item in history:
        role = item.get("role", "")
        content = item.get("content", "")
        msg_type = item.get("type", "")

        if role == "user":
            with st.chat_message("user"):
                st.markdown(content)
        elif role == "assistant":
            with st.chat_message("assistant"):
                if msg_type == "quiz":
                    st.markdown(f"**测验题**\n\n{content}")
                elif msg_type == "diagnostic":
                    st.markdown(f"**诊断报告**\n\n{content}")
                    retry = item.get("retry", "")
                    if retry:
                        st.info(f"重试引导: {retry}")
                elif msg_type == "socratic":
                    idx = history.index(item)
                    stream_key = f"streamed_{idx}"
                    is_last = (idx == len(history) - 1)
                    if is_last and not st.session_state.get(stream_key, False):
                        import time
                        def _stream():
                            for ch in content:
                                yield ch
                                time.sleep(0.005)
                        st.write_stream(_stream)
                        st.session_state[stream_key] = True
                    else:
                        st.markdown(f"**苏格拉底追问**\n\n{content}")
                    probe = item.get("probe", "")
                    if probe:
                        st.caption(f"追问: {probe}")
                    # 显示来源引用
                    source_chunks = st.session_state.get("last_source_chunks", [])
                    if source_chunks:
                        with st.expander("来源引用", expanded=False):
                            for i, chunk in enumerate(source_chunks, 1):
                                st.markdown(f"**[{i}]** {chunk.get('chunk_text', '')[:200]}...")
                elif msg_type == "review":
                    st.markdown(f"**错题回顾**\n\n{content}")
                else:
                    st.markdown(content)


def _execute_turn(user_input: str, state: CognitiveState, vault_uuid: str) -> None:
    """执行一轮认知交互。"""
    # ── Guardian 死锁检测 ─────────────────────────────────
    record_user_input(user_input)
    if evaluate_deadlock():
        st.rerun()
        return

    status = st.empty()
    status.info(f"[{state.value.upper()}] 正在路由...")

    # 记录用户输入
    _append_history("user", user_input, "")

    user_id = binder.get_state("user_id", "anonymous")

    # 构建最近对话历史（供神经评估使用）
    history = st.session_state.get(_SSK_HISTORY, [])
    chat_history = [
        {"role": h["role"], "content": h["content"]}
        for h in history[-10:]
    ]

    # Phase 7: 每轮开始时重置相变 flag（允许新相变触发）
    from frontend.holographic_console import reset_phase_transition_flag
    reset_phase_transition_flag()

    async def _loop() -> Dict[str, Any]:
        selected_sources = st.session_state.get("selected_sources")
        return await _COG.generate_response(
            user_input=user_input,
            current_state=state,
            vault_uuid=vault_uuid,
            top_k=5,
            user_id=user_id,
            chat_history=chat_history,
            state_sink=_STATE_SINK,
            selected_sources=selected_sources,
        )

    try:
        result = asyncio.run(_loop())
        status.empty()

        # 检索来源 chunks（用于引用显示）
        from core.rag_pipeline import get_pipeline
        _pipeline = get_pipeline()
        chunks = asyncio.run(_pipeline.retrieve(user_input, vault_uuid, top_k=5))
        st.session_state["last_source_chunks"] = chunks

        msg_type = result.get("type", "")

        if msg_type == "socratic":
            _append_history(
                "assistant",
                result.get("text", ""),
                "socratic",
                probe=result.get("probe", ""),
            )

        elif msg_type == "quiz":
            quiz_data = result.get("quiz", {})
            display = result.get("display", quiz_data.get("question", ""))
            st.session_state[_SSK_QUIZ_ACTIVE] = True
            _append_history("assistant", display, "quiz")

        elif msg_type == "diagnostic":
            diag = result.get("result", {})
            display = result.get("display", diag.get("diagnosis", ""))
            retry = result.get("retry", diag.get("retry_prompt", ""))
            st.session_state[_SSK_QUIZ_ACTIVE] = False
            # Phase 7: 写 mastery 相变 flag
            mastery_delta = float(diag.get("mastery_delta", 0.0))
            # 读旧 mastery（从 DB 估算）
            old_level = st.session_state.get("nb_mh_last_mastery_level", 50.0)
            new_level = max(0.0, min(100.0, old_level + mastery_delta))
            st.session_state["nb_mh_last_mastery_level"] = new_level
            st.session_state["nb_mh_last_mastery_delta"] = mastery_delta
            # Phase 7: 遥测事件
            from utils.telemetry_events import log_mastery
            log_mastery(level=new_level, delta=mastery_delta)
            _append_history("assistant", display, "diagnostic", retry=retry)

        elif msg_type == "review":
            _append_history(
                "assistant",
                result.get("text", ""),
                "review",
                probe=result.get("probe", ""),
            )

        else:
            _append_history("assistant", str(result), "raw")

        st.rerun()

    except Exception as e:
        logger.error("Cognitive turn failed: %s", e)
        status.error(f"认知引擎阻断: {e}")
        return


def _append_history(
    role: str,
    content: str,
    msg_type: str,
    probe: str = "",
    retry: str = "",
) -> None:
    """向当前模式的对话历史追加一条记录。"""
    entry: Dict[str, Any] = {
        "role": role,
        "content": content,
        "type": msg_type,
    }
    if probe:
        entry["probe"] = probe
    if retry:
        entry["retry"] = retry
    st.session_state[_SSK_HISTORY].append(entry)

    # 持久化到数据库
    from utils.db_manager import db_pool
    vault_uuid = binder.get_state("vault_uuid", "")
    user_id = binder.get_state("user_id", "anonymous")
    if vault_uuid:
        db_pool.save_chat_message(vault_uuid, user_id, role, content, msg_type)
