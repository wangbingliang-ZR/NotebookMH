"""ui/chat_panel.py — 对话面板"""
import asyncio
import traceback

import streamlit as st

from core.chat import answer
from core.db import db_manager


def _history_for_llm(vault_uuid: str, user_id: str) -> list[dict]:
    rows = db_manager.load_chat(vault_uuid, user_id)
    return [{"role": r.role, "content": r.content,
             "citations": r.citations or []} for r in rows]


def _render_message(msg: dict, idx: int = 0, vault_uuid: str = "",
                     user_id: str = "") -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        cites = msg.get("citations") or []
        if cites and msg["role"] == "assistant":
            with st.expander(f"引用 {len(cites)} 条"):
                for c in cites:
                    st.markdown(f"**[{c['index']}]** 《{c.get('file_name','?')}》")
                    full = c.get("full_text") or c.get("preview", "")
                    with st.expander("查看原文"):
                        st.text(full)
            if vault_uuid and st.button("📝 保存为笔记", key=f"save_chat_{idx}"):
                title = msg["content"][:30] + "..."
                db_manager.save_note(vault_uuid, user_id, title, msg["content"])
                st.success("已保存到笔记")


def render() -> None:
    vault_uuid = st.session_state.get("vault_uuid", "")
    user_id = st.session_state.get("user_id", "anonymous")

    if not vault_uuid:
        st.info("👈 请先在左侧选择或新建笔记库")
        return

    st.markdown("### 对话")

    docs = db_manager.list_documents(vault_uuid)
    history = _history_for_llm(vault_uuid, user_id)
    for i, msg in enumerate(history):
        _render_message(msg, i, vault_uuid, user_id)

    if history:
        if st.button("清空对话", key="btn_clear_chat"):
            db_manager.clear_chat(vault_uuid, user_id)
            st.rerun()

    if not history:
        suggested = []
        for d in docs[:3]:
            if d.suggested_questions:
                suggested.extend(d.suggested_questions[:2])
        if suggested:
            st.markdown("**建议问题:**")
            for i, q in enumerate(suggested[:5]):
                if st.button(q, key=f"sugg_{i}", use_container_width=True):
                    st.session_state["_pending_query"] = q
                    st.rerun()

    pending = st.session_state.pop("_pending_query", None)
    query = pending or st.chat_input("提出你的问题...")
    if not query:
        return

    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        cite_box = st.empty()
        sources = st.session_state.get("selected_sources") or None
        pending_candidates = st.session_state.get("chat_candidates") or None
        text_buf = ""
        citations: list[dict] = []
        new_candidates: list[dict] | None = None
        sources_changed = False
        placeholder.markdown("_AI 正在思考..._")

        async def _run():
            nonlocal text_buf, citations, new_candidates, sources_changed
            async for ev in answer(query, vault_uuid, user_id,
                                   history=history, source_hashes=sources,
                                   pending_candidates=pending_candidates):
                if ev["type"] == "citations":
                    citations = ev["data"]
                elif ev["type"] == "delta":
                    text_buf += ev["text"]
                    placeholder.markdown(text_buf + "▌")
                elif ev["type"] == "search_results":
                    new_candidates = ev["data"]
                elif ev["type"] == "sources_added":
                    sources_changed = True
                elif ev["type"] == "done":
                    placeholder.markdown(text_buf)

        try:
            asyncio.run(_run())
            if citations:
                with cite_box.expander(f"引用 {len(citations)} 条"):
                    for c in citations:
                        st.markdown(f"**[{c['index']}]** 《{c.get('file_name','?')}》")
                        full = c.get("full_text") or c.get("preview", "")
                        with st.expander("查看原文"):
                            st.text(full)
        except Exception:
            placeholder.empty()
            st.error("对话失败，错误详情如下（请截图反馈）：")
            st.code(traceback.format_exc())
            return

    # Agent：暂存本轮搜到的候选，供下一轮导入
    if new_candidates is not None:
        st.session_state["chat_candidates"] = new_candidates
    # 导入完成后清空候选
    if sources_changed:
        st.session_state.pop("chat_candidates", None)

    st.rerun()
