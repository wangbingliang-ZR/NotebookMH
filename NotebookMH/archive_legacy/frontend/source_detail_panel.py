"""frontend/source_detail_panel.py - 来源详情面板"""
import streamlit as st
from utils.state_manager import binder
from utils.db_manager import db_pool


def render(content_hash: str) -> None:
    """显示单个来源的详细信息。"""
    vault_uuid = binder.get_state("vault_uuid", "")
    if not vault_uuid:
        st.error("请先选择笔记库。")
        return

    doc = db_pool.get_document(vault_uuid, content_hash)
    if not doc:
        st.error("未找到该来源。")
        return

    st.markdown(f"### {doc.file_name}")

    col1, col2, col3 = st.columns(3)
    with col1:
        size_kb = doc.doc_size / 1024 if doc.doc_size else 0
        st.metric("大小", f"{size_kb:.1f} KB")
    with col2:
        st.metric("页数", doc.page_count or "-")
    with col3:
        st.metric("创建时间", doc.created_at[:10] if doc.created_at else "-")

    if hasattr(doc, "summary") and doc.summary:
        st.markdown("**摘要**")
        st.markdown(doc.summary)

    if hasattr(doc, "key_topics") and doc.key_topics:
        st.markdown("**关键主题**")
        st.markdown(doc.key_topics)

    if hasattr(doc, "suggested_questions") and doc.suggested_questions:
        st.markdown("**建议问题**")
        for q in doc.suggested_questions.strip().split("\n"):
            if q.strip():
                st.markdown(f"- {q.strip()}")

    if hasattr(doc, "full_text") and doc.full_text:
        with st.expander("原文预览"):
            st.text_area("全文", value=doc.full_text, height=300, disabled=True, key="full_text_view")

    st.divider()
    st.markdown("**文档片段**")

    chunks = db_pool.get_chunks_by_doc(vault_uuid, content_hash)
    if chunks:
        for idx, chunk_text, header in chunks[:20]:
            with st.expander(f"片段 {idx + 1}: {header or '无标题'}"):
                st.markdown(chunk_text[:500] + ("..." if len(chunk_text) > 500 else ""))
    else:
        st.info("暂无片段数据。")

    if st.button("返回来源列表", key="btn_back_sources"):
        if "selected_source_hash" in st.session_state:
            del st.session_state["selected_source_hash"]
        st.rerun()
