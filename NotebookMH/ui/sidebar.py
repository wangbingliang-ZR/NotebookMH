"""ui/sidebar.py — 侧边栏（用户 + Vault + 来源）"""
import streamlit as st
from core.db import db_manager


@st.dialog("来源详情", width="large")
def _show_source_dialog(vault_uuid: str, content_hash: str):
    doc = db_manager.get_document(vault_uuid, content_hash)
    if not doc:
        st.error("文档不存在")
        return
    st.markdown(f"### 📄 {doc.file_name}")
    st.caption(
        f"类型: {doc.source_type} | 大小: {doc.doc_size} 字节 | "
        f"页数: {doc.page_count or '—'}"
    )
    if doc.source_url:
        st.markdown(f"来源: {doc.source_url}")
    if doc.summary:
        st.markdown("**摘要**")
        st.write(doc.summary)
    chunks = db_manager.get_chunks(vault_uuid, content_hash)
    st.markdown(f"**共 {len(chunks)} 个片段**")
    for c in chunks[:20]:
        with st.expander(f"片段 #{c.chunk_index + 1}"):
            st.text(c.chunk_text)


def _get_user_id() -> str:
    return st.session_state.get("user_id", "anonymous")


def _get_vault_uuid() -> str:
    return st.session_state.get("vault_uuid", "")


def render_user_section() -> None:
    st.markdown("### 用户")
    name = st.text_input(
        "用户名", value=_get_user_id(), key="ui_user_input",
        help="输入用户名以切换个人空间",
    )
    if name and name.strip() and name.strip() != _get_user_id():
        st.session_state["user_id"] = name.strip()
        st.session_state["vault_uuid"] = ""
        st.rerun()


def render_vault_section() -> None:
    st.markdown("### 笔记库")
    user_id = _get_user_id()
    vaults = db_manager.list_vaults(user_id)

    if not vaults:
        st.caption("还没有笔记库，请新建一个")
    else:
        options = {v.vault_uuid: v.vault_name for v in vaults}
        keys = list(options.keys())
        current = _get_vault_uuid()
        if current not in options:
            current = keys[0]
            st.session_state["vault_uuid"] = current

        selected = st.selectbox(
            "当前库", options=keys,
            format_func=lambda u: options[u],
            index=keys.index(current),
            key="ui_vault_select",
        )
        if selected != _get_vault_uuid():
            st.session_state["vault_uuid"] = selected
            st.rerun()

    with st.expander("新建笔记库"):
        new_name = st.text_input("名称", key="ui_new_vault_name", label_visibility="collapsed",
                                 placeholder="输入库名")
        if st.button("创建", key="ui_btn_create_vault", use_container_width=True):
            if new_name.strip():
                uuid = db_manager.create_vault(user_id, new_name.strip())
                st.session_state["vault_uuid"] = uuid
                st.rerun()
            else:
                st.warning("请输入名称")

    if vaults and _get_vault_uuid():
        with st.expander("删除当前库"):
            st.caption("删除后不可恢复")
            if st.button("确认删除", key="ui_btn_delete_vault",
                         use_container_width=True, type="secondary"):
                db_manager.delete_vault(_get_vault_uuid())
                st.session_state["vault_uuid"] = ""
                st.rerun()


def render_upload_section() -> None:
    import asyncio
    from config import SUPPORTED_EXTS, MAX_FILE_SIZE_MB
    from core.ingest import ingest_file, ingest_text, ingest_url

    vault_uuid = _get_vault_uuid()
    st.markdown("### 来源")

    if not vault_uuid:
        st.caption("先选择一个笔记库")
        return

    docs = db_manager.list_documents(vault_uuid)
    if len(docs) >= 50:
        st.warning("已达 50 个来源上限，请先删除部分")
        return

    uploaded = st.file_uploader(
        "上传文件", type=SUPPORTED_EXTS,
        accept_multiple_files=True, key="ui_file_uploader",
    )
    if uploaded:
        for f in uploaded:
            if f.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                st.warning(f"{f.name} 超过 {MAX_FILE_SIZE_MB}MB 限制")
                continue
            data = f.read()
            try:
                result = asyncio.run(ingest_file(vault_uuid, f.name, data))
                if result["status"] == "ok":
                    st.success(f"{f.name}: {result['chunks']} 片段")
                elif result["status"] == "duplicate":
                    st.info(f"{f.name}: 已存在")
                else:
                    st.error(f"{f.name}: {result['msg']}")
            except Exception:
                st.error(f"{f.name} 上传失败，请重试或换文件格式")

    with st.expander("粘贴文本"):
        pasted = st.text_area("内容", key="ui_paste_text", height=120)
        title = st.text_input("标题", key="ui_paste_title", placeholder="输入标题")
        if st.button("保存", key="ui_btn_paste"):
            if pasted.strip() and title.strip():
                try:
                    result = asyncio.run(ingest_text(vault_uuid, title.strip(), pasted.strip()))
                    st.success(result["msg"]) if result["status"] == "ok" else st.error(result["msg"])
                except Exception:
                    st.error("粘贴文本保存失败，请重试")
            else:
                st.warning("标题和内容不能为空")

    with st.expander("添加网页链接"):
        url = st.text_input("URL", key="ui_url_input", placeholder="https://...")
        if st.button("获取", key="ui_btn_fetch_url"):
            if url.strip():
                try:
                    result = asyncio.run(ingest_url(vault_uuid, url.strip()))
                    if result["status"] == "ok":
                        st.success(result["msg"])
                        st.rerun()
                    else:
                        st.error(result["msg"])
                except Exception:
                    st.error(f"URL 抓取失败，请检查链接有效性")
            else:
                st.warning("请输入 URL")

    if docs:
        st.caption(f"已收录 {len(docs)} 个来源")
        selected: list[str] = []
        for d in docs[:50]:
            c0, c1, c2 = st.columns([1, 7, 1])
            is_sel = c0.checkbox(
                "", value=True,
                key=f"sel_{d.content_hash[:10]}",
                label_visibility="collapsed",
            )
            if c1.button(f"📄 {d.file_name[:30]}",
                         key=f"view_{d.content_hash[:10]}",
                         use_container_width=True):
                _show_source_dialog(vault_uuid, d.content_hash)
            if c2.button("✕", key=f"del_{d.content_hash[:10]}", help="删除"):
                from core.vector_store import vector_store
                db_manager.delete_document(vault_uuid, d.content_hash)
                vector_store.delete(vault_uuid, d.content_hash)
                st.rerun()
            if is_sel:
                selected.append(d.content_hash)
        st.session_state["selected_sources"] = selected


def render() -> None:
    with st.sidebar:
        render_user_section()
        st.divider()
        render_vault_section()
        st.divider()
        render_upload_section()
