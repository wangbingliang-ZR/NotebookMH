"""
frontend/qa_panel.py - 问答检索主界面

职责：
  - Streamlit 主界面问答输入框
  - 调用 core.rag_pipeline.IngestionPipeline.retrieve() 执行混合检索
  - 展示检索结果（chunk_text、source、score、metadata）
  - 严禁在 app.py 中写入具体 UI 逻辑
"""

import asyncio
import logging
from typing import Any, Dict, List

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from core.rag_pipeline import get_pipeline
from core.llm_engine import get_llm_engine
from core.persona_engine import PersonaEngine
from core.memory_engine import get_memory_engine
from utils.state_manager import binder

logger = logging.getLogger(__name__)

_PIPELINE = get_pipeline()
_LLM = get_llm_engine()
_MEMORY = get_memory_engine()


def render() -> None:
    """渲染主界面问答面板。"""
    if st is None:
        return

    st.divider()
    st.subheader("🔍 认知检索问答 (Phase 3)")

    # 获取当前 vault 与人格态
    vault_uuid = binder.get_state("vault_uuid", "default_vault")
    teacher_type = binder.get_state("teacher_type", "auto")
    user_mode = binder.get_state("user_mode", "adult")
    emotion_state = binder.get_state("emotion_state", "专注")

    # 展示当前生效人格
    persona_label = PersonaEngine.get_resolved_label(teacher_type, emotion_state, user_mode)
    st.caption(f"当前 Vault: `{vault_uuid}` · 生效人格: `{persona_label}`")

    # 问答输入
    query = st.text_input(
        "输入你的问题",
        placeholder="例如：这份文档的核心观点是什么？",
        key="nb_mh_query_input",
    )

    top_k = st.slider("检索深度 (top_k)", min_value=1, max_value=10, value=5, key="nb_mh_topk")

    if st.button("🧠 启动混合检索 + 人格回答", key="btn_retrieve"):
        if not query.strip():
            st.warning("请输入问题后再检索。")
            return
        _run_rag_qa(query.strip(), vault_uuid, top_k, teacher_type, user_mode, emotion_state)


def _run_rag_qa(
    query: str,
    vault_uuid: str,
    top_k: int,
    teacher_type: str,
    user_mode: str,
    emotion_state: str,
) -> None:
    """执行异步混合检索 → 人格注入 → LLM 生成回答。"""
    status = st.empty()
    status.info("🔄 正在执行 Dense + Sparse + RRF 融合检索...")

    async def _loop() -> List[Dict[str, Any]]:
        return await _PIPELINE.retrieve(query, vault_uuid, top_k=top_k)

    try:
        # Step 1: 混合检索
        chunks = asyncio.run(_loop())
        if not chunks:
            status.empty()
            st.warning("未检索到相关知识。请先通过侧边栏上传并摄入文档。")
            return

        status.info(f"🧠 检索命中 {len(chunks)} 条，正在注入人格生成回答...")

        # Step 2: 生成人格 system_prompt
        system_prompt = PersonaEngine.generate_system_prompt(
            teacher_type=teacher_type,
            user_mode=user_mode,
            emotion_state=emotion_state,
        )

        # Step 3: LLM 生成 RAG 回答（阻塞操作在 to_thread 中，已由 llm_engine 内部处理）
        ai_resp = asyncio.run(
            _LLM.rag_answer(
                question=query,
                context_chunks=chunks,
                system_prompt=system_prompt,
                temperature=0.7,
            )
        )

        status.empty()

        # ── 展示 AI 回答 ──────────────────────────────────
        st.success("✅ 回答已生成")
        st.markdown(f"**{ai_resp.explanation}**")

        if ai_resp.question:
            st.info(f"💡 跟进问题: {ai_resp.question}")
        if ai_resp.hint:
            st.caption(f"🎯 提示: {ai_resp.hint}")
        if ai_resp.encouragement:
            st.caption(f"🌟 {ai_resp.encouragement}")
        if ai_resp.diagnosis:
            st.caption(f"📊 诊断: {ai_resp.diagnosis}")

        # ── Phase 3: 记忆固化 ────────────────────────────
        user_id = binder.get_state("user_id", "anonymous")
        _MEMORY.log_exchange(
            user_id=user_id,
            query=query,
            response=ai_resp.explanation,
            question=ai_resp.question,
            c_load=ai_resp.c_load,
            e_valence=ai_resp.e_valence,
            diagnosis=ai_resp.diagnosis,
        )
        # 同步认知探针到 GlobalState
        if ai_resp.c_load is not None:
            binder.update_state("c_load", ai_resp.c_load)
        if ai_resp.e_valence is not None:
            binder.update_state("e_valence", ai_resp.e_valence)
        logger.info("Exchange logged for user=%s", user_id)

        # ── 展示检索原始 chunks（可折叠参考）───────────────
        st.divider()
        st.caption("📚 参考知识片段（原始检索结果）")
        for rank, item in enumerate(chunks, start=1):
            with st.expander(
                f"#{rank} [{item.get('source', '?').upper()}] 相关性: {item.get('score', 0):.3f}"
            ):
                st.markdown(f"{item['chunk_text']}")
                meta = item.get("metadata", {})
                if meta:
                    st.json(meta)
                else:
                    idx = item.get("chunk_index", -1)
                    if idx >= 0:
                        st.caption(f"chunk_index: {idx}")

    except Exception as e:
        logger.error("RAG QA failed: %s", e)
        status.error(f"问答失败: {e}")
