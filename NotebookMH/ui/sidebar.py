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

    with st.expander("� 批量导入网页链接"):
        st.caption("每行一个 URL，系统会逐个抓取并加为来源")
        bulk_urls = st.text_area(
            "URL 列表", key="ui_bulk_urls",
            height=120,
            placeholder="https://www.zhongkao.com/...\nhttps://www.xbjy.com/...",
        )
        if st.button("批量导入", key="ui_btn_bulk_import", use_container_width=True):
            lines = [u.strip() for u in bulk_urls.splitlines() if u.strip().startswith("http")]
            if not lines:
                st.warning("没有检测到有效的 http/https 链接")
            else:
                progress = st.progress(0, text=f"0 / {len(lines)}")
                ok_count = 0
                fail_count = 0
                fail_list: list[str] = []
                for i, u in enumerate(lines):
                    try:
                        res = asyncio.run(ingest_url(vault_uuid, u))
                        if res.get("status") == "ok":
                            ok_count += 1
                        else:
                            fail_count += 1
                            fail_list.append(u[:60])
                    except Exception:
                        fail_count += 1
                        fail_list.append(u[:60])
                    progress.progress(
                        (i + 1) / len(lines),
                        text=f"{i + 1} / {len(lines)}  成功 {ok_count}  失败 {fail_count}",
                    )
                progress.empty()
                st.success(f"完成：成功 {ok_count} 个，失败 {fail_count} 个")
                if fail_list:
                    with st.expander("失败的链接"):
                        for u in fail_list:
                            st.markdown(f"- `{u}`")
                if ok_count:
                    st.rerun()

    with st.expander("�🔍 AI 联网找资料"):
        st.caption("输入主题 → AI 搜索候选 → 你勾选 → 一键导入")
        topic = st.text_input("研究主题 / 需求", key="ui_research_topic",
                              placeholder="如：2024年河北省初中生物学业水平考试")

        # ── Phase 1: 搜索 ──
        if st.button("🔍 搜索候选来源", key="ui_btn_research_search",
                     use_container_width=True):
            if topic.strip():
                from core.research import plan_and_discover
                with st.spinner("正在为「{}」规划知识结构并联网搜集资料，这一步会分多个维度并行搜索，请稍候 20-40 秒...".format(topic.strip())):
                    try:
                        candidates = asyncio.run(plan_and_discover(topic.strip(), max_total=20))
                        st.session_state["ui_research_results"] = candidates
                        st.session_state["ui_research_topic_value"] = topic.strip()
                        st.rerun()
                    except Exception:
                        st.error("搜索失败，请稍后重试")
            else:
                st.warning("请输入研究主题")

        # ── Phase 2: 展示候选，用户勾选 ──
        candidates = st.session_state.get("ui_research_results", [])
        if candidates:
            st.divider()
            st.markdown(
                f"**找到 {len(candidates)} 个候选来源** "
                f"（主题：{st.session_state.get('ui_research_topic_value', '')}）"
            )
            st.caption("勾选想导入的来源，点击下方「导入选中来源」")

            selected_indices: list[int] = []
            for i, c in enumerate(candidates):
                with st.container(border=True):
                    cols = st.columns([1, 12])
                    with cols[0]:
                        checked = st.checkbox(
                            "", key=f"ui_research_chk_{i}", value=True,
                            label_visibility="collapsed",
                        )
                    with cols[1]:
                        st.markdown(f"**{c['title']}**")
                        st.caption(
                            f"🔗 [{c['url'][:50]}...]({c['url']})"
                        )
                        if c.get("reason"):
                            st.markdown(f"💡 **AI：** {c['reason']}")
                        st.caption(f"{c['preview']}...")
                    if checked:
                        selected_indices.append(i)

            c0, c1 = st.columns(2)
            if c0.button(
                "✅ 导入选中来源", key="ui_btn_research_import",
                use_container_width=True, type="primary",
            ):
                selected = [candidates[i] for i in selected_indices]
                if not selected:
                    st.warning("请至少勾选一项")
                else:
                    from core.research import ingest_selected
                    with st.spinner("正在导入..."):
                        try:
                            added = asyncio.run(ingest_selected(vault_uuid, selected))
                            st.success(f"已导入 {len(added)} 个来源")
                            st.session_state.pop("ui_research_results", None)
                            st.session_state.pop("ui_research_topic_value", None)
                            st.rerun()
                        except Exception:
                            st.error("导入失败，请重试")

            if c1.button("❌ 清空结果", key="ui_btn_research_clear",
                         use_container_width=True):
                st.session_state.pop("ui_research_results", None)
                st.session_state.pop("ui_research_topic_value", None)
                st.rerun()

        elif "ui_research_results" in st.session_state and not candidates:
            st.info("未找到符合条件的候选来源，换个更具体的说法再试")
            st.session_state.pop("ui_research_results", None)

    if docs:
        st.caption(f"已收录 {len(docs)} 个来源")

        # ── 顶部批量操作（最醒目）──
        if len(docs) >= 50:
            st.error("� 已达 50 个来源上限，必须删除部分才能导入新资料")
        c0, c1 = st.columns(2)
        if c0.button("🗑️ 清空全部来源", key="btn_del_all_top",
                     type="primary", use_container_width=True):
            st.session_state["_confirm_clear_all"] = True

        if c1.button("📋 展开批量选择", key="btn_toggle_batch",
                     use_container_width=True):
            st.session_state["_show_batch_del"] = not st.session_state.get("_show_batch_del", False)
            st.rerun()

        # 确认清空弹窗
        if st.session_state.get("_confirm_clear_all"):
            st.warning(f"确认删除全部 {len(docs)} 个来源？不可恢复！")
            cca, ccb = st.columns(2)
            if cca.button("确认清空", key="btn_confirm_clear",
                          type="primary", use_container_width=True):
                from core.vector_store import vector_store
                for d in docs:
                    db_manager.delete_document(vault_uuid, d.content_hash)
                    vector_store.delete(vault_uuid, d.content_hash)
                st.session_state.pop("_confirm_clear_all", None)
                st.success("已清空全部来源")
                st.rerun()
            if ccb.button("取消", key="btn_cancel_clear",
                          use_container_width=True):
                st.session_state.pop("_confirm_clear_all", None)
                st.rerun()

        # 批量选择模式
        if st.session_state.get("_show_batch_del"):
            with st.container(border=True):
                st.markdown("**批量删除**（勾选后点下方删除按钮）")
                del_marks: list[str] = []
                for d in docs[:50]:
                    if st.checkbox(f"{d.file_name[:34]}",
                                   key=f"delchk_{d.content_hash[:10]}"):
                        del_marks.append(d.content_hash)
                if st.button(f"删除勾选的 {len(del_marks)} 个来源", key="btn_del_checked",
                             use_container_width=True, disabled=not del_marks):
                    from core.vector_store import vector_store
                    for h in del_marks:
                        db_manager.delete_document(vault_uuid, h)
                        vector_store.delete(vault_uuid, h)
                    st.success(f"已删除 {len(del_marks)} 个来源")
                    st.rerun()

        st.divider()

        # ── 来源列表（查看 + 单个删除）──
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
            if c2.button("✕", key=f"del_{d.content_hash[:10]}", help="删除此来源"):
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
