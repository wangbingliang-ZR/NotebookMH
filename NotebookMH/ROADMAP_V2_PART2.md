# NotebookMH 步骤 26-50（续 ROADMAP_V2.md）

> 本文档是 ROADMAP_V2.md 的续篇。铁律、代码规范、文件速查见 ROADMAP_V2.md。

---

### 步骤26：自定义报告

**文件**：`frontend/studio_panel.py`
**做法**：工具卡片之后、笔记列表之前，添加自定义输入框：
```python
    st.divider()
    st.markdown('<p style="font-size:15px;font-weight:600;color:#202124;">自定义生成</p>', unsafe_allow_html=True)
    custom_prompt = st.text_area("描述需求", key="studio_custom", height=80, placeholder="写博客/考前重点/对比分析...")
    if custom_prompt and st.button("生成", key="btn_custom"):
        custom_tool = {
            "key": "custom", "title": "自定义报告",
            "prompt_query": custom_prompt,
            "prompt_gen": f"用户要求：{custom_prompt}\n\n基于以下内容完成：\n\n{{context}}",
            "system": "你是全能助手。用中文回答。",
        }
        _generate_content(vault_uuid, custom_tool)
```
**验证**：`python -m py_compile frontend/studio_panel.py`

---

### 步骤27：闪卡DB表

**文件**：`utils/db_manager.py`
**做法**：添加 ORM + CRUD。

ORM（放在其他 ORM 之后）：
```python
class FlashcardORM(Base):
    __tablename__ = "flashcard_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    mastery = Column(Integer, default=0)  # 0=未学 1=模糊 2=已掌握
    review_count = Column(Integer, default=0)
    created_at = Column(String(32), default=lambda: _utc_now())
```

DatabasePool 中添加：
```python
    def save_flashcards(self, vault_uuid, cards):
        with self.session() as sess:
            for c in cards:
                sess.add(FlashcardORM(vault_uuid=vault_uuid, question=c["question"], answer=c["answer"]))
            sess.commit()

    def list_flashcards(self, vault_uuid):
        with self.session() as sess:
            return sess.query(FlashcardORM).filter_by(vault_uuid=vault_uuid).all()

    def update_flashcard_mastery(self, card_id, mastery):
        with self.session() as sess:
            card = sess.query(FlashcardORM).get(card_id)
            if card:
                card.mastery = mastery
                card.review_count += 1
                sess.commit()

    def delete_all_flashcards(self, vault_uuid):
        with self.session() as sess:
            sess.query(FlashcardORM).filter_by(vault_uuid=vault_uuid).delete()
            sess.commit()
```
**验证**：`python -m py_compile utils/db_manager.py`

---

### 步骤28：闪卡生成改造

**文件**：`frontend/studio_panel.py`
**做法**：
1. 找到 `_STUDIO_TOOLS` 中 key 为 flashcard 的条目，修改 prompt_gen 要求返回 JSON：
```
"返回JSON数组：[{\"question\":\"问题\",\"answer\":\"答案\"}]\n只返回JSON。\n\n内容：\n{context}"
```
2. `_generate_content` 中，检测到 flashcard 时解析 JSON 存 DB：
```python
        if tool["key"] == "flashcard":
            import json as _json
            try:
                cards = _json.loads(result)
                if isinstance(cards, list):
                    from utils.db_manager import db_pool as _db
                    _db.save_flashcards(vault_uuid, cards)
                    save_note(tool["title"], f"已生成 {len(cards)} 张闪卡")
                    st.rerun()
                    return
            except _json.JSONDecodeError:
                pass
```
**易错**：JSON 中的双引号要用 `\"` 转义（在 Python 字符串中）。

---

### 步骤29：闪卡交互UI

**新建文件**：`frontend/flashcard_panel.py`
**完整代码**：
```python
"""交互式闪卡面板"""
import streamlit as st
from utils.state_manager import binder
from utils.db_manager import db_pool


def render():
    vault_uuid = binder.get_state("vault_uuid", "")
    if not vault_uuid:
        st.info("请先选择笔记库。")
        return

    cards = db_pool.list_flashcards(vault_uuid)
    if not cards:
        st.info("暂无闪卡。在Studio点击闪卡生成。")
        return

    idx = st.session_state.get("fc_idx", 0)
    if idx >= len(cards):
        idx = 0
    card = cards[idx]

    st.markdown(f"**{idx+1} / {len(cards)}**")

    # 问题
    st.markdown(
        f'<div style="background:#f0f4ff;border-radius:12px;padding:24px;min-height:80px;font-size:16px;">'
        f'{card.question}</div>', unsafe_allow_html=True,
    )

    show = st.session_state.get("fc_show", False)
    if not show:
        if st.button("显示答案", key="fc_flip", use_container_width=True):
            st.session_state["fc_show"] = True
            st.rerun()
    else:
        st.markdown(
            f'<div style="background:#e8f5e9;border-radius:12px;padding:24px;min-height:80px;font-size:16px;">'
            f'{card.answer}</div>', unsafe_allow_html=True,
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

    mastered = sum(1 for c in cards if c.mastery == 2)
    st.progress(mastered / len(cards), text=f"掌握: {mastered}/{len(cards)}")


def _next(total):
    idx = st.session_state.get("fc_idx", 0) + 1
    st.session_state["fc_idx"] = idx if idx < total else 0
    st.session_state["fc_show"] = False
    st.rerun()
```

然后在 `app.py` 的 Studio 区域添加：
```python
    with st.expander("闪卡练习", expanded=False):
        from frontend import flashcard_panel
        flashcard_panel.render()
```
**验证**：两个文件都 py_compile。

---

### 步骤30：测验DB表

**文件**：`utils/db_manager.py`
**做法**：添加 ORM + CRUD。
```python
class QuizHistoryORM(Base):
    __tablename__ = "quiz_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    options = Column(Text, nullable=False)  # JSON: ["A...", "B...", "C...", "D..."]
    correct = Column(String(8), nullable=False)  # "A" / "B" / "C" / "D"
    explanation = Column(Text, default="")
    user_answer = Column(String(8), default="")
    is_correct = Column(Integer, default=-1)  # -1=未答 0=错 1=对
    created_at = Column(String(32), default=lambda: _utc_now())
```

CRUD：
```python
    def save_quiz_questions(self, vault_uuid, questions):
        """questions = [{"question","options":[],"correct","explanation"}]"""
        import json as _json
        with self.session() as sess:
            for q in questions:
                sess.add(QuizHistoryORM(
                    vault_uuid=vault_uuid, question=q["question"],
                    options=_json.dumps(q.get("options", []), ensure_ascii=False),
                    correct=q.get("correct", ""), explanation=q.get("explanation", ""),
                ))
            sess.commit()

    def list_quiz_unanswered(self, vault_uuid):
        with self.session() as sess:
            return sess.query(QuizHistoryORM).filter_by(vault_uuid=vault_uuid, is_correct=-1).all()

    def answer_quiz(self, quiz_id, user_answer):
        with self.session() as sess:
            q = sess.query(QuizHistoryORM).get(quiz_id)
            if q:
                q.user_answer = user_answer
                q.is_correct = 1 if user_answer == q.correct else 0
                sess.commit()
                return q.is_correct == 1
        return False
```

---

### 步骤31：测验生成

**文件**：`frontend/studio_panel.py`
**做法**：`_STUDIO_TOOLS` 的测验条目 prompt 改为要求 JSON 返回：
```
返回JSON数组：[{"question":"题目","options":["A.xx","B.xx","C.xx","D.xx"],"correct":"A","explanation":"解析"}]
只返回JSON。
```
`_generate_content` 中检测 quiz/test，解析 JSON 存 DB。

---

### 步骤32：测验交互UI

**新建文件**：`frontend/quiz_panel.py`
**结构**（参考步骤29闪卡面板）：
- 显示题目 + `st.radio` 选项
- 提交按钮 → `db_pool.answer_quiz` → 显示对错+解析
- 下一题按钮
- 底部显示正确率

然后在 `app.py` Studio区域添加 `st.expander("测验")` 调用。

---

### 步骤33：闪卡/测验参数

**文件**：`frontend/studio_panel.py`
**做法**：闪卡和测验按钮改为 `st.expander`，内有：
- `st.slider("数量", 5, 30, 10)`
- `st.selectbox("难度", ["基础","中等","困难"])`
- `st.text_input("主题（可选）")`
- 生成按钮

动态构建 prompt 拼入参数。

---

### 步骤34：笔记持久化DB

**文件**：`utils/db_manager.py`
```python
class NoteORM(Base):
    __tablename__ = "note_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    pinned = Column(Integer, default=0)
    created_at = Column(String(32), default=lambda: _utc_now())
```
添加 save/list/update/delete CRUD。

---

### 步骤35：笔记迁移到DB

**文件**：`frontend/studio_panel.py`
**做法**：`save_note` 从写 session_state 改为写 DB。`_render_notes` 从 DB 读取。

---

### 步骤36：笔记编辑+置顶

**文件**：`frontend/studio_panel.py`
**做法**：每条笔记添加编辑按钮（展开为 text_area）和置顶 checkbox。查询时 ORDER BY pinned DESC。

---

### 步骤37：导出Markdown

**文件**：`frontend/studio_panel.py`
**做法**：笔记列表上方添加：
```python
    all_notes = db_pool.list_notes(vault_uuid, user_id)
    if all_notes:
        md = "\n\n---\n\n".join(f"## {n.title}\n{n.content}" for n in all_notes)
        st.download_button("导出MD", md.encode("utf-8"), "notes.md", "text/markdown")
```

---

### 步骤38：导出Word

**文件**：`frontend/studio_panel.py`
**做法**：用 `python-docx`（已在 requirements）：
```python
    if st.button("导出Word", key="btn_export_docx"):
        from docx import Document
        import io
        doc = Document()
        for n in all_notes:
            doc.add_heading(n.title, level=2)
            doc.add_paragraph(n.content)
        buf = io.BytesIO()
        doc.save(buf)
        st.download_button("下载", buf.getvalue(), "notes.docx")
```

---

### 步骤39：来源详情面板

**新建文件**：`frontend/source_detail_panel.py`
**功能**：显示单个来源的摘要、关键主题、建议问题、chunk 列表。
**路由**：用 session_state `selected_source_hash` 控制。在来源列表的 expander 中添加"查看详情"按钮。

---

### 步骤40：来源全文存储

**文件**：`utils/db_manager.py` + `core/rag_pipeline.py`
**做法**：
1. DocumentRegistryORM 添加 `full_text = Column(Text, default="")`
2. 迁移 ALTER TABLE
3. ingest_document 中存 `text[:50000]`

---

### 步骤41：来源全文预览

**文件**：`frontend/source_detail_panel.py`
**做法**：`st.expander("原文")` 中用 `st.text_area(disabled=True)` 显示。

---

### 步骤42：来源选择性对话

**文件**：`frontend/ingestion_panel.py`
**做法**：每个来源加 `st.checkbox`，选中的 hash 存 `st.session_state["selected_sources"]`。
**文件**：`core/cognitive_engine.py`
**做法**：检索时 filter `content_hash in selected_sources`。

---

### 步骤43：错题记录DB

**文件**：`utils/db_manager.py`
```python
class WrongAnswerORM(Base):
    __tablename__ = "wrong_answer_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    user_answer = Column(String(256), default="")
    correct_answer = Column(String(256), default="")
    explanation = Column(Text, default="")
    mastered = Column(Integer, default=0)  # 0=未掌握 1=已掌握
    created_at = Column(String(32), default=lambda: _utc_now())
```

---

### 步骤44：错题复盘面板

**新建文件**：`frontend/review_panel.py`
**功能**：显示未掌握错题，重新作答后标记掌握。结构参考闪卡面板。

---

### 步骤45：学习进度看板

**新建文件**：`frontend/progress_panel.py`
**功能**：4个 `st.metric` 显示来源数/笔记数/闪卡掌握率/待复习错题数。在 Studio 面板顶部调用。

---

### 步骤46：更多格式 - MD/CSV/JSON

**文件**：`frontend/ingestion_panel.py`（type列表加 md/csv/json）
**文件**：`core/rag_pipeline.py`（`_parse_document` 添加分支）
- `.md`：直接当文本处理
- `.csv`：`csv.reader` 转文本
- `.json`：`json.dumps(indent=2)` 转文本

---

### 步骤47：更多格式 - PPTX

**文件**：`core/rag_pipeline.py`
**前置**：`pip install python-pptx`（已在 requirements）
```python
async def _parse_pptx(self, file_bytes):
    from pptx import Presentation
    import io
    prs = Presentation(io.BytesIO(file_bytes))
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                texts.append(shape.text.strip())
    return "\n\n".join(texts), len(prs.slides)
```

---

### 步骤48：图片OCR

**文件**：`core/rag_pipeline.py` + `frontend/ingestion_panel.py`
**做法**：上传器 type 加 png/jpg/jpeg。用已有的 `rapidocr-onnxruntime` 做 OCR。
```python
async def _parse_image(self, file_bytes):
    import io
    def _sync():
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image
        import numpy as np
        ocr = RapidOCR()
        img = Image.open(io.BytesIO(file_bytes))
        result, _ = ocr(np.array(img))
        if result:
            return "\n".join(str(item[1]) for item in result if isinstance(item, (list,tuple)) and len(item)>1), 1
        return "", 0
    return await asyncio.to_thread(_sync)
```

---

### 步骤49：全局错误处理

**文件**：`app.py`
**做法**：在 main 函数最外层加 try/except：
```python
try:
    # 原有代码
except Exception as e:
    st.error(f"系统错误: {e}")
    import traceback
    with st.expander("错误详情"):
        st.code(traceback.format_exc())
```

---

### 步骤50：响应式布局

**文件**：`app.py`（CSS 部分，此步骤允许改 CSS）
**做法**：添加媒体查询：
```css
@media (max-width: 768px) {
    [data-testid="stHorizontalBlock"] { flex-direction: column !important; }
    [data-testid="stHorizontalBlock"] > div { width: 100% !important; }
}
```

---

## NotebookLM 功能对照

| NotebookLM 功能 | 步骤 | 覆盖 |
|----------------|------|------|
| PDF/DOCX/TXT | 已完成 | 100% |
| 网页URL | 06-07 | 100% |
| 粘贴文本 | 08 | 100% |
| 图片OCR | 48 | 100% |
| CSV/MD/JSON | 46 | 100% |
| PPTX | 47 | 100% |
| 50来源上限 | 09-10 | 100% |
| 来源选择过滤 | 42 | 100% |
| 来源摘要 | 11-13 | 100% |
| 来源全文 | 40-41 | 100% |
| 多轮对话 | 18 | 100% |
| 引用[1][2] | 21-22 | 100% |
| 流式输出 | 16-17 | 100% |
| 建议问题 | 14-15 | 100% |
| 历史持久化 | 19-20 | 100% |
| 思维导图 | 23-24 | 90% |
| 数据表格 | 25 | 100% |
| 自定义报告 | 26 | 100% |
| 闪卡交互 | 27-29,33 | 100% |
| 测验交互 | 30-33 | 100% |
| 笔记持久化 | 34-36 | 100% |
| 导出MD/Word | 37-38 | 100% |
| 错题复盘 | 43-44 | 100% |
| 学习进度 | 45 | 100% |
| Audio/Video | 不做 | 0% |
| Infographic | 不做 | 0% |
| Slide Deck | 不做 | 0% |

**完成50步后覆盖 NotebookLM 可实现功能的 ~88%。**
