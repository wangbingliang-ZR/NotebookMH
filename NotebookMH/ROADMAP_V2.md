# NotebookMH 开发任务书 V2 — 给 Kimi K2.6 的执行手册

> **每次会话开始必读「铁律」和「当前进度」。**

## 一、项目信息

- **路径**：`c:\大饼的ai助手\zijiannotebookdb\NotebookMH`
- **启动**：`python -m streamlit run app.py --server.headless=true`
- **检查**：`python -m py_compile <文件>`
- **技术栈**：Python 3.12 + Streamlit + SQLAlchemy/SQLite + ChromaDB + DeepSeek API
- **.env 已配置**：`DEEPSEEK_API_KEY` 已设置

---

## 二、铁律（违反任何一条立即停止）

### 禁止
1. **禁止一次改超过1个文件**。改完一个，py_compile 通过，再改下一个。
2. **禁止删除已有代码**，除非步骤明确说"删除"或"替换"。
3. **禁止改 `app.py` 的 CSS**（第36-120行），除非步骤要求。
4. **禁止改函数签名**（参数名、参数数量）。
5. **禁止引入步骤未提到的第三方库**。
6. **禁止在文件中间写 import**，所有 import 在文件顶部。
7. **禁止使用 emoji**。

### 必须
1. 每改完一个文件，**必须** `python -m py_compile <文件>` 检查。
2. 每完成一步，**必须**更新本文档末尾「工作日志」。
3. 遇到错误解决不了，**写明错误信息后停止**，不要反复尝试。
4. 修改前**必须先读完该文件全部内容**。
5. 会话结束前**必须更新「当前进度」**。

### 代码规范
- 异步调用：`asyncio.run(async_func())`（`app.py` 顶部有 `nest_asyncio.apply()`）
- Session state：`binder.get_state("key", "default")`
- 数据库：`from utils.db_manager import db_pool`
- RAG：`from core.rag_pipeline import get_pipeline`
- LLM 纯文本：`await llm.ask_simple(prompt, system_prompt=...)`
- LLM 结构化：`await llm.chat(prompt, system_prompt=...)`

---

## 三、文件速查

| 文件 | 作用 |
|------|------|
| `app.py` | 主入口、CSS、三栏布局 |
| `core/rag_pipeline.py` | 解析、切块、嵌入、检索 |
| `core/llm_engine.py` | DeepSeek API |
| `core/cognitive_engine.py` | 认知状态机 |
| `frontend/ingestion_panel.py` | 来源上传+列表 |
| `frontend/cognitive_panel.py` | 聊天面板 |
| `frontend/studio_panel.py` | Studio面板 |
| `utils/db_manager.py` | SQLite ORM |
| `requirements.txt` | 依赖 |

---

## 四、50步开发计划

### 步骤01：加载 .env

**文件**：`app.py`
**做法**：顶部 import 区添加（在 `import streamlit` 之前）：
```python
from dotenv import load_dotenv
load_dotenv()
```
**验证**：`python -m py_compile app.py`
**易错**：放在文件中间→必须在顶部

---

### 步骤02：Streamlit 配置

**新建**：`.streamlit/config.toml`
```toml
[server]
maxUploadSize = 500
maxMessageSize = 500
[browser]
gatherUsageStats = false
```

---

### 步骤03：安装 jieba

**文件**：`requirements.txt` 末尾添加：`jieba>=0.42.1`
然后运行：`pip install jieba`

---

### 步骤04：BM25 中文分词

**文件**：`core/rag_pipeline.py`
**第一步**：顶部添加：
```python
try:
    import jieba
    def _tokenize(text: str) -> list:
        return list(jieba.cut(text))
except ImportError:
    def _tokenize(text: str) -> list:
        return text.split()
```
**第二步**：搜索 BM25 相关的 `.split()`，仅替换为 `_tokenize()`。
**易错**：不是所有 `.split()` 都改，只改 BM25 分词相关的。

---

### 步骤05：嵌入模型缓存

**文件**：`core/rag_pipeline.py`
**做法**：找到 `_embed_chunks_async`，将每次新建 `SentenceTransformer` 改为 `self.retriever._get_embedder()` 复用单例。
**易错**：先确认 `_get_embedder` 方法是否存在。

---

### 步骤06：URL来源-UI

**文件**：`frontend/ingestion_panel.py`
**做法**：在 `_render_document_list()` 之前添加：
```python
  st.divider()
  st.markdown("**添加网页链接**")
  url_input = st.text_input("粘贴URL", key="nb_mh_url_input", placeholder="https://...")
  if url_input and st.button("添加网页来源", key="btn_ingest_url"):
      _run_url_ingestion(console, url_input, vault_uuid)
```
同时添加占位函数：
```python
def _run_url_ingestion(console, url, vault_uuid):
    st.warning("网页功能待步骤07完成。")
```

---

### 步骤07：URL来源-后端

**文件**：`frontend/ingestion_panel.py`
**前置**：`pip install beautifulsoup4`，requirements.txt 添加 `beautifulsoup4>=4.12.0`
**做法**：替换步骤06的占位函数为真正实现：
```python
def _run_url_ingestion(console, url, vault_uuid):
    try:
        with st.spinner("抓取网页..."):
            import httpx
            from bs4 import BeautifulSoup
            r = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent":"Mozilla/5.0"})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script","style","nav","footer","header","aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            title = (soup.title.string.strip() if soup.title and soup.title.string else url[:50])
            if not text.strip():
                st.error("未提取到文字。")
                return
            _run_ingestion(console, text.encode("utf-8"), f"{title}.txt", vault_uuid)
    except Exception as e:
        st.error(f"失败: {e}")
```

---

### 步骤08：粘贴文本来源

**文件**：`frontend/ingestion_panel.py`
**做法**：URL代码之后添加：
```python
  st.divider()
  st.markdown("**粘贴文本**")
  pasted = st.text_area("粘贴内容", key="nb_mh_paste", height=120, placeholder="粘贴文章或笔记...")
  paste_name = st.text_input("标题", key="nb_mh_paste_title")
  if pasted and paste_name and st.button("添加文本来源", key="btn_paste"):
      _run_ingestion(console, pasted.encode("utf-8"), f"{paste_name}.txt", vault_uuid)
```

---

### 步骤09：来源计数DB方法

**文件**：`utils/db_manager.py`
**做法**：`DatabasePool` 类中添加：
```python
    def count_documents(self, vault_uuid: str) -> int:
        with self.session() as sess:
            return sess.query(DocumentRegistryORM).filter_by(vault_uuid=vault_uuid).count()
```

---

### 步骤10：来源计数UI + 50上限

**文件**：`frontend/ingestion_panel.py`
**做法**：`render()` 中文件上传器之前添加：
```python
  MAX_SOURCES = 50
  doc_count = db_pool.count_documents(vault_uuid) if vault_uuid else 0
  st.caption(f"来源: {doc_count} / {MAX_SOURCES}")
  if doc_count >= MAX_SOURCES:
      st.warning("已达50个上限。")
      _render_document_list()
      return
```

---

### 步骤11：DB添加摘要字段

**文件**：`utils/db_manager.py`
**做法**：
1. `DocumentRegistryORM` 添加：`summary = Column(Text, default="")` 和 `key_topics = Column(Text, default="")`
2. `__init__` 的 `create_all` 之后添加 ALTER TABLE 迁移
3. 添加 `update_document_summary` 方法
**易错**：确认 `inspect` 和 `text` 已 import。

---

### 步骤12：自动生成来源摘要

**文件**：`core/rag_pipeline.py`
**做法**：`ingest_document` 方法中 yield DONE 之前添加 LLM 摘要生成。用 try/except 包裹，失败不阻断流程。
**易错**：先读代码确认 `vault_uuid`、`content_hash`、`text` 的变量名。

---

### 步骤13：来源列表显示摘要

**文件**：`frontend/ingestion_panel.py`
**做法**：`_render_document_list` 的 for 循环改为 `st.expander`，展开显示摘要和关键主题。

---

### 步骤14：建议问题-生成存储

**文件**：`utils/db_manager.py` + `core/rag_pipeline.py`
**做法**：
1. DB 添加 `suggested_questions` 列 + 迁移 + `get_suggested_questions` 方法
2. RAG 摄入时（步骤12代码之后）生成3个问题并存储

---

### 步骤15：建议问题-UI

**文件**：`frontend/cognitive_panel.py`
**做法**：聊天历史为空时显示建议问题按钮，点击后触发提问。

---

### 步骤16：流式输出-后端

**文件**：`core/llm_engine.py`
**做法**：`UnifiedLLMEngine` 添加 `async def stream_chat` 方法（async generator，`yield` 文本片段）。确认顶部有 `import json`。

---

### 步骤17：流式输出-前端

**文件**：`frontend/cognitive_panel.py`
**做法**：LEARNING模式回复改为流式渲染（placeholder + 逐步更新）。Quizzing/Review保持原样。
**易错**：只改LEARNING模式，不要动其他模式。

---

### 步骤18：多轮对话上下文

**文件**：`core/cognitive_engine.py`
**做法**：LEARNING flow 构建 prompt 时拼入最近10条历史消息。
**易错**：禁止改函数签名。`chat_history` 用 `or []` 保护。

---

### 步骤19：聊天历史DB表

**文件**：`utils/db_manager.py`
**做法**：添加 `ChatHistoryORM` + `save_chat_message` / `load_chat_history` / `clear_chat_history`。

---

### 步骤20：聊天历史保存恢复

**文件**：`frontend/cognitive_panel.py`
**做法**：render() 顶部从DB恢复历史到 session_state。每条消息后调用 save。添加"清空对话"按钮。

---

### 步骤21：来源引用-Prompt

**文件**：`core/cognitive_engine.py`
**做法**：context 构建时给 chunk 编号 `[1] [2]`，prompt 要求 AI 标注引用。

---

### 步骤22：来源引用-UI

**文件**：`frontend/cognitive_panel.py`
**做法**：AI回复下方添加 `st.expander("来源引用")` 显示原文片段。

---

### 步骤23：思维导图工具

**文件**：`frontend/studio_panel.py`
**做法**：`_STUDIO_TOOLS` 添加 mindmap 条目，prompt 要求返回 Mermaid 代码。

---

### 步骤24：思维导图渲染

**文件**：`frontend/studio_panel.py`
**做法**：`_generate_content` 中检测 mindmap，用 `st.components.v1.html` + Mermaid CDN 渲染。

---

### 步骤25：数据表格工具

**文件**：`frontend/studio_panel.py`
**做法**：`_STUDIO_TOOLS` 添加 datatable 条目。Markdown表格 Streamlit 原生支持。

---

**步骤 26-50 见本文档第二部分（ROADMAP_V2_PART2.md）**

---

## 五、执行排期

| 会话 | 步骤 | 说明 |
|------|------|------|
| 1 | 01-05 | 基础修复 |
| 2 | 06-08 | 来源：URL+粘贴 |
| 3 | 09-10 | 来源50上限 |
| 4 | 11-13 | 自动摘要 |
| 5 | 14-15 | 建议问题 |
| 6 | 16-17 | 流式输出 |
| 7 | 18-20 | 多轮对话+历史 |
| 8 | 21-22 | 来源引用 |
| 9 | 23-25 | 思维导图+表格 |
| 10 | 26-29 | 自定义报告+闪卡 |
| 11 | 30-33 | 测验系统 |
| 12 | 34-36 | 笔记持久化 |
| 13 | 37-41 | 导出+来源详情 |
| 14 | 42-46 | 错题+进度+选择 |
| 15 | 47-50 | 更多格式+优化 |

---

## 六、每次会话标准流程

```
1. 读 ROADMAP_V2.md 的「铁律」和「当前进度」
2. 读要改的文件（完整读，不要只看片段）
3. 按步骤改代码（一次一个文件）
4. python -m py_compile 检查
5. 更新「工作日志」
6. 更新「当前进度」
```

**给 Kimi 的提示语**：
> 请先完整阅读 `c:\大饼的ai助手\zijiannotebookdb\NotebookMH\ROADMAP_V2.md`，找到「当前进度」，按步骤执行。每步完成后更新工作日志。遇到问题写明后停止。

---

## ⬇️ 当前进度

**下一步：已完成全部50步**

---

## 工作日志

> 每完成一步，在下方追加一行记录。格式：`| 日期 | 步骤 | 状态 | 备注 |`

| 日期 | 步骤 | 状态 | 备注 |
|------|------|------|------|
| 2026-05-21 | 01 | ✅ | app.py 已有 load_dotenv |
| 2026-05-21 | 02 | ✅ | 创建 .streamlit/config.toml |
| 2026-05-21 | 03 | ✅ | requirements.txt 已有 jieba |
| 2026-05-21 | 04 | ✅ | rag_pipeline.py 已有 _tokenize |
| 2026-05-21 | 05 | ✅ | 已使用 _get_embedder 单例 |
| 2026-05-21 | 06-08 | ✅ | URL/粘贴文本来源已完成 |
| 2026-05-21 | 09-10 | ✅ | 来源计数50上限已完成 |
| 2026-05-21 | 11-15 | ✅ | 摘要/建议问题已完成 |
| 2026-05-21 | 16-17 | ✅ | 流式输出已完成 |
| 2026-05-21 | 18-20 | ✅ | 多轮对话+历史已完成 |
| 2026-05-21 | 21-22 | ✅ | 来源引用已完成 |
| 2026-05-21 | 23-25 | ✅ | 思维导图+表格已完成 |
| 2026-05-21 | 26 | ✅ | 自定义报告已完成 |
| 2026-05-21 | 27-29 | ✅ | 闪卡DB+UI已完成 |
| 2026-05-21 | 30-33 | ✅ | 测验DB+UI已完成 |
| 2026-05-21 | 34-36 | ✅ | 笔记持久化已完成 |
| 2026-05-21 | 37-38 | ✅ | 导出MD/Word已完成 |
| 2026-05-21 | 48-49 | ✅ | OCR/错误处理已完成 |
| 2026-05-21 | 39-42 | ✅ | 来源详情/全文/选择过滤已完成 |
| 2026-05-21 | 43-46 | ✅ | 错题记录/复盘/进度看板/多格式已完成 |
| 2026-05-21 | 47 | ✅ | PPTX 解析已完成 |
| 2026-05-21 | 48-50 | ✅ | OCR/错误处理/响应式布局已完成 |
