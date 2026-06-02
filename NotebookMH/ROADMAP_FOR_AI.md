# NotebookMH 功能开发路线图 — 对标 NotebookLM

> **文档用途**：本文档是给后续 AI 编程助手（如 Kimi K2.6）的**完整开发指南**。  
> **使用方法**：每次开新会话时，让 AI 先读此文档，然后从"当前进度"标记处继续执行。  
> **项目路径**：`c:\大饼的ai助手\zijiannotebookdb\NotebookMH`  
> **技术栈**：Python 3.12 + Streamlit + SQLAlchemy/SQLite + ChromaDB + sentence-transformers + DeepSeek API  
> **排除功能**：不做视频生成、不做音频播客生成（Audio Overview）

---

## 当前已完成的功能清单

| 模块 | 状态 | 文件 |
|------|------|------|
| PDF/DOCX/TXT 文档解析 | ✅ 完成 | `core/rag_pipeline.py` |
| OCR fallback（扫描版 PDF） | ✅ 完成 | `core/rag_pipeline.py` |
| 语义切块（800字+150重叠） | ✅ 完成 | `core/rag_pipeline.py` `SemanticAnatomyKnife` |
| 向量嵌入 (all-MiniLM-L6-v2) | ✅ 完成 | `core/rag_pipeline.py` |
| ChromaDB 稠密向量检索 | ✅ 完成 | `core/rag_pipeline.py` |
| BM25 稀疏关键词检索 | ✅ 完成 | `core/rag_pipeline.py` `HybridRetriever` |
| RRF 排名融合 + 重排序 | ✅ 完成 | `core/rag_pipeline.py` |
| DeepSeek LLM 调用 | ✅ 完成 | `core/llm_engine.py` |
| Mock 降级（无 API Key） | ✅ 完成 | `core/llm_engine.py` |
| 多文件批量上传 | ✅ 完成 | `frontend/ingestion_panel.py` |
| 认知状态机 (Learning/Quizzing/Review) | ✅ 完成 | `core/cognitive_engine.py` |
| 教师人格引擎 | ✅ 完成 | `core/persona_engine.py` |
| Studio 面板 6 个生成工具 | ✅ 完成 | `frontend/studio_panel.py` |
| 笔记保存 | ✅ 完成 | `frontend/studio_panel.py` |
| 用户/Vault 隔离 | ✅ 完成 | `utils/db_manager.py` |
| 白色极简 UI 主题 | ✅ 完成 | `app.py` CSS |

---

## 需要开发的功能（共 25 个步骤）

每个步骤标注：
- **目标**：做什么
- **文件**：改哪些文件
- **详细做法**：具体代码改动
- **验收标准**：怎样算完成
- **依赖**：需要先完成哪个步骤

---

### 步骤 1：网页 URL 来源摄入

**目标**：用户可以粘贴一个网页 URL，系统自动抓取网页内容，作为来源文档存入知识库。对标 NotebookLM 的"Add Website URL"功能。

**文件**：
- 修改 `frontend/ingestion_panel.py` — 添加 URL 输入框
- 修改 `core/rag_pipeline.py` — 添加 `_parse_url` 方法
- 修改 `utils/db_manager.py` — `register_document` 支持 URL 类型来源

**详细做法**：

1. 在 `ingestion_panel.py` 的 `render()` 函数中，在文件上传器**下方**添加：
```python
st.divider()
st.markdown("**或添加网页链接**")
url_input = st.text_input("粘贴网页 URL", key="nb_mh_url_input", placeholder="https://example.com/article")
if url_input and st.button("添加网页来源", key="btn_ingest_url"):
    _run_url_ingestion(console, url_input, vault_uuid)
```

2. 新增 `_run_url_ingestion` 函数，逻辑：
   - 用 `httpx` GET 请求抓取网页 HTML
   - 用 `beautifulsoup4`（需加入 requirements.txt）提取正文文本
   - 移除 `<script>`, `<style>`, `<nav>`, `<footer>` 等非正文标签
   - 提取 `<title>` 作为文件名
   - 将提取的文本转为 bytes，调用现有的 `_run_ingestion(console, text_bytes, title, vault_uuid)`

3. 在 `core/rag_pipeline.py` 的 `IngestionPipeline` 类中添加：
```python
async def _parse_url(self, url: str) -> Tuple[str, int]:
    """抓取网页并提取正文。"""
    import httpx
    from bs4 import BeautifulSoup
    
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    title = soup.title.string if soup.title else url
    page_count = max(1, len(text) // 1800)
    return text, page_count
```

4. 在 `requirements.txt` 添加：`beautifulsoup4>=4.12.0`

**验收标准**：粘贴一个知乎文章或维基百科 URL → 点击"添加网页来源" → 左侧来源列表出现该网页 → Studio 能基于该网页生成摘要。

**依赖**：无

---

### 步骤 2：来源数量上限管理（50 个来源）

**目标**：对标 NotebookLM 的 50 来源上限。在 UI 上显示"X / 50 来源"，超过 50 时禁止继续添加。

**文件**：
- 修改 `frontend/ingestion_panel.py`
- 可选：`utils/db_manager.py` 添加 `count_documents(vault_uuid)` 方法

**详细做法**：

1. 在 `utils/db_manager.py` 的 `DatabasePool` 类中添加：
```python
def count_documents(self, vault_uuid: str) -> int:
    """统计某 Vault 下的文档数量。"""
    with self.session() as sess:
        return sess.query(DocumentRegistryORM).filter_by(vault_uuid=vault_uuid).count()
```

2. 在 `ingestion_panel.py` 的 `render()` 顶部：
```python
MAX_SOURCES = 50
vault_uuid = binder.get_state("vault_uuid", "default_vault")
doc_count = db_pool.count_documents(vault_uuid) if vault_uuid else 0
st.caption(f"来源: {doc_count} / {MAX_SOURCES}")

if doc_count >= MAX_SOURCES:
    st.warning(f"已达到 {MAX_SOURCES} 个来源上限，请删除旧来源后再添加。")
    _render_document_list()
    return  # 不再显示上传器
```

3. 上传按钮处也要检查：上传 N 个文件后不能超过 50，超过的部分跳过并提示。

**验收标准**：显示 "来源: 3 / 50"；上传超过 50 个文件时提示并阻止。

**依赖**：无

---

### 步骤 3：来源级别摘要（自动生成）

**目标**：每次上传新文档后，自动生成该文档的摘要和关键主题，存入数据库。对标 NotebookLM 点击来源时显示的"Source Overview"。

**文件**：
- 修改 `utils/db_manager.py` — 给 `DocumentRegistryORM` 添加 `summary` 和 `key_topics` 字段
- 修改 `core/rag_pipeline.py` — 摄入完成后自动调用 LLM 生成摘要
- 修改 `frontend/ingestion_panel.py` — 来源列表点击可展开显示摘要

**详细做法**：

1. 在 `utils/db_manager.py` 的 `DocumentRegistryORM` 添加两列：
```python
summary = Column(Text, default="")
key_topics = Column(Text, default="")  # JSON 字符串: ["主题1", "主题2", ...]
```

2. 在 `DatabasePool` 类添加：
```python
def update_document_summary(self, vault_uuid: str, content_hash: str, summary: str, key_topics: str) -> None:
    with self.session() as sess:
        doc = sess.query(DocumentRegistryORM).filter_by(
            vault_uuid=vault_uuid, content_hash=content_hash
        ).first()
        if doc:
            doc.summary = summary
            doc.key_topics = key_topics
            sess.commit()
```

3. 在 `core/rag_pipeline.py` 的 `ingest_document` 方法中，`DONE` 事件之前添加：
```python
# ── Step 8: 自动生成来源摘要 ────────────────────────
yield {"status": "SUMMARIZING", "elapsed_ms": _ms(t0)}
try:
    from core.llm_engine import get_llm_engine
    llm = get_llm_engine()
    full_text = text[:3000]  # 取前 3000 字避免超长
    summary = await llm.ask_simple(
        f"请用中文为以下文档写一段 100 字以内的摘要：\n\n{full_text}",
        system_prompt="你是文档摘要助手。"
    )
    topics_resp = await llm.ask_simple(
        f"请从以下文档中提取 5 个关键主题词（用逗号分隔）：\n\n{full_text}",
        system_prompt="你是关键词提取助手。只返回逗号分隔的关键词。"
    )
    db_pool.update_document_summary(vault_uuid, content_hash, summary, topics_resp)
    yield {"status": "SUMMARY_OK", "elapsed_ms": _ms(t0)}
except Exception as e:
    logger.warning("Auto-summary failed (non-critical): %s", e)
    yield {"status": "SUMMARY_SKIP", "elapsed_ms": _ms(t0)}
```

4. 在 `frontend/ingestion_panel.py` 的 `_render_document_list` 中，把每个文档改为 `st.expander`：
```python
for doc in docs:
    with st.expander(f"{doc.file_name} ({size_kb:.1f}KB)"):
        if doc.summary:
            st.markdown(f"**摘要**: {doc.summary}")
        if doc.key_topics:
            st.markdown(f"**关键主题**: {doc.key_topics}")
        if st.button("删除", key=f"btn_del_{doc.content_hash}"):
            db_pool.delete_document(vault_uuid, doc.content_hash)
            st.rerun()
```

5. **数据库迁移**：因为添加了新列，需要在 `DatabasePool.__init__` 中加迁移逻辑：
```python
# 检查并添加新列（向后兼容）
with self.session() as sess:
    inspector = inspect(self._engine)
    columns = [c["name"] for c in inspector.get_columns("document_registry")]
    if "summary" not in columns:
        sess.execute(text("ALTER TABLE document_registry ADD COLUMN summary TEXT DEFAULT ''"))
    if "key_topics" not in columns:
        sess.execute(text("ALTER TABLE document_registry ADD COLUMN key_topics TEXT DEFAULT ''"))
    sess.commit()
```

**验收标准**：上传一个 PDF → 左侧来源列表点击展开 → 可看到自动生成的摘要和关键主题。

**依赖**：无

---

### 步骤 4：聊天中的来源引用（Inline Citations）

**目标**：对标 NotebookLM 最核心的功能——AI 回答时附带来源引用标记，如 [1][2]，点击可跳转到原文段落。

**文件**：
- 修改 `core/llm_engine.py` — 修改 `rag_answer` 的 prompt，要求 LLM 在回答中标注引用
- 修改 `core/cognitive_engine.py` — 将检索到的 chunks 元数据传递给前端
- 修改 `frontend/cognitive_panel.py` — 渲染引用标记和来源弹窗

**详细做法**：

1. 修改 `core/llm_engine.py` 中 `rag_answer` 的 prompt：
```python
rag_prompt = f"""请根据以下检索到的知识片段回答问题。

【用户问题】
{question}

【检索到的知识片段】
{context_str}

【要求】
- 仅基于上述知识片段作答
- 在回答中用 [1] [2] 等标记引用了哪个知识片段
- 如果知识不足以回答，请诚实说明
- 返回 JSON 格式: {{"explanation": "你的回答（含引用标记）", "citations": [1, 2]}}
"""
```

2. 在 `AIResponse` 模型中添加：
```python
citations: Optional[List[int]] = Field(None, description="引用的知识片段编号列表")
```

3. 修改 `core/cognitive_engine.py` 的 `_learning_flow` 返回值，增加 `chunks` 字段：
```python
return {
    "type": "socratic",
    "text": text,
    "probe": probe,
    "context_snippets": len(context.split("---")),
    "source_chunks": chunks,  # 新增：传递原始检索结果给前端
}
```

4. 修改 `frontend/cognitive_panel.py` 渲染聊天消息时：
   - 检测文本中的 `[1]`、`[2]` 标记
   - 在消息下方显示"来源引用"折叠区域
   - 点击编号展开对应的原文片段

```python
# 在渲染 AI 回复后
source_chunks = item.get("source_chunks", [])
if source_chunks:
    with st.expander("查看来源引用"):
        for i, chunk in enumerate(source_chunks, 1):
            st.markdown(f"**[{i}]** {chunk.get('metadata', {}).get('header_hierarchy', '未知来源')}")
            st.caption(chunk.get("chunk_text", "")[:200] + "...")
```

**验收标准**：在聊天中提问 → AI 回答带 [1][2] 引用 → 点击"查看来源引用"可看到原文片段。

**依赖**：无

---

### 步骤 5：.env 文件自动加载

**目标**：确保 `.env` 文件中的 `DEEPSEEK_API_KEY` 等环境变量在应用启动时自动加载。目前 `llm_engine.py` 直接用 `os.getenv()`，但 Streamlit 启动时不一定加载 `.env`。

**文件**：
- 修改 `app.py` — 在最顶部加载 `.env`

**详细做法**：

在 `app.py` 的最顶部（import 之后、`st.set_page_config` 之前）添加：
```python
from dotenv import load_dotenv
load_dotenv()  # 加载 .env 文件中的环境变量
```

`requirements.txt` 已有 `python-dotenv>=1.0.0`，无需添加。

**验收标准**：启动应用后，`os.getenv("DEEPSEEK_API_KEY")` 返回有效值；LLM 不再走 Mock 模式。

**依赖**：无

---

### 步骤 6：交互式闪卡 UI

**目标**：对标 NotebookLM 的 Flashcards 功能。不只是生成文字，而是真正的**翻转卡片 UI**：正面显示问题，点击翻转显示答案，用户可标记"已掌握/未掌握"，系统跟踪掌握率。

**文件**：
- 新建 `frontend/flashcard_panel.py`
- 修改 `frontend/studio_panel.py` — 闪卡按钮改为跳转到闪卡面板
- 修改 `utils/db_manager.py` — 添加 `flashcard_registry` 表
- 修改 `app.py` — 添加闪卡面板路由

**详细做法**：

1. 在 `utils/db_manager.py` 添加新 ORM 模型：
```python
class FlashcardORM(Base):
    __tablename__ = "flashcard_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    mastery = Column(Integer, default=0)  # 0=未学, 1=模糊, 2=已掌握
    review_count = Column(Integer, default=0)
    created_at = Column(String(32), default=lambda: _utc_now())
```

2. 添加 CRUD 方法：`save_flashcards(vault_uuid, cards)`, `list_flashcards(vault_uuid)`, `update_flashcard_mastery(card_id, mastery)`

3. 修改 `frontend/studio_panel.py` 中闪卡工具的生成逻辑：
   - LLM prompt 改为要求返回 JSON 数组格式：`[{"question": "...", "answer": "..."}, ...]`
   - 解析 JSON 并存入 `flashcard_registry` 表
   - 生成完成后用 `st.session_state["show_flashcards"] = True` 切换视图

4. 新建 `frontend/flashcard_panel.py`：
```python
def render():
    cards = db_pool.list_flashcards(vault_uuid)
    if not cards:
        st.info("暂无闪卡，请在 Studio 中生成。")
        return
    
    # 当前卡片索引
    idx = st.session_state.get("fc_index", 0)
    card = cards[idx]
    
    st.markdown(f"**卡片 {idx+1} / {len(cards)}**")
    
    # 正面（问题）
    st.markdown(f'<div style="background:#f0f4ff; border-radius:12px; padding:24px; min-height:120px; font-size:16px;">{card.question}</div>', unsafe_allow_html=True)
    
    # 翻转按钮
    if st.button("显示答案", key="fc_flip"):
        st.session_state["fc_show_answer"] = True
    
    if st.session_state.get("fc_show_answer"):
        st.markdown(f'<div style="background:#e8f5e9; border-radius:12px; padding:24px; font-size:16px;">{card.answer}</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("未掌握", key="fc_fail"):
                db_pool.update_flashcard_mastery(card.id, 0)
                _next_card(cards)
        with col2:
            if st.button("模糊", key="fc_fuzzy"):
                db_pool.update_flashcard_mastery(card.id, 1)
                _next_card(cards)
        with col3:
            if st.button("已掌握", key="fc_pass"):
                db_pool.update_flashcard_mastery(card.id, 2)
                _next_card(cards)
    
    # 进度条
    mastered = sum(1 for c in cards if c.mastery == 2)
    st.progress(mastered / len(cards), text=f"掌握率: {mastered}/{len(cards)}")
```

**验收标准**：Studio 生成闪卡 → 进入闪卡面板 → 正面显示问题 → 点击翻转 → 标记掌握度 → 进度条更新。

**依赖**：步骤 5

---

### 步骤 7：交互式测验系统（选择题 + 判分）

**目标**：对标 NotebookLM 的 Quiz 功能。生成选择题，用户作答后即时判分，显示正确答案和解析。

**文件**：
- 修改 `core/cognitive_engine.py` — 优化 quizzing_flow 的 prompt，生成标准选择题
- 新建 `frontend/quiz_panel.py` — 独立的测验 UI
- 修改 `utils/db_manager.py` — 添加 `quiz_history` 表记录测试结果

**详细做法**：

1. 定义测验题 Pydantic 模型（在 `core/llm_engine.py`）：
```python
class QuizQuestion(BaseModel):
    question: str
    options: List[str]  # ["A. xxx", "B. xxx", "C. xxx", "D. xxx"]
    correct: str  # "A" / "B" / "C" / "D"
    explanation: str  # 答案解析

class QuizSet(BaseModel):
    questions: List[QuizQuestion]
```

2. 在 Studio 面板添加"生成测验"按钮，prompt 要求 LLM 返回 QuizSet JSON：
```
请基于以下内容生成 10 道选择题（每题 4 个选项），返回 JSON：
{"questions": [{"question": "...", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], "correct": "A", "explanation": "..."}]}
```

3. 用 `llm.structured_extract(prompt, QuizSet)` 解析。

4. 新建 `frontend/quiz_panel.py`：
   - 逐题显示，用 `st.radio` 让用户选择
   - 提交后判分，显示对错和解析
   - 最后显示总分和错题列表
   - 错题存入数据库，供步骤 12 复盘使用

**验收标准**：点击"生成测验" → 显示 10 道选择题 → 用户作答 → 提交后看到分数和解析。

**依赖**：步骤 5

---

### 步骤 8：对话历史持久化

**目标**：保存聊天记录到数据库，下次打开应用可恢复历史对话。对标 NotebookLM 的对话持久性。

**文件**：
- 修改 `utils/db_manager.py` — 添加 `chat_history` 表
- 修改 `frontend/cognitive_panel.py` — 每条消息存入数据库，启动时恢复

**详细做法**：

1. 在 `utils/db_manager.py` 添加：
```python
class ChatHistoryORM(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    role = Column(String(16), nullable=False)  # "user" / "assistant"
    content = Column(Text, nullable=False)
    msg_type = Column(String(32), default="text")  # "text", "quiz", "socratic"
    metadata_json = Column(Text, default="{}")  # 额外元数据 JSON
    created_at = Column(String(32), default=lambda: _utc_now())
```

2. 添加方法：
   - `save_chat_message(vault_uuid, user_id, role, content, msg_type, metadata)`
   - `load_chat_history(vault_uuid, user_id, limit=100) -> List[ChatHistoryORM]`
   - `clear_chat_history(vault_uuid, user_id)`

3. 修改 `frontend/cognitive_panel.py`：
   - 在 `render()` 顶部，从数据库恢复 `st.session_state` 中的聊天记录
   - 每次发送/接收消息后，调用 `save_chat_message` 存入数据库
   - 添加"清空对话"按钮

**验收标准**：发送几条消息 → 刷新页面 → 历史对话仍在 → 可以清空。

**依赖**：无

---

### 步骤 9：笔记编辑与管理

**目标**：对标 NotebookLM 的 Notes 功能。笔记可以编辑、置顶、搜索，不只是只读列表。

**文件**：
- 修改 `frontend/studio_panel.py` — 增强笔记管理
- 修改 `utils/db_manager.py` — 笔记持久化到数据库（目前只在 session_state）

**详细做法**：

1. 在 `utils/db_manager.py` 添加：
```python
class NoteORM(Base):
    __tablename__ = "note_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    pinned = Column(Integer, default=0)  # 0=未置顶, 1=置顶
    created_at = Column(String(32), default=lambda: _utc_now())
    updated_at = Column(String(32), default=lambda: _utc_now())
```

2. CRUD 方法：`save_note`, `list_notes`, `update_note`, `delete_note`, `toggle_pin`

3. 修改 `frontend/studio_panel.py` 的笔记区：
   - 笔记从数据库加载（不再只用 session_state）
   - 每条笔记支持：编辑（`st.text_area`）、置顶、删除
   - 置顶笔记排在最前
   - 添加"新建笔记"按钮，用户可手动写笔记
   - 添加搜索框，按关键词过滤笔记

**验收标准**：笔记持久化 → 刷新不丢失 → 可编辑 → 可置顶 → 可搜索。

**依赖**：无

---

### 步骤 10：来源概览面板（Source Overview）

**目标**：对标 NotebookLM 点击来源后显示的详细概览。包括：文档摘要、关键主题、可以针对单个来源提问。

**文件**：
- 新建 `frontend/source_detail_panel.py`
- 修改 `frontend/ingestion_panel.py` — 点击来源名称进入详情
- 修改 `app.py` — 路由来源详情视图

**详细做法**：

1. 在 `frontend/ingestion_panel.py` 的来源列表中，点击来源名称时：
```python
if st.button(doc.file_name, key=f"btn_view_{doc.content_hash}"):
    st.session_state["viewing_source"] = doc.content_hash
    st.rerun()
```

2. 新建 `frontend/source_detail_panel.py`：
```python
def render(content_hash: str):
    doc = db_pool.get_document(vault_uuid, content_hash)
    st.markdown(f"### {doc.file_name}")
    st.markdown(f"**摘要**: {doc.summary}")
    st.markdown(f"**关键主题**: {doc.key_topics}")
    st.markdown(f"**大小**: {doc.doc_size/1024:.1f}KB | **页数**: {doc.page_count}")
    
    # 来源级问答
    st.divider()
    question = st.text_input("针对此来源提问", key="source_qa_input")
    if question and st.button("提问"):
        # 只检索该文档的 chunks
        chunks = db_pool.get_chunks_by_doc(vault_uuid, content_hash)
        # ... LLM 回答
```

3. 在 `utils/db_manager.py` 添加 `get_document` 和 `get_chunks_by_doc` 方法。

**验收标准**：左侧来源列表点击文档名 → 进入来源详情 → 可看到摘要/主题 → 可针对该来源单独提问。

**依赖**：步骤 3

---

### 步骤 11：Markdown / 纯文本来源支持增强

**目标**：除了 PDF/DOCX/TXT，还支持 .md (Markdown)、.csv、.json 文件上传。增加来源类型覆盖面。

**文件**：
- 修改 `frontend/ingestion_panel.py` — 扩展 file_uploader 的 type 列表
- 修改 `core/rag_pipeline.py` — 添加 `_parse_csv` 和 `_parse_markdown` 方法

**详细做法**：

1. 修改上传器：
```python
type=["pdf", "docx", "txt", "md", "csv", "json"]
```

2. 在 `_parse_document` 方法中添加分支：
```python
if file_name.lower().endswith(".md"):
    return file_bytes.decode("utf-8", errors="ignore"), 1
if file_name.lower().endswith(".csv"):
    return await self._parse_csv(file_bytes)
if file_name.lower().endswith(".json"):
    return await self._parse_json(file_bytes)
```

3. CSV 解析：用 `pandas.read_csv` 将表格转为文本描述。
4. JSON 解析：递归提取所有字符串值，拼接为文本。

**验收标准**：上传 .md / .csv / .json 文件 → 成功解析 → 可被检索。

**依赖**：无

---

### 步骤 12：错题复盘系统

**目标**：对标 NotebookLM 的复习功能。收集用户在测验和闪卡中的错误，生成错题本，支持针对性复习。

**文件**：
- 新建 `frontend/review_panel.py`
- 修改 `utils/db_manager.py` — 添加 `wrong_answer_registry` 表
- 修改 `frontend/quiz_panel.py` — 错题自动记录
- 修改 `frontend/flashcard_panel.py` — "未掌握"的卡片记录

**详细做法**：

1. 在 `utils/db_manager.py` 添加：
```python
class WrongAnswerORM(Base):
    __tablename__ = "wrong_answer_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    user_answer = Column(Text, default="")
    correct_answer = Column(Text, nullable=False)
    explanation = Column(Text, default="")
    source_type = Column(String(32), default="quiz")  # "quiz" / "flashcard"
    review_count = Column(Integer, default=0)
    mastered = Column(Integer, default=0)  # 0=未掌握 1=已掌握
    created_at = Column(String(32), default=lambda: _utc_now())
```

2. 在 `quiz_panel.py` 判分后，将错题调用 `db_pool.save_wrong_answer(...)` 存入。

3. 新建 `frontend/review_panel.py`：
   - 显示所有未掌握的错题
   - 可重新作答，答对后标记为已掌握
   - 显示错题统计：总数、已掌握、待复习
   - 可生成"错题针对性练习"：将错题涉及的知识点发给 LLM，生成新的练习题

4. 在 Studio 面板添加"错题复盘"入口按钮。

**验收标准**：做测验答错 → 错题自动入库 → 错题复盘面板可查看 → 重新作答后标记已掌握。

**依赖**：步骤 7

---

### 步骤 13：学习进度看板

**目标**：显示用户学习进度概览，包括：来源数量、笔记数量、闪卡掌握率、测验平均分、学习时长。

**文件**：
- 新建 `frontend/progress_panel.py`
- 修改 `app.py` — 在主区域顶部或 Studio 面板中嵌入进度概览

**详细做法**：

1. 新建 `frontend/progress_panel.py`：
```python
def render():
    vault_uuid = binder.get_state("vault_uuid", "")
    user_id = binder.get_state("user_id", "")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        doc_count = db_pool.count_documents(vault_uuid)
        st.metric("来源数", f"{doc_count}/50")
    with col2:
        note_count = db_pool.count_notes(vault_uuid, user_id)
        st.metric("笔记", note_count)
    with col3:
        cards = db_pool.list_flashcards(vault_uuid)
        mastered = sum(1 for c in cards if c.mastery == 2)
        total = len(cards)
        st.metric("闪卡掌握", f"{mastered}/{total}" if total else "0")
    with col4:
        wrongs = db_pool.count_wrong_answers(vault_uuid, user_id, mastered=0)
        st.metric("待复习错题", wrongs)
```

2. 在 `app.py` 的 `chat_col` 顶部渲染进度面板（或放在 Studio 面板顶部）。

**验收标准**：打开应用即可看到 4 个指标卡：来源数 / 笔记数 / 闪卡掌握率 / 待复习错题。

**依赖**：步骤 6, 7, 9, 12

---

### 步骤 14：导出功能（笔记/学习指南导出为文件）

**目标**：用户可以把笔记、学习指南、测验结果导出为 Markdown 或 DOCX 文件下载。

**文件**：
- 修改 `frontend/studio_panel.py` — 添加导出按钮
- 可选新建 `utils/export_helper.py`

**详细做法**：

1. 在 Studio 面板每条笔记卡片上添加"导出"按钮。

2. 导出逻辑：
```python
import io

def export_as_markdown(notes: list) -> bytes:
    content = "# NotebookMH 学习笔记\n\n"
    for note in notes:
        content += f"## {note['title']}\n\n{note['content']}\n\n---\n\n"
    return content.encode("utf-8")

# Streamlit 下载按钮
md_bytes = export_as_markdown(notes)
st.download_button("导出为 Markdown", data=md_bytes, file_name="notes.md", mime="text/markdown")
```

3. 可选：用 `python-docx` 生成 DOCX 文件（requirements.txt 已有）：
```python
from docx import Document
doc = Document()
doc.add_heading("NotebookMH 学习笔记", 0)
for note in notes:
    doc.add_heading(note["title"], level=1)
    doc.add_paragraph(note["content"])
buf = io.BytesIO()
doc.save(buf)
st.download_button("导出为 Word", data=buf.getvalue(), file_name="notes.docx")
```

**验收标准**：点击导出按钮 → 浏览器下载 .md 或 .docx 文件 → 内容正确。

**依赖**：步骤 9

---

### 步骤 15：多轮对话上下文管理

**目标**：当前每次提问都是独立的。需要将最近 N 轮对话作为上下文传给 LLM，使 AI 能记住之前的问答。

**文件**：
- 修改 `core/cognitive_engine.py` — `generate_response` 接收并使用 `chat_history`
- 修改 `core/llm_engine.py` — `_post_chat` 支持多轮 messages 列表
- 修改 `frontend/cognitive_panel.py` — 将历史消息传入 engine

**详细做法**：

1. `cognitive_engine.py` 已有 `chat_history` 参数，但目前只用于情绪评估。需要在 `_learning_flow` 中将最近 5 轮对话拼入 messages：
```python
# 构建多轮消息
messages = [{"role": "system", "content": system_prompt}]
for msg in (chat_history or [])[-10:]:  # 最近 10 条
    messages.append({"role": msg["role"], "content": msg["content"]})
messages.append({"role": "user", "content": user_input})
```

2. 修改 `_post_chat` 使其直接接收完整的 messages 列表（已支持）。

3. 在 `frontend/cognitive_panel.py` 发送请求时，把 `st.session_state` 中的历史记录传入：
```python
history = [
    {"role": item["role"], "content": item.get("text", item.get("content", ""))}
    for item in st.session_state.get("cognitive_chat_history", [])
]
result = await engine.generate_response(
    user_input=user_input,
    current_state=current_state,
    vault_uuid=vault_uuid,
    chat_history=history,
    ...
)
```

**验收标准**：连续提问"光合作用是什么" → "它的产物是什么" → AI 能理解"它"指光合作用。

**依赖**：无

---

### 步骤 16：全局搜索功能

**目标**：在聊天区顶部添加搜索框，可以搜索所有来源文档的内容，快速定位知识。

**文件**：
- 修改 `frontend/cognitive_panel.py` — 添加搜索框
- 利用现有的 `rag_pipeline.retrieve()` 方法

**详细做法**：

在 `cognitive_panel.py` 的聊天输入框上方添加：
```python
with st.expander("搜索来源内容", expanded=False):
    search_query = st.text_input("输入关键词搜索", key="global_search")
    if search_query:
        pipeline = get_pipeline()
        results = asyncio.run(pipeline.retrieve(search_query, vault_uuid, top_k=5))
        for i, chunk in enumerate(results, 1):
            meta = chunk.get("metadata", {})
            st.markdown(f"**[{i}]** {meta.get('header_hierarchy', '未知')}")
            st.caption(chunk.get("chunk_text", "")[:300])
            st.divider()
```

**验收标准**：输入关键词 → 显示匹配的文档片段 → 可看到来源信息。

**依赖**：无

---

### 步骤 17：Streamlit 上传大小配置

**目标**：Streamlit 默认上传限制 200MB。需要在 `.streamlit/config.toml` 中配置，确保大文件可上传。

**文件**：
- 新建 `.streamlit/config.toml`

**详细做法**：

创建 `.streamlit/config.toml`：
```toml
[server]
maxUploadSize = 500
maxMessageSize = 500

[browser]
gatherUsageStats = false
```

**验收标准**：可上传 200MB+ 的 PDF 文件。

**依赖**：无

---

### 步骤 18：中文分词优化 BM25

**目标**：当前 BM25 用 `str.split()` 分词，对中文无效。需要改为 `jieba` 中文分词。

**文件**：
- 修改 `core/rag_pipeline.py` — `HybridRetriever.add_chunks` 和 `search_bm25`
- 修改 `requirements.txt` — 添加 `jieba`

**详细做法**：

1. 在 `requirements.txt` 添加：`jieba>=0.42.1`

2. 在 `core/rag_pipeline.py` 顶部添加：
```python
try:
    import jieba
    def tokenize(text: str) -> List[str]:
        return list(jieba.cut(text))
except ImportError:
    def tokenize(text: str) -> List[str]:
        return text.split()
```

3. 替换 `add_chunks` 中的 `c.split()` 为 `tokenize(c)`。
4. 替换 `search_bm25` 中的 `query.split()` 为 `tokenize(query)`。

**验收标准**：搜索中文关键词（如"光合作用"）能准确匹配到包含该词的文档片段。

**依赖**：无

---

### 步骤 19：错误处理与用户友好提示

**目标**：目前很多错误直接抛异常。需要全面添加 try-except 和友好的中文错误提示。

**文件**：
- 修改 `frontend/cognitive_panel.py`
- 修改 `frontend/studio_panel.py`
- 修改 `frontend/ingestion_panel.py`

**详细做法**：

为每个关键操作添加 try-except：
```python
# 示例：Studio 面板
try:
    result = asyncio.run(_run())
    save_note(tool["title"], result)
except httpx.ConnectError:
    st.error("无法连接到 AI 服务器，请检查网络连接。")
except httpx.HTTPStatusError as e:
    if e.response.status_code == 401:
        st.error("API Key 无效，请检查 .env 文件中的 DEEPSEEK_API_KEY。")
    elif e.response.status_code == 429:
        st.error("API 调用频率过高，请稍后再试。")
    else:
        st.error(f"AI 服务返回错误: {e.response.status_code}")
except Exception as e:
    st.error(f"生成失败: {e}")
```

对 LLM 超时、网络错误、API Key 错误、文件解析错误等分别给出有意义的提示。

**验收标准**：API Key 错误时提示"请检查 .env 中的密钥"；网络断开时提示"请检查网络"。

**依赖**：无

---

### 步骤 20：PPT / PPTX 文件支持

**目标**：支持上传 PowerPoint 文件作为来源。

**文件**：
- 修改 `core/rag_pipeline.py` — 添加 `_parse_pptx`
- 修改 `frontend/ingestion_panel.py` — type 列表加 `pptx`
- 修改 `requirements.txt` — 添加 `python-pptx`

**详细做法**：

1. `requirements.txt` 添加：`python-pptx>=0.6.21`

2. 在 `_parse_document` 添加：
```python
if file_name.lower().endswith(".pptx"):
    return await self._parse_pptx(file_bytes)
```

3. 实现 `_parse_pptx`：
```python
async def _parse_pptx(self, file_bytes: bytes) -> Tuple[str, int]:
    import io
    from pptx import Presentation
    
    def _sync():
        prs = Presentation(io.BytesIO(file_bytes))
        parts = []
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = [f"--- Slide {slide_num} ---"]
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_texts.append(shape.text.strip())
            parts.append("\n".join(slide_texts))
        text = "\n\n".join(parts)
        return text, len(prs.slides)
    
    return await asyncio.to_thread(_sync)
```

**验收标准**：上传 .pptx 文件 → 解析为文本 → 可被检索。

**依赖**：无

---

### 步骤 21：YouTube / Bilibili 链接支持

**目标**：粘贴视频链接，自动提取字幕/描述作为来源（不做视频播放）。

**文件**：
- 修改 `frontend/ingestion_panel.py` — URL 输入支持视频链接检测
- 修改 `core/rag_pipeline.py` — 添加视频字幕提取

**详细做法**：

1. 在 `requirements.txt` 添加：`yt-dlp>=2024.1.0`

2. 检测 URL 类型：
```python
def _is_video_url(url: str) -> bool:
    return any(d in url for d in ["youtube.com", "youtu.be", "bilibili.com"])
```

3. 视频字幕提取：
```python
async def _parse_video_url(self, url: str) -> Tuple[str, int]:
    import yt_dlp
    
    def _sync():
        ydl_opts = {"writesubtitles": True, "writeautomaticsub": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "")
            description = info.get("description", "")
            # 尝试获取字幕
            subtitles = info.get("subtitles", {}) or info.get("automatic_captions", {})
            sub_text = ""
            for lang in ["zh-Hans", "zh", "en"]:
                if lang in subtitles:
                    # 提取字幕文本...
                    break
            text = f"标题: {title}\n\n描述: {description}\n\n字幕:\n{sub_text}"
            return text, 1
    
    return await asyncio.to_thread(_sync)
```

**验收标准**：粘贴 YouTube/B站 链接 → 提取视频标题+字幕 → 存入来源列表。

**依赖**：步骤 1

---

### 步骤 22：来源选择性对话

**目标**：对标 NotebookLM 的"Select sources"功能。用户可以勾选部分来源，让 AI 只基于选中的来源回答。

**文件**：
- 修改 `frontend/ingestion_panel.py` — 每个来源添加 checkbox
- 修改 `frontend/cognitive_panel.py` — 检索时只检索选中的来源
- 修改 `core/rag_pipeline.py` — `retrieve` 方法添加 `doc_hashes` 过滤参数

**详细做法**：

1. 在来源列表中添加 checkbox：
```python
for doc in docs:
    selected = st.checkbox(doc.file_name, value=True, key=f"src_sel_{doc.content_hash}")
    if selected:
        selected_hashes.append(doc.content_hash)
st.session_state["selected_sources"] = selected_hashes
```

2. 修改 `rag_pipeline.py` 的 `retrieve` 方法：
```python
async def retrieve(self, query, vault_uuid, top_k=5, doc_hashes=None):
    # ChromaDB 查询时添加 where 过滤
    if doc_hashes:
        results = collection.query(
            query_embeddings=...,
            where={"doc_hash": {"$in": doc_hashes}},
            ...
        )
```

3. 在 `cognitive_panel.py` 调用检索时传入 `selected_sources`。

**验收标准**：取消勾选某来源 → 提问 → AI 回答不包含该来源的内容。

**依赖**：无

---

### 步骤 23：键盘快捷键与 UX 优化

**目标**：Enter 键直接发送消息（而非 Shift+Enter），提升交互效率。

**文件**：
- 修改 `frontend/cognitive_panel.py` — 用 `st.chat_input` 替代 `st.text_input`

**详细做法**：

将当前的 `st.text_input` + `st.button("提交")` 替换为 Streamlit 原生的聊天组件：
```python
# 替换为
user_input = st.chat_input("输入你的问题...", key="chat_input")
if user_input:
    # 处理消息...
```

同时用 `st.chat_message` 替代手动渲染消息：
```python
for msg in chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
```

**验收标准**：输入框在页面底部 → 按 Enter 直接发送 → 消息以对话气泡形式显示。

**依赖**：无

---

### 步骤 24：响应式布局（移动端适配）

**目标**：在窄屏/手机上，三栏布局自动变为单栏。

**文件**：
- 修改 `app.py` — 添加 CSS 媒体查询

**详细做法**：

在全局 CSS 中添加：
```css
@media (max-width: 768px) {
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
    }
    [data-testid="stHorizontalBlock"] > div {
        width: 100% !important;
        flex: 1 1 100% !important;
    }
}
```

**验收标准**：浏览器窗口缩小到手机宽度 → 布局自动变为上下排列。

**依赖**：无

---

### 步骤 25：性能优化 — 嵌入模型缓存

**目标**：当前每次嵌入都重新加载模型，耗时且占内存。需要单例缓存。

**文件**：
- 修改 `core/rag_pipeline.py` — `_embed_chunks_async` 使用缓存的 embedder

**详细做法**：

1. 将 `_embed_chunks_async` 中的 `SentenceTransformer("all-MiniLM-L6-v2")` 改为使用 `self._get_embedder()`（已有此方法但未被使用）：
```python
async def _embed_chunks_async(self, chunks: List[Dict[str, Any]]) -> List[List[float]]:
    def _sync_embed() -> List[List[float]]:
        model = self._get_embedder()  # 复用单例，不重复加载
        texts = [c["chunk_text"] for c in chunks]
        emb = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return emb.tolist()
    return await asyncio.to_thread(_sync_embed)
```

2. 添加 `@st.cache_resource` 装饰器到 `get_pipeline()` 工厂函数，确保全局只有一个 pipeline 实例。

**验收标准**：连续上传多个文件 → 第二个文件开始嵌入速度明显更快（模型不重复加载）。

**依赖**：无

---

### 步骤 26：流式输出（Streaming）— AI 打字效果

**目标**：对标 NotebookLM 的核心体验。AI 回复不是等 10 秒蹦出一整段，而是逐字流式显示，像打字一样。这是用户体验的巨大差距。

**文件**：
- 修改 `core/llm_engine.py` — 添加 `stream_chat` 方法，使用 SSE 流式接口
- 修改 `frontend/cognitive_panel.py` — 用 `st.write_stream` 渲染流式输出

**详细做法**：

1. 在 `core/llm_engine.py` 添加流式方法：
```python
async def stream_chat(
    self,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
):
    """流式输出，yield 每个文本 chunk。"""
    if _USE_MOCK:
        # Mock 模式模拟流式
        mock_text = _mock_ask().get("explanation", "")
        for char in mock_text:
            yield char
            await asyncio.sleep(0.02)
        return

    sys_msg = system_prompt or "You are a helpful AI tutor."
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": prompt},
    ]
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "stream": True,  # 关键：开启流式
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async with client.stream(
            "POST", f"{_BASE_URL}/chat/completions",
            headers=headers, json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue
```

2. 在 `frontend/cognitive_panel.py` 中，将 AI 回复改为流式渲染：
```python
# 替换原来的 st.markdown(response_text) 为：
with st.chat_message("assistant"):
    response_placeholder = st.empty()
    full_response = ""
    async for chunk in engine.stream_chat(user_input, system_prompt=sys_prompt):
        full_response += chunk
        response_placeholder.markdown(full_response + "▌")  # 光标效果
    response_placeholder.markdown(full_response)
```

**注意**：Streamlit 的 `st.write_stream()` 也可以用，但需要把 async generator 转为 sync generator（用 `asyncio.run()` 包装每次 yield）。

**验收标准**：提问后 AI 回答逐字出现，像 ChatGPT 一样有打字效果，不是等很久蹦出一整段。

**依赖**：步骤 5

---

### 步骤 27：建议问题（Suggested Questions）

**目标**：对标 NotebookLM 的"Suggested prompts"。用户添加来源后，系统自动生成 3-5 个建议问题，显示在聊天区，用户一键点击即可提问。

**文件**：
- 修改 `frontend/cognitive_panel.py` — 在聊天历史为空时显示建议问题
- 修改 `core/rag_pipeline.py` 或新建辅助函数 — 生成建议问题
- 修改 `utils/db_manager.py` — 缓存建议问题

**详细做法**：

1. 在 `utils/db_manager.py` 的 `DocumentRegistryORM` 添加字段（如果步骤 3 已添加 `key_topics`，可复用）：
```python
suggested_questions = Column(Text, default="")  # JSON: ["问题1", "问题2", ...]
```

2. 在摄入完成后（步骤 3 的自动摘要之后），生成建议问题：
```python
questions_resp = await llm.ask_simple(
    f"请基于以下内容，生成 3 个用户最可能想问的问题（用 JSON 数组格式返回）：\n\n{full_text[:3000]}",
    system_prompt="你是问题生成助手。只返回 JSON 数组，如 [\"问题1\", \"问题2\", \"问题3\"]"
)
```

3. 在 `frontend/cognitive_panel.py` 中，当聊天历史为空时：
```python
chat_history = st.session_state.get("cognitive_chat_history", [])
if not chat_history:
    st.markdown("**你可以试试问这些：**")
    suggested = _get_suggested_questions(vault_uuid)  # 从数据库读取
    for q in suggested:
        if st.button(q, key=f"suggest_{hash(q)}"):
            # 将问题填入输入框并触发提交
            st.session_state["pending_question"] = q
            st.rerun()
```

4. 在 Studio 面板顶部也显示建议问题。

**验收标准**：上传文档后 → 聊天区显示 3 个建议问题按钮 → 点击后自动提问并获得回答。

**依赖**：步骤 3

---

### 步骤 28：复制粘贴文本作为来源

**目标**：对标 NotebookLM 的"Copied text"来源类型。用户直接粘贴一段文字（如笔记、文章片段），存为来源。

**文件**：
- 修改 `frontend/ingestion_panel.py` — 添加文本粘贴区
- 修改 `core/rag_pipeline.py` — 支持纯文本直接摄入（跳过文件解析）

**详细做法**：

1. 在 `ingestion_panel.py` 的 URL 输入之后添加：
```python
st.divider()
st.markdown("**或粘贴文本**")
pasted_text = st.text_area(
    "粘贴文本内容作为来源",
    key="nb_mh_paste_text",
    height=150,
    placeholder="在这里粘贴文章、笔记、或任何文本内容..."
)
paste_title = st.text_input("来源标题", key="nb_mh_paste_title", placeholder="给这段文本取个名字")
if pasted_text and paste_title and st.button("添加文本来源", key="btn_paste_source"):
    text_bytes = pasted_text.encode("utf-8")
    file_name = f"{paste_title}.txt"
    _run_ingestion(console, text_bytes, file_name, vault_uuid)
```

这非常简单——把粘贴的文本当作 .txt 文件处理，现有管线直接支持。

**验收标准**：粘贴一段文字 → 输入标题 → 点击添加 → 来源列表出现 → 可被检索和引用。

**依赖**：无

---

### 步骤 29：图片来源支持（PNG/JPG → OCR 提取文字）

**目标**：对标 NotebookLM 的图片来源。上传图片，自动 OCR 提取文字内容，存为来源。

**文件**：
- 修改 `frontend/ingestion_panel.py` — file_uploader type 添加图片格式
- 修改 `core/rag_pipeline.py` — 添加 `_parse_image` 方法

**详细做法**：

1. 修改上传器：
```python
type=["pdf", "docx", "txt", "md", "csv", "json", "pptx", "png", "jpg", "jpeg", "webp"]
```

2. 在 `_parse_document` 添加图片分支：
```python
img_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
if file_name.lower().endswith(img_exts):
    return await self._parse_image(file_bytes)
```

3. 实现 `_parse_image`（复用已有的 `rapidocr-onnxruntime`，不需要新依赖！）：
```python
async def _parse_image(self, file_bytes: bytes) -> Tuple[str, int]:
    """OCR 提取图片中的文字。"""
    import io
    
    def _sync():
        try:
            from rapidocr_onnxruntime import RapidOCR
            from PIL import Image
            import numpy as np
            
            ocr = RapidOCR()
            img = Image.open(io.BytesIO(file_bytes))
            result, _ = ocr(np.array(img))
            if result:
                text = "\n".join(
                    str(item[1]) if isinstance(item, (list, tuple)) and len(item) > 1 else ""
                    for item in result
                )
                return text, 1
            return "", 0
        except Exception as e:
            logger.error("Image OCR failed: %s", e)
            return "", 0
    
    return await asyncio.to_thread(_sync)
```

**验收标准**：上传一张含文字的图片（如教材截图）→ 自动 OCR → 来源列表出现 → 可检索图中文字。

**依赖**：无（rapidocr-onnxruntime 已在 requirements.txt 中）

---

### 步骤 30：音频文件来源（MP3/WAV → 语音转文字）

**目标**：对标 NotebookLM 的音频来源。上传录音文件，自动转为文字，存为来源。

**文件**：
- 修改 `frontend/ingestion_panel.py` — type 添加音频格式
- 修改 `core/rag_pipeline.py` — 添加 `_parse_audio` 方法
- 修改 `requirements.txt` — 添加 `openai-whisper` 或用 DeepSeek 的语音转文字 API

**详细做法**：

方案 A（推荐，简单）：使用在线 API（如 DeepSeek 或 OpenAI 的 Whisper API）：
```python
async def _parse_audio(self, file_bytes: bytes, file_name: str) -> Tuple[str, int]:
    """音频转文字。"""
    import httpx
    
    async with httpx.AsyncClient(timeout=120) as client:
        # 使用 OpenAI Whisper API（DeepSeek 不提供语音 API）
        # 需要在 .env 中配置 OPENAI_API_KEY
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        r = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (file_name, file_bytes)},
            data={"model": "whisper-1", "language": "zh"},
        )
        r.raise_for_status()
        text = r.json().get("text", "")
        page_count = max(1, len(text) // 1800)
        return text, page_count
```

方案 B（离线，但需要大模型下载）：使用本地 `faster-whisper`：
```
# requirements.txt 添加：
faster-whisper>=1.0.0
```
```python
async def _parse_audio(self, file_bytes: bytes, file_name: str) -> Tuple[str, int]:
    import io, tempfile
    from faster_whisper import WhisperModel
    
    def _sync():
        model = WhisperModel("base", device="cpu")
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(file_name)[1], delete=False) as f:
            f.write(file_bytes)
            f.flush()
            segments, _ = model.transcribe(f.name, language="zh")
            text = " ".join(seg.text for seg in segments)
        return text, max(1, len(text) // 1800)
    
    return await asyncio.to_thread(_sync)
```

**验收标准**：上传 MP3 录音 → 自动转文字 → 来源列表出现 → 可检索录音内容。

**依赖**：无

---

### 步骤 31：思维导图（Mind Map）生成

**目标**：对标 NotebookLM 的 Mind Map 功能。基于来源内容生成概念关系图，以可视化方式展示。这是 NotebookLM 很受欢迎的功能。

**文件**：
- 修改 `frontend/studio_panel.py` — 添加思维导图工具卡片
- 新建 `frontend/mindmap_panel.py` — 思维导图渲染
- 修改 `requirements.txt` — 确认 `streamlit-agraph` 或用 Mermaid.js

**详细做法**：

方案（推荐）：让 LLM 生成 Mermaid 格式的思维导图代码，用 `st.html` + Mermaid.js CDN 渲染：

1. 在 Studio 工具列表 `_STUDIO_TOOLS` 中添加：
```python
{
    "key": "mindmap",
    "title": "思维导图",
    "desc": "可视化概念关系图",
    "prompt_query": "核心概念及其关系",
    "prompt_gen": (
        "请基于以下内容生成一个 Mermaid 格式的思维导图。\n"
        "要求：\n"
        "1. 使用 mindmap 语法\n"
        "2. 包含核心概念和子概念\n"
        "3. 层级不超过 3 层\n"
        "4. 只返回 Mermaid 代码，不要其他文字\n"
        "格式示例：\n"
        "mindmap\n"
        "  root((主题))\n"
        "    概念A\n"
        "      子概念A1\n"
        "      子概念A2\n"
        "    概念B\n"
        "      子概念B1\n\n"
        "内容：\n{context}"
    ),
    "system": "你是思维导图生成助手。只返回 Mermaid mindmap 代码，不要任何其他文字或 markdown 标记。",
},
```

2. 但思维导图不应该存为笔记纯文本。需要特殊处理：检测 `tool["key"] == "mindmap"` 时，不调用通用的 `save_note`，而是：
```python
if tool["key"] == "mindmap":
    st.session_state["mindmap_code"] = result
    # 渲染 Mermaid
    st.html(f"""
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <div class="mermaid" style="background:white; padding:20px; border-radius:12px;">
    {result}
    </div>
    <script>mermaid.initialize({{startOnLoad:true}});</script>
    """)
```

3. 如果网络不通（CDN 不可用），可以降级为纯文本缩进格式显示。

**验收标准**：点击"思维导图"生成按钮 → 页面显示可视化的概念关系图 → 层级清晰。

**依赖**：步骤 5

---

### 步骤 32：数据表格生成（Data Table）

**目标**：对标 NotebookLM 的 Data Table 功能。让 AI 从来源中提取结构化数据，以表格形式展示。

**文件**：
- 修改 `frontend/studio_panel.py` — 添加数据表格工具

**详细做法**：

1. 在 `_STUDIO_TOOLS` 添加：
```python
{
    "key": "datatable",
    "title": "数据表格",
    "desc": "从来源中提取结构化表格",
    "prompt_query": "关键数据和对比信息",
    "prompt_gen": (
        "请基于以下内容，提取关键信息并整理为 Markdown 表格。\n"
        "要求：\n"
        "1. 表格列数 3-6 列\n"
        "2. 行数 5-15 行\n"
        "3. 包含表头\n"
        "4. 只返回 Markdown 表格，不要其他文字\n\n"
        "内容：\n{context}"
    ),
    "system": "你是数据整理助手。只返回 Markdown 格式的表格。",
},
```

2. 生成后直接用 `st.markdown(result)` 渲染即可，Streamlit 原生支持 Markdown 表格。

3. 可选增强：解析 Markdown 表格为 `pandas.DataFrame`，用 `st.dataframe(df)` 渲染交互式表格（支持排序/筛选）：
```python
import pandas as pd
import io

if tool["key"] == "datatable":
    try:
        # 尝试解析 Markdown 表格为 DataFrame
        lines = [l for l in result.strip().split("\n") if "|" in l and not l.strip().startswith("|---")]
        if lines:
            headers = [h.strip() for h in lines[0].split("|") if h.strip()]
            rows = []
            for line in lines[1:]:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if cells:
                    rows.append(cells)
            df = pd.DataFrame(rows, columns=headers[:len(rows[0])] if rows else headers)
            st.dataframe(df, use_container_width=True)
    except:
        st.markdown(result)  # 降级为纯 Markdown
```

**验收标准**：点击"数据表格" → 生成结构化表格 → 可交互排序筛选。

**依赖**：步骤 5

---

### 步骤 33：自定义报告（Custom Reports）

**目标**：对标 NotebookLM 的 Reports 功能。不只是预设的学习指南/摘要，用户可以自己描述想要什么样的报告。

**文件**：
- 修改 `frontend/studio_panel.py` — 添加自定义报告入口

**详细做法**：

在 Studio 面板工具网格**下方**添加自定义生成区：
```python
st.divider()
st.markdown(
    '<p style="font-size:15px; font-weight:600; color:#202124; margin:12px 0 8px;">自定义生成</p>',
    unsafe_allow_html=True,
)
custom_prompt = st.text_area(
    "描述你想生成的内容",
    key="studio_custom_prompt",
    height=80,
    placeholder="例如：帮我写一篇关于这些内容的博客文章 / 生成一份考前复习重点 / 对比分析文档A和B的异同..."
)
if custom_prompt and st.button("生成", key="btn_studio_custom"):
    custom_tool = {
        "key": "custom",
        "title": "自定义报告",
        "prompt_query": custom_prompt,
        "prompt_gen": f"用户要求：{custom_prompt}\n\n请基于以下来源内容完成用户的要求：\n\n{{context}}",
        "system": "你是一个全能助手，请按用户要求生成内容。用中文回答。",
    }
    _generate_content(vault_uuid, custom_tool)
```

**验收标准**：输入自定义需求（如"写一篇博客"）→ 基于来源生成 → 保存为笔记。

**依赖**：无

---

### 步骤 34：闪卡/测验自定义参数

**目标**：对标 NotebookLM 的闪卡和测验自定义。用户可以选择数量、难度、聚焦主题。

**文件**：
- 修改 `frontend/studio_panel.py` — 闪卡和测验按钮替换为带参数的弹窗

**详细做法**：

将闪卡和测验的"生成"按钮改为 `st.expander`，里面放参数选择器：

```python
# 替换闪卡的简单按钮为：
with st.expander("闪卡设置"):
    fc_count = st.slider("卡片数量", 5, 30, 10, key="fc_count")
    fc_difficulty = st.selectbox("难度", ["基础", "中等", "困难"], key="fc_diff")
    fc_topic = st.text_input("聚焦主题（可选）", key="fc_topic", placeholder="留空则覆盖所有内容")
    if st.button("生成闪卡", key="btn_gen_fc"):
        # 动态构建 prompt
        prompt = f"请生成 {fc_count} 张{fc_difficulty}难度的闪卡"
        if fc_topic:
            prompt += f"，聚焦于「{fc_topic}」主题"
        # ... 调用生成
```

测验同理：
```python
with st.expander("测验设置"):
    quiz_count = st.slider("题目数量", 5, 20, 10, key="quiz_count")
    quiz_difficulty = st.selectbox("难度", ["基础", "中等", "困难"], key="quiz_diff")
    quiz_type = st.selectbox("题型", ["选择题", "判断题", "填空题", "混合"], key="quiz_type")
    quiz_topic = st.text_input("聚焦主题（可选）", key="quiz_topic")
    if st.button("生成测验", key="btn_gen_quiz"):
        # ...
```

**验收标准**：闪卡/测验有参数选择器 → 选择 20 题困难级别 → 生成结果符合设置。

**依赖**：步骤 6, 7

---

### 步骤 35：来源内容全文预览

**目标**：对标 NotebookLM 点击来源后可以查看原文全文。用户应该能看到上传的文档原始内容。

**文件**：
- 修改 `utils/db_manager.py` — 存储原始文本
- 修改 `frontend/source_detail_panel.py`（步骤 10 创建的）— 添加全文预览

**详细做法**：

1. 在 `DocumentRegistryORM` 添加字段：
```python
full_text = Column(Text, default="")  # 存储解析后的全文
```

2. 在 `rag_pipeline.py` 的 `ingest_document` 中，解析完文本后存入：
```python
db_pool.update_document_fulltext(vault_uuid, content_hash, text[:50000])  # 限制 50K 字
```

3. 在来源详情面板中添加全文预览：
```python
with st.expander("查看原文", expanded=False):
    full_text = db_pool.get_document_fulltext(vault_uuid, content_hash)
    if full_text:
        st.text_area("原文内容", full_text, height=400, disabled=True)
    else:
        st.caption("原文未存储")
```

**验收标准**：来源详情页 → 展开"查看原文" → 可看到文档的解析后全文。

**依赖**：步骤 10

---

## NotebookLM vs NotebookMH 功能对照表

完成全部 35 步后的覆盖情况：

| NotebookLM 功能 | 对应步骤 | 覆盖度 |
|----------------|---------|--------|
| **来源：PDF/DOCX/TXT** | 已完成 | 100% |
| **来源：网页 URL** | 步骤 1 | 100% |
| **来源：复制粘贴文本** | 步骤 28 | 100% |
| **来源：图片 OCR** | 步骤 29 | 100% |
| **来源：音频转文字** | 步骤 30 | 90%（依赖 API） |
| **来源：CSV/MD/JSON** | 步骤 11 | 100% |
| **来源：PPTX** | 步骤 20 | 100% |
| **来源：YouTube 字幕** | 步骤 21 | 80% |
| **来源：50 个上限** | 步骤 2 | 100% |
| **来源：选择性过滤** | 步骤 22 | 100% |
| **来源概览/摘要** | 步骤 3, 10 | 100% |
| **来源全文预览** | 步骤 35 | 100% |
| **来源：Google Docs/Sheets** | 不做 | 0%（Google 专属） |
| **来源：Web 搜索/Deep Research** | 不做 | 0%（需要 Google 搜索 API） |
| **聊天：多轮对话** | 步骤 15 | 100% |
| **聊天：来源引用 [1][2]** | 步骤 4 | 100% |
| **聊天：流式输出** | 步骤 26 | 100% |
| **聊天：建议问题** | 步骤 27 | 100% |
| **聊天：历史持久化** | 步骤 8 | 100% |
| **Studio：文档摘要** | 已完成 | 100% |
| **Studio：FAQ** | 已完成 | 100% |
| **Studio：学习指南** | 已完成 | 100% |
| **Studio：时间线** | 已完成 | 100% |
| **Studio：简报文档** | 已完成 | 100% |
| **Studio：闪卡（交互式）** | 步骤 6, 34 | 100% |
| **Studio：测验（交互式）** | 步骤 7, 34 | 100% |
| **Studio：思维导图** | 步骤 31 | 90%（Mermaid 近似） |
| **Studio：数据表格** | 步骤 32 | 100% |
| **Studio：自定义报告** | 步骤 33 | 100% |
| **Studio：Audio Overview** | 不做 | 0%（用户明确排除） |
| **Studio：Video Overview** | 不做 | 0%（用户明确排除） |
| **Studio：Infographic** | 不做 | 0%（需要图片生成模型） |
| **Studio：Slide Deck** | 不做 | 0%（过于复杂） |
| **笔记管理** | 步骤 9 | 100% |
| **导出功能** | 步骤 14 | 100% |
| **错题复盘** | 步骤 12 | 100%（超越 NotebookLM） |
| **学习进度** | 步骤 13 | 100%（超越 NotebookLM） |
| **键盘快捷键 + UX** | 步骤 23, 24 | 90% |

**预计完成后覆盖 NotebookLM 可实现功能的 85-90%。**  
不做的 4 项（Google Docs、Web Deep Research、Audio/Video Overview、Infographic/Slide Deck）需要 Google 专属 API 或图片/视频生成模型，不在本地应用的合理范围内。

---

## 建议执行顺序（更新版，共 15 个会话）

| 会话 | 步骤 | 说明 | 预计时长 |
|------|------|------|---------|
| 会话 1 | **步骤 5, 18, 25** | 基础修复：.env 加载、中文分词、嵌入缓存 | 30 分钟 |
| 会话 2 | **步骤 1, 2, 28** | 来源扩展：URL + 50 上限 + 粘贴文本 | 40 分钟 |
| 会话 3 | **步骤 3, 27** | 自动摘要 + 建议问题 | 40 分钟 |
| 会话 4 | **步骤 26** | 流式输出（核心体验大提升） | 30 分钟 |
| 会话 5 | **步骤 4, 15** | 来源引用 + 多轮对话 | 40 分钟 |
| 会话 6 | **步骤 8, 23** | 对话历史持久化 + chat_input 改造 | 30 分钟 |
| 会话 7 | **步骤 6, 34** | 交互式闪卡 + 自定义参数 | 45 分钟 |
| 会话 8 | **步骤 7** | 交互式测验系统 | 40 分钟 |
| 会话 9 | **步骤 10, 35** | 来源详情面板 + 全文预览 | 40 分钟 |
| 会话 10 | **步骤 12, 13** | 错题复盘 + 学习进度看板 | 40 分钟 |
| 会话 11 | **步骤 9, 14** | 笔记管理增强 + 导出功能 | 30 分钟 |
| 会话 12 | **步骤 31, 32, 33** | 思维导图 + 数据表格 + 自定义报告 | 45 分钟 |
| 会话 13 | **步骤 11, 20, 29** | 更多文件格式：MD/CSV/PPTX/图片 | 40 分钟 |
| 会话 14 | **步骤 22, 30** | 来源选择性对话 + 音频转文字 | 40 分钟 |
| 会话 15 | **步骤 21, 19, 24, 17** | YouTube + 错误处理 + 响应式 + 配置 | 45 分钟 |

---

## 每次会话的标准流程

让 AI 每次开始时执行以下步骤：

```
1. 阅读本文档 (ROADMAP_FOR_AI.md)
2. 找到"当前进度"标记，确认要做哪些步骤
3. 阅读涉及的文件，理解现有代码
4. 按步骤实现功能
5. 运行 `python -m py_compile <file>` 验证语法
6. 重启 Streamlit 服务测试
7. 完成后，在本文档的对应步骤后标注 ✅ 和完成日期
8. 更新"当前进度"标记到下一批步骤
```

每次会话开始时，复制以下提示语给 AI：

> 请先阅读 `c:\大饼的ai助手\zijiannotebookdb\NotebookMH\ROADMAP_FOR_AI.md`，找到"当前进度"标记，执行对应的步骤。每完成一步，在文档中标注 ✅。全部完成后更新"当前进度"。

---

## ⬇️ 当前进度

**下一个要执行的会话：会话 1（步骤 5, 18, 25）**

---

## 关键文件路径速查

| 文件 | 用途 |
|------|------|
| `app.py` | 主入口，页面配置，CSS，三栏布局 |
| `core/rag_pipeline.py` | RAG 管线：解析、切块、嵌入、检索 |
| `core/llm_engine.py` | LLM 调用（DeepSeek/OpenAI），Mock 降级 |
| `core/cognitive_engine.py` | 认知状态机（Learning/Quizzing/Review） |
| `core/persona_engine.py` | 教师人格（启发型/严师型/自适应） |
| `frontend/ingestion_panel.py` | 文件上传 + 来源列表 |
| `frontend/cognitive_panel.py` | 聊天面板 |
| `frontend/studio_panel.py` | 右侧 Studio（生成工具 + 笔记） |
| `utils/db_manager.py` | SQLite 数据库 ORM + CRUD |
| `utils/state_manager.py` | Streamlit session state 绑定 |
| `.env` | API 密钥（DEEPSEEK_API_KEY 等） |
| `requirements.txt` | Python 依赖 |

---

## 环境配置提醒

```bash
# .env 文件（已创建）
DEEPSEEK_API_KEY=sk-xxxxx
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat

# 启动命令
cd c:\大饼的ai助手\zijiannotebookdb\NotebookMH
python -m streamlit run app.py --server.headless=true

# 语法检查
python -m py_compile app.py
python -m py_compile core/rag_pipeline.py
```
