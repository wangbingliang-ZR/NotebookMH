# Phase B — 上传链路完善（Step 10-17）

> **执行前必读**: `ARCHITECTURE.md` + 最近 5 步 PROGRESS.md
> **本阶段目标**: URL/粘贴文本/删除/筛选/详情/容量/错误提示
> **Checkpoint**: Step 10、15 完成后做

---

## Step 10：URL + 粘贴文本上传

**目标**: sidebar 支持 URL 抓取和粘贴文本两种来源。

**操作**: 在 `ui/sidebar.py` 的 `render_upload_section` 末尾（`st.rerun()` 之后、函数结束之前）追加:

```python
    # URL 来源
    with st.expander("从网页 URL 添加"):
        url = st.text_input("URL", key="ui_url_input",
                            label_visibility="collapsed",
                            placeholder="https://...")
        if st.button("抓取", key="ui_btn_url", use_container_width=True):
            if url.strip().startswith(("http://", "https://")):
                from core.ingest import ingest_url
                with st.spinner("抓取中..."):
                    try:
                        r = asyncio.run(ingest_url(vault_uuid, url.strip()))
                        if r["status"] == "ok":
                            st.success(r["msg"])
                        else:
                            st.warning(r["msg"])
                        st.rerun()
                    except Exception:
                        st.code(traceback.format_exc())
            else:
                st.warning("请输入 http(s):// 开头的 URL")

    # 粘贴文本来源
    with st.expander("粘贴文本"):
        title = st.text_input("标题", key="ui_paste_title",
                              label_visibility="collapsed", placeholder="标题")
        text = st.text_area("内容", height=150, key="ui_paste_text",
                            label_visibility="collapsed", placeholder="粘贴内容...")
        if st.button("添加", key="ui_btn_paste", use_container_width=True):
            if title.strip() and text.strip():
                from core.ingest import ingest_text
                with st.spinner("添加中..."):
                    try:
                        r = asyncio.run(ingest_text(
                            vault_uuid, title.strip(), text.strip()))
                        if r["status"] == "ok":
                            st.success(r["msg"])
                        else:
                            st.warning(r["msg"])
                        st.rerun()
                    except Exception:
                        st.code(traceback.format_exc())
            else:
                st.warning("标题和内容都需要填写")
```

⚠️ `asyncio` 和 `traceback` 必须已在函数开头 import（Step 9 中已加）。

**验收**:
1. URL: 粘贴一个静态网页 URL（如 https://example.com），点抓取 → 来源列表新增一条
2. 粘贴: 标题"测试笔记" + 一段文本，点添加 → 来源列表新增一条
3. 无 Traceback

---

## Step 10 完成 → CHECKPOINT 2

**强制动作**:
1. 重读 ARCHITECTURE.md
2. 重读 PROGRESS.md Step 6-10
3. 在 PROGRESS.md 写 Checkpoint 2
4. 偏离即修

---

## Step 11：来源删除按钮

**目标**: 每条来源旁有"✕"按钮，点击同步删除 DB + ChromaDB。

**操作**: 在 `ui/sidebar.py` 中找到 `render_upload_section` 内的:
```python
for d in docs[:20]:
    st.markdown(f"📄 {d.file_name}")
```
替换为:
```python
for d in docs[:50]:
    c1, c2 = st.columns([8, 1])
    c1.markdown(f"📄 {d.file_name[:30]}")
    if c2.button("✕", key=f"del_{d.content_hash[:10]}", help="删除"):
        from core.vector_store import vector_store
        db_manager.delete_document(vault_uuid, d.content_hash)
        vector_store.delete(vault_uuid, d.content_hash)
        st.rerun()
```

**验收**:
1. 已上传 2 个文件 → 点其中一个的 ✕
2. 列表减少一条
3. Chroma 验证: `vector_store.query(...)` 不再返回被删的 doc_hash 内容

---

## Step 12：来源数量上限 + 容量提示

**目标**: 达到 50 个来源时禁止上传。

**操作**: 在 `render_upload_section` 中 `uploaded = st.file_uploader(...)` **之前**添加:
```python
if len(docs) >= 50:
    st.warning("已达 50 个来源上限，请先删除部分")
    return
```

并把容量提示改为带颜色:
```python
ratio = len(docs) / 50
if ratio >= 0.9:
    st.markdown(f":red[已上传 {len(docs)} / 50]")
elif ratio >= 0.7:
    st.markdown(f":orange[已上传 {len(docs)} / 50]")
else:
    st.caption(f"已上传 {len(docs)} / 50")
```

**验收**: 临时把上限改成 2 测试，传第 3 个文件应被拒绝。测试完改回 50。

---

## Step 13：来源勾选筛选

**目标**: 每条来源前加 checkbox，选中的列表写入 `st.session_state["selected_sources"]`。

**操作**: 替换 Step 11 的列表渲染为:
```python
selected: list[str] = []
for d in docs[:50]:
    c0, c1, c2 = st.columns([1, 7, 1])
    is_sel = c0.checkbox(
        "", value=True,
        key=f"sel_{d.content_hash[:10]}",
        label_visibility="collapsed",
    )
    if is_sel:
        selected.append(d.content_hash)
    c1.markdown(f"📄 {d.file_name[:30]}")
    if c2.button("✕", key=f"del_{d.content_hash[:10]}", help="删除"):
        from core.vector_store import vector_store
        db_manager.delete_document(vault_uuid, d.content_hash)
        vector_store.delete(vault_uuid, d.content_hash)
        st.rerun()
st.session_state["selected_sources"] = selected
```

**验收**:
1. 取消某个来源的勾 → `st.session_state["selected_sources"]` 应少一项
2. 浏览器开发者工具或临时打印验证

加临时验证（可选删除）:
```python
st.caption(f"已选 {len(selected)} 个源用于对话")
```

---

## Step 14：单文件大小限制 + Streamlit 配置

**目标**: 单文件超过 500MB 拒绝。

**操作**:
1. 编辑或创建 `.streamlit/config.toml`:
   ```toml
   [server]
   maxUploadSize = 500
   headless = true

   [theme]
   base = "light"
   primaryColor = "#1a73e8"
   ```
2. Step 9 已加运行时检查 `len(data) > 500 * 1024 * 1024 → st.error`，确认仍在。

**验收**:
1. `streamlit run app.py` 启动后，文件上传组件提示 "Limit 500MB"
2. （可选）造一个 600MB 文件 → 应被前端拒绝

---

## Step 15：上传错误统一友好提示

**目标**: 任何 ingest 异常 → 显示 `st.code(traceback.format_exc())`，并带文件名上下文。

**操作**: 复查 `render_upload_section` 中 3 个 `try/except`:
- 文件: `st.error(f"{f.name} 失败:")` + `st.code(traceback.format_exc())`
- URL: `st.error(f"URL 抓取失败: {url}")` + `st.code(...)`
- 粘贴: `st.error("粘贴文本失败:")` + `st.code(...)`

确保 except 块**始终**输出 traceback（不准 `pass` 或 `logger.warning(...)` 后吃掉）。

**验收**:
1. 故意上传一个把 .png 改名 .pdf 的损坏文件
2. 应看到红色错误框，含 traceback 文字
3. 应用不崩溃，可继续操作

---

## Step 15 完成 → CHECKPOINT 3

按规则重读架构 + 最近 5 步，写 Checkpoint 3。

---

## Step 16：来源详情弹窗

**目标**: 点击来源名 → Streamlit dialog 显示前 20 个 chunk + 元信息。

**操作**: 在 `ui/sidebar.py` 文件顶部（import 之后、函数定义之前）添加:

```python
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
```

把 Step 13 列表渲染中的 `c1.markdown(f"📄 {d.file_name[:30]}")` 替换为按钮:
```python
if c1.button(f"📄 {d.file_name[:30]}",
             key=f"view_{d.content_hash[:10]}",
             use_container_width=True):
    _show_source_dialog(vault_uuid, d.content_hash)
```

**禁止**:
- ❌ 新建 `ui/source_panel.py`（不在架构清单内）
- ❌ 用 `st.expander` 替代 dialog（用户体验差）

**验收**:
1. 点击任一来源名 → 弹窗显示标题、元信息、片段列表
2. 展开任一片段 → 显示原文文本
3. 关闭弹窗回到主界面

---

## Step 17：阶段 B 集成验收

**目标**: 完整跑一遍 Phase B 全部功能。

**操作**（人工浏览器）:
1. 用户 alice + 新建 vault `bench_B`
2. 上传 1 个 PDF（真实文件，几页中文）
3. 上传 1 个 TXT
4. 抓取 1 个 URL（如 https://zh.wikipedia.org/wiki/光合作用 的纯文本页）
5. 粘贴 1 段文本（标题 + 内容）
6. 验证: 来源列表 4 条，容量显示 `4 / 50`
7. 点击任一来源 → 弹窗正常显示片段
8. 取消某条勾选 → `已选 3 个源用于对话`
9. 点 ✕ 删除一条 → 列表减少
10. 全程无 Traceback

**SQL 验证**:
```powershell
python -c "
from core.db import db_manager
from core.vector_store import vector_store
vs = db_manager.list_vaults('alice')
for v in vs:
    if v.vault_name == 'bench_B':
        ds = db_manager.list_documents(v.vault_uuid)
        print(f'{v.vault_name}: {len(ds)} docs')
        for d in ds:
            ch = db_manager.get_chunks(v.vault_uuid, d.content_hash)
            print(f'  {d.file_name} | type={d.source_type} | chunks={len(ch)}')
        r = vector_store.query(v.vault_uuid, '测试', top_k=2)
        print(f'  Chroma 命中: {len(r)}')
"
```

**预期**: SQLite 和 ChromaDB 数据一致，每个文档都有对应 chunks。

**记录 PROGRESS.md**:
```
[Step 17] ✅ 阶段 B 集成
- 测试用例: 4 种来源类型全通
- 12 项进度: F3=✅ F4=✅ F5=✅ F7=✅
```

---

## 阶段 B 完成

阅读 `plans/phase_c_chat.md` 进入对话阶段。
