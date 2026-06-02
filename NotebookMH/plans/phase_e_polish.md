# Phase E — 体验打磨（Step 33-40）

> **执行前必读**: `ARCHITECTURE.md` + 最近 5 步 PROGRESS.md
> **本阶段目标**: 笔记导出、空状态、错误兜底、响应式、顶部统计、视觉一致
> **Checkpoint**: Step 35、40 完成后做

---

## Step 33：从对话保存到笔记

**目标**: 对话气泡下方有"保存为笔记"按钮，可把 AI 回复存为笔记。

**操作**: 修改 `ui/chat_panel.py` 的 `_render_message`:

```python
def _render_message(msg: dict, idx: int = 0, vault_uuid: str = "",
                    user_id: str = "") -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        cites = msg.get("citations") or []
        if cites and msg["role"] == "assistant":
            with st.expander(f"引用 {len(cites)} 条"):
                for c in cites:
                    st.markdown(f"**[{c['index']}]** 《{c.get('file_name','?')}》")
                    st.caption(c.get("preview", ""))
            # 保存为笔记
            if st.button("📝 保存为笔记", key=f"save_chat_{idx}"):
                title = msg["content"][:30] + "..."
                db_manager.save_note(vault_uuid, user_id, title, msg["content"])
                st.success("已保存到笔记")
```

在 `render()` 中调用改为:
```python
for i, msg in enumerate(history):
    _render_message(msg, i, vault_uuid, user_id)
```

**验收**:
1. 已有一轮对话
2. AI 气泡下方"保存为笔记"按钮
3. 点击 → Studio 面板"我的笔记"出现该条目

---

## Step 34：笔记导出 MD / Word / PDF

**目标**: 笔记区每条笔记可导出 3 种格式。

**操作**: 在 `ui/studio_panel.py` 的 `_render_notes_section` 中扩展:

```python
def _render_notes_section(vault_uuid: str, user_id: str) -> None:
    st.markdown("### 我的笔记")
    notes = db_manager.list_notes(vault_uuid, user_id)
    if not notes:
        st.caption("还没有保存的笔记")
        return
    for n in notes[:20]:
        with st.expander(f"{'📌 ' if n.pinned else ''}{n.title}"):
            st.markdown(n.content)

            # 导出按钮
            md_bytes = f"# {n.title}\n\n{n.content}".encode("utf-8")
            cols = st.columns(5)
            cols[0].download_button("MD", md_bytes, file_name=f"{n.title}.md",
                                    mime="text/markdown", key=f"dl_md_{n.id}")
            cols[1].download_button("Word", _to_docx(n.title, n.content),
                                    file_name=f"{n.title}.docx",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"dl_docx_{n.id}")
            cols[2].download_button("PDF", _to_pdf(n.title, n.content),
                                    file_name=f"{n.title}.pdf",
                                    mime="application/pdf",
                                    key=f"dl_pdf_{n.id}")
            if cols[3].button("置顶", key=f"pin_{n.id}"):
                db_manager.toggle_pin_note(n.id); st.rerun()
            if cols[4].button("删除", key=f"del_note_{n.id}"):
                db_manager.delete_note(n.id); st.rerun()


def _to_docx(title: str, content: str) -> bytes:
    import io
    from docx import Document
    doc = Document()
    doc.add_heading(title, level=1)
    for para in content.split("\n\n"):
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _to_pdf(title: str, content: str) -> bytes:
    """简易 PDF：用 fpdf2（已在 requirements 中？否则用 reportlab）"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import io
        # 注册中文字体
        try:
            pdfmetrics.registerFont(TTFont("CJK", "C:/Windows/Fonts/simhei.ttf"))
            font_name = "CJK"
        except Exception:
            font_name = "Helvetica"
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setFont(font_name, 16)
        c.drawString(50, 800, title)
        c.setFont(font_name, 11)
        y = 770
        for line in content.split("\n"):
            if y < 50:
                c.showPage()
                y = 800
                c.setFont(font_name, 11)
            c.drawString(50, y, line[:80])
            y -= 18
        c.save()
        return buf.getvalue()
    except ImportError:
        # 降级到纯文本伪 PDF
        return f"{title}\n\n{content}".encode("utf-8")
```

如 `requirements.txt` 缺 `reportlab`，**追加** `reportlab>=4.0.0` 并 `pip install reportlab`。

**验收**:
1. 笔记区任一条目展开
2. 点 "MD" → 下载 .md 文件，内容正确
3. 点 "Word" → 下载 .docx，Word 打开看到标题和正文
4. 点 "PDF" → 下载 .pdf，PDF 阅读器打开看到中文不乱码

---

## Step 35：空状态 UI（无 vault / 无源 / 无对话）

**目标**: 用户看到清晰的"下一步该做什么"指引。

**操作**:
1. `app.py` 主区域改为:
   ```python
   user_id = st.session_state.get("user_id", "anonymous")
   vault_uuid = st.session_state.get("vault_uuid", "")

   if not vault_uuid:
       # 整体空状态
       st.markdown("## 👋 欢迎使用 NotebookMH")
       st.markdown(
           "**第一步**: 在左侧输入用户名\n\n"
           "**第二步**: 在左侧"新建笔记库"\n\n"
           "**第三步**: 上传资料并开始对话"
       )
       st.stop()

   left, right = st.columns([5, 3], gap="large")
   with left:
       chat_panel.render()
   with right:
       studio_panel.render()
   ```

2. `chat_panel.py` 中 vault 存在但无来源:
   ```python
   docs = db_manager.list_documents(vault_uuid)
   if not docs:
       st.info("📥 请先在左侧上传资料，才能开始对话")
       return
   ```

3. `studio_panel.py` 中 vault 存在但无来源:
   ```python
   docs = db_manager.list_documents(vault_uuid)
   if not docs:
       st.caption("先上传资料再生成 Studio 内容")
       return
   ```

**验收**:
1. 新建用户 "bob"（无库）→ 主区显示欢迎页
2. 新建库后未传文件 → 中间区显示"请先上传"，Studio 区显示"先上传资料"
3. 上传后 → 两边正常显示

---

## Step 35 完成 → CHECKPOINT 7

按规则重读 + 写 Checkpoint 7。

---

## Step 36：全局错误兜底

**目标**: 任何未捕获异常 → 显示友好提示 + 详细 traceback。

**操作**: 在 `app.py` 主区域包一层:

```python
import traceback

try:
    # ... 原有 left/right 渲染 ...
    pass
except Exception:
    st.error("应用出现异常，请查看下方详情或刷新重试。")
    st.code(traceback.format_exc())
```

并在 `core/chat.py`、`core/studio.py` 关键路径加 logging。

**验收**:
1. 手动制造一个异常（例如临时把 `core/db.py` 改坏一行）
2. 启动应用应看到红色错误提示 + traceback（不是白屏）
3. 改回后正常

---

## Step 37：顶部统计条

**目标**: 顶部显示 4 个指标: 来源数 / 笔记数 / 闪卡数 / 错题数。

**操作**: 在 `app.py` 主区上方（`left, right = ...` 之前）添加:

```python
def _render_top_metrics(vault_uuid: str, user_id: str) -> None:
    from core.db import db_manager
    docs = db_manager.list_documents(vault_uuid)
    notes = db_manager.list_notes(vault_uuid, user_id)
    cards = db_manager.list_flashcards(vault_uuid)
    wrongs = db_manager.list_wrong_answers(vault_uuid, only_unmastered=True)
    cols = st.columns(4)
    cols[0].metric("来源", f"{len(docs)} / 50")
    cols[1].metric("笔记", len(notes))
    cols[2].metric("闪卡", len(cards))
    cols[3].metric("待复习错题", len(wrongs))

_render_top_metrics(vault_uuid, user_id)
st.divider()
```

**验收**:
1. 数字与各区列表实际数量一致
2. 删除一条来源 → 来源数 -1

---

## Step 38：响应式布局 + 视觉一致

**目标**: 窄屏（<1100px）时 Studio 折叠到 expander；按钮风格统一。

**操作**:
1. `app.py` 顶部 markdown 注入 CSS:
   ```python
   st.markdown("""
   <style>
   /* 紧凑按钮 */
   .stButton button { padding: 0.25rem 0.75rem; }
   /* sidebar 内 expander 标题加粗 */
   section[data-testid="stSidebar"] .streamlit-expanderHeader { font-weight: 600; }
   /* 移动端: 主区竖排 */
   @media (max-width: 1100px) {
     [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
   }
   </style>
   """, unsafe_allow_html=True)
   ```

2. 复查所有按钮 label，移除冗余 emoji（保留功能 emoji 如 ✕ 📝 📥）

**验收**:
1. Chrome 调整窗口宽度 < 1100px
2. Studio 区应自动堆到对话区下方
3. 按钮整体紧凑统一

---

## Step 39：建议问题 + 提交快捷键

**目标**: 空对话时显示 3-5 个"建议问题"按钮；输入框支持 Enter 提交。

**操作**: 在 `chat_panel.py` 的 `render()` 中，`history` 为空且有 docs 时插入:

```python
if not history:
    # 取第一个 doc 的 suggested_questions
    docs = db_manager.list_documents(vault_uuid)
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

# 处理来自建议按钮的待提交查询
pending = st.session_state.pop("_pending_query", None)
query = pending or st.chat_input("提出你的问题...")
```

⚠️ `suggested_questions` 字段在上传时**没自动生成**——本期不强制要求，若字段为空就不显示建议（用户可手动问）。

**验收**:
1. 新对话面板（空历史）→ 若 doc 有 suggested_questions 字段，显示按钮
2. 点按钮 → 自动作为 query 提交
3. Enter 键提交（Streamlit chat_input 默认支持）

---

## Step 40：阶段 E 集成验收

**目标**: 端到端体验跑一遍，确保流畅、美观、无错。

**操作**（人工）:
1. 全新用户 alice2，全新库
2. 上传 1 个 PDF
3. 顶部统计应显示 `来源 1/50, 笔记 0`
4. 对话 → 保存为笔记 → 统计变 `笔记 1`
5. Studio 生成摘要 → 保存 → 笔记 2
6. 生成闪卡 → 入库 → 统计变 `闪卡 N`
7. 生成测验 → 答错 1 道 → 错题 1
8. 错题标记掌握 → 错题 0
9. 笔记导出 MD/Word/PDF 各下载一份打开
10. 窗口缩到 800px → 布局自动堆叠
11. 全程无 Traceback

**记录**:
```
[Step 40] ✅ 阶段 E 集成
- 12 项进度: F12=✅
- 全部 12 项完成度: F1-F12 = ✅
```

---

## ⛳ Checkpoint 8（Step 40 完成后必做）

按规则重读 + 写 Checkpoint 8。

---

## 阶段 E 完成

阅读 `plans/phase_f_final.md`。
